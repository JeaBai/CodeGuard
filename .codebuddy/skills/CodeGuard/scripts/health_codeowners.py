#!/usr/bin/env python3
"""module_health 子模块 — CODEOWNERS 解析与所有权计算 (v1.3.0 P0b)
============================================================
从 module_health.py 拆分的独立子模块，提供 GitHub CODEOWNERS 文件的
解析、模块路径模式匹配与所有权映射计算。

函数：
  parse_codeowners(codeowners_path)                → 解析 CODEOWNERS 规则
  _match_codeowners_pattern(module_path, patterns) → 模块路径匹配
  compute_codeowners_ownership(modules, path)      → 所有权映射

被 module_health.py 通过 re-export 聚合，外部仍可用：
  from module_health import compute_codeowners_ownership
"""

from __future__ import annotations

import fnmatch
import os
from typing import Any, Dict, List, Set

import _health_common as _c


def parse_codeowners(codeowners_path: str) -> Dict[str, List[str]]:
    """解析 GitHub CODEOWNERS 文件。

    返回：{glob_pattern: [owners_list], ...}
    忽略空行和 # 注释行。
    """
    if not os.path.isfile(codeowners_path):
        _c._log(f"CODEOWNERS 文件不存在: {codeowners_path}")
        return {}

    patterns: Dict[str, List[str]] = {}
    with open(codeowners_path, "r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            parts = stripped.split()
            if len(parts) < 2:
                continue
            pattern = parts[0]
            owners = [p.lstrip("@") for p in parts[1:]]
            patterns[pattern] = owners

    _c._log(f"CODEOWNERS 加载: {len(patterns)} 条规则")
    return patterns


def _match_codeowners_pattern(module_path: str, patterns: Dict[str, List[str]]) -> List[str]:
    """将模块路径匹配 CODEOWNERS 规则，返回所有者列表。"""
    owners: List[str] = []
    for pattern, pat_owners in patterns.items():
        # 支持目录模式 `/src/` 和文件模式
        if fnmatch.fnmatch(module_path, pattern.strip("/") + "/*"):
            owners.extend(pat_owners)
        elif fnmatch.fnmatch(module_path, pattern.strip("/")):
            owners.extend(pat_owners)
        # 精确目录匹配
        clean_pattern = pattern.strip("/")
        if module_path.startswith(clean_pattern + "/") or module_path == clean_pattern:
            owners.extend(pat_owners)
    return list(set(owners)) if owners else []


def compute_codeowners_ownership(
    modules: Dict[str, Any],
    codeowners_path: str,
) -> Dict[str, Dict[str, Any]]:
    """基于 CODEOWNERS 计算模块所有权映射。

    返回：{module_name: {owners, owner_count, files_matched, uncovered_files}}
    """
    patterns = parse_codeowners(codeowners_path)
    if not patterns:
        return {}

    result: Dict[str, Dict[str, Any]] = {}
    for mod_name, mod_data in modules.items():
        files = mod_data.get("files", [])
        all_owners: Set[str] = set()
        matched = 0
        unmatched = 0

        for fpath in files:
            path_owners = _match_codeowners_pattern(fpath, patterns)
            if path_owners:
                all_owners.update(path_owners)
                matched += 1
            else:
                unmatched += 1

        result[mod_name] = {
            "owners": sorted(all_owners),
            "owner_count": len(all_owners),
            "files_matched": matched,
            "uncovered_files": unmatched,
        }

    return result
