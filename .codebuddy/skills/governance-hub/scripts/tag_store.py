#!/usr/bin/env python3
"""
Governance Hub Tag Manager (v1.0.0)
=====================================
模块标签管理系统 — 与 CodeGuard blueprint_schema.py 的 _VALID_TAGS 白名单对齐。

功能：
  - list_tags()                      列出所有可用标签及说明
  - apply_tag(blueprint, module, tag)  给模块打标签
  - remove_tag(blueprint, module, tag) 移除标签
  - get_constraints(module)            获取模块当前所有标签的合并约束
  - validate_tags(blueprint)           检查标签冲突
  - check_violation(blueprint, module, action)  检查操作是否被标签允许
  - export_constraint_doc(blueprint)   导出人话版本的约束说明文档

用法：
  python tag_manager.py --blueprint <path> --action list
  python tag_manager.py --blueprint <path> --action apply --module <name> --tag <tag>
  python tag_manager.py --blueprint <path> --action remove --module <name> --tag <tag>
  python tag_manager.py --blueprint <path> --action validate
  python tag_manager.py --blueprint <path> --action check --module <name> --action-type <verb>
  python tag_manager.py --blueprint <path> --action export-doc --output <path>

设计依据：
  - 与 CodeGuard blueprint_schema.py 的标签白名单深度集成
  - 标签约束 ai_constraint 字段直接注入 AI 生成上下文（三层防线之第一层）
  - 冲突检测基于 tag_definitions.json 中 conflicts_with 字段
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# ============================================================
# 常量
# ============================================================

_SCRIPT_DIR = Path(__file__).resolve().parent
_TAG_DEFS_PATH = _SCRIPT_DIR / "tag_definitions.json"

_VALID_MODULE_TAGS = frozenset({
    "frozen", "no_split", "allow_split", "leaf_only",
    "shared_util", "global_config", "test_only", "legacy", "core",
})

_VALID_PARAM_TAGS = frozenset({"global_config", "local_only", "immutable"})

_VALID_ACTIONS = frozenset({
    "split_file", "merge_files", "change_api", "add_dependency",
    "copy_function", "new_global_var", "rename_export", "move_code",
    "add_file", "delete_file",
})

# ============================================================
# 工具函数
# ============================================================

def _log(msg: str) -> None:
    sys.stderr.write(f"[TagManager] {msg}\n")
    sys.stderr.flush()


def _load_tag_defs() -> dict:
    """加载 tag_definitions.json。"""
    if not _TAG_DEFS_PATH.exists():
        raise FileNotFoundError(f"标签定义文件不存在: {_TAG_DEFS_PATH}")
    with open(_TAG_DEFS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_blueprint(path: str) -> dict:
    """加载 blueprint JSON 文件。"""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_blueprint(blueprint: dict, path: str) -> None:
    """保存 blueprint JSON 文件。"""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(blueprint, f, indent=2, ensure_ascii=False)
    _log(f"蓝图已更新: {path}")


def _find_module(blueprint: dict, module_name: str) -> dict | None:
    """在蓝图中根据名称查找模块。"""
    for m in blueprint.get("modules", []):
        if m.get("name") == module_name:
            return m
    return None
