"""标签管理 CLI 入口。"""
from __future__ import annotations

import argparse
import json
import os
import sys

from tag_store import _log
from tag_api import list_tags, apply_tag, remove_tag, validate_tags
from tag_check import check_violation
from tag_export import export_constraint_doc

# ============================================================
# CLI 入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="Governance Hub Tag Manager — 模块标签管理系统",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python tag_manager.py --blueprint blueprint.json --action list
  python tag_manager.py --blueprint blueprint.json --action apply --module auth_service --tag frozen
  python tag_manager.py --blueprint blueprint.json --action remove --module auth_service --tag frozen
  python tag_manager.py --blueprint blueprint.json --action validate
  python tag_manager.py --blueprint blueprint.json --action check --module auth_service --action-type split_file
  python tag_manager.py --blueprint blueprint.json --action export-doc --output constraints.md
        """,
    )
    parser.add_argument("--blueprint", required=True, help="architecture_blueprint.json 路径")
    parser.add_argument("--action", required=True,
                        choices=["list", "apply", "remove", "validate", "check", "export-doc"],
                        help="操作类型")
    parser.add_argument("--module", help="模块名称（apply/remove/check 需要）")
    parser.add_argument("--tag", help="标签名称（apply/remove 需要）")
    parser.add_argument("--action-type", help="操作动词（check 需要），如 split_file/change_api 等")
    parser.add_argument("--output", help="导出文件路径（export-doc 需要）")
    parser.add_argument("--format", default="text", choices=["text", "json"],
                        help="输出格式")
    args = parser.parse_args()

    # 检查蓝图文件存在
    if not os.path.isfile(args.blueprint):
        _log(f"错误: 蓝图文件不存在: {args.blueprint}")
        sys.exit(1)

    # 分发操作
    if args.action == "list":
        result = list_tags()
        if args.format == "json":
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            _print_tags_text(result)

    elif args.action == "apply":
        if not args.module or not args.tag:
            _log("错误: --action apply 需要 --module 和 --tag")
            sys.exit(1)
        result = apply_tag(args.blueprint, args.module, args.tag)
        _print_result(result, args.format)

    elif args.action == "remove":
        if not args.module or not args.tag:
            _log("错误: --action remove 需要 --module 和 --tag")
            sys.exit(1)
        result = remove_tag(args.blueprint, args.module, args.tag)
        _print_result(result, args.format)

    elif args.action == "validate":
        result = validate_tags(args.blueprint)
        if args.format == "json":
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            _print_validate_text(result)

    elif args.action == "check":
        if not args.module or not args.action_type:
            _log("错误: --action check 需要 --module 和 --action-type")
            sys.exit(1)
        result = check_violation(args.blueprint, args.module, args.action_type)
        if args.format == "json":
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            icon = "✅ 允许" if result["allowed"] else "❌ 禁止"
            print(f"{icon}: {result['reason']}")
            if result.get("blocked_by_tag"):
                print(f"  阻断标签: {result['blocked_by_tag']}")

    elif args.action == "export-doc":
        doc = export_constraint_doc(args.blueprint)
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(doc)
            _log(f"约束文档已导出至: {args.output}")
        else:
            print(doc)


def _print_result(result: dict, fmt: str) -> None:
    if fmt == "json":
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        status = result.get("status", "unknown")
        icon = {"applied": "✅", "removed": "✅", "already_exists": "⚠️", "not_found": "⚠️", "error": "❌"}.get(status, "")
        print(f"{icon} {result.get('message', '')}")
        if result.get("tags"):
            print(f"   当前标签: {', '.join(result['tags'])}")


def _print_tags_text(data: dict) -> None:
    """格式化打印标签列表（纯文本）。"""
    print("\n" + "=" * 60)
    print("  标签管理 — 可用标签清单")
    print("=" * 60)

    meta = data.get("_meta", {})
    print(f"  版本: {meta.get('version', 'N/A')}  "
          f"模块标签: {meta.get('total_module_tags', 0)}  参数标签: {meta.get('total_param_tags', 0)}")
    print()

    print("  ── 模块标签 ──")
    for tag, info in data.get("module_tags", {}).items():
        sev = info.get("severity_hint", "info")
        sev_icon = {"block": "⛔", "warn": "⚠️", "info": "ℹ️"}.get(sev, "")
        print(f"  {sev_icon} [{tag}] {info['description']}")
        if info.get("conflicts_with"):
            print(f"       冲突: {', '.join(info['conflicts_with'])}")
        print(f"       允许: {', '.join(info['allows'][:3])}{'...' if len(info['allows']) > 3 else ''}")
        print(f"       禁止: {', '.join(info['forbids'][:3])}{'...' if len(info['forbids']) > 3 else ''}")
        print()

    print("  ── 参数标签 ──")
    for tag, info in data.get("param_tags", {}).items():
        scope = info.get("scope", "any")
        print(f"  [{tag}] ({scope}) {info.get('description', '')}")
    print()

    print("  ── 操作动词 ──")
    for verb, desc in data.get("action_verbs", {}).items():
        print(f"  {verb:20s} — {desc}")
    print("=" * 60)


def _print_validate_text(result: dict) -> None:
    """格式化打印校验结果（纯文本）。"""
    print(f"\n标签校验 — 状态: {result['status']}")
    print(f"  模块总数: {result.get('total_modules', 0)}")
    print(f"  冲突: {len(result.get('conflicts', []))}")
    print(f"  过期 legacy: {len(result.get('expired_legacy', []))}")
    print(f"  警告: {len(result.get('warnings', []))}")

    for c in result.get("conflicts", []):
        print(f"  ❌ {c['module']}: '{c['tag']}' 与 '{c['conflicts_with']}' 冲突")

    for e in result.get("expired_legacy", []):
        print(f"  ⏰ {e}")

    for w in result.get("warnings", []):
        print(f"  ⚠️ {w}")

    if result["status"] == "valid":
        print("\n✅ 所有标签配置一致，无冲突。")


if __name__ == "__main__":
    main()
