#!/usr/bin/env python3
"""
Governance Hub Risk Gate — facade 入口（向后兼容）。
实现已拆分至 risk_gate_store / risk_gate_api / risk_gate_integration / risk_gate_cli。
"""
from risk_gate_api import (  # noqa: F401
    classify_risk,
    check_gate,
    generate_confirmation,
    generate_diff_preview,
    execute_with_gate,
)
from risk_gate_cli import main  # noqa: F401


if __name__ == "__main__":
    main()
