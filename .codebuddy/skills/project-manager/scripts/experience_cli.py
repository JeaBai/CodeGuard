"""经验资产库 CLI 入口。"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from experience_api import register, search
from experience_ops import load_to_context, tag, expire, list_by_project, stats
from experience_store import dedup_check, backup_to_json, restore_from_json

def main():
    parser = argparse.ArgumentParser(description="经验资产库管理器 — project-manager v2.2")
    parser.add_argument("--action", required=True, choices=[
        "register", "search", "load", "tag", "expire", "list-by-project", "stats",
        "dedup-check", "backup", "restore",  # v2.3 新增
    ])
    parser.add_argument("--type", help="资产类型 (register 用)")
    parser.add_argument("--title", help="资产标题 (register 用)")
    parser.add_argument("--content", help="资产内容 (register 用)")
    parser.add_argument("--tags", default="", help="逗号分隔标签")
    parser.add_argument("--visibility", default="private", help="可见性级别")
    parser.add_argument("--project", default="", help="来源项目名称")
    parser.add_argument("--owner", default="", help="所有者")
    parser.add_argument("--source", default="", help="来源描述")
    parser.add_argument("--keywords", default="", help="搜索关键词（空格分隔）")
    parser.add_argument("--asset-id", default="", help="资产 ID")
    parser.add_argument("--version-tag", default="", help="版本标签 (tag 用)")
    parser.add_argument("--use-fts", action="store_true", help="使用 SQLite FTS5 全文检索 (search 用)")  # v2.3
    parser.add_argument("--format", default="json", choices=["json", "text"],
                        help="输出格式")

    args = parser.parse_args()

    result: Any = {}

    if args.action == "register":
        if not args.type or not args.title or not args.content:
            print("错误: register 需要 --type --title --content", file=sys.stderr)
            sys.exit(2)
        result = register(
            asset_type=args.type, title=args.title, content=args.content,
            tags=args.tags, visibility=args.visibility, project_name=args.project,
            owner=args.owner, source=args.source,
        )

    elif args.action == "search":
        result = search(keywords=args.keywords, visibility_filter=args.visibility,
                        asset_type_filter=args.type, tag_filter=args.tags,
                        use_fts=args.use_fts)

    elif args.action == "load":
        if not args.asset_id:
            print("错误: load 需要 --asset-id", file=sys.stderr)
            sys.exit(2)
        result = load_to_context(args.asset_id)

    elif args.action == "tag":
        if not args.asset_id or not args.version_tag:
            print("错误: tag 需要 --asset-id --version-tag", file=sys.stderr)
            sys.exit(2)
        result = tag(args.asset_id, args.version_tag)

    elif args.action == "expire":
        if not args.asset_id:
            print("错误: expire 需要 --asset-id", file=sys.stderr)
            sys.exit(2)
        result = expire(args.asset_id)

    elif args.action == "list-by-project":
        result = list_by_project(args.project)

    elif args.action == "stats":
        result = stats()

    elif args.action == "dedup-check":
        result = dedup_check(args.title, args.content)

    elif args.action == "backup":
        result = backup_to_json(args.output)

    elif args.action == "restore":
        result = restore_from_json(args.output)

    if args.format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        if isinstance(result, list):
            for item in result:
                print(f"- [{item.get('asset_type', '?')}] {item.get('title', '?')} "
                      f"(ID: {item.get('asset_id', '?')}, v{item.get('version', '?')})")
                if item.get("tags"):
                    print(f"  标签: {', '.join(item['tags'])}")
        elif isinstance(result, dict):
            for k, v in result.items():
                print(f"{k}: {v}")


if __name__ == "__main__":
    main()
