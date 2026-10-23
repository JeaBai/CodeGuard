#!/usr/bin/env python3
"""
Governance Hub ADR Manager (v1.0.0)
======================================
架构决策记录（ADR）管理系统 — 记录每个架构决策的上下文、理由、影响和回滚计划。

ADR 文件存储于 .codebuddy/decisions/ 目录，每条决策一个 JSON 文件。

功能：
  - create_adr(...)                       创建新 ADR，自动生成递增 ID
  - list_adrs(status_filter=None)         列出所有 ADR，可按状态过滤
  - get_adr(id) → dict                    获取单条 ADR 完整内容
  - update_adr(id, **fields)              更新 ADR 字段（含状态转换校验）
  - get_active_context() → str            AI 会话恢复核心函数
  - supersede_adr(old_id, new_id, reason) 标记旧 ADR 被新 ADR 替代
  - get_rollback_info(id) → dict          获取回滚信息
  - export_timeline(output_path) → str    导出 ADR 时间线 Markdown

用法：
  python adr_manager.py --action list
  python adr_manager.py --action list --status implemented
  python adr_manager.py --action get --id ADR-001
  python adr_manager.py --action active-context
  python adr_manager.py --action create --title "拆分auth_service" --context "..." --decision "..."
  python adr_manager.py --action update --id ADR-001 --status implemented
  python adr_manager.py --action timeline --output docs/adr-timeline.md

设计依据：
  - 与 CodeGuard 三层防线闭环：ADR 记录检测→决策→修复→验证
  - 与 tag_manager.py 协同：tags_affected 记录标签变更，可自动 apply/remove
  - 与 intent_protection 互补：ADR 关注"为什么这么做"，保护项关注"为什么不改"
  - 参考 Michael Nygard ADR 格式（简化版，聚焦 AI 辅助可操作）
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ============================================================
# 常量
# ============================================================

_DEFAULT_DECISIONS_DIR = ".codebuddy/decisions"

_VALID_STATUSES = frozenset({
    "proposed", "in_review", "implemented", "superseded", "rejected", "rolled_back",
})

_VALID_STATUS_TRANSITIONS: dict[str, frozenset] = {
    "proposed": frozenset({"in_review", "rejected", "implemented"}),
    "in_review": frozenset({"proposed", "implemented", "rejected"}),
    "implemented": frozenset({"superseded", "rolled_back"}),
    "superseded": frozenset(),
    "rejected": frozenset({"proposed"}),
    "rolled_back": frozenset({"proposed"}),
}

_STATUS_ICONS = {
    "proposed": "💡", "in_review": "👁️", "implemented": "✅",
    "superseded": "🔄", "rejected": "❌", "rolled_back": "⏪",
}

# ============================================================
# 工具函数
# ============================================================

def _log(msg: str) -> None:
    sys.stderr.write(f"[ADRManager] {msg}\n")
    sys.stderr.flush()


def _get_decision_dir(project_root: str | None = None) -> Path:
    """获取 ADR 存储目录。"""
    base = Path(project_root) if project_root else Path.cwd()
    dec_dir = base / _DEFAULT_DECISIONS_DIR
    dec_dir.mkdir(parents=True, exist_ok=True)
    return dec_dir


def _next_id(dec_dir: Path) -> str:
    """扫描已有 ADR，生成下一个递增 ID。"""
    max_num = 0
    for fname in dec_dir.iterdir():
        m = re.match(r"ADR-(\d{3,})", fname.stem)
        if m:
            max_num = max(max_num, int(m.group(1)))
    return f"ADR-{max_num + 1:03d}"


def _slugify(title: str) -> str:
    """标题 → 文件名用的短 slug。"""
    slug = re.sub(r'[^\w\s-]', '', title.lower())
    slug = re.sub(r'[-\s]+', '-', slug)
    return slug.strip('-')[:50]


def _load_adr(filepath: Path) -> dict | None:
    """加载单个 ADR JSON 文件。"""
    try:
        return json.loads(filepath.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _save_adr(filepath: Path, adr: dict) -> None:
    """保存 ADR JSON 文件。"""
    filepath.parent.mkdir(parents=True, exist_ok=True)
    filepath.write_text(json.dumps(adr, indent=2, ensure_ascii=False), encoding="utf-8")


def _list_adr_files(dec_dir: Path) -> list[Path]:
    """列出所有 ADR JSON 文件，按 ID 排序。"""
    if not dec_dir.exists():
        return []
    files = [f for f in dec_dir.iterdir()
             if f.suffix == ".json" and re.match(r"ADR-\d{3,}", f.stem)]
    files.sort(key=lambda f: f.stem)
    return files


def _parse_json_field(value: str, field_name: str) -> Any:
    """解析 JSON 字符串字段，失败时记录警告并返回空值。"""
    if not value:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        _log(f"警告: '{field_name}' JSON 解析失败，已跳过")
        return None


def _format_date(date_str: str) -> str:
    """格式化 ISO8601 日期为短格式 YYYY-MM-DD。"""
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d")
    except (ValueError, AttributeError):
        return date_str[:10] if date_str else ""
