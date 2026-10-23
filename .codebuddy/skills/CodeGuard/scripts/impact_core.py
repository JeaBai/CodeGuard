#!/usr/bin/env python3
"""
CodeGuard Impact Analyzer (v1.0.0)
=====================================
变更影响分析系统 — 在代码变更前评估对全局的影响范围。
支持四维分析 + 多语言 + 架构蓝图集成。

分析能力：
  - analyze_change(file, function, change_type)    函数签名变更影响
  - analyze_file_move(file)                         文件移动/删除影响
  - analyze_global_var(name)                        全局变量变更影响
  - analyze_module_dep(module, change_type)         模块依赖变更影响

用法：
  python impact_analyzer.py --action analyze --file src/auth/login.py --function login --change add_param
  python impact_analyzer.py --action file-move --file src/old/location.py
  python impact_analyzer.py --action global-var --name DATABASE_URL
  python impact_analyzer.py --action module-dep --module auth_service --change remove_dep

设计依据：
  - 与 architecture_blueprint.json 集成加速模块级分析
  - 与 L2 context detail 集成获取函数调用关系
  - 复用 quality_core 的 strip_comments_and_strings + AST 函数
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

# ============================================================
# 内部导入
# ============================================================

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

import quality_core as _core  # noqa: E402

# ============================================================
# 常量
# ============================================================

_REPORTS_DIR = ".codebuddy/impact_reports"

_SKIP_DIRS = frozenset({
    ".git", "__pycache__", "node_modules", "venv", ".venv",
    "dist", "build", "target", ".codebuddy", ".idea", ".vscode",
    ".cursor", "vendor", ".terraform",
})

_SOURCE_EXTS = frozenset({
    ".py", ".js", ".ts", ".tsx", ".mjs", ".java", ".go", ".cs", ".rs",
})

_CHANGE_TYPES = frozenset({
    "add_param", "remove_param", "change_return", "rename", "delete",
})

# ============================================================
# 工具函数
# ============================================================

def _log(msg: str) -> None:
    sys.stderr.write(f"[Impact] {msg}\n")
    sys.stderr.flush()


def _collect_files(root: str) -> list[str]:
    files = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS and not d.startswith(".")]
        for fname in filenames:
            if os.path.splitext(fname)[1].lower() in _SOURCE_EXTS:
                files.append(os.path.join(dirpath, fname))
    return files


def _rel(path: str, root: str) -> str:
    return os.path.relpath(path, root).replace("\\", "/")


def _detect_lang(filepath: str) -> str:
    ext = os.path.splitext(filepath)[1].lower()
    return {
        ".py": "python", ".js": "javascript", ".ts": "javascript",
        ".tsx": "javascript", ".mjs": "javascript", ".java": "java",
        ".go": "go", ".cs": "csharp", ".rs": "rust",
    }.get(ext, "unknown")


def _read_file(filepath: str) -> str | None:
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except (OSError, UnicodeDecodeError):
        return None


def _load_blueprint(project_root: str) -> dict | None:
    candidates = [
        os.path.join(project_root, "architecture_blueprint.json"),
        os.path.join(project_root, ".codebuddy", "architecture_blueprint.json"),
    ]
    for bp in candidates:
        if os.path.isfile(bp):
            try:
                return json.loads(open(bp, "r", encoding="utf-8").read())
            except (json.JSONDecodeError, OSError):
                pass
    return None


# ============================================================
# 报告保存
# ============================================================

def _save_report(project_root: str, result: dict, tag: str) -> dict:
    """保存分析报告到 .codebuddy/impact_reports/。"""
    reports_dir = os.path.join(project_root, _REPORTS_DIR)
    os.makedirs(reports_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    fname = f"{tag}_{ts}.json"
    fpath = os.path.join(reports_dir, fname)
    result["report_file"] = fpath
    result["generated_at"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")
    with open(fpath, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False, default=str)
    _log(f"报告已保存: {fpath}")
    return result


def _save_or_return(project_root: str, result: dict, tag: str) -> dict:
    return _save_report(project_root, result, tag)


def _infer_root(start: str) -> str:
    for _ in range(5):
        if os.path.isdir(os.path.join(start, ".codebuddy")):
            return start
        parent = os.path.dirname(start)
        if parent == start:
            break
        start = parent
    return start
