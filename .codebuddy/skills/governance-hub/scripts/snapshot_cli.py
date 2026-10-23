"""快照 CLI 入口。"""
from __future__ import annotations

import argparse
import json
import os
import sys

from snapshot_store import _log
from snapshot_api import (
    create_snapshot,
    compare_snapshots,
    auto_gate,
    get_snapshot,
    list_snapshots,
    rollback_to,
)

# ============================================================
# CLI 入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="Governance Hub Snapshot Manager — 架构快照与回滚系统",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python snapshot_manager.py --action create --trigger "pre-refactor:ADR-001" --project .
  python snapshot_manager.py --action compare --before SNAP-20260801-001 --after SNAP-20260801-002
  python snapshot_manager.py --action gate --before SNAP-20260801-001 --after SNAP-20260801-002
  python snapshot_manager.py --action list
  python snapshot_manager.py --action get --id SNAP-20260801-001
  python snapshot_manager.py --action rollback --id SNAP-20260801-001
        """,
    )
    parser.add_argument("--action", required=True,
                        choices=["create", "compare", "gate", "list", "get", "rollback"],
                        help="操作类型")
    parser.add_argument("--project", default=".", help="项目根目录")
    parser.add_argument("--trigger", default="manual", help="快照触发原因 (create)")
    parser.add_argument("--id", help="快照 ID (get/rollback)")
    parser.add_argument("--before", help="之前的快照 ID (compare/gate)")
    parser.add_argument("--after", help="之后的快照 ID (compare/gate)")
    parser.add_argument("--format", default="text", choices=["text", "json"],
                        help="输出格式")
    args = parser.parse_args()

    project = os.path.abspath(args.project)

    if args.action == "create":
        result = create_snapshot(args.trigger, project)
        _output(result, args.format)
    elif args.action == "compare":
        _check_req(args.before, "--before", "compare")
        _check_req(args.after, "--after", "compare")
        result = compare_snapshots(args.before, args.after, project)
        _output(result, args.format, _fmt_compare)
    elif args.action == "gate":
        _check_req(args.before, "--before", "gate")
        _check_req(args.after, "--after", "gate")
        result = auto_gate(args.before, args.after, project)
        _output(result, args.format, _fmt_gate)
    elif args.action == "list":
        result = list_snapshots(project)
        _output(result, args.format, _fmt_list)
    elif args.action == "get":
        _check_req(args.id, "--id", "get")
        snap = get_snapshot(args.id, project)
        if snap is None:
            print(f"快照 '{args.id}' 不存在")
            sys.exit(1)
        _output(snap, args.format, _fmt_snapshot)
    elif args.action == "rollback":
        _check_req(args.id, "--id", "rollback")
        result = rollback_to(args.id, project)
        _output(result, args.format, _fmt_rollback)


def _check_req(value: str | None, flag: str, action: str) -> None:
    if not value:
        _log(f"错误: --action {action} 需要 {flag}")
        sys.exit(1)


def _output(data: Any, fmt: str, text_fmt=None) -> None:
    if fmt == "json":
        print(json.dumps(data, indent=2, ensure_ascii=False, default=str))
    elif text_fmt:
        text_fmt(data)
    elif isinstance(data, dict):
        status = data.get("status", "")
        icon = {"created": "✅", "not_found": "❌", "pending_manual": "⏪"}.get(status, "")
        print(f"{icon} {status}: {data.get('snapshot_id', data.get('message', ''))}")
    else:
        print(data)


def _fmt_compare(r: dict) -> None:
    print(f"\n{'=' * 60}")
    print(f"  快照对比: {r.get('before_id', '?')} → {r.get('after_id', '?')}")
    print(f"  裁定: {r.get('verdict', 'N/A').upper()}")
    print(f"{'=' * 60}")
    for label, key in [("✅ 改善", "improved"), ("❌ 恶化", "degraded"),
                       ("➡️ 不变", "unchanged")]:
        items = r.get(key, [])
        if items:
            print(f"\n  {label}:")
            for item in items:
                print(f"    - {item}")
    fc = r.get("file_changes", {})
    if fc.get("added") or fc.get("modified") or fc.get("removed"):
        print(f"\n  📁 文件变更:")
        if fc.get("added"):
            print(f"    +{len(fc['added'])} 新增")
        if fc.get("removed"):
            print(f"    -{len(fc['removed'])} 删除")
        if fc.get("modified"):
            print(f"     {len(fc['modified'])} 修改")
    if r.get("reject_reasons"):
        print(f"\n  ⛔ 拒绝原因:")
        for reason in r["reject_reasons"]:
            print(f"    - {reason}")
    print(f"\n{'=' * 60}")


def _fmt_gate(r: dict) -> None:
    verdict = r.get("gate_result", "PENDING")
    icons = {"APPROVE": "✅", "REJECT": "⛔", "MANUAL_REVIEW": "⚠️"}
    icon = icons.get(verdict, "")
    print(f"\n{icon} 门禁结果: {verdict}")
    if r.get("should_rollback"):
        print(f"  建议: 回滚到 {r.get('before_id', '')}")
    for item in r.get("improved", [])[:5]:
        print(f"  ✅ {item}")
    for item in r.get("degraded", [])[:5]:
        print(f"  ❌ {item}")
    for reason in r.get("reject_reasons", []):
        print(f"  ⛔ {reason}")


def _fmt_list(r: dict) -> None:
    print(f"\n快照列表: {r['total']} 个")
    print("-" * 70)
    for s in r.get("snapshots", []):
        sid = s.get("snapshot_id", "")
        ts = (s.get("timestamp", "") or "")[:19]
        trigger = (s.get("trigger", "") or "")[:30]
        print(f"  {sid} | {ts} | {trigger}")
        print(f"    文件:{s.get('files',0)} 函数:{s.get('functions',0)} "
              f"CC(max={s.get('max_cc',0)},avg={s.get('avg_cc',0)}) "
              f"Block:{s.get('blocks',0)} Warn:{s.get('warns',0)}")


def _fmt_snapshot(snap: dict) -> None:
    m = snap.get("metrics", {})
    print(f"\n快照: {snap.get('snapshot_id', '')}")
    print(f"  时间: {snap.get('timestamp', '')}")
    print(f"  触发: {snap.get('trigger', '')}")
    print(f"  Git:  {(snap.get('git_commit', '') or 'N/A')[:8]}")
    print(f"  蓝图: {snap.get('blueprint_hash', 'N/A')}")
    print(f"\n  指标:")
    for key, label in [("total_files","文件"), ("total_functions","函数"),
                       ("total_lines","行数"), ("max_complexity","最大CC"),
                       ("avg_complexity","平均CC"), ("duplicate_blocks","重复块"),
                       ("architecture_cycles","循环依赖"), ("codeguard_blocks","CG阻塞"),
                       ("codeguard_warns","CG警告"), ("global_vars","全局变量"),
                       ("test_coverage","覆盖率%")]:
        print(f"    {label}: {m.get(key, 'N/A')}")
    print(f"  文件哈希: {len(snap.get('file_hashes', {}))} 个")


def _fmt_rollback(r: dict) -> None:
    print(f"\n回滚: {r.get('snapshot_id', '')}")
    print(f"  触发原因: {r.get('trigger', '')}")
    print(f"  文件数:   {r.get('file_count', 0)}")
    print(f"  建议命令: {r.get('suggested_command', '无')}")
    print(f"  说明:     {r.get('message', '')}")


if __name__ == "__main__":
    main()
