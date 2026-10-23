from __future__ import annotations

import argparse
import json
import os
import sys

from impact_core import _log
from impact_api import (
    analyze_change,
    analyze_file_move,
    analyze_global_var,
    analyze_module_dep,
)

# ============================================================
# CLI 入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="CodeGuard Impact Analyzer — 变更影响分析系统",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python impact_analyzer.py --action analyze --file src/auth/login.py --function login --change add_param
  python impact_analyzer.py --action analyze --file src/auth/login.py --function login --change delete
  python impact_analyzer.py --action file-move --file src/old/location.py
  python impact_analyzer.py --action global-var --name DATABASE_URL
  python impact_analyzer.py --action module-dep --module auth_service --change remove_dep
        """,
    )
    parser.add_argument("--action", required=True,
                        choices=["analyze", "file-move", "global-var", "module-dep"],
                        help="分析类型")
    parser.add_argument("--file", help="源文件路径 (analyze/file-move)")
    parser.add_argument("--function", help="函数名 (analyze)")
    parser.add_argument("--change", help="变更类型: add_param|remove_param|change_return|rename|delete")
    parser.add_argument("--name", help="全局变量名 (global-var)")
    parser.add_argument("--module", help="模块名 (module-dep)")
    parser.add_argument("--project", default=".", help="项目根目录")
    parser.add_argument("--format", default="text", choices=["text", "json"],
                        help="输出格式")
    args = parser.parse_args()

    project = os.path.abspath(args.project)

    if args.action == "analyze":
        _check(args.file, "--file", "analyze")
        _check(args.function, "--function", "analyze")
        change = args.change or "add_param"
        result = analyze_change(args.file, args.function, change, project)
        _output(result, args.format, _fmt_analyze)
    elif args.action == "file-move":
        _check(args.file, "--file", "file-move")
        result = analyze_file_move(args.file, project)
        _output(result, args.format, _fmt_impact)
    elif args.action == "global-var":
        _check(args.name, "--name", "global-var")
        result = analyze_global_var(args.name, project)
        _output(result, args.format, _fmt_global_var)
    elif args.action == "module-dep":
        _check(args.module, "--module", "module-dep")
        change = args.change or "remove_dep"
        result = analyze_module_dep(args.module, change, project)
        _output(result, args.format, _fmt_module_dep)


def _check(value: str | None, flag: str, action: str) -> None:
    if not value:
        _log(f"错误: --action {action} 需要 {flag}")
        sys.exit(1)


def _output(data: dict, fmt: str, text_fmt=None) -> None:
    if fmt == "json":
        print(json.dumps(data, indent=2, ensure_ascii=False, default=str))
    elif text_fmt:
        text_fmt(data)
    else:
        if "error" in data:
            print(f"错误: {data['error']}")
        else:
            impact = data.get("impacted_count", data.get("total_refs", 0))
            breaking = "⚠️ 破坏性" if data.get("breaking") else "✅ 安全"
            print(f"{breaking}: 影响 {impact} 处")
            print(f"建议: {data.get('recommendation', 'N/A')}")
            if data.get("alternatives"):
                for alt in data["alternatives"]:
                    print(f"  → {alt}")


def _fmt_analyze(r: dict) -> None:
    print(f"\n{'=' * 60}")
    print(f"  变更: {r.get('change', 'N/A')}")
    print(f"  影响: {r.get('impacted_count', 0)} 处调用")
    breaking = "⚠️ 破坏性变更" if r.get("breaking") else "✅ 安全变更"
    print(f"  性质: {breaking}")
    print(f"  建议: {r.get('recommendation', 'N/A')}")
    print(f"{'=' * 60}")
    if r.get("alternatives"):
        print("\n  替代方案:")
        for alt in r["alternatives"]:
            print(f"    → {alt}")
    impacted = r.get("impacted_files", [])
    if impacted:
        print(f"\n  受影响位置:")
        for imp in impacted[:15]:
            tag = {"direct_call": "📞", "test": "🧪", "import_ref": "📦"}.get(imp["type"], "📍")
            print(f"    {tag} {imp['file']}:{imp['line']}")
            if imp.get("snippet"):
                print(f"       {imp['snippet'][:80]}")
            if imp.get("action_needed"):
                print(f"       → {imp['action_needed']}")
        if len(impacted) > 15:
            print(f"    ... +{len(impacted) - 15} 处")
    if r.get("report_file"):
        print(f"\n  报告: {r['report_file']}")


def _fmt_impact(r: dict) -> None:
    print(f"\n文件影响: {r.get('impacted_count', 0)} 处引用")
    breaking = "⚠️ 需要同步更新" if r.get("breaking") else "✅ 可安全移动"
    print(f"评估: {breaking}")
    print(f"建议: {r.get('recommendation', 'N/A')}")
    for alt in r.get("alternatives", []):
        print(f"  → {alt}")
    for ref in r.get("impacted_files", [])[:10]:
        print(f"  📦 {ref['file']}:{ref['line']}")
        print(f"     {ref.get('snippet', '')[:80]}")


def _fmt_global_var(r: dict) -> None:
    reads = r.get("reads", 0)
    writes = r.get("writes", 0)
    print(f"\n全局变量: {r.get('variable', '?')}")
    print(f"  读取: {reads} 处  写入: {writes} 处")
    breaking = "⚠️ 破坏性" if r.get("breaking") else "✅ 安全"
    print(f"  评估: {breaking}")
    for alt in r.get("alternatives", []):
        print(f"  → {alt}")
    for ref in r.get("impacted_files", [])[:10]:
        icon = {"variable_write": "✏️", "variable_read": "👁️"}.get(ref["type"], "📍")
        print(f"  {icon} {ref['file']}:{ref['line']}  {ref.get('snippet', '')[:60]}")


def _fmt_module_dep(r: dict) -> None:
    print(f"\n模块依赖: {r.get('module', '?')} ({r.get('change', '')})")
    print(f"  影响模块: {r.get('impacted_count', 0)} 个")
    print(f"  前向依赖: {', '.join(r.get('forward_deps', []))}")
    print(f"  反向依赖: {', '.join(r.get('reverse_deps', []))}")
    breaking = "⚠️ 破坏性" if r.get("breaking") else "✅ 安全"
    print(f"  评估: {breaking}")
    print(f"  说明: {r.get('description', '')}")


if __name__ == "__main__":
    main()
