"""任务状态操作 — complete / fail / status / blocked / reorder。"""
from __future__ import annotations

from collections import defaultdict

from refactor_queue_store import (
    _PRIORITIES,
    _PRIORITY_ORDER,
    _load_queue,
    _load_locks,
    _save_queue,
    _find_task,
    _now,
    _log,
)
from refactor_queue_locks import unlock_files, _check_files_locked

# ============================================================
# 公共 API：complete_task() / fail_task()
# ============================================================

def complete_task(task_id: str, snapshot_after: str = "",
                  gate_result: str = "", project_root: str = ".") -> dict:
    """标记任务完成。"""
    data = _load_queue(project_root)
    task = _find_task(data, task_id)
    if task is None:
        return {"status": "not_found", "id": task_id}

    task["status"] = "completed"
    task["completed_at"] = _now()
    if snapshot_after:
        task["snapshot_after"] = snapshot_after
    if gate_result:
        task["gate_result"] = gate_result

    # 从队列移到已完成
    data["queue"] = [t for t in data["queue"] if t["id"] != task_id]
    data.setdefault("completed", []).append(task)
    _save_queue(data, project_root)

    # 自动释放文件锁
    unlock_files(task_id, project_root)
    _log(f"完成: {task_id} — 门禁: {gate_result or 'N/A'}")
    return {"status": "completed", "id": task_id}


def fail_task(task_id: str, reason: str = "", project_root: str = ".") -> dict:
    """标记任务失败。"""
    data = _load_queue(project_root)
    task = _find_task(data, task_id)
    if task is None:
        return {"status": "not_found", "id": task_id}

    task["status"] = "failed"
    task["_failed_reason"] = reason
    task["completed_at"] = _now()

    data["queue"] = [t for t in data["queue"] if t["id"] != task_id]
    data.setdefault("failed", []).append(task)
    _save_queue(data, project_root)

    unlock_files(task_id, project_root)
    _log(f"失败: {task_id} — {reason}")
    return {"status": "failed", "id": task_id}


# ============================================================
# 公共 API：get_queue_status() / get_blocked_tasks()
# ============================================================

def get_queue_status(project_root: str = ".") -> dict:
    """获取队列概览。"""
    data = _load_queue(project_root)
    queue = data.get("queue", [])
    counts = defaultdict(int)
    for t in queue:
        counts[t.get("status", "pending")] += 1

    # 检查阻塞
    blocked = _find_blocked(data)
    pending_count = counts.get("pending", 0)

    return {
        "total_queue": len(queue),
        "pending": pending_count,
        "in_progress": counts.get("in_progress", 0),
        "blocked_by_deps": blocked["by_deps"],
        "blocked_by_locks": blocked["by_locks"],
        "completed": len(data.get("completed", [])),
        "failed": len(data.get("failed", [])),
    }


def get_blocked_tasks(project_root: str = ".") -> dict:
    """获取被阻塞的任务详情。"""
    data = _load_queue(project_root)
    blocked = _find_blocked(data)
    locks = _load_locks(project_root)

    results = []
    for task in data.get("queue", []):
        if task.get("status") != "pending":
            continue
        deps = task.get("depends_on", [])
        completed_ids = {t["id"] for t in data.get("completed", [])}
        missing = [d for d in deps if d not in completed_ids]
        locked = _check_files_locked(task.get("files_locked", []), locks, task["id"])
        if missing or locked:
            results.append({
                "id": task["id"],
                "title": task.get("title", ""),
                "priority": task.get("priority", ""),
                "blocked_by_deps": missing,
                "blocked_by_files": locked,
                "depends_on": deps,
            })

    return {"blocked_tasks": results, "count": len(results)}


def _find_blocked(data: dict) -> dict:
    """查找阻塞任务统计。"""
    completed_ids = {t["id"] for t in data.get("completed", [])}
    by_deps = 0
    by_locks = 0

    for task in data.get("queue", []):
        if task.get("status") != "pending":
            continue
        deps = task.get("depends_on", [])
        if any(d not in completed_ids for d in deps):
            by_deps += 1
        elif task.get("_blocked_by_locks"):
            by_locks += 1

    return {"by_deps": by_deps, "by_locks": by_locks}


# ============================================================
# 公共 API：reorder()
# ============================================================

def reorder(task_id: str, new_priority: str, project_root: str = ".") -> dict:
    """调整任务优先级。"""
    if new_priority not in _PRIORITIES:
        return {"status": "error", "message": f"无效优先级 '{new_priority}'"}

    data = _load_queue(project_root)
    task = _find_task(data, task_id)
    if task is None:
        return {"status": "not_found", "id": task_id}

    old_p = task.get("priority", "")
    task["priority"] = new_priority
    data["queue"].sort(key=lambda t: (_PRIORITY_ORDER.get(t["priority"], 99), t.get("created_at", "")))
    _save_queue(data, project_root)
    _log(f"优先级调整: {task_id} {old_p} → {new_priority}")
    return {"status": "reordered", "id": task_id, "old_priority": old_p, "new_priority": new_priority}
