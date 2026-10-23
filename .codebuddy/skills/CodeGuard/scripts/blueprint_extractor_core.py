#!/usr/bin/env python3
"""
CodeGuard Blueprint Extractor (v1.0.0)
======================================
从 blueprint_generator.py 拆分出的文件提取/解析逻辑模块。

包含：
  - 文件收集与模块划分
  - 依赖图构建与循环检测
  - 多语言公共 API 提取（Python/JS/TS/Java/Go/C#/Rust）
  - 参数流与嵌套层级提取
  - 跨文件重复函数检测

设计依据：
  - 与 quality_arch.py 共享 MULTILANG_IMPORT_PATTERNS 实现一致的多语言 import 提取
  - 复用 quality_core 的 count_lines_of_code / strip_comments_and_strings / get_nesting_depth
"""

from __future__ import annotations

import ast
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

# ============================================================
# 内部模块导入（脚本运行目录为 scripts/，支持直接导入同目录模块）
# ============================================================

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

import quality_core as _core  # noqa: E402

# 延迟导入避免循环依赖
_quality_arch = None


def _get_quality_arch():
    global _quality_arch
    if _quality_arch is None:
        import quality_arch as qa
        _quality_arch = qa
    return _quality_arch


# ============================================================
# 常量定义（文件收集相关）
# ============================================================

SKIP_DIRS = frozenset({
    ".git", "__pycache__", "node_modules", "venv", ".venv",
    "dist", "build", "target", ".codebuddy", ".idea", ".vscode",
    ".cursor", "vendor", ".terraform",
})

SOURCE_EXTS = frozenset({
    ".py", ".js", ".ts", ".tsx", ".mjs",
    ".java", ".go", ".cs", ".rs",
    ".cpp", ".c", ".h", ".hpp",
})


# ============================================================
# 工具函数
# ============================================================

def _relpath(filepath: str, root: str) -> str:
    """将绝对路径转为相对于项目根目录的相对路径（正斜杠）。"""
    rel = os.path.relpath(filepath, root)
    return rel.replace("\\", "/")


def _collect_files(root: str) -> list[str]:
    """遍历项目目录收集源码文件，排除 SKIP_DIRS。"""
    files = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        rel_dir = os.path.relpath(dirpath, root)
        if any(part.startswith(".") for part in rel_dir.split(os.sep) if part):
            continue
        for fname in filenames:
            ext = os.path.splitext(fname)[1].lower()
            if ext in SOURCE_EXTS:
                files.append(os.path.join(dirpath, fname))
    return files


# ============================================================
# 模块提取
# ============================================================

def _extract_modules(root: str, all_files: list[str]) -> dict[str, dict]:
    """按一级子目录/根级文件划分模块，提取路径、文件数、总行数。

    Returns:
        {module_name: {path, files: [str], file_count, total_lines}}
    """
    modules: dict[str, dict] = {}
    has_root_files = False

    for filepath in all_files:
        rel = _relpath(filepath, root)
        parts = rel.split("/")

        if len(parts) == 1:
            # 根级文件归入 "__root__" 模块
            has_root_files = True
            module_name = "__root__"
            module_path = "."
        else:
            module_name = parts[0]
            module_path = parts[0]

        if module_name not in modules:
            modules[module_name] = {
                "path": module_path,
                "files": [],
                "file_count": 0,
                "total_lines": 0,
            }
        modules[module_name]["files"].append(filepath)
        modules[module_name]["file_count"] += 1

        # 统计行数
        try:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            modules[module_name]["total_lines"] += _core.count_lines_of_code(content)
        except (OSError, UnicodeDecodeError):
            pass

    # 若只有根级文件且无子目录模块，不设 __root__
    if not has_root_files or len(modules) > 1:
        pass

    return modules
