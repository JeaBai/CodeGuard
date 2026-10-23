#!/usr/bin/env python3
"""
quality_c_dialect.py — C 方言分类器
=====================================
区分「通用 C/C++ 开发」与「嵌入式 C 开发」的唯一判定入口。

设计目标（对齐嵌入式 C/C++ 全覆盖实施计划）：
  - 单一职责：只做方言识别，不直接产出 issue
  - O(n) 单次正则扫描，无性能负担
  - 显式覆盖优先级最高（rules.json `_c_dialect` 字段）
  - 零外部依赖，后续可扩展 Ada/Rust 嵌入式

判定结果：
  "generic"        — 通用 C/C++ 项目（桌面/服务端/算法）
  "embedded"       — 嵌入式 C（裸机/RTOS/单片机/固件）
  "rust-embedded"  — Rust 嵌入式（no_std / cortex_m / embedded_hal）

用法：
  from quality_c_dialect import detect_c_dialect
  dialect = detect_c_dialect(filepath, content, explicit="auto")
"""

import os
import re

# ============================================================
# 项目级显式方言覆盖（由 quality_check 启动时从 rules.json 读取）
# ============================================================

_EXPLICIT_DIALECT = "auto"


def set_explicit_dialect(dialect):
    """设置项目级显式方言（"auto" / "generic" / "embedded"）。

    由 quality_check.run_quality_check 启动时从 .code-guardian/rules.json
    的 `_c_dialect` 字段读取并调用。非法值静默忽略（保持 auto）。
    """
    global _EXPLICIT_DIALECT  # codeguard: ignore GOLD_NO_GLOBAL_STATE
    if dialect in ("auto", "generic", "embedded", "rust-embedded"):
        _EXPLICIT_DIALECT = dialect


def get_explicit_dialect():
    """返回当前项目级显式方言设置。"""
    return _EXPLICIT_DIALECT


# ============================================================
# 嵌入式信号特征（按优先级分组）
# ============================================================

# 1) RTOS / 嵌入式操作系统头文件（强信号）
_RTOS_HEADERS = (
    "freertos.h", "freertosconfig.h", "task.h", "queue.h", "semphr.h",
    "zephyr.h", "zephyr/kernel.h", "rtthread.h", "ucos_ii.h", "os.h",
    "mbed.h", "arduino.h", "ch.h", "chthreads.h", "ti/sysbios", "embos.h",
)

# 2) MCU / 厂商 SDK 头文件（强信号）
_MCU_HEADERS = (
    "stm32f", "stm32h", "stm32l", "stm32g", "esp32", "esp8266",
    "nrf52", "nrf_drv", "samd", "samc", "msp430", "avr/io", "avr/interrupt",
    "pic", "mk64f", "imxrt", "gd32", "hc32", "cw32", "apm32", "ch32",
    "at32", "lpc17", "lpc40", "tm4c", "stm8",
)

# 3) ISR / 中断服务程序定义特征
_ISR_PATTERNS = (
    r'__attribute__\s*\(\s*\(\s*interrupt',
    r'__attribute__\s*\(\s*\(\s*signal',
    r'\bISR\s*\(\s*[A-Za-z_0-9_]+\s*\)',
    r'\bIRQHandler\s*\(',          # CMSIS 命名约定
    r'\b__irq\b',
    r'\binterrupt\s+void\b',
    r'\bvoid\s+\w*_isr\s*\(',
    r'\bISR_ATTR\b',
)

# 4) 寄存器映射 / 内存映射 I/O（volatile 指针 + 十六进制地址）
_REGISTER_PATTERNS = (
    r'\*\s*\(\s*volatile\s+(?:uint\d+_t|unsigned\s+(?:int|char|short|long))\s*\*\s*\)\s*0x',
    r'#\s*define\s+\w+\s+\*\s*\(\s*volatile\s+',
    r'\*\(\s*volatile\s+uint\d+_t\s*\*\s*\)',
)

# 5) 链接脚本 / 特殊 section 特征
_LINKER_PATTERNS = (
    r'\bSECTIONS\s*\{',            # 链接脚本
    r'\bMEMORY\s*\{',              # 链接脚本内存布局
    r'__attribute__\s*\(\s*\(\s*section\s*\(\s*"\.',
    r'\.isr_vector',               # 中断向量表
)

# 6) 内联汇编 / 直接寄存器访问
_ASM_PATTERNS = (
    r'\basm\s+volatile\b',
    r'\b__asm\b',
    r'\b__asm__\s*\(',
    r'\basm\s*\(',
)

# 7) 裸机特征（无 OS 直接操作硬件寄存器）
_BAREMETAL_PATTERNS = (
    r'\bSREG\b',                   # AVR 状态寄存器
    r'\bPORT[A-Z]\b\s*=',          # AVR 端口写
    r'\bDDR[A-Z]\b\s*=',           # AVR 数据方向寄存器
    r'\bGPIO[A-Z0-9_]*\s*->',      # STM32 GPIO 结构体访问
    r'\bRCC->',                    # STM32 时钟控制
    r'\bNVIC_',                    # 嵌套向量中断控制器
)


def _match_any(content, patterns):
    """检查内容是否命中任意模式。返回命中数量。"""
    hits = 0
    for pat in patterns:
        if re.search(pat, content):
            hits += 1
    return hits


# ============================================================
# Rust 嵌入式信号特征
# ============================================================

RUST_EMBEDDED_SIGNALS = {
    'no_std': r'#!\[no_std\]',
    'cortex_m': r'use\s+cortex_m\b',
    'embedded_hal': r'use\s+embedded_hal\b',
    'rp_pico': r'use\s+rp_pico\b',
    'stm32_hal': r'use\s+stm32f\d*xx_hal\b',
    'nrf_hal': r'use\s+nrf\d*xx_hal\b',
    'esp_hal': r'use\s+esp_idf_(?:hal|svc)\b',
    'defmt': r'use\s+defmt\b',
    'rtic': r'use\s+rtic\b',
    'panic_halt': r'use\s+panic_halt\b',
}


def detect_rust_embedded(file_path: str, content: str) -> bool:
    """检测文件是否为Rust嵌入式代码。

    通过特征信号(no_std, cortex_m, embedded_hal等)判断。
    """
    if not file_path.endswith('.rs'):
        return False

    # 至少匹配2个信号才判定为rust-embedded
    match_count = 0
    for signal_name, pattern in RUST_EMBEDDED_SIGNALS.items():
        if re.search(pattern, content):
            match_count += 1

    # no_std是强信号，单独匹配也判定
    if re.search(RUST_EMBEDDED_SIGNALS['no_std'], content):
        return True

    return match_count >= 2


def detect_c_dialect(filepath, content, explicit="auto"):
    """识别 C/C++/Rust 文件方言。

    Args:
        filepath: 文件路径（str 或 Path）
        content: 文件内容（str）
        explicit: 显式方言覆盖，取值 "auto" / "generic" / "embedded" / "rust-embedded"

    Returns:
        "generic" / "embedded" / "rust-embedded"
    """
    # 1) 显式覆盖优先级最高
    if explicit in ("generic", "embedded", "rust-embedded"):
        return explicit

    # 2) Rust embedded 检测（.rs 文件优先判定）
    path_str = str(filepath)
    if path_str.endswith('.rs'):
        if detect_rust_embedded(path_str, content):
            return "rust-embedded"
        return "generic"

    # 3) 文件扩展名硬信号
    path = path_str.lower()
    ext = os.path.splitext(path)[1]
    if ext in (".ld", ".s"):
        return "embedded"

    # 4) 内容信号加权判定
    score = 0

    # RTOS / MCU 头文件（每个 +3，强信号）
    include_lines = re.findall(r'#\s*include\s*[<"]([^>"]+)[>"]', content)
    include_text = " ".join(include_lines).lower()
    for hdr in _RTOS_HEADERS:
        if hdr in include_text:
            score += 3
    for hdr in _MCU_HEADERS:
        if hdr in include_text:
            score += 3

    # ISR 定义（每个 +2）
    score += _match_any(content, _ISR_PATTERNS) * 2

    # 寄存器映射（每个 +2）
    score += _match_any(content, _REGISTER_PATTERNS) * 2

    # 链接脚本 / section（每个 +2）
    score += _match_any(content, _LINKER_PATTERNS) * 2

    # 内联汇编（每个 +1）
    score += _match_any(content, _ASM_PATTERNS)

    # 裸机特征（每个 +1）
    score += _match_any(content, _BAREMETAL_PATTERNS)

    # 阈值：>=3 判定为 embedded，避免单次弱命中误判
    if score >= 3:
        return "embedded"
    return "generic"


# 信号分组描述（数据驱动，供 dialect_reason 使用）
_SIGNAL_DESCRIPTIONS = (
    ("检测到 ISR 中断服务程序定义", _ISR_PATTERNS),
    ("检测到内存映射寄存器 (volatile 指针)", _REGISTER_PATTERNS),
    ("检测到链接脚本/section 特征", _LINKER_PATTERNS),
    ("检测到内联汇编", _ASM_PATTERNS),
    ("检测到裸机寄存器操作", _BAREMETAL_PATTERNS),
)


def _collect_embedded_signals(content, include_text):
    """收集嵌入式信号描述，返回原因列表。"""
    reasons = []
    rtos_hits = [h for h in _RTOS_HEADERS if h in include_text]
    mcu_hits = [h for h in _MCU_HEADERS if h in include_text]
    if rtos_hits:
        reasons.append(f"RTOS 头文件: {', '.join(rtos_hits[:3])}")
    if mcu_hits:
        reasons.append(f"MCU SDK 头文件: {', '.join(mcu_hits[:3])}")
    for desc, patterns in _SIGNAL_DESCRIPTIONS:
        if _match_any(content, patterns):
            reasons.append(desc)
    return reasons


def _include_text(content):
    """提取 #include 头文件名并归一化为小写文本。"""
    include_lines = re.findall(r'#\s*include\s*[<"]([^>"]+)[>"]', content)
    return " ".join(include_lines).lower()


def dialect_reason(filepath, content, explicit="auto"):
    """返回方言判定结果 + 命中的信号明细（用于日志/调试）。

    Returns:
        (dialect, [信号描述列表])
    """
    if explicit in ("generic", "embedded", "rust-embedded"):
        return explicit, [f"显式覆盖 _c_dialect={explicit}"]

    path_str = str(filepath)
    if path_str.endswith('.rs'):
        if detect_rust_embedded(path_str, content):
            return "rust-embedded", ["Rust 嵌入式信号: no_std / cortex_m / embedded_hal"]
        return "generic", ["Rust 文件但无嵌入式信号"]

    ext = os.path.splitext(str(filepath).lower())[1]
    if ext in (".ld", ".s"):
        return "embedded", [f"文件扩展名 {ext} 为链接脚本/汇编"]

    reasons = _collect_embedded_signals(content, _include_text(content))
    dialect = detect_c_dialect(filepath, content, explicit)
    return dialect, reasons
