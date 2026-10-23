#!/usr/bin/env python3
"""
经验资产库管理器 — facade 入口（向后兼容）。
实现已拆分至 experience_store / experience_api / experience_ops / experience_cli。
"""
from experience_api import register, search  # noqa: F401
from experience_ops import (  # noqa: F401
    load_to_context,
    tag,
    expire,
    list_by_project,
    stats,
)
from experience_store import dedup_check, backup_to_json, restore_from_json  # noqa: F401
from experience_cli import main  # noqa: F401


if __name__ == "__main__":
    main()
