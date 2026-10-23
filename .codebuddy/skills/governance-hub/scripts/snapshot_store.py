#!/usr/bin/env python3
"""
Governance Hub Snapshot Manager (v1.0.0)
==========================================
架构快照与回滚系统 — 在重构/修复前后创建快照，自动对比指标变化，
判断是否批准变更，支持回滚到历史快照。

快照存储于 .codebuddy/snapshots/ 目录，每条一个 JSON 文件。

功能：
  - create_snapshot(trigger, project_path)          创建快照（含 CodeGuard 指标 + 文件哈希）
  - compare_snapshots(before_id, after_id)           对比两个快照的指标变化
  - get_snapshot(id)                                 获取快照详情
  - list_snapshots()                                 列出所有快照
  - rollback_to(id)                                  回滚到指定快照
  - auto_gate(before_id, after_id)                   自动门禁判断（reject/approve/manual_review）

用法：
  python snapshot_manager.py --action create --trigger "pre-refactor:ADR-001" --project .
  python snapshot_manager.py --action compare --before SNAP-20260801-001 --after SNAP-20260801-002
  python snapshot_manager.py --action gate --before SNAP-20260801-001 --after SNAP-20260801-002
  python snapshot_manager.py --action list
  python snapshot_manager.py --action rollback --id SNAP-20260801-001

集成：
  - CodeGuard: 调用 quality_check.run_quality_check() 采集指标
  - ADR Manager: 自动关联 ADR、写入 metrics_before/after、状态联动
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ============================================================
# 常量
# ============================================================

_SNAPSHOTS_DIR = ".codebuddy/snapshots"

_SKIP_DIRS = frozenset({
    ".git", "__pycache__", "node_modules", "venv", ".venv",
    "dist", "build", "target", ".codebuddy", ".idea", ".vscode",
    ".cursor", "vendor", ".terraform",
})

_SOURCE_EXTS = frozenset({
    ".py", ".js", ".ts", ".tsx", ".mjs", ".java", ".go", ".cs", ".rs",
    ".cpp", ".c", ".h",
})

# 门禁阈值
_GATE_DEGRADE_THRESHOLD = 1.20      # 恶化 >20% → reject
_GATE_NEUTRAL_THRESHOLD = 1.10      # 变化 ≤10% → 中性

_REJECT_IF_INCREASED = frozenset({
    "max_complexity", "duplicate_blocks", "duplicate_lines",
    "architecture_cycles", "codeguard_blocks", "codeguard_warns", "global_vars",
})
_REJECT_IF_DECREASED = frozenset({"test_coverage"})


# ============================================================
# 工具函数
# ============================================================

def _log(msg: str) -> None:
    sys.stderr.write(f"[Snapshot] {msg}\n")
    sys.stderr.flush()


def _get_snapshots_dir(project_root: str) -> Path:
    d = Path(project_root) / _SNAPSHOTS_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def _snapshot_id() -> str:
    now = datetime.now(timezone.utc)
    return f"SNAP-{now.strftime('%Y%m%d')}-{now.strftime('%H%M%S')}"


def _list_snapshot_files(snapshot_dir: Path) -> list[Path]:
    if not snapshot_dir.exists():
        return []
    files = [f for f in snapshot_dir.iterdir()
             if f.suffix == ".json" and re.match(r"SNAP-\d{8}-\d{6}", f.stem)]
    files.sort(key=lambda f: f.stem)
    return files


def _load_snapshot(snap_dir: Path, snap_id: str) -> dict | None:
    """加载单个快照 JSON 文件。"""
    fpath = snap_dir / f"{snap_id}.json"
    if not fpath.exists():
        return None
    try:
        return json.loads(fpath.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _save_snapshot(snap_dir: Path, data: dict) -> str:
    """保存快照并返回文件路径。"""
    snap_id = data["snapshot_id"]
    fpath = snap_dir / f"{snap_id}.json"
    fpath.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return str(fpath)
