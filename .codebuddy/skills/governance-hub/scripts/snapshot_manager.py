#!/usr/bin/env python3
"""
Governance Hub Snapshot Manager — facade 入口（向后兼容）。
实现已拆分至 snapshot_store / snapshot_collect / snapshot_api / snapshot_cli。
外部 `from snapshot_manager import create_snapshot` 用法保持不变。
"""
from snapshot_api import (  # noqa: F401
    create_snapshot,
    compare_snapshots,
    auto_gate,
    get_snapshot,
    list_snapshots,
    rollback_to,
)
from snapshot_cli import main  # noqa: F401


if __name__ == "__main__":
    main()
