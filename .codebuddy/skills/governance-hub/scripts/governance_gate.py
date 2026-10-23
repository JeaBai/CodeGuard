#!/usr/bin/env python3
"""
发布前治理三合一门禁 — facade 入口（向后兼容）。
实现已拆分至 governance_gate_cost / contract / trace / deploy / cli。
"""
from governance_gate_cost import cost_baseline_check  # noqa: F401
from governance_gate_contract import contract_breaking_check  # noqa: F401
from governance_gate_trace import requirement_trace_check, auto_trace_check  # noqa: F401
from governance_gate_deploy import deploy_integrity_check  # noqa: F401
from governance_gate_cli import main  # noqa: F401


if __name__ == "__main__":
    main()
