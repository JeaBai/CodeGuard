#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fc_common.py — fc-guardian 共享工具（模块复用）

统一「用户代码」与「库/资料目录」的判定，避免参考资料污染检测结果。
各检测器复用 find_user_sources / find_ioc，保证判定口径一致。
"""
import re
from pathlib import Path

# 库/资料/工程目录黑名单（飞控项目常见非用户代码目录）
# 注意：不含 "测试"/"test"/"tests"，避免误杀含这些字样的父目录（如部署路径）
EXCLUDE_DIR_NAMES = {
    "Drivers", "Middlewares", "Libraries",      # HAL/中间件/标准外设库
    "资料", "文档", "doc", "docs",              # 参考资料/文档
    "example", "examples", "demo", "示例",      # 示例代码
    "MDK-ARM", "EWARM", "IAR",                 # IDE 工程目录
    ".git", "__pycache__",                      # 元数据
}

# 用户代码源文件扩展名
_SOURCE_EXTS = {".c", ".cpp", ".h", ".hpp"}


def is_excluded(path):
    """判断路径是否属于库/资料目录。"""
    return any(part in EXCLUDE_DIR_NAMES for part in path.parts)


def find_user_sources(root):
    """查找用户代码源文件（排除库/资料目录）。

    Returns:
        [Path, ...] 用户 .c/.cpp/.h 文件列表
    """
    sources = []
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix not in _SOURCE_EXTS:
            continue
        if is_excluded(p):
            continue
        sources.append(p)
    return sources


def find_ioc(root):
    """查找项目 .ioc 文件（优先项目根目录，排除资料目录）。

    Returns:
        Path 或 None
    """
    # 优先项目根目录的 .ioc
    for p in root.glob("*.ioc"):
        return p
    # 否则递归查找，排除资料目录
    for p in root.rglob("*.ioc"):
        if is_excluded(p):
            continue
        return p
    return None


def _main_c_priority(p):
    """main.c 定位优先级评分：Core/Src=3 > 任意 Src=2 > 其他 main.c=1 > 非 main.c=0。"""
    if p.name != "main.c":
        return 0
    if "Core" in p.parts and "Src" in p.parts:
        return 3
    if "Src" in p.parts:
        return 2
    return 1


def find_main_c(sources):
    """从源文件列表中定位 main.c（优先 Core/Src 或 Src 下的）。

    Returns:
        Path 或 None
    """
    mains = [p for p in sources if p.name == "main.c"]
    if mains:
        return max(mains, key=_main_c_priority)
    return sources[0] if sources else None
