#!/usr/bin/env python3
"""
Project Manager Refactor Queue — facade 入口（向后兼容）。
实现已拆分至 refactor_queue_store / core / locks / tasks / import / cli。
外部 `from refactor_queue import enqueue` 用法保持不变。
"""
from refactor_queue_core import enqueue, dequeue  # noqa: F401
from refactor_queue_locks import lock_files, unlock_files, check_file_lock  # noqa: F401
from refactor_queue_tasks import (  # noqa: F401
    complete_task,
    fail_task,
    get_queue_status,
    get_blocked_tasks,
    reorder,
)
from refactor_queue_import import import_refactor_tasks  # noqa: F401
from refactor_queue_cli import main  # noqa: F401


if __name__ == "__main__":
    main()
