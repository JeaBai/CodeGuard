#!/usr/bin/env python3
"""orchestrator.py — CodeGuard 多 Agent 编排器

在单 Agent 模式下模拟 Team Mode 协作流程：
  Architect (约束注入) → Generator (代码生成) → Reviewer (质量审查)

输出端到端的质量治理报告，可在 CI/CD 中独立使用。

用法:
  python orchestrator.py --path . --format json    # 全流程编排
  python orchestrator.py --path . --mode diff      # 增量编排
"""
import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from architect import generate_constraints
from reviewer import run_review


def orchestrate(project_root: str, mode: str = "personal") -> dict:
    """编排完整的三层防线流程。

    Returns:
        编排报告 {phase, constraints, review, exit_code}
    """
    # Phase 1: Architect → 约束注入
    constraints = generate_constraints(project_root)

    # Phase 2: Reviewer → 质量门禁（Generator 由 CodeBuddy 负责代码生成）
    review = run_review(project_root, mode=mode)

    # Phase 3: 汇总
    exit_code = max(
        review["exit_code"],
        0 if constraints.get("has_custom") else 0,
    )

    phases = [
        {"phase": "architect", "status": "done", "output": "constraints injected"},
        {"phase": "generator", "status": "delegated", "output": "code generation delegated to CodeBuddy/LLM"},
        {"phase": "reviewer", "status": "done", "output": f"quality gate: {review['verdict']}"},
    ]

    return {
        "type": "orchestration_report",
        "version": "1.0",
        "exit_code": exit_code,
        "verdict": review["verdict"],
        "phases": phases,
        "constraints_summary": {
            "project_type": constraints["project_type"],
            "languages": constraints["languages"],
            "block_rules_count": len(constraints["block_rules"]),
            "warn_rules_count": len(constraints["warn_rules"]),
            "custom_rules_count": len(constraints["custom_rules"]),
            "checklist": constraints["checklist"],
        },
        "review_summary": review["summary"],
        "top_issues": [i for i in review["issues"] if i["severity"] == "block"][:5],
    }


def main():
    parser = argparse.ArgumentParser(description="CodeGuard Orchestrator — 多 Agent 编排器")
    parser.add_argument("--path", default=".", help="项目根目录")
    parser.add_argument("--mode", choices=["personal", "team", "diff"], default="personal")
    parser.add_argument("--format", choices=["json", "summary"], default="json")
    args = parser.parse_args()

    report = orchestrate(args.path, args.mode)

    if args.format == "summary":
        summary = report["review_summary"]
        checklist = report["constraints_summary"]["checklist"]
        print(f"项目类型: {report['constraints_summary']['project_type']}")  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
        print(f"语言: {', '.join(report['constraints_summary']['languages'])}")  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
        print(f"阻断规则: {report['constraints_summary']['block_rules_count']} 条")  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
        print(f"质量门禁: {report['verdict']}")  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
        print(f"BLOCK={summary['blocks']} WARN={summary['warnings']} INFO={summary['info']}")  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
        print(f"平均置信度: {summary['avg_confidence']}")  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
        print("\n约束注入清单:")  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
        for item in checklist[:5]:
            print(f"  - {item}")  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2))  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION

    return report["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
