#!/usr/bin/env python3
"""
Governance Hub ADR Manager — facade 入口（向后兼容）。
实现已拆分至 adr_store / adr_crud / adr_context / adr_cli。
"""
from adr_crud import create_adr, list_adrs, get_adr, update_adr  # noqa: F401
from adr_context import (  # noqa: F401
    get_active_context,
    supersede_adr,
    get_rollback_info,
    export_timeline,
)
from adr_cli import main  # noqa: F401


if __name__ == "__main__":
    main()
