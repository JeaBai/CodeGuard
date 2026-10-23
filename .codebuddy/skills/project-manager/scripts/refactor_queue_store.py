#!/usr/bin/env python3
"""
Project Manager Refactor Queue (v1.0.0)
==========================================
渐进式重构队列管理 — 将 CodeGuard 检测结果转化为有序的重构任务队列，
配合文件锁机制确保 AI 并发会话安全。

数据文件:
  .codebuddy/refactor_queue.json  — 队列状态（pending/in_progress/completed/failed）
  .codebuddy/file_locks.json      — 文件锁（防止并发修改冲突）

功能：
  enqueue(title, description, files, priority, depends_on, tags_required)    入队
  dequeue()                                                                  取下一个可执行任务
  lock_files(task_id)                                                        锁定文件
  unlock_files(task_id)                                                      解锁
  check_file_lock(file_path)                                                 检查锁
  complete_task(task_id, snapshot_after, gate_result)                        完成
  fail_task(task_id, reason)                                                 失败
  get_queue_status()                                                         队列概览
  reorder(task_id, new_position)                                             调整优先级
  get_blocked_tasks()                                                        阻塞任务
  import_refactor_tasks(codeguard_output, blueprint_path)                    从 CG 导入

用法：
  python refactor_queue.py --action enqueue --title "修复SQL注入" --files src/db/query.py --priority P0
  python refactor_queue.py --action dequeue
  python refactor_queue.py --action status
  python refactor_queue.py --action complete --id RF-001 --gate-result approve
  python refactor_queue.py --action fail --id RF-001 --reason "测试失败"
  python refactor_queue.py --action import --codeguard-output issues.json --blueprint blueprint.json
  python refactor_queue.py --action check-lock --file src/auth/auth_service.py

设计依据:
  - 与 CodeGuard 质量门禁闭环: 检测问题 → 入队重构 → 完成后重新门禁
  - 与 Snapshot Manager 联动: 重构前后快照对比可自动门禁
  - 与 ADR Manager 联动: 重构决策可关联 ADR
  - 文件锁防止多会话协作时的修改冲突
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ============================================================
# 常量
# ============================================================

_QUEUE_FILE = ".codebuddy/refactor_queue.json"
_LOCKS_FILE = ".codebuddy/file_locks.json"

_DEFAULT_SESSION = os.environ.get("SESSION_ID", f"session_{os.getpid()}")

_PRIORITY_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}

_LOCK_TIMEOUT_HOURS = 2

_VALID_STATUSES = frozenset({"pending", "in_progress", "completed", "failed"})

_PRIORITIES = frozenset({"P0", "P1", "P2", "P3"})


# ============================================================
# 工具函数
# ============================================================

def _log(msg: str) -> None:
    sys.stderr.write(f"[RefactorQ] {msg}\n")
    sys.stderr.flush()


def _load_json(filepath: str) -> dict:
    path = Path(filepath)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_json(filepath: str, data: dict) -> None:
    Path(filepath).parent.mkdir(parents=True, exist_ok=True)
    Path(filepath).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _next_id(items: list[dict]) -> str:
    max_num = 0
    for item in items:
        m = re.match(r"RF-(\d+)", item.get("id", ""))
        if m:
            max_num = max(max_num, int(m.group(1)))
    return f"RF-{max_num + 1:03d}"


# ---- 队列数据加载/保存 ----

def _load_queue(project_root: str = ".") -> dict:
    path = os.path.join(project_root, _QUEUE_FILE)
    data = _load_json(path)
    data.setdefault("queue", [])
    data.setdefault("completed", [])
    data.setdefault("failed", [])
    return data


def _save_queue(data: dict, project_root: str = ".") -> None:
    path = os.path.join(project_root, _QUEUE_FILE)
    _save_json(path, data)


# ---- 文件锁 ----

def _load_locks(project_root: str = ".") -> dict:
    path = os.path.join(project_root, _LOCKS_FILE)
    return _load_json(path)


def _save_locks(locks: dict, project_root: str = ".") -> None:
    path = os.path.join(project_root, _LOCKS_FILE)
    _save_json(path, locks)


# ============================================================
# 工具函数：查找任务
# ============================================================

def _find_task(data: dict, task_id: str) -> dict | None:
    for key in ("queue", "completed", "failed"):
        for t in data.get(key, []):
            if t.get("id") == task_id:
                return t
    return None
