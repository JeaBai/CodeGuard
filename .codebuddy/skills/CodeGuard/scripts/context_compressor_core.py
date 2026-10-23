#!/usr/bin/env python3
"""
CodeGuard Context Compressor (v1.0.0)
========================================
分层上下文压缩系统 — 将项目知识按 L0→L3 四级粒度压缩，
使 AI 每次会话只加载必要上下文，节省 token 同时保持架构感知。

四层结构：
  L0 (全项目级) — architecture_blueprint.json 精简版 (≤500行)
  L1 (模块组级) — 每模块组一份 contract.md (≤200行/组)
  L2 (单模块级) — 每模块一份 detail.md (≤100行/模块)
  L3 (源文件级) — 原始代码（仅加载待修改文件）

功能：
  generate_all(project_path, blueprint_path, output_dir)    生成全部 L0-L3
  generate_l0(blueprint_path)                                从蓝图生成 L0 精简版
  generate_l1(project_path, module_name, blueprint_path)     生成 L1 contract.md
  generate_l2(project_path, module_name, blueprint_path)     生成 L2 detail.md
  get_context_for_task(task, blueprint, l1_dir, l2_dir)      智能上下文选择 (见 context_selector.py)
  refresh(file_path)                                         增量刷新 L2 (见 context_selector.py)

用法：
  python context_compressor.py --action generate-all --project . --blueprint blueprint.json --output .codebuddy/context/
  python context_compressor.py --action get-context --task "重构 auth_service" --blueprint blueprint.json
  python context_compressor.py --action refresh --file src/auth/auth_core.py

设计依据：
  - "Lost in the Middle" 效应：AI 长上下文中间部分信息被遗忘，分层加载避免超长上下文
  - 与 CodeGuard 三层防线协同：L0/L1 注入第一层约束，L2 注入第二层自查依据
  - 复用 quality_core.py AST 分析函数：compute_cyclomatic_complexity / get_nesting_depth / count_lines_of_code

注：L0-L3 选择逻辑（get_context_for_task / refresh / 函数分析 / 文件收集）已拆分至
    context_selector.py，本文件保留核心压缩（L0/L1/L2 生成）与 CLI 入口。
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
# 内部导入
# ============================================================

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from context_selector import (  # noqa: E402
    _analyze_generic_functions,
    _analyze_python_functions,
    _collect_files,
    get_context_for_task,
    refresh,
    _print_context_result,
)

# ============================================================
# 常量
# ============================================================

L0_FILENAME = "L0_project_summary.md"
L0_SIZE_TARGET = 500

# ============================================================
# 工具函数
# ============================================================

def _log(msg: str) -> None:
    sys.stderr.write(f"[CC] {msg}\n")
    sys.stderr.flush()


def _rel(path: str, root: str) -> str:
    return os.path.relpath(path, root).replace("\\", "/")


def _read_blueprint(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ============================================================
# L0: 项目级精简摘要
# ============================================================

def generate_l0(blueprint_path: str) -> str:
    """从 architecture_blueprint.json 生成 L0 项目摘要 (≤500行 Markdown)。

    Returns:
        Markdown 格式的 L0 文档字符串。
    """
    bp = _read_blueprint(blueprint_path)
    modules = bp.get("modules", [])
    deps = bp.get("dependency_graph", {})
    constraints = bp.get("constraints", {})
    shared = bp.get("shared_utils", [])

    lines = [
        f"# L0 项目摘要: {bp.get('project_name', 'Unknown')}",
        f"> Blueprint 版本: {bp.get('version', 'N/A')} | 生成: {bp.get('generated_at', '')}",
        f"> 压缩时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"> 模块: {len(modules)} | 共享工具: {len(shared)} | 依赖边: {sum(len(v) for v in deps.values())}",
        "", "---", "", "## 模块清单", "",
        "| 模块 | 路径 | 标签 | 文件数 | 行数 | 嵌套 | 公共API |",
        "|------|------|------|--------|------|------|---------|",
    ]

    for m in modules:
        tags_str = ", ".join(m.get("tags", [])) or "—"
        api_count = len(m.get("public_api", []))
        lines.append(
            f"| {m.get('name', '?')} | {m.get('path', '')} | {tags_str} | "
            f"{m.get('file_count', 0)} | {m.get('total_lines', 0)} | "
            f"{m.get('max_nesting', 0)} | {api_count} |"
        )

    lines.extend([
        "", "---", "", "## 依赖图", "",
        "```",
    ])
    for m_name, dep_list in deps.items():
        if dep_list:
            lines.append(f"  {m_name} → {', '.join(dep_list)}")
        else:
            lines.append(f"  {m_name}")
    lines.append("```")

    lines.extend([
        "", "---", "", "## 全局约束", "",
        "| 约束项 | 值 |",
        "|--------|-----|",
    ])
    for k, v in constraints.items():
        lines.append(f"| {k} | {v} |")

    if shared:
        lines.extend([
            "", "---", "", "## 共享工具", "",
            "| 函数 | 位置 | 消费者数 |",
            "|------|------|----------|",
        ])
        for s in shared:
            lines.append(
                f"| {s.get('name', '')} | {s.get('location', '')} | "
                f"{len(s.get('consumers', []))} |"
            )

    # 标签分布
    tag_dist: dict[str, int] = {}
    for m in modules:
        for tag in m.get("tags", []):
            tag_dist[tag] = tag_dist.get(tag, 0) + 1

    if tag_dist:
        lines.extend([
            "", "---", "", "## 标签分布", "",
            "| 标签 | 模块数 | 含义 |",
            "|------|--------|------|",
        ])
        tag_meanings = {
            "core": "核心模块，修改需测试",
            "frozen": "冻结，禁止结构性修改",
            "no_split": "禁止拆分",
            "allow_split": "允许拆分",
            "leaf_only": "叶节点，不可新增依赖",
            "shared_util": "共享工具函数",
            "test_only": "仅测试用",
            "legacy": "遗留代码，暂不修改",
            "global_config": "全局配置项",
        }
        for tag, count in sorted(tag_dist.items(), key=lambda x: -x[1]):
            meaning = tag_meanings.get(tag, "")
            lines.append(f"| {tag} | {count} | {meaning} |")

    lines.extend(["", "---", "*L0 上下文 — AI 每次会话必读*", ""])
    return "\n".join(lines)
