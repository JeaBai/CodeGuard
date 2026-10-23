"""核心任务操作 — enqueue / dequeue。"""
from __future__ import annotations

from refactor_queue_store import (
    _PRIORITIES,
    _PRIORITY_ORDER,
    _load_queue,
    _load_locks,
    _save_queue,
    _next_id,
    _now,
    _DEFAULT_SESSION,
    _log,
)
from refactor_queue_locks import _clean_stale_locks, _check_files_locked

# ============================================================
# 公共 API：enqueue()
# ============================================================

def enqueue(title: str, files: list[str], priority: str = "P2",
            description: str = "", depends_on: list[str] | None = None,
            tags_required: dict[str, str] | None = None,
            project_root: str = ".") -> dict:
    """将重构任务入队。"""
    if priority not in _PRIORITIES:
        return {"status": "error", "message": f"无效优先级 '{priority}'，有效: {sorted(_PRIORITIES)}"}

    data = _load_queue(project_root)
    all_items = data["queue"] + data["completed"] + data["failed"]
    rid = _next_id(all_items)

    task = {
        "id": rid,
        "priority": priority,
        "title": title,
        "description": description,
        "files_locked": files,
        "depends_on": depends_on or [],
        "adr_id": None,
        "status": "pending",
        "assigned_to": None,
        "created_at": _now(),
        "started_at": None,
        "completed_at": None,
        "snapshot_before": None,
        "snapshot_after": None,
        "gate_result": None,
        "tags_required": tags_required or {},
        "max_nesting_target": None,
    }

    data["queue"].append(task)
    data["queue"].sort(key=lambda t: (_PRIORITY_ORDER.get(t["priority"], 99), t["created_at"]))
    _save_queue(data, project_root)
    _log(f"入队: {rid} ({priority}) — {title}")
    return {"status": "enqueued", "id": rid, "task": task}


# ============================================================
# 公共 API：dequeue()
# ============================================================

def dequeue(project_root: str = ".") -> dict:
    """取出下一个可执行任务。

    条件: 1) status=pending  2) 优先级最高  3) depends_on 全部 completed
           4) files_locked 文件未被其他任务锁定
    """
    data = _load_queue(project_root)
    queue = data.get("queue", [])
    locks = _load_locks(project_root)

    # 收集已完成任务ID和已锁定文件
    completed_ids = {t["id"] for t in data.get("completed", [])}
    in_progress_ids = {t["id"] for t in data.get("queue", [])
                       if t.get("status") == "in_progress"}

    # 清理过期锁
    _clean_stale_locks(locks, project_root)

    for task in sorted(queue, key=lambda t: _PRIORITY_ORDER.get(t["priority"], 99)):
        if task.get("status") != "pending":
            continue

        # 检查依赖是否完成
        deps = task.get("depends_on", [])
        missing_deps = [d for d in deps if d not in completed_ids]
        if missing_deps:
            task["_blocked_by_deps"] = missing_deps
            continue

        # 检查文件锁
        locked_files = _check_files_locked(task.get("files_locked", []), locks, task["id"])
        if locked_files:
            task["_blocked_by_locks"] = locked_files
            continue

        # 可执行：标记为 in_progress
        task["status"] = "in_progress"
        task["assigned_to"] = _DEFAULT_SESSION
        task["started_at"] = _now()
        _save_queue(data, project_root)
        _log(f"出队: {task['id']} — {task['title']}")
        return {"status": "dequeued", "task": task}

    return {"status": "no_available_tasks", "message": "无可执行任务（依赖未完成或文件被锁）"}
