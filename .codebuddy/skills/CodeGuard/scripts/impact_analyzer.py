#!/usr/bin/env python3
"""
CodeGuard Impact Analyzer — facade 入口（向后兼容）。
实现已拆分至 impact_core / impact_callers / impact_deps / impact_api / impact_cli。
外部 `from impact_analyzer import analyze_change` 用法保持不变。
"""
from impact_api import (  # noqa: F401
    analyze_change,
    analyze_file_move,
    analyze_global_var,
    analyze_module_dep,
)
from impact_cli import main  # noqa: F401


if __name__ == "__main__":
    main()
