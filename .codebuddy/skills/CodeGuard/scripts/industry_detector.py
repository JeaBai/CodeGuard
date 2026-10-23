#!/usr/bin/env python3
"""
industry_detector.py — 行业维度自动检测模块 (v1.0.0)
=====================================================
根据项目特征自动检测行业维度 (web/embedded/safety)，用于选择对应的门禁规则集。

检测优先级:
  1. config.json 显式指定 → 直接使用
  2. ISO 26262 / ASIL / IEC 61508 关键词 → safety
  3. C/H/S 文件 + ISR/volatile/register 信号 → embedded
  4. Cargo.toml + no_std/cortex_m → embedded (Rust)
  5. 链接脚本/启动文件存在 → embedded
  6. package.json / requirements.txt → web
  7. 默认 → web

用法:
  from industry_detector import resolve_profile
  industry, profile_path = resolve_profile("/path/to/project")
"""

import json
import os
import re
from pathlib import Path
from typing import Tuple, Optional


# ============================================================
# 信号模式定义
# ============================================================

# 嵌入式 C 信号: ISR 定义、volatile MMIO、寄存器宏
_EMBEDDED_C_SIGNALS = (
    r'\bISR\s*\(\s*[A-Za-z_0-9_]+\s*\)',
    r'\bvoid\s+\w*_isr\s*\(',
    r'\bvoid\s+\w*_IRQHandler\s*\(',
    r'\*\s*\(\s*volatile\s+(?:uint\d+_t|unsigned\s+(?:int|char|short|long))\s*\*\s*\)\s*0x',
    r'#\s*define\s+\w+\s+\*\s*\(\s*volatile\s+',
    r'__IRQ\s|__attribute__\s*\(\(interrupt\)\)',
    r'\bNVIC_\w+\s*\(',
    r'\bHAL_\w+_\w+\s*\(',
    r'\bLL_\w+_\w+\s*\(',
)

# Rust 嵌入式信号
_RUST_EMBEDDED_SIGNALS = (
    r'#!\[no_std\]',
    r'use\s+cortex_m\b',
    r'use\s+embedded_hal\b',
    r'use\s+stm32\d+',
    r'cortex_m_rt::entry',
)

# 安全关键信号
_SAFETY_SIGNALS = (
    r'\bISO\s*26262\b',
    r'\bASIL\s*[ABCD]\b',
    r'\bIEC\s*61508\b',
    r'\bIEC\s*62304\b',
    r'\bfunctional\s*safety\b',
    r'\bsafety.critical\b',
)

# Web/云信号
_WEB_SIGNALS = (
    r'package\.json',
    r'requirements\.txt',
    r'go\.mod',
    r'pom\.xml',
    r'build\.gradle',
    r'Dockerfile',
    r'docker-compose',
)


# ============================================================
# 检测函数
# ============================================================

def _check_embedded_c_files(root: Path) -> bool:
    """检测项目中是否存在嵌入式 C 信号。"""
    max_files = 50  # 限制扫描文件数，避免大项目超时
    count = 0
    for path in root.rglob("*"):
        if count >= max_files:
            break
        if not path.is_file():
            continue
        # 跳过排除目录（含测试/示例/文档目录，防止测试夹具触发误检）
        parts = path.parts
        if any(skip in parts for skip in (
            ".git", "__pycache__", "node_modules", "vendor",
            "third_party", "CMSIS", "Hal", "Drivers",
            "build", "Debug", "Release", ".codebuddy",
            "tests", "test", "testing", "fixtures",
            "samples", "examples", "docs", "doc",
        )):
            continue
        if path.suffix not in (".c", ".h", ".cpp", ".hpp"):
            continue
        count += 1
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
            for pattern in _EMBEDDED_C_SIGNALS:
                if re.search(pattern, content, re.IGNORECASE):
                    return True
        except (OSError, UnicodeDecodeError):
            continue
    return False


def _check_rust_embedded(root: Path) -> bool:
    """检测 Rust 嵌入式项目。"""
    cargo = root / "Cargo.toml"
    if not cargo.exists():
        return False
    try:
        content = cargo.read_text(encoding="utf-8", errors="ignore")
        # 快速检查 no_std
        if "no_std" in content:
            return True
        # 检查嵌入式依赖
        for pattern in _RUST_EMBEDDED_SIGNALS:
            if re.search(pattern, content):
                return True
    except (OSError, UnicodeDecodeError):
        pass

    # 检查 src/ 下的 .rs 文件（跳过测试目录）
    _rust_skip = {"tests", "test", "fixtures", "examples", "benches"}
    src_dir = root / "src"
    if src_dir.exists():
        for rs_file in src_dir.rglob("*.rs"):
            if _rust_skip.intersection(rs_file.parts):
                continue
            try:
                content = rs_file.read_text(encoding="utf-8", errors="ignore")
                for pattern in _RUST_EMBEDDED_SIGNALS:
                    if re.search(pattern, content):
                        return True
            except (OSError, UnicodeDecodeError):
                continue
    return False


def _check_toolchain_files(root: Path) -> bool:
    """检测嵌入式工具链文件 (链接脚本/启动文件/交叉编译配置)。"""
    # 排除测试/示例/文档目录，防止测试夹具触发误检
    _skip_parts = {".git", "node_modules", "tests", "test", "testing",
                   "fixtures", "samples", "examples", "docs", "doc",
                   ".codebuddy", "vendor", "third_party"}

    # 链接脚本
    for ld in root.rglob("*.ld"):
        if not _skip_parts.intersection(ld.parts):
            return True

    # 启动文件
    for pattern in ("*startup*", "*_startup*", "*vector*"):
        for f in root.rglob(pattern):
            if f.suffix in (".s", ".S", ".c") and not _skip_parts.intersection(f.parts):
                return True

    # Makefile 中的交叉编译工具链
    for mf in root.rglob("Makefile"):
        if _skip_parts.intersection(mf.parts):
            continue
        try:
            content = mf.read_text(encoding="utf-8", errors="ignore")
            if re.search(r'arm-none-eabi|arm-linux-gnueabi|riscv\d+-', content):
                return True
        except (OSError, UnicodeDecodeError):
            continue

    # CMakeLists.txt 中的交叉编译配置
    for cm in root.rglob("CMakeLists.txt"):
        if _skip_parts.intersection(cm.parts):
            continue
        try:
            content = cm.read_text(encoding="utf-8", errors="ignore")
            if re.search(r'CMAKE_TOOLCHAIN_FILE|cross.compil|arm-none-eabi', content, re.IGNORECASE):
                return True
        except (OSError, UnicodeDecodeError):
            continue

    return False


def _check_safety_signals(root: Path) -> bool:
    """检测安全关键项目标记。"""
    # 检查文档中的安全标准关键词
    doc_dirs = [root, root / "docs", root / "doc"]
    for doc_dir in doc_dirs:
        if not doc_dir.exists():
            continue
        for pattern in ("*.md", "*.txt", "*.rst", "*.pdf"):
            for f in doc_dir.glob(pattern):
                try:
                    content = f.read_text(encoding="utf-8", errors="ignore")
                    for pat in _SAFETY_SIGNALS:
                        if re.search(pat, content, re.IGNORECASE):
                            return True
                except (OSError, UnicodeDecodeError):
                    continue

    # 检查 safety/ 或 asil/ 目录
    for dir_name in ("safety", "asil", "functional_safety"):
        if (root / dir_name).exists():
            return True

    return False


def _check_web_signals(root: Path) -> bool:
    """检测 Web/云项目标记。"""
    for signal in _WEB_SIGNALS:
        if (root / signal).exists():
            return True
    return False


def detect_industry(project_root: str) -> str:
    """根据项目特征自动检测行业维度。

    Args:
        project_root: 项目根目录路径

    Returns:
        "web" | "embedded" | "safety"
    """
    root = Path(project_root)

    # 1. 安全关键信号 (最高优先级)
    if _check_safety_signals(root):
        return "safety"

    # 2. 嵌入式 C 信号
    if _check_embedded_c_files(root):
        return "embedded"

    # 3. Rust 嵌入式信号
    if _check_rust_embedded(root):
        return "embedded"

    # 4. 工具链文件信号
    if _check_toolchain_files(root):
        return "embedded"

    # 5. Web/云信号
    if _check_web_signals(root):
        return "web"

    # 6. 默认
    return "web"


def get_config(project_root: str) -> Optional[dict]:
    """读取 .code-guardian/config.json 配置。

    Returns:
        配置字典，或 None（配置文件不存在时）
    """
    config_path = os.path.join(project_root, ".code-guardian", "config.json")
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError, KeyError):
        return None


def resolve_profile(project_root: str) -> Tuple[str, str, Optional[str]]:
    """解析最终的行业配置和规则集路径。

    Args:
        project_root: 项目根目录路径

    Returns:
        (industry, gate_level, profile_path)
        - industry: "web" | "embedded" | "safety"
        - gate_level: "gold" | "silver" | "bronze"
        - profile_path: 规则集文件路径 (相对于 .code-guardian/)，或 None
    """
    config = get_config(project_root)
    config_dir = os.path.join(project_root, ".code-guardian")

    # 读取配置值
    if config:
        industry_setting = config.get("industry", "auto")
        gate_level = config.get("gate_level", "gold")
    else:
        industry_setting = "auto"
        gate_level = "gold"

    # 解析行业
    if industry_setting == "auto":
        industry = detect_industry(project_root)
    else:
        industry = industry_setting

    # 映射到规则集文件 (None = 使用现有 rules.json / rules-silver.json)
    profile_map = {
        ("web", "gold"): None,          # 使用现有 rules.json
        ("web", "silver"): "rules-silver.json",  # 使用现有 rules-silver.json
        ("web", "bronze"): None,        # 回退到内置 bronze 阈值
        ("embedded", "gold"): "profiles/embedded-gold.json",
        ("embedded", "silver"): "profiles/embedded-silver.json",
        ("embedded", "bronze"): None,
        ("safety", "gold"): "profiles/safety-gold-asil-dc.json",
        ("safety", "silver"): "profiles/safety-silver-asil-ba.json",
        ("safety", "bronze"): None,
    }

    profile_path = profile_map.get((industry, gate_level))

    # 检查规则集文件是否存在
    if profile_path:
        full_path = os.path.join(config_dir, profile_path)
        if not os.path.exists(full_path):
            # 回退到 web-gold (现有 rules.json)
            profile_path = None

    return industry, gate_level, profile_path


if __name__ == "__main__":
    import sys
    root = sys.argv[1] if len(sys.argv) > 1 else "."
    industry, level, profile = resolve_profile(root)
    print(f"Industry: {industry}")
    print(f"Gate Level: {level}")
    print(f"Profile: {profile or '(built-in)'}")
