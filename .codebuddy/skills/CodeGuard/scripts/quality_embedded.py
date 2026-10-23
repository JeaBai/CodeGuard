#!/usr/bin/env python3
"""
quality_embedded.py — 嵌入式 C 专用检测模块
=============================================
仅对 embedded 方言（由 quality_c_dialect 判定）执行，generic 方言永不调用，
从架构上杜绝「通用 C 规则」与「嵌入式 C 规则」互相污染。

检测项（对齐 MISRA C:2012 + 嵌入式最佳实践）：
  1. 动态内存禁用     — malloc/free/calloc/realloc/new/delete（MISRA 21.x）
  2. 递归调用         — 嵌入式硬禁（栈溢出风险，MISRA 17.x）
  3. goto 滥用        — MISRA 15.x 建议限制
  4. ISR 安全         — ISR 内调用阻塞/重型函数（printf/sleep/delay）
  5. volatile 正确性  — 内存映射寄存器指针必须 volatile
  6. 栈深度           — 局部大数组（嵌入式 RAM 受限）

置信度说明：
  - 正则/启发式检测默认 80（对齐 CodeGuard 正则近似级别）
  - 强证据（如明确 malloc 调用）可传 90+

用法：
  from quality_embedded import check_embedded_c_file
  check_embedded_c_file(filepath, collector, dialect="embedded")
"""

import re

import os
import sys as _sys
_sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'internal'))
from detector_registry import register_detector, get_detectors

# ============================================================
# 阈值常量（模块级，避免魔法数字散落）
# ============================================================

_ISR_MAX_LINES = 80          # ISR 函数体最大行数（超出提示拆分）
_STACK_ARRAY_MAX_BYTES = 256  # 局部大数组阈值（嵌入式栈紧张）
_GOTO_WARN_COUNT = 2          # 单函数 goto 超过此数告警

# ============================================================
# 检测模式
# ============================================================

# 1) 动态内存分配（嵌入式硬禁 — MISRA 21.x 建议）
_DYNAMIC_ALLOC_PATTERNS = (
    r'\b(?:p?malloc|calloc|realloc|free)\s*\(',
    r'\bnew\b\s+[A-Za-z_][\w:<>]*\s*(?:\(|\[)',
    r'\bdelete\b\s*(?:\[\s*\]\s*)?[\w.]+',
    r'\bstd::make_(?:unique|shared)\b',
)

# 2) 递归调用（MISRA 17.x 硬禁）
_RECURSION_PATTERNS = (
    r'\brecursive\b',          # 注释/命名信号
    r'static\s+\w+\s+(\w+)\s*\(',  # 函数定义（配合后续自调用检测）
)

# 3) goto（MISRA 15.x 建议限制）
_GOTO_PATTERN = re.compile(r'\bgoto\s+\w+\s*;')

# 4) ISR 定义特征
_ISR_DEF_PATTERNS = (
    r'__attribute__\s*\(\s*\(\s*interrupt',
    r'__attribute__\s*\(\s*\(\s*signal',
    r'\bISR\s*\(\s*([A-Za-z_0-9_]+)\s*\)',
    r'\w*IRQHandler\s*\(',          # CMSIS 命名: EXTI0_IRQHandler / USART1_IRQHandler
    r'\b__irq\b',
    r'\bvoid\s+(\w*_isr)\s*\(',
    r'\binterrupt\s+void\s+(\w+)\s*\(',
)

# 5) ISR 内禁止调用的阻塞/重型函数
_ISR_BLOCKING_CALLS = (
    r'\bprintf\s*\(',          # 阻塞式串口输出
    r'\b(?:v?print|puts|putchar|printf|scanf)\s*\(',
    r'\b(?:vTaskDelay|HAL_Delay|delay\w*|sleep|usleep|msleep)\s*\(',  # v2.2.1: delay\w* 覆盖 delay_ms/delay_us（下划线是词字符，原 delay 不匹配）
    r'\b(?:xQueueSend|xSemaphoreTake|xSemaphoreGive)\s*\(',  # 可能导致阻塞的 FreeRTOS API
    r'\b(?:malloc|free|calloc|realloc)\s*\(',  # ISR 内禁止动态内存
    r'\b(?:printf|snprintf|sprintf)\s*\(',
)

# 6) volatile 寄存器访问缺失检测 — 内存映射指针应有 volatile
_REGISTER_PTR_NO_VOLATILE = (
    r'\*\s*\(\s*(uint\d+_t|unsigned\s+(?:int|char|short|long))\s*\*\s*\)\s*0x'
)

# 7) 局部大数组（栈深度风险）— 排除 static（静态存储不在栈上）
_LOCAL_ARRAY_PATTERN = re.compile(
    r'(?<!static\s)(?:uint\d+_t|int|char|unsigned\s+\w+)\s+(\w+)\s*\[\s*(\d+)\s*\]\s*;'
)


# ============================================================
# 辅助函数
# ============================================================

def _line_no(text, pos):
    """根据字符偏移计算 1-based 行号。"""
    return text[:pos].count("\n") + 1


def _function_bodies(content):
    """粗略切分 C 函数体（按大括号配对的顶层函数）。返回 [(name, body, start_line)]。

    注意：这是正则近似，非完整 C 解析器，仅用于检测定位。
    """
    functions = []
    # 匹配函数定义：返回类型 + 函数名 + (参数) + {
    func_def = re.compile(
        r'(?:^|\n)\s*'
        r'(?:static\s+|inline\s+|__attribute__\(\([^)]+\)\)\s+|volatile\s+)*'
        r'(?:void|int|char|short|long|float|double|unsigned\s+\w+|'
        r'uint\d+_t|int\d+_t|bool|size_t)\s*\*?\s*'
        r'(\w+)\s*\([^;{]*\)\s*\{',
        re.MULTILINE
    )
    for m in func_def.finditer(content):
        name = m.group(1)
        start = m.end() - 1  # '{' 位置
        start_line = _line_no(content, m.start())
        # 大括号配对
        depth = 1
        i = start + 1
        while i < len(content) and depth > 0:
            if content[i] == '{':
                depth += 1
            elif content[i] == '}':
                depth -= 1
            i += 1
        body = content[start:i]
        functions.append((name, body, start_line))
    return functions


# ============================================================
# 主检测入口
# ============================================================

def check_embedded_c_file(filepath, collector, dialect="embedded"):
    """嵌入式 C 文件检测入口（仅 embedded 方言调用）。

    Args:
        filepath: 文件路径
        collector: IssueCollector 实例（鸭子类型，调用 .add(...)）
        dialect: 方言标记（预期为 "embedded"）
    """
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
    except OSError:
        return

    _check_dynamic_alloc(filepath, content, collector)
    _check_recursion(filepath, content, collector)
    _check_goto(filepath, content, collector)
    _check_isr_safety(filepath, content, collector)
    _check_volatile_register(filepath, content, collector)
    _check_local_array_stack(filepath, content, collector)

    # 从注册器加载额外检测器（插件化扩展点）
    extra_detectors = get_detectors("embedded")
    for detector in extra_detectors:
        # 跳过已在本函数中直接调用的检测器
        if hasattr(detector, '_detector_category') and detector._detector_category in (
            'memory', 'recursion', 'goto', 'isr', 'volatile', 'stack'
        ):
            continue  # 已通过原有逻辑调用
        try:
            detector(filepath, content, collector)
        except Exception:
            pass  # 插件检测器异常不影响主流程


# ============================================================
# 单规则检测函数
# ============================================================

@register_detector("embedded", "memory")
def _check_dynamic_alloc(filepath, content, collector):
    """动态内存分配禁用（MISRA 21.x）—— 嵌入式硬禁。"""
    for pat in _DYNAMIC_ALLOC_PATTERNS:
        for m in re.finditer(pat, content):
            line = _line_no(content, m.start())
            call = m.group().strip()
            collector.add(
                "block", "embedded_memory", filepath, line,
                f"嵌入式代码使用动态内存分配: {call}（MISRA C:2012 Dir 21 建议禁用）",
                "改用静态分配/内存池/固定大小缓冲区，避免堆碎片与分配失败风险",
                confidence=92,
            )


@register_detector("embedded", "recursion")
def _check_recursion(filepath, content, collector):
    """递归调用检测（MISRA 17.2）—— 嵌入式硬禁（栈溢出风险）。"""
    functions = _function_bodies(content)
    names = {n for n, _, _ in functions}
    for name, body, start_line in functions:
        # 在函数体内检测自调用
        call_pat = re.compile(r'\b' + re.escape(name) + r'\s*\(')
        for m in call_pat.finditer(body):
            line = start_line + _line_no(body, m.start()) - 1
            collector.add(
                "block", "embedded_recursion", filepath, line,
                f"函数 {name} 存在递归调用（MISRA C:2012 17.2 禁用）",
                "改写为迭代实现；嵌入式栈空间有限，递归易导致栈溢出",
                confidence=90,
            )


@register_detector("embedded", "goto")
def _check_goto(filepath, content, collector):
    """goto 使用检测（MISRA 15.x 建议限制）。"""
    functions = _function_bodies(content)
    for name, body, start_line in functions:
        gotos = _GOTO_PATTERN.findall(body)
        if len(gotos) >= _GOTO_WARN_COUNT:
            line = start_line
            collector.add(
                "warn", "embedded_goto", filepath, line,
                f"函数 {name} 使用 {len(gotos)} 处 goto（MISRA C:2012 15.x 建议限制）",
                "改用结构化控制流（if/switch/break/continue）替代 goto",
                confidence=82,
            )


def _locate_function_body(content, start):
    """从函数定义位置向后定位函数体（大括号配对）。

    Returns:
        函数体字符串（含大括号），找不到返回 None。
    """
    brace = content.find('{', start)
    if brace == -1:
        return None
    depth = 1
    i = brace + 1
    while i < len(content) and depth > 0:
        if content[i] == '{':
            depth += 1
        elif content[i] == '}':
            depth -= 1
        i += 1
    return content[brace:i]


def _iter_isr_bodies(content):
    """迭代 ISR 函数体，yield (line, body)。"""
    for def_pat in _ISR_DEF_PATTERNS:
        for m in re.finditer(def_pat, content):
            body = _locate_function_body(content, m.start())
            if body is not None:
                yield _line_no(content, m.start()), body


def _check_isr_blocking_calls(filepath, body, line, collector):
    """检测 ISR 内的阻塞/重型调用。"""
    for call_pat in _ISR_BLOCKING_CALLS:
        for cm in re.finditer(call_pat, body):
            call_line = line + _line_no(body, cm.start()) - 1
            collector.add(
                "block", "embedded_isr", filepath, call_line,
                f"ISR 内调用阻塞/重型函数: {cm.group().strip()}",
                "ISR 应保持短小、无阻塞；将耗时操作移至主循环或任务队列处理",
                confidence=90,
            )


def _check_isr_length(filepath, body, line, collector):
    """ISR 函数体长度检查。"""
    body_lines = body.count("\n")
    if body_lines > _ISR_MAX_LINES:
        collector.add(
            "warn", "embedded_isr", filepath, line,
            f"ISR 函数体 {body_lines} 行，超过建议上限 {_ISR_MAX_LINES} 行",
            "拆分 ISR：ISR 内仅置标志位，实际处理移至主循环/任务",
            confidence=80,
        )


@register_detector("embedded", "isr")
def _check_isr_safety(filepath, content, collector):
    """ISR 安全检测：ISR 内禁止阻塞/重型调用 + ISR 过长提示。"""
    for line, body in _iter_isr_bodies(content):
        _check_isr_blocking_calls(filepath, body, line, collector)
        _check_isr_length(filepath, body, line, collector)


@register_detector("embedded", "volatile")
def _check_volatile_register(filepath, content, collector):
    """volatile 正确性：内存映射寄存器指针必须 volatile。"""
    for m in re.finditer(_REGISTER_PTR_NO_VOLATILE, content):
        line = _line_no(content, m.start())
        collector.add(
            "warn", "embedded_volatile", filepath, line,
            f"内存映射寄存器指针未使用 volatile: {m.group().strip()}",
            "寄存器访问必须加 volatile 防止编译器优化掉读/写（如 *(volatile uint32_t*)0x...）",
            confidence=85,
        )


@register_detector("embedded", "stack")
def _check_local_array_stack(filepath, content, collector):
    """栈深度：局部大数组检测（嵌入式 RAM 受限）。"""
    for m in _LOCAL_ARRAY_PATTERN.finditer(content):
        arr_name = m.group(1)
        arr_size = int(m.group(2))
        # 估算字节数（按 int/uint32_t 4 字节粗估，仅作启发式）
        est_bytes = arr_size * 4
        if est_bytes > _STACK_ARRAY_MAX_BYTES:
            line = _line_no(content, m.start())
            collector.add(
                "warn", "embedded_stack", filepath, line,
                f"局部数组 {arr_name}[{arr_size}] 估算占用 {est_bytes} 字节栈空间（超出 {_STACK_ARRAY_MAX_BYTES} 字节建议值）",
                "大数组改用 static 或全局/静态内存池，避免栈溢出",
                confidence=78,
            )


# ============================================================
# Phase 3 扩展检测器：ISR优先级 / 看门狗 / 电源管理
# ============================================================

@register_detector("embedded", "isr_priority")
def _check_isr_priority(filepath, content, collector):
    """ISR优先级分组配置检测。

    检查NVIC优先级分组是否在初始化时正确设置。
    """
    has_priority_group = bool(re.search(r'NVIC_SetPriorityGrouping\s*\(', content))
    # 仅匹配裸 NVIC_SetPriority（CMSIS 层），HAL_NVIC_SetPriority 依赖 HAL_Init 已设置的分组，不算违规
    has_priority_set = bool(re.search(r'(?<!HAL_)NVIC_SetPriority\s*\(', content))
    if has_priority_set and not has_priority_group:
        collector.add(
            "warn", "embedded_isr_priority", filepath, 0,
            "设置了中断优先级(NVIC_SetPriority)但未配置优先级分组(NVIC_SetPriorityGrouping)",
            "在系统初始化时调用NVIC_SetPriorityGrouping()确保优先级分组正确",
            confidence=82,
        )


@register_detector("embedded", "watchdog")
def _check_watchdog(filepath, content, collector):
    """看门狗配置和喂狗逻辑检测。

    启用了看门狗但未找到喂狗调用，可能导致系统复位。
    """
    has_wdg_init = bool(re.search(r'(?:IWDG|WWDG)_Init\s*\(', content))
    has_wdg_enable = bool(re.search(r'(?:IWDG|WWDG)_Enable\s*\(', content))

    if has_wdg_init or has_wdg_enable:
        has_reload = bool(re.search(r'(?:IWDG|WWDG)_(?:ReloadCounter|Refresh)\s*\(', content))
        if not has_reload:
            collector.add(
                "block", "embedded_watchdog", filepath, 0,
                "启用了看门狗但未找到喂狗(IWDG_ReloadCounter)调用，可能导致系统复位",
                "在主循环或RTOS任务中定期调用喂狗函数",
                confidence=90,
            )


@register_detector("embedded", "power_mgmt")
def _check_power_mgmt(filepath, content, collector):
    """电源管理检测。

    检查低功耗模式配置和唤醒源设置。
    """
    has_sleep = bool(re.search(r'__WFI\s*\(\s*\)|__WFE\s*\(\s*\)|PWR_EnterSleepMode\s*\(', content))
    has_wakeup_source = bool(re.search(
        r'EXTI_LineConfig\s*\(|RTC_AlarmCmd\s*\(|PWR_WakeUpPinCmd\s*\(', content))

    if has_sleep and not has_wakeup_source:
        collector.add(
            "info", "embedded_power_mgmt", filepath, 0,
            "使用低功耗模式(WFI/WFE/SleepMode)但未检测到唤醒源配置",
            "确保配置了EXTI/RTC/WakeUp Pin等唤醒源，否则系统无法从低功耗模式恢复",
            confidence=70,
        )
