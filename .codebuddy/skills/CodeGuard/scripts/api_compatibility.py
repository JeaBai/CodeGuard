#!/usr/bin/env python3
"""API 破坏性变更检测器 (v1.0.0 — P2a)
============================================================
对比前后两份 architecture_blueprint.json 的 public_api，标记：
  1. removed       — 上版本存在但当前版本删除的函数
  2. changed_sig   — 函数签名（参数数量/名称）变更
  3. added         — 新增的公共函数
  4. deprecated    — 标记为 deprecated 但仍存在的函数

企业对标:
  - Google API Improvement Proposals (AIP) 破坏性变更检测
  - semver MAJOR/MINOR/PATCH 兼容矩阵
  - Bazel/Buck 跨模块 API 契约检测

用法:
  python api_compatibility.py --old-v1.json blueprint_v1.json --new-v2.json blueprint_v2.json
                              [--format text|json] [--output report.md]

库模式:
  from api_compatibility import diff_blueprints, format_report
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import textwrap
from typing import Any, Dict, List, Optional


def _log(msg: str) -> None:
    sys.stderr.write(f"[api_compat] {msg}\n")
    sys.stderr.flush()


# ============================================================
# 蓝图加载
# ============================================================

def load_blueprint(bp_path: str) -> Dict[str, Any]:
    if not os.path.isfile(bp_path):
        raise FileNotFoundError(f"蓝图文件不存在: {bp_path}")
    with open(bp_path, "r", encoding="utf-8") as f:
        bp = json.load(f)
    if "modules" not in bp:
        raise ValueError("蓝图缺少 modules 字段")
    modules_raw = bp["modules"]
    if isinstance(modules_raw, list):
        bp["modules"] = {m["name"]: m for m in modules_raw if isinstance(m, dict) and "name" in m}
    _log(f"加载蓝图: {bp_path} ({len(bp['modules'])} 模块)")
    return bp


# ============================================================
# 核心分析：diff 两个蓝图的 public_api
# ============================================================

def _extract_api_index(modules: Dict[str, Any]) -> Dict[str, Dict[str, Dict[str, Any]]]:
    """从蓝图模块中提取 {module_name: {func_name: func_spec}} 索引。"""
    index: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for mod_name, mod_data in modules.items():
        public_api = mod_data.get("public_api", [])
        mod_funcs: Dict[str, Dict[str, Any]] = {}
        for func in public_api:
            if not isinstance(func, dict):
                continue
            fname = func.get("name", "")
            if not fname:
                continue
            mod_funcs[fname] = {
                "arity": func.get("arity", -1),
                "params": func.get("params", func.get("signature", "")),
                "file": func.get("file", ""),
                "deprecated": func.get("deprecated", False),
            }
        if mod_funcs:
            index[mod_name] = mod_funcs
    return index


def diff_blueprints(
    old_bp: Dict[str, Any],
    new_bp: Dict[str, Any],
) -> Dict[str, Any]:
    """对比两个版本的蓝图，产出破坏性变更清单。"""
    old_index = _extract_api_index(old_bp.get("modules", {}))
    new_index = _extract_api_index(new_bp.get("modules", {}))

    result: Dict[str, Any] = {
        "old_version": old_bp.get("version", "unknown"),
        "new_version": new_bp.get("version", "unknown"),
        "total_modules_old": len(old_bp.get("modules", {})),
        "total_modules_new": len(new_bp.get("modules", {})),
        "removed": [],
        "changed_signature": [],
        "added": [],
        "deprecated": [],
        "removed_modules": [],
        "summary": {"breaking_changes": 0, "risk_level": "low"},
    }

    # 1) 检测 removed / changed_sig / added
    for mod_name, old_funcs in old_index.items():
        new_funcs = new_index.get(mod_name, {})

        # 模块被删除 → 全部函数标记为 removed
        if mod_name not in new_index:
            result["removed_modules"].append(mod_name)
            for fname, spec in old_funcs.items():
                result["removed"].append({
                    "module": mod_name, "function": fname,
                    "old_arity": spec["arity"], "old_params": spec["params"],
                    "change": "ENTIRE_MODULE_REMOVED",
                })
            continue

        for fname, old_spec in old_funcs.items():
            if fname not in new_funcs:
                result["removed"].append({
                    "module": mod_name, "function": fname,
                    "old_arity": old_spec["arity"], "old_params": old_spec["params"],
                    "change": "FUNCTION_REMOVED",
                })
            else:
                new_spec = new_funcs[fname]
                # 检测签名变更
                sig_changed = False
                sig_detail = []
                if old_spec["arity"] != new_spec["arity"] and new_spec["arity"] >= 0:
                    sig_changed = True
                    sig_detail.append(f"arity: {old_spec['arity']} → {new_spec['arity']}")
                old_params = str(old_spec.get("params", ""))
                new_params = str(new_spec.get("params", ""))
                if old_params != new_params and old_params and new_params:
                    sig_changed = True
                    sig_detail.append(f"params changed")

                if sig_changed:
                    result["changed_signature"].append({
                        "module": mod_name, "function": fname,
                        "old_arity": old_spec["arity"],
                        "new_arity": new_spec["arity"],
                        "detail": "; ".join(sig_detail),
                    })

    # 2) 检测 added
    for mod_name, new_funcs in new_index.items():
        old_funcs = old_index.get(mod_name, {})
        for fname in new_funcs:
            if fname not in old_funcs:
                result["added"].append({
                    "module": mod_name, "function": fname,
                    "new_arity": new_funcs[fname]["arity"],
                })

    # 3) 检测 deprecated
    for mod_name, new_funcs in new_index.items():
        for fname, spec in new_funcs.items():
            if spec.get("deprecated"):
                result["deprecated"].append({
                    "module": mod_name, "function": fname,
                })

    # 4) 汇总
    breaking = len(result["removed"]) + len(result["changed_signature"])
    result["summary"]["breaking_changes"] = breaking
    if breaking == 0:
        result["summary"]["risk_level"] = "safe"
    elif breaking <= 3:
        result["summary"]["risk_level"] = "medium"
    else:
        result["summary"]["risk_level"] = "high"
    result["summary"]["compatible"] = (breaking == 0)

    return result


# ============================================================
# 格式化输出
# ============================================================

def _fmt_markdown(diff: Dict[str, Any]) -> str:
    """生成 Markdown 报告。"""
    lines = [
        f"# API 破坏性变更报告",
        f"",
        f"**旧版本**: {diff['old_version']} ({diff['total_modules_old']} 模块)  ",
        f"**新版本**: {diff['new_version']} ({diff['total_modules_new']} 模块)  ",
        f"**兼容性**: {'✅ 兼容' if diff['summary']['compatible'] else '⚠️ 破坏性变更'}  ",
        f"**风险等级**: {diff['summary']['risk_level'].upper()}  ",
        f"**破坏性变更数**: {diff['summary']['breaking_changes']}  ",
        f"",
    ]

    # 被移除的函数
    if diff["removed"]:
        lines.append("## 🔴 移除的 API")
        lines.append("")
        lines.append("| 模块 | 函数 | 旧参数数量 | 变更类型 |")
        lines.append("|------|------|------------|----------|")
        for item in diff["removed"]:
            lines.append(f"| {item['module']} | `{item['function']}` | {item['old_arity']} | {item['change']} |")
        lines.append("")

    # 签名变更
    if diff["changed_signature"]:
        lines.append("## 🟡 签名变更")
        lines.append("")
        lines.append("| 模块 | 函数 | 旧参数数→新参数数 | 详情 |")
        lines.append("|------|------|--------------------|------|")
        for item in diff["changed_signature"]:
            lines.append(f"| {item['module']} | `{item['function']}` | "
                         f"{item['old_arity']}→{item['new_arity']} | {item['detail']} |")
        lines.append("")

    # 被删除的整个模块
    if diff["removed_modules"]:
        lines.append("## 🔴 移除的模块")
        lines.append("")
        for mod in diff["removed_modules"]:
            lines.append(f"- `{mod}`")
        lines.append("")

    # 新增
    if diff["added"]:
        lines.append("## 🟢 新增的 API")
        lines.append("")
        lines.append("| 模块 | 函数 | 参数数量 |")
        lines.append("|------|------|----------|")
        for item in diff["added"][:30]:
            lines.append(f"| {item['module']} | `{item['function']}` | {item['new_arity']} |")
        if len(diff["added"]) > 30:
            lines.append(f"| ... | +{len(diff['added']) - 30} 更多 | |")
        lines.append("")

    # Deprecated
    if diff["deprecated"]:
        lines.append("## ⚠️ 标记为废弃的 API")
        lines.append("")
        for item in diff["deprecated"]:
            lines.append(f"- `{item['module']}::{item['function']}`")
        lines.append("")

    return "\n".join(lines)


def _fmt_text(diff: Dict[str, Any]) -> str:
    """纯文本简单输出。"""
    lines = [
        f"API 兼容性: {diff['old_version']} → {diff['new_version']}",
        f"  破坏性变更: {diff['summary']['breaking_changes']}  |  风险: {diff['summary']['risk_level']}",
    ]
    if diff["removed"]:
        lines.append(f"  移除: {len(diff['removed'])} 个函数 / {len(diff['removed_modules'])} 个模块")
    if diff["changed_signature"]:
        lines.append(f"  签名变更: {len(diff['changed_signature'])} 个")
    if diff["added"]:
        lines.append(f"  新增: {len(diff['added'])} 个函数")
    if diff["deprecated"]:
        lines.append(f"  废弃: {len(diff['deprecated'])} 个")
    return "\n".join(lines)


# ============================================================
# CLI 入口
# ============================================================

def main() -> None:
    parser = argparse.ArgumentParser(
        description="API 破坏性变更检测器 — 对比两份蓝图 public_api 差异",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
        示例:
          python api_compatibility.py --old blueprint_v1.json --new blueprint_v2.json
          python api_compatibility.py --old v1.json --new v2.json --format json
          python api_compatibility.py --old v1.json --new v2.json --output compat_report.md
        """),
    )
    parser.add_argument("--old", required=True, help="旧版本 architecture_blueprint.json")
    parser.add_argument("--new", required=True, help="新版本 architecture_blueprint.json")
    parser.add_argument("--format", choices=["markdown", "text", "json"], default="markdown",
                        help="输出格式（默认 markdown，Markdown 报表）")
    parser.add_argument("--output", "-o", default="", help="输出文件路径（默认 stdout）")

    args = parser.parse_args()

    try:
        old_bp = load_blueprint(args.old)
        new_bp = load_blueprint(args.new)
    except (FileNotFoundError, ValueError) as e:
        _log(f"错误: {e}")
        sys.exit(1)

    diff = diff_blueprints(old_bp, new_bp)

    if args.format == "json":
        output = json.dumps(diff, ensure_ascii=False, indent=2)
    elif args.format == "text":
        output = _fmt_text(diff)
    else:  # markdown
        output = _fmt_markdown(diff)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output)
        _log(f"报告已写入: {args.output}")
    else:
        sys.stdout.write(output + "\n")
        sys.stdout.flush()

    # 退出码: 0=兼容 / 1=破坏性变更
    if not diff["summary"]["compatible"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
