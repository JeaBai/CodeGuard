#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""refresh_checker.py — 飞控控制循环刷新率/阻塞延迟检测

检测 main.c 主循环 + 定时器中断/RTOS 任务：
  - fc-refresh-no-loop: 主循环无固定控制周期（缺定时器中断/RTOS 任务调度）（warn）
  - fc-refresh-blocking-delay: 控制循环内阻塞延时（HAL_Delay/vTaskDelay）（block）

对标 PX4 调度规范：飞控控制循环须有固定周期（如 400Hz），阻塞延时破坏实时性。
"""
import re
from pathlib import Path

import fc_common


def _find_c_sources(root):
    """查找飞控核心源码（排除库/资料目录）。"""
    sources = fc_common.find_user_sources(root)
    # 只保留 .c/.cpp（refresh 检测关注实现，不看头文件）
    return [p for p in sources if p.suffix in (".c", ".cpp")]


def check_control_loop(root, collector):
    """检测主循环是否有固定控制周期。

    判定：存在定时器中断回调（HAL_TIM_PeriodElapsedCallback）或 RTOS 任务
    （xTaskCreate/osThreadNew）或 SysTick 定时控制，则视为有固定周期。
    """
    sources = _find_c_sources(root)
    if not sources:
        return

    has_fixed_period = False
    for p in sources:
        text = p.read_text(encoding="utf-8", errors="ignore")
        # 固定周期信号
        if re.search(r'HAL_TIM_PeriodElapsedCallback', text):
            has_fixed_period = True
        if re.search(r'xTaskCreate|osThreadNew|vTaskDelayUntil', text):
            has_fixed_period = True
        # SysTick 计数器控制
        if re.search(r'HAL_GetTick\(\)|uwTick', text):
            has_fixed_period = True

    if not has_fixed_period:
        main_c = fc_common.find_main_c(sources)
        if main_c is None:
            return
        collector.add(
            "warn", "fc_refresh", str(main_c), 0,
            "主循环未检测到固定控制周期（缺定时器中断/RTOS 任务调度）",
            "使用定时器中断（如 TIM 周期回调）或 RTOS 任务实现固定频率控制循环",
            confidence=75,
        )


def _is_blocking_delay(line):
    """判断是否阻塞延时调用（HAL_Delay/vTaskDelay）。"""
    return bool(re.search(r'HAL_Delay\s*\(|vTaskDelay\s*\(|osDelay\s*\(', line))


def _is_control_loop_context(line):
    """判断是否进入控制循环上下文（while(1)/for(;;) 主循环 或 定时器回调）。

    v3.0.0: 移除 IRQHandler/ISR 分支 —— 普通中断内的阻塞调用交由嵌入式管理
    (embedded_isr) 检测，避免 fc_refresh 与 embedded_isr 规则重叠。
    """
    if re.search(r'while\s*\(\s*1\s*\)|for\s*\(\s*;\s*;\s*\)', line):
        return True
    # 定时器回调（飞控控制循环载体）
    if re.search(r'HAL_TIM_PeriodElapsedCallback', line):
        return True
    return False


def _scan_for_blocking_delay(lines, path, collector):
    """三态状态机 + 大括号深度跟踪，精确界定控制循环块边界。

    state: outside（块外）/ pending（已见控制循环关键字，等 `{` 开块）/ inside（块内）。
    块闭合（depth 回落到 control_depth）时自动复位，消除跨块误报。

    v3.0.0: 修复 in_control_ctx 布尔标志永不复位缺陷 —— 原实现一旦匹配
    控制循环关键字就置 True，导致 while(1) 块闭合后其他函数的 HAL_Delay 被误报。
    """
    state = "outside"
    depth = 0
    control_depth = 0
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        opens = stripped.count("{")
        closes = stripped.count("}")
        if state == "outside" and _is_control_loop_context(stripped):
            state = "pending"
            control_depth = depth
        if state == "pending" and opens > 0:
            state = "inside"
        if state == "inside" and _is_blocking_delay(stripped):
            collector.add(
                "block", "fc_refresh", str(path), i,
                f"控制循环/中断内使用阻塞延时: {stripped[:60]}",
                "阻塞延时破坏实时性；改用定时器中断/非阻塞状态机调度",
                confidence=90,
            )
        depth += opens - closes
        if state == "inside" and depth <= control_depth:
            state = "outside"


def check_blocking_delay(root, collector):
    """检测控制循环/中断回调内的阻塞延时调用。

    阻塞延时在主循环破坏刷新率，在定时器回调/ISR 中则直接锁死中断，
    是飞控失控的直接原因。
    """
    sources = _find_c_sources(root)
    if not sources:
        return

    for p in sources:
        text = p.read_text(encoding="utf-8", errors="ignore")
        _scan_for_blocking_delay(text.splitlines(), p, collector)


def scan_refresh(root, collector):
    """刷新率检测入口。"""
    check_control_loop(root, collector)
    check_blocking_delay(root, collector)
