#!/usr/bin/env python3
"""
CodeGuard Context Compressor — facade 入口（向后兼容）。
实现已拆分至 context_compressor_core / levels / api / cli。
"""
from context_compressor_core import (  # noqa: F401
    generate_l0,
    get_context_for_task,
    refresh,
)
from context_compressor_levels import generate_l1, generate_l2  # noqa: F401
from context_compressor_api import generate_all  # noqa: F401
from context_compressor_cli import main  # noqa: F401


if __name__ == "__main__":
    main()
