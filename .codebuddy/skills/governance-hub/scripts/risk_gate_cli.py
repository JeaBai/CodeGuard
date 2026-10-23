"""风险门禁 CLI 入口。"""
from __future__ import annotations

import argparse
import json

from risk_gate_store import _load_config
from risk_gate_api import (
    classify_risk,
    check_gate,
    generate_confirmation,
    generate_diff_preview,
)

# ============================================================
# CLI 入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="Governance Hub Risk Gate — 三级风险门禁系统",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python risk_gate.py --action check --type split_function --file src/auth/login.py --function login
  python risk_gate.py --action classify --type change_public_api --file src/auth/login.py
  python risk_gate.py --action confirm --type split_function --details "拆成3个函数"
  python risk_gate.py --action diff --type split_module --file src/auth/ --changes "+ 三行新代码"
  python risk_gate.py --action config --show
        """,
    )
    parser.add_argument("--action", required=True,
                        choices=["check", "classify", "confirm", "diff", "config"],
                        help="操作类型")
    parser.add_argument("--type", dest="action_type", default="",
                        help="操作类型 (如 split_function, change_public_api)")
    parser.add_argument("--file", default="", help="文件路径")
    parser.add_argument("--function", default="", help="函数名")
    parser.add_argument("--details", default="", help="操作详情 (confirm)")
    parser.add_argument("--changes", default="", help="提议的变更 (diff)")
    parser.add_argument("--blueprint", default="", help="architecture_blueprint.json 路径")
    parser.add_argument("--module", default="", help="模块名 (confirm 消息用)")
    parser.add_argument("--line-count", type=int, default=0, help="行数 (confirm 消息用)")
    parser.add_argument("--targets", default="3 个小函数", help="拆分目标 (confirm 消息用)")
    parser.add_argument("--format", default="text", choices=["text", "json"],
                        help="输出格式")
    args = parser.parse_args()

    if args.action == "check":
        result = check_gate(args.action_type, args.file, args.function,
                            args.blueprint)
        _output(result, args.format, _fmt_gate)
    elif args.action == "classify":
        result = classify_risk(args.action_type, args.file, args.function,
                               args.blueprint)
        _output(result, args.format, _fmt_risk)
    elif args.action == "confirm":
        msg = generate_confirmation(args.action_type, args.file,
                                    args.function, args.details,
                                    module=args.module,
                                    line_count=args.line_count,
                                    targets=args.targets)
        print(msg)
    elif args.action == "diff":
        risk = classify_risk(args.action_type, args.file, args.function,
                             args.blueprint) if args.blueprint else None
        preview = generate_diff_preview(args.action_type, args.file,
                                        args.changes, risk)
        print(preview)
    elif args.action == "config":
        if args.format == "json":
            config = _load_config()
            print(json.dumps(config, indent=2, ensure_ascii=False))
        else:
            _print_config()


def _output(data: dict, fmt: str, text_fmt=None) -> None:
    if fmt == "json":
        print(json.dumps(data, indent=2, ensure_ascii=False, default=str))
    elif text_fmt:
        text_fmt(data)
    else:
        for k, v in data.items():
            if not isinstance(v, (list, dict)):
                print(f"{k}: {v}")


def _fmt_risk(r: dict) -> None:
    icons = {"low": "🟢", "medium": "🟡", "high": "🔴", "rejected": "⛔"}
    level = r.get("level", "?")
    icon = icons.get(level, "")
    print(f"\n{icon} 风险等级: {level.upper()}")
    print(f"  门禁: {r.get('gate', '?')}")
    print(f"  原因: {r.get('reason', '')}")
    if r.get("escalated"):
        print(f"  升级 ⬆️:")
        for reason in r.get("escalation_reasons", []):
            print(f"    - {reason}")
    if r.get("blocked"):
        print(f"  ⛔ 已阻止执行")


def _fmt_gate(r: dict) -> None:
    if r.get("blocked"):
        print(f"\n⛔ 禁止执行: {r.get('next_step', '')}")
        return
    icons = {"low": "🟢", "medium": "🟡", "high": "🔴"}
    level = r.get("level", "?")
    print(f"\n{icons.get(level, '')} 门禁检查: {level.upper()} — 允许执行")
    print(f"  下一步: {r.get('next_step', '')}")
    if r.get("confirmation_message"):
        print(f"\n  {r['confirmation_message']}")
    if r.get("escalate_reasons"):
        print(f"\n  升级原因:")
        for reason in r["escalate_reasons"]:
            print(f"    - {reason}")


def _print_config() -> None:
    config = _load_config()
    for section, icon in [("auto_approve", "🟢"), ("confirm_required", "🟡"),
                          ("manual_required", "🔴")]:
        sec = config.get(section, {})
        print(f"\n{icon} {section}: {sec.get('description', '')}")
        print(f"   门禁: {sec.get('gate', '')}")
        print("   规则:")
        for rule in sec.get("rules", []):
            print(f"     - {rule.get('action', '?')} ({rule.get('risk', '?')})")

    esc = config.get("escalation_rules", {})
    print(f"\n⚡ 升级规则:")
    thresholds = esc.get("impact_count_threshold", {})
    print(f"   影响数: low→medium>{thresholds.get('from_low_to_medium','?')}, "
          f"medium→high>{thresholds.get('from_medium_to_high','?')}")
    print(f"   受保护文件: {esc.get('protected_file', {}).get('action', '')}")
    print(f"   锁定文件: {esc.get('locked_file', {}).get('action', '')}")


if __name__ == "__main__":
    main()
