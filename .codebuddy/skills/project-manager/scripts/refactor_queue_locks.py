"""文件锁机制 — 锁定/解锁/检查文件锁。"""
from __future__ import annotations

from datetime import datetime, timezone

from refactor_queue_store import (
    _LOCK_TIMEOUT_HOURS,
    _load_locks,
    _save_locks,
    _load_queue,
    _find_task,
    _DEFAULT_SESSION,
    _now,
    _log,
)

# ============================================================
# 文件锁机制
# ============================================================

def lock_files(task_id: str, project_root: str = ".") -> dict:
    """锁定任务涉及的所有文件。"""
    data = _load_queue(project_root)
    task = _find_task(data, task_id)
    if task is None:
        return {"status": "not_found", "id": task_id}

    locks = _load_locks(project_root)
    _clean_stale_locks(locks, project_root)
    now = _now()
    locked = []

    for f in task.get("files_locked", []):
        existing = locks.get(f, {})
        if existing.get("locked_by", "") != task_id:
            locks[f] = {
                "locked_by": task_id,
                "locked_at": now,
                "session": _DEFAULT_SESSION,
            }
            locked.append(f)

    _save_locks(locks, project_root)
    _log(f"锁定 {len(locked)} 个文件 → {task_id}")
    return {"status": "locked", "task_id": task_id, "files": locked}


def unlock_files(task_id: str, project_root: str = ".") -> dict:
    """释放任务所有文件锁。"""
    locks = _load_locks(project_root)
    released = []
    for f, info in list(locks.items()):
        if info.get("locked_by") == task_id:
            del locks[f]
            released.append(f)

    _save_locks(locks, project_root)
    _log(f"释放 {len(released)} 个文件锁 → {task_id}")
    return {"status": "unlocked", "task_id": task_id, "files": released}


def check_file_lock(file_path: str, project_root: str = ".") -> dict:
    """检查文件是否被锁定。"""
    locks = _load_locks(project_root)
    _clean_stale_locks(locks, project_root)
    info = locks.get(file_path)

    if not info:
        return {"file": file_path, "locked": False, "free": True}

    task_id = info.get("locked_by", "")
    locked_at = info.get("locked_at", "")
    return {
        "file": file_path,
        "locked": True,
        "locked_by": task_id,
        "locked_at": locked_at,
        "session": info.get("session", ""),
        "free": False,
    }


def _check_files_locked(files: list[str], locks: dict, current_task: str) -> list[str]:
    """检查文件列表中被其他任务锁定的。"""
    locked = []
    for f in files:
        info = locks.get(f, {})
        if info and info.get("locked_by", "") != current_task:
            locked.append(f"{f} (被 {info.get('locked_by', '?')} 锁定)")
    return locked


def _clean_stale_locks(locks: dict, project_root: str = ".") -> None:
    """清理过期的文件锁（>2小时）。"""
    now = datetime.now(timezone.utc)
    stale = []
    for f, info in locks.items():
        try:
            locked_at = datetime.fromisoformat(info.get("locked_at", "").replace("Z", "+00:00"))
            if (now - locked_at).total_seconds() > _LOCK_TIMEOUT_HOURS * 3600:
                stale.append(f)
        except (ValueError, AttributeError):
            stale.append(f)

    for f in stale:
        task_id = locks[f].get("locked_by", "?")
        del locks[f]
        _log(f"⚠️ 过期锁已清理: {f} (原锁定: {task_id})")

    if stale:
        _save_locks(locks, project_root)
