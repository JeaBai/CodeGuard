"""发布前治理门禁 CLI 入口。"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from _governance_core import (  # noqa: E402
    GATE_ITEMS,
    normalize_issue,
    emit_results,
    consume_iac_report,
)
from governance_gate_cost import cost_baseline_check  # noqa: E402
from governance_gate_contract import contract_breaking_check  # noqa: E402
from governance_gate_trace import requirement_trace_check, auto_trace_check  # noqa: E402
from governance_gate_deploy import deploy_integrity_check  # noqa: E402

# ── 主流程 ─────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(
        description='发布前治理三合一门禁（成本基线 + 契约破坏性 + 需求追溯）',
    )
    ap.add_argument('--mode', default='release',
                    choices=['release', 'cost-only', 'contract-only', 'trace-only', 'deploy-only', 'auto-trace'],
                    help='检视模式（默认 release）')
    ap.add_argument('--path', default='.', help='项目根目录（默认当前目录）')
    ap.add_argument('--cost-threshold', type=int, default=20,
                    help='成本偏离阈值百分比（默认 20）')
    ap.add_argument('--coverage-ratio', type=float, default=0.8,
                    help='需求追溯最低覆盖率（默认 0.8）')
    ap.add_argument('--iac-report', default=None,
                    help='iac-guardian --bridge JSON 路径（注入成本检视）')
    ap.add_argument('--format', choices=['text', 'json'], default='text',
                    help='输出格式')
    args = ap.parse_args()

    root = Path(args.path).resolve()
    if not root.exists():
        print(f'路径不存在: {root}', file=sys.stderr)  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
        sys.exit(2)

    checks_to_run = {
        'release': ['cost-baseline', 'contract-breaking', 'requirement-trace', 'deploy-integrity'],
        'cost-only': ['cost-baseline'],
        'contract-only': ['contract-breaking'],
        'trace-only': ['requirement-trace'],
        'deploy-only': ['deploy-integrity'],
        'auto-trace': ['auto-trace'],
    }[args.mode]

    check_dispatch = {
        'cost-baseline': (cost_baseline_check, args.cost_threshold),
        'contract-breaking': (contract_breaking_check, None),
        'requirement-trace': (requirement_trace_check, args.coverage_ratio),
        'deploy-integrity': (deploy_integrity_check, None),
        'auto-trace': (auto_trace_check, args.coverage_ratio),
    }

    all_issues: list[dict[str, Any]] = []
    for gate_key in checks_to_run:
        gate = GATE_ITEMS[gate_key]
        check_fn, extra_param = check_dispatch[gate_key]
        result = check_fn(root, extra_param) if extra_param is not None else check_fn(root)
        for issue in result:
            issue.setdefault('gate', gate['id'])
            issue.setdefault('dimension', gate['dimension'])
        all_issues.extend(normalize_issue(i) for i in result)

    if args.iac_report:
        iac_path = Path(args.iac_report).resolve()
        iac_issues = consume_iac_report(iac_path)
        for issue in iac_issues:
            issue.setdefault('gate', GATE_ITEMS['cost-baseline']['id'])
            issue.setdefault('dimension', 'D11')
        all_issues.extend(normalize_issue(i) for i in iac_issues)

    blocks = [i for i in all_issues if i['severity'] == 'block']
    warns = [i for i in all_issues if i['severity'] == 'warn']
    exit_code = 2 if blocks else (1 if warns else 0)

    emit_results(all_issues, args.mode, args.format, exit_code)
    sys.exit(exit_code)


if __name__ == '__main__':
    main()
