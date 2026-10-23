"""ADR CLI 入口。"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from adr_store import _log, _parse_json_field, _format_date, _STATUS_ICONS
from adr_crud import list_adrs, get_adr, create_adr, update_adr
from adr_context import get_active_context, supersede_adr, get_rollback_info, export_timeline

# ============================================================
# CLI 入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="Governance Hub ADR Manager — 架构决策记录管理系统",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python adr_manager.py --action list
  python adr_manager.py --action list --status implemented
  python adr_manager.py --action get --id ADR-001
  python adr_manager.py --action active-context
  python adr_manager.py --action create --title "拆分auth_service" --context "..." --decision "..."
  python adr_manager.py --action update --id ADR-001 --status implemented
  python adr_manager.py --action supersede --old ADR-001 --new ADR-003 --reason "按新需求重做"
  python adr_manager.py --action timeline --output docs/adr-timeline.md
        """,
    )
    parser.add_argument("--action", required=True,
                        choices=["list", "get", "active-context", "create",
                                 "update", "supersede", "rollback-info", "timeline"],
                        help="操作类型")
    parser.add_argument("--id", help="ADR ID (get/update/rollback-info)")
    parser.add_argument("--status", help="过滤状态 / 更新目标状态")
    parser.add_argument("--title", help="ADR 标题 (create)")
    parser.add_argument("--context", default="", help="决策背景 (create)")
    parser.add_argument("--decision", default="", help="决策内容 (create/update)")
    parser.add_argument("--files-changed", default="", help="逗号分隔的变更文件 (create)")
    parser.add_argument("--rollback-plan", default="", help="回滚方案 (create/update)")
    parser.add_argument("--tests-required", default="", help="逗号分隔的测试列表 (create)")
    parser.add_argument("--tags-added", default="", help="新增标签 JSON (create)")
    parser.add_argument("--tags-removed", default="", help="移除标签 JSON (create)")
    parser.add_argument("--consequences-positive", default="", help="积极影响逗号分隔 (create)")
    parser.add_argument("--consequences-negative", default="", help="消极影响逗号分隔 (create)")
    parser.add_argument("--metrics-before", default="", help="修复前指标 JSON (create/update)")
    parser.add_argument("--metrics-after", default="", help="修复后指标 JSON (update)")
    parser.add_argument("--verified-by", default="", help="逗号分隔的验证方式 (update)")
    parser.add_argument("--session-id", default="", help="AI 会话标识 (create)")
    parser.add_argument("--old", dest="old_id", help="旧 ADR ID (supersede)")
    parser.add_argument("--new", dest="new_id", help="新 ADR ID (supersede)")
    parser.add_argument("--reason", default="", help="替代/更新原因")
    parser.add_argument("--output", help="输出文件路径 (timeline)")
    parser.add_argument("--project-root", default=None, help="项目根目录")
    parser.add_argument("--format", default="text", choices=["text", "json"], help="输出格式")
    args = parser.parse_args()

    root = args.project_root

    if args.action == "list":
        result = list_adrs(args.status, root)
        _output(result, args.format, _fmt_list)
    elif args.action == "get":
        _check_arg(args.id, "--id", "get")
        adr = get_adr(args.id, root)
        if adr is None:
            print(f"ADR '{args.id}' 不存在")
            sys.exit(1)
        _output(adr, args.format, _fmt_adr)
    elif args.action == "active-context":
        print(get_active_context(root))
    elif args.action == "create":
        _check_arg(args.title, "--title", "create")
        cons = {
            "positive": [p.strip() for p in args.consequences_positive.split(",") if p.strip()],
            "negative": [n.strip() for n in args.consequences_negative.split(",") if n.strip()],
        }
        files = [f.strip() for f in args.files_changed.split(",") if f.strip()]
        tests = [t.strip() for t in args.tests_required.split(",") if t.strip()]
        tags: dict = {"added": {}, "removed": {}}
        added = _parse_json_field(args.tags_added, "tags_added")
        if isinstance(added, dict):
            tags["added"] = added
        removed = _parse_json_field(args.tags_removed, "tags_removed")
        if isinstance(removed, dict):
            tags["removed"] = removed

        result = create_adr(
            title=args.title, context=args.context, decision=args.decision,
            consequences=cons, files_changed=files, rollback_plan=args.rollback_plan,
            tests_required=tests, tags_affected=tags,
            session_id=args.session_id, project_root=root,
        )
        m_before = _parse_json_field(args.metrics_before, "metrics_before")
        if isinstance(m_before, dict) and result["status"] == "created":
            update_adr(result["id"], root, metrics_before=m_before)
        _output(result, args.format)
    elif args.action == "update":
        _check_arg(args.id, "--id", "update")
        fields: dict[str, Any] = {}
        for flag, key in [("--status", "status"), ("--decision", "decision"),
                          ("--title", "title"), ("--rollback-plan", "rollback_plan")]:
            val = getattr(args, flag.replace("--", "").replace("-", "_"), None)
            if val:
                fields[key] = val
        for flag, key in [("--metrics-before", "metrics_before"),
                          ("--metrics-after", "metrics_after")]:
            val = getattr(args, flag.replace("--", "").replace("-", "_"), None)
            if val:
                fields[key] = val
        if args.verified_by:
            fields["verified_by"] = [v.strip() for v in args.verified_by.split(",") if v.strip()]
        if not fields:
            _log("错误: 未提供任何要更新的字段")
            sys.exit(1)
        result = update_adr(args.id, root, **fields)
        _output(result, args.format)
    elif args.action == "supersede":
        _check_arg(args.old_id, "--old", "supersede")
        _check_arg(args.new_id, "--new", "supersede")
        result = supersede_adr(args.old_id, args.new_id, args.reason, root)
        _output(result, args.format)
    elif args.action == "rollback-info":
        _check_arg(args.id, "--id", "rollback-info")
        result = get_rollback_info(args.id, root)
        _output(result, args.format, _fmt_rollback)
    elif args.action == "timeline":
        md = export_timeline(root)
        if args.output:
            Path(args.output).write_text(md, encoding="utf-8")
            _log(f"时间线已导出至: {args.output}")
        else:
            print(md)


# ============================================================
# 输出格式化
# ============================================================

def _check_arg(value: str | None, flag: str, action: str) -> None:
    if not value:
        _log(f"错误: --action {action} 需要 {flag}")
        sys.exit(1)


def _output(data: Any, fmt: str, text_formatter=None) -> None:
    if fmt == "json":
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return
    if text_formatter:
        text_formatter(data)
    elif isinstance(data, dict):
        status = data.get("status", "")
        icon = {"created": "✅", "updated": "✅", "superseded": "🔄",
                "not_found": "❌", "invalid_transition": "❌"}.get(status, "")
        msg = data.get("message", "")
        print(f"{icon} {status}: {data.get('id', '')}")
        if msg:
            print(f"   {msg}")
    else:
        print(data)


def _fmt_list(result: dict) -> None:
    label = "全部"
    total = result.get("total", 0)
    print(f"\nADR 列表 ({label}): {total} 条")
    print("=" * 60)
    sc = result.get("status_counts", {})
    if sc:
        print("状态统计:")
        for s in sorted(sc):
            icon = _STATUS_ICONS.get(s, "")
            print(f"  {icon} {s}: {sc[s]}")
        print()
    for a in result.get("adrs", []):
        s = a.get("status", "")
        icon = _STATUS_ICONS.get(s, "")
        print(f"  {icon} [{a['id']}] {a['title']}")
        print(f"     状态: {s} | {_format_date(a.get('date', ''))}")
        d = a.get("decision", "")
        if d:
            print(f"     决策: {d}")
        f = a.get("files_changed", [])
        if f:
            print(f"     文件: {', '.join(f[:3])}")
        print()
    if not result.get("adrs"):
        print("  *(无匹配的 ADR)*")
    print("=" * 60)


def _fmt_adr(adr: dict) -> None:
    s = adr.get("status", "")
    icon = _STATUS_ICONS.get(s, s)
    print(f"\n{'=' * 60}")
    print(f"  {icon} [{adr.get('id')}] {adr.get('title')}")
    print(f"{'=' * 60}")
    print(f"  日期: {adr.get('date', '')}")
    print(f"  状态: {s}")
    print(f"  背景: {adr.get('context', '')}")
    print(f"  决策: {adr.get('decision', '')}")
    cons = adr.get("consequences", {})
    if cons.get("positive"):
        print(f"  积极: {', '.join(cons['positive'])}")
    if cons.get("negative"):
        print(f"  消极: {', '.join(cons['negative'])}")
    for label, key in [("变更文件", "files_changed"), ("所需测试", "tests_required"),
                       ("验证方式", "verified_by")]:
        items = adr.get(key, [])
        if items:
            print(f"  {label}: {', '.join(items)}")
    tags = adr.get("tags_affected", {})
    if tags.get("added"):
        print(f"  新增标签: {json.dumps(tags['added'], ensure_ascii=False)}")
    if tags.get("removed"):
        print(f"  移除标签: {json.dumps(tags['removed'], ensure_ascii=False)}")
    rb = adr.get("rollback_plan", "")
    if rb:
        print(f"  回滚方案: {rb}")
    before = adr.get("metrics_before", {})
    after = adr.get("metrics_after", {})
    if before or after:
        print(f"  修复前: {json.dumps(before, ensure_ascii=False)}")
        print(f"  修复后: {json.dumps(after, ensure_ascii=False)}")


def _fmt_rollback(result: dict) -> None:
    aid = result.get("adr_id", "")
    print(f"\n回滚信息 — {aid}")
    print("-" * 40)
    print(f"  标题: {result.get('title', '')}")
    print(f"  状态: {result.get('status', '')}")
    print(f"  方案: {result.get('rollback_plan', '')}")
    for key, label in [("files_changed", "文件"), ("tests_required", "测试")]:
        items = result.get(key, [])
        if items:
            print(f"  {label}: {', '.join(items)}")
    before = result.get("metrics_before", {})
    after = result.get("metrics_after", {})
    if before and after:
        print(f"  指标: {json.dumps(before, ensure_ascii=False)} → {json.dumps(after, ensure_ascii=False)}")


if __name__ == "__main__":
    main()
