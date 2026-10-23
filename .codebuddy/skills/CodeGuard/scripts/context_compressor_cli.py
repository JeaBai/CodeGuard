"""上下文压缩器 CLI 入口。"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

from context_compressor_core import (
    generate_l0,
    get_context_for_task,
    refresh,
    _print_context_result,
    _log,
)
from context_compressor_levels import generate_l1, generate_l2
from context_compressor_api import generate_all

# ============================================================
# CLI 入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="CodeGuard Context Compressor — 分层上下文压缩系统",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python context_compressor.py --action generate-all --project . --blueprint blueprint.json --output .codebuddy/context/
  python context_compressor.py --action generate-l0 --blueprint blueprint.json --output l0.md
  python context_compressor.py --action generate-l1 --project . --module auth_service --blueprint blueprint.json
  python context_compressor.py --action generate-l2 --project . --module auth_service --blueprint blueprint.json
  python context_compressor.py --action get-context --task "重构 auth_service 的 login 函数" --blueprint blueprint.json
  python context_compressor.py --action refresh --file src/auth/auth_core.py
        """,
    )
    parser.add_argument("--action", required=True,
                        choices=["generate-all", "generate-l0", "generate-l1",
                                 "generate-l2", "get-context", "refresh"],
                        help="操作类型")
    parser.add_argument("--project", default=".", help="项目根目录")
    parser.add_argument("--blueprint", default="", help="architecture_blueprint.json 路径")
    parser.add_argument("--output", default=".codebuddy/context/", help="输出目录")
    parser.add_argument("--module", default="", help="模块名 (generate-l1/l2)")
    parser.add_argument("--task", default="", help="任务描述 (get-context)")
    parser.add_argument("--file", default="", help="源文件路径 (refresh)")
    parser.add_argument("--format", default="text", choices=["text", "json"],
                        help="输出格式")
    args = parser.parse_args()

    if args.action == "generate-all":
        if not args.blueprint:
            _log("错误: --action generate-all 需要 --blueprint")
            sys.exit(1)
        result = generate_all(args.project, args.blueprint, args.output)
        _output(result, args.format)
    elif args.action == "generate-l0":
        if not args.blueprint:
            _log("错误: --action generate-l0 需要 --blueprint")
            sys.exit(1)
        text = generate_l0(args.blueprint)
        if args.output and args.output != ".codebuddy/context/":
            os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(text)
            _log(f"L0 已保存: {args.output}")
        else:
            print(text)
    elif args.action == "generate-l1":
        if not args.module:
            _log("错误: --action generate-l1 需要 --module")
            sys.exit(1)
        text = generate_l1(args.project, args.module, args.blueprint or "")
        if args.output and args.output != ".codebuddy/context/":
            os.makedirs(args.output, exist_ok=True)
            fpath = os.path.join(args.output, f"{args.module}_contract.md")
            with open(fpath, "w", encoding="utf-8") as f:
                f.write(text)
            _log(f"L1 已保存: {fpath}")
        else:
            print(text)
    elif args.action == "generate-l2":
        if not args.module:
            _log("错误: --action generate-l2 需要 --module")
            sys.exit(1)
        text = generate_l2(args.project, args.module, args.blueprint or "")
        print(text)
    elif args.action == "get-context":
        if not args.task:
            _log("错误: --action get-context 需要 --task")
            sys.exit(1)
        # 推断 L1/L2 目录
        ctx_dir = os.path.join(args.project, ".codebuddy", "context")
        l1_dir = os.path.join(ctx_dir, "L1_modules")
        l2_dir = os.path.join(ctx_dir, "L2_details")
        result = get_context_for_task(
            args.task, args.blueprint,
            l1_dir if os.path.isdir(l1_dir) else None,
            l2_dir if os.path.isdir(l2_dir) else None,
        )
        if args.format == "json":
            r = dict(result)
            r.pop("l0", None)  # L0 太长不放入 JSON
            print(json.dumps(r, indent=2, ensure_ascii=False))
        else:
            _print_context_result(result)
    elif args.action == "refresh":
        if not args.file:
            _log("错误: --action refresh 需要 --file")
            sys.exit(1)
        result = refresh(args.file, args.blueprint or None)
        _output(result, args.format)


def _output(data: Any, fmt: str) -> None:
    if fmt == "json":
        print(json.dumps(data, indent=2, ensure_ascii=False, default=str))
    elif isinstance(data, dict):
        for k, v in data.items():
            if not isinstance(v, (list, dict, str)):
                print(f"{k}: {v}")
        if data.get("status"):
            icon = {"generated": "✅", "refreshed": "✅",
                    "not_found": "❌"}.get(data["status"], "")
            print(f"{icon} {data['status']}: {data.get('module', '') or data.get('reason', '')}")
    else:
        print(data)


if __name__ == "__main__":
    main()
