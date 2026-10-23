#!/usr/bin/env python3
"""
Governance Hub Intent Protection (v1.0.0)
============================================
设计意图保护系统 — 记录用户已确认为有意设计的代码模式，
防止 CodeGuard 误报，在 IssueCollector.add() 之前自动过滤。

功能：
  - add_protection(file, function, line_range, code_smell, reason, decision, tags, expires)  新增保护项
  - remove_protection(id)                移除保护项
  - check_protected(file, line, rule_id) 检查某行某规则是否被保护
  - list_expired()                       列出已过期的保护项
  - list_active()                        列出所有活跃保护项
  - export_report()                      导出保护清单人话报告

CodeGuard 集成：
  # 在 IssueCollector.add() 之前调用
  result = intent_protection.check_protected(filepath, line, category)
  if result["protected"]:
      if result["action"] == "skip":
          return  # 跳过此 issue
      elif result["action"] == "downgrade_to_info":
          severity = "info"
      elif result["action"] == "report_with_note":
          message += f" [保护项 {result['protection_id']}: 用户已确认为有意设计]"

用法：
  python intent_protection.py --action add --file payment.py --function process --smell "..." --reason "..." --decision "..." --tags no_split,legacy --expires 2026-12-31
  python intent_protection.py --action remove --id PROT-001
  python intent_protection.py --action check --file payment.py --line 100 --rule GOLD_NO_PRINT_PRODUCTION
  python intent_protection.py --action list-expired
  python intent_protection.py --action list-active
  python intent_protection.py --action report --output protection_report.md

设计依据：
  - 与 CodeGuard IssueCollector.add() 的 codeguard:ignore 行级豁免互补（行级 vs 块级/函数级）
  - 与 tag_manager.py 的标签系统协同（protected_tags 字段引用模块标签）
  - 自动过期机制：每次 check_protected() 时检测 expires 字段
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ============================================================
# 常量
# ============================================================

_SCRIPT_DIR = Path(__file__).resolve().parent
_DATA_PATH = _SCRIPT_DIR / "intent_protection.json"

_TAG_ACTION_MAP = {
    "no_split": "skip",
    "legacy": "skip",
    "frozen": "skip",
    "global_config": "downgrade_to_info",
    "test_only": "downgrade_to_info",
}

DEFAULT_ACTION = "report_with_note"

_VALID_STATUSES = frozenset({"active", "expired", "revoked"})


# ============================================================
# 工具函数
# ============================================================

def _log(msg: str) -> None:
    sys.stderr.write(f"[IntentProtection] {msg}\n")
    sys.stderr.flush()


def _load_data() -> dict:
    """加载 intent_protection.json。"""
    if not _DATA_PATH.exists():
        return {"_meta": {}, "protected_items": []}
    with open(_DATA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_data(data: dict) -> None:
    """保存 intent_protection.json。"""
    data.setdefault("_meta", {})["last_updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with open(_DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    _log(f"数据已保存: {_DATA_PATH}")


def _next_id(items: list[dict]) -> str:
    """自动生成下一个保护项 ID (PROT-001, PROT-002, ...)。"""
    max_num = 0
    for item in items:
        pid = item.get("id", "")
        match = re.match(r"PROT-(\d+)", pid)
        if match:
            max_num = max(max_num, int(match.group(1)))
    return f"PROT-{max_num + 1:03d}"


def _auto_expire(items: list[dict]) -> bool:
    """自动将过期项 status 改为 'expired'。返回是否有变更。"""
    now = datetime.now(timezone.utc)
    changed = False
    for item in items:
        if item.get("status") != "active":
            continue
        expires_str = item.get("expires", "")
        if not expires_str:
            continue
        try:
            # 尝试多种 ISO8601 格式
            for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ"):
                try:
                    expire_date = (datetime.strptime(expires_str.replace("Z", "+0000"),
                                                     fmt.replace("Z", "+0000"))
                                   .replace(tzinfo=timezone.utc))
                    if expire_date < now:
                        item["status"] = "expired"
                        item["notes"] = (item.get("notes", "") +
                                         f" [自动过期于 {now.strftime('%Y-%m-%d')}]").strip()
                        changed = True
                        _log(f"保护项 {item['id']} 已过期: {item.get('function', item.get('file', ''))}")
                    break
                except ValueError:
                    continue
        except (ValueError, TypeError):
            pass
    return changed


def _resolve_action(tags: list[str]) -> str:
    """根据标签列表解析保护动作。

    规则（优先级从高到低）：
      - no_split / legacy / frozen → skip（完全跳过 CodeGuard 检测）
      - global_config / test_only → downgrade_to_info（降级为 info）
      - 其他 → report_with_note（保留 issue 但添加保护标记）
    """
    for tag in tags:
        if tag in _TAG_ACTION_MAP:
            return _TAG_ACTION_MAP[tag]
    return DEFAULT_ACTION


def _match_file(file_pattern: str, target_file: str) -> bool:
    """检查文件路径是否匹配模式（支持后缀匹配和路径段匹配）。"""
    if file_pattern == target_file:
        return True
    normalized_pattern = file_pattern.replace("\\", "/").lower()
    normalized_target = target_file.replace("\\", "/").lower()
    if normalized_target.endswith(normalized_pattern):
        return True
    if f"/{normalized_pattern}" in normalized_target or normalized_target.endswith(f"/{normalized_pattern}"):
        return True
    pattern_parts = [p for p in normalized_pattern.split("/") if p]
    target_parts = [p for p in normalized_target.split("/") if p]
    if len(pattern_parts) <= len(target_parts):
        if target_parts[-len(pattern_parts):] == pattern_parts:
            return True
    return False


def _in_line_range(line: int, line_range: list[int]) -> bool:
    """检查行号是否在保护范围内。"""
    if not line_range or len(line_range) < 2:
        return True  # 无范围限制 = 全文件保护
    return line_range[0] <= line <= line_range[1]


# ============================================================
# 公共 API：add_protection()
# ============================================================

def add_protection(
    file: str,
    function: str,
    line_range: list[int],
    code_smell: str,
    reason: str,
    decision: str,
    tags: list[str],
    expires: str,
    protected_by: str = "",
    suppress_rules: list[str] | None = None,
) -> dict:
    """新增保护项。

    Args:
        file: 源文件路径。
        function: 函数名（空字符串表示文件级保护）。
        line_range: [start, end] 或空列表 []。
        code_smell: 代码异味描述。
        reason: 保护原因。
        decision: 团队决策。
        tags: 关联标签列表。
        expires: 过期日期 (YYYY-MM-DD 或 ISO8601)。
        protected_by: 创建者。
        suppress_rules: 被抑制的 CodeGuard 规则 ID。

    Returns:
        {"status": "added", "id": str, "item": dict}
    """
    data = _load_data()
    items = data.setdefault("protected_items", [])

    # 自动过期检查
    _auto_expire(items)

    # 生成 ID
    pid = _next_id(items)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    action = _resolve_action(tags)

    item = {
        "id": pid,
        "file": file,
        "function": function,
        "line_range": line_range if line_range else [],
        "code_smell": code_smell,
        "reason": reason,
        "decision": decision,
        "protected_tags": tags,
        "protected_by": protected_by or os.environ.get("USER", os.environ.get("USERNAME", "unknown")),
        "created_at": now,
        "expires": expires,
        "status": "active",
        "action": action,
        "suppress_rules": suppress_rules or [],
        "notes": "",
    }

    items.append(item)
    _save_data(data)
    _log(f"新增保护项: {pid} ({file}{':' + function if function else ''})")
    return {"status": "added", "id": pid, "item": item}


# ============================================================
# 公共 API：remove_protection()
# ============================================================

def remove_protection(pid: str) -> dict:
    """移除保护项。

    Returns:
        {"status": "removed" | "not_found", "id": str}
    """
    data = _load_data()
    items = data.setdefault("protected_items", [])

    for i, item in enumerate(items):
        if item.get("id") == pid:
            removed = items.pop(i)
            _save_data(data)
            _log(f"移除保护项: {pid}")
            return {"status": "removed", "id": pid, "item": removed}

    return {"status": "not_found", "id": pid}


# ============================================================
# 公共 API：check_protected()
# ============================================================

def check_protected(file: str, line: int, rule_id: str = "") -> dict:
    """检查某行某规则是否被保护。

    这是 CodeGuard 集成的核心入口点。在 IssueCollector.add() 之前调用此函数。

    Args:
        file: 源文件路径。
        line: 行号。
        rule_id: CodeGuard 规则 ID（如 GOLD_NO_PRINT_PRODUCTION），用于精确规则匹配。

    Returns:
        {
            "protected": bool,
            "protection_id": str | None,
            "action": "skip" | "downgrade_to_info" | "report_with_note" | None,
            "reason": str,
            "protected_tags": [str],
        }
    """
    data = _load_data()
    items = data.setdefault("protected_items", [])

    # 自动过期检查
    if _auto_expire(items):
        _save_data(data)
        # 重新加载以获取更新后的状态
        data = _load_data()
        items = data.setdefault("protected_items", [])

    for item in items:
        if item.get("status") != "active":
            continue

        # 文件匹配
        if not _match_file(item.get("file", ""), file):
            continue

        # 行范围匹配
        if not _in_line_range(line, item.get("line_range", [])):
            continue

        # 规则匹配（如果提供了 rule_id 且保护项指定了 suppress_rules）
        suppress_rules = item.get("suppress_rules", [])
        if rule_id and suppress_rules:
            if rule_id not in suppress_rules:
                continue

        # 找到匹配的保护项
        action = item.get("action", DEFAULT_ACTION)
        return {
            "protected": True,
            "protection_id": item.get("id"),
            "action": action,
            "reason": item.get("reason", ""),
            "protected_tags": item.get("protected_tags", []),
            "decision": item.get("decision", ""),
            "note": f"[保护项 {item.get('id')}: {item.get('decision', '用户已确认为有意设计')}]",
        }

    return {
        "protected": False,
        "protection_id": None,
        "action": None,
        "reason": "",
        "protected_tags": [],
        "decision": "",
        "note": "",
    }


# ============================================================
# 公共 API：list_expired()
# ============================================================

def list_expired() -> dict:
    """列出已过期的保护项。

    Returns:
        {"expired": [item], "count": int}
    """
    data = _load_data()
    items = data.setdefault("protected_items", [])
    _auto_expire(items)

    expired = [item for item in items if item.get("status") == "expired"]
    return {"expired": expired, "count": len(expired)}


# ============================================================
# 公共 API：list_active()
# ============================================================

def list_active() -> dict:
    """列出所有活跃保护项。

    Returns:
        {"active": [item], "count": int, "by_tag": {tag: count}}
    """
    data = _load_data()
    items = data.setdefault("protected_items", [])
    _auto_expire(items)

    active = [item for item in items if item.get("status") == "active"]
    by_tag: dict[str, int] = {}
    for item in active:
        for tag in item.get("protected_tags", []):
            by_tag[tag] = by_tag.get(tag, 0) + 1

    return {"active": active, "count": len(active), "by_tag": by_tag}


# ============================================================
# 公共 API：export_report()
# ============================================================

def export_report() -> str:
    """导出保护清单人话报告（Markdown 格式）。

    Returns:
        完整的 Markdown 文档字符串。
    """
    data = _load_data()
    items = data.setdefault("protected_items", [])
    _auto_expire(items)

    active_items = [i for i in items if i.get("status") == "active"]
    expired_items = [i for i in items if i.get("status") == "expired"]
    revoked_items = [i for i in items if i.get("status") == "revoked"]

    lines = []
    lines.append("# 设计意图保护清单")
    lines.append("")
    lines.append(f"> 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"> 活跃保护项: {len(active_items)} | 已过期: {len(expired_items)} | 已撤销: {len(revoked_items)}")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 统计摘要")
    lines.append("")

    # 按标签统计
    tag_stats: dict[str, int] = {}
    action_stats: dict[str, int] = {}
    for item in active_items:
        for tag in item.get("protected_tags", []):
            tag_stats[tag] = tag_stats.get(tag, 0) + 1
        action = item.get("action", DEFAULT_ACTION)
        action_stats[action] = action_stats.get(action, 0) + 1

    lines.append("### 按标签分布")
    lines.append("")
    lines.append("| 标签 | 保护项数 | CodeGuard 动作 |")
    lines.append("|------|----------|---------------|")
    for tag, count in sorted(tag_stats.items(), key=lambda x: -x[1]):
        action = _TAG_ACTION_MAP.get(tag, DEFAULT_ACTION)
        action_icon = {"skip": "跳过", "downgrade_to_info": "降级为 info", "report_with_note": "报告+标记"}.get(action, action)
        lines.append(f"| {tag} | {count} | {action_icon} |")
    lines.append("")

    lines.append("### 按动作分布")
    lines.append("")
    for action, count in sorted(action_stats.items()):
        lines.append(f"- **{action}**: {count} 项")
    lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## 活跃保护项")
    lines.append("")

    if not active_items:
        lines.append("*(当前无活跃保护项)*")
    else:
        for item in active_items:
            pid = item.get("id", "")
            fname = item.get("file", "")
            func = item.get("function", "")
            tags = item.get("protected_tags", [])
            action = item.get("action", "")
            expires = item.get("expires", "")

            lines.append(f"### {pid}: {fname}")
            if func:
                lines.append(f"**函数**: `{func}`")
            lines.append(f"- **行范围**: {_fmt_range(item.get('line_range', []))}")
            lines.append(f"- **代码异味**: {item.get('code_smell', '')}")
            lines.append(f"- **保护原因**: {item.get('reason', '')}")
            lines.append(f"- **团队决策**: {item.get('decision', '')}")
            lines.append(f"- **标签**: {', '.join(tags)} → CodeGuard 动作: `{action}`")
            lines.append(f"- **创建者**: {item.get('protected_by', '')} | 创建于: {item.get('created_at', '')}")
            if expires:
                lines.append(f"- **过期日期**: {expires}")
            if item.get("suppress_rules"):
                lines.append(f"- **抑制规则**: {', '.join(item['suppress_rules'])}")
            lines.append("")

    # 过期项
    if expired_items:
        lines.append("---")
        lines.append("")
        lines.append("## ⚠️ 已过期保护项")
        lines.append("")
        lines.append("> 以下保护项已过期，CodeGuard 不再跳过这些代码。请确认是否需要续期或处理。")
        lines.append("")
        for item in expired_items:
            lines.append(f"- **{item.get('id')}**: {item.get('file', '')} — {item.get('reason', '')}")
            lines.append(f"  过期于: {item.get('expires', '')}")
            lines.append("")

    # 已撤销项
    if revoked_items:
        lines.append("---")
        lines.append("")
        lines.append("## 已撤销保护项")
        lines.append("")
        for item in revoked_items:
            lines.append(f"- **{item.get('id')}**: {item.get('file', '')} — {item.get('reason', '')}")
            lines.append("")

    lines.append("---")
    lines.append("")
    lines.append(f"*报告由 Governance Hub Intent Protection v1.0.0 自动生成*")
    lines.append("")

    return "\n".join(lines)


def _fmt_range(line_range: list[int]) -> str:
    """格式化行范围。"""
    if not line_range or len(line_range) < 2:
        return "整个文件"
    return f"L{line_range[0]}-L{line_range[1]}"


# ============================================================
# CLI 入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="Governance Hub Intent Protection — 设计意图保护系统",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python intent_protection.py --action add \\
      --file src/legacy/payment.py --function process_response \\
      --smell "函数380行，圈复杂度22" --reason "兼容14种老网关格式" \\
      --decision "禁止拆分，等迁移后删除" --tags no_split,legacy \\
      --expires 2026-12-31

  python intent_protection.py --action check \\
      --file src/legacy/payment.py --line 100 --rule GOLD_NO_PRINT_PRODUCTION

  python intent_protection.py --action list-active
  python intent_protection.py --action list-expired
  python intent_protection.py --action remove --id PROT-001
  python intent_protection.py --action report --output protection_report.md
  python intent_protection.py --action report --format json
        """,
    )
    parser.add_argument("--action", required=True,
                        choices=["add", "remove", "check", "list-active", "list-expired", "report"],
                        help="操作类型")
    parser.add_argument("--file", help="文件路径 (add/check)")
    parser.add_argument("--function", default="", help="函数名 (add)")
    parser.add_argument("--line-range", help="行范围，如 '45,425' (add)")
    parser.add_argument("--line", type=int, help="行号 (check)")
    parser.add_argument("--rule", default="", help="CodeGuard 规则 ID (check)")
    parser.add_argument("--smell", default="", help="代码异味描述 (add)")
    parser.add_argument("--reason", default="", help="保护原因 (add)")
    parser.add_argument("--decision", default="", help="团队决策 (add)")
    parser.add_argument("--tags", default="", help="逗号分隔的标签列表 (add)")
    parser.add_argument("--expires", default="", help="过期日期 YYYY-MM-DD (add)")
    parser.add_argument("--protected-by", default="", help="创建者 (add)")
    parser.add_argument("--suppress-rules", default="", help="逗号分隔的抑制规则 ID (add)")
    parser.add_argument("--id", help="保护项 ID (remove)")
    parser.add_argument("--output", help="输出文件路径 (report)")
    parser.add_argument("--format", default="text", choices=["text", "json"],
                        help="输出格式")
    parser.add_argument("--action-field", default="",
                        help="显式设置 CodeGuard 动作: skip/downgrade_to_info/report_with_note（覆盖标签推断）")
    args = parser.parse_args()

    # 分发操作
    if args.action == "add":
        if not args.file:
            _log("错误: --action add 需要 --file")
            sys.exit(1)

        # 解析标签
        tags = [t.strip() for t in args.tags.split(",") if t.strip()] if args.tags else []
        suppress_rules = [r.strip() for r in args.suppress_rules.split(",") if r.strip()] if args.suppress_rules else []

        # 解析行范围
        line_range = []
        if args.line_range:
            parts = args.line_range.split(",")
            if len(parts) == 2:
                try:
                    line_range = [int(parts[0].strip()), int(parts[1].strip())]
                except ValueError:
                    _log("错误: --line-range 格式应为 'start,end' (如 '45,425')")
                    sys.exit(1)

        result = add_protection(
            file=args.file,
            function=args.function,
            line_range=line_range,
            code_smell=args.smell,
            reason=args.reason,
            decision=args.decision,
            tags=tags,
            expires=args.expires,
            protected_by=args.protected_by,
            suppress_rules=suppress_rules,
        )

        # 如果用户显式指定了 action，覆盖自动推断
        if args.action_field and result["status"] == "added":
            data = _load_data()
            for item in data.get("protected_items", []):
                if item.get("id") == result["id"]:
                    item["action"] = args.action_field
                    _save_data(data)
                    result["item"]["action"] = args.action_field
                    break

        _print_result(result, args.format)

    elif args.action == "remove":
        if not args.id:
            _log("错误: --action remove 需要 --id")
            sys.exit(1)
        result = remove_protection(args.id)
        _print_result(result, args.format)

    elif args.action == "check":
        if not args.file:
            _log("错误: --action check 需要 --file")
            sys.exit(1)
        result = check_protected(args.file, args.line or 0, args.rule)
        if args.format == "json":
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            if result["protected"]:
                action_icon = {"skip": "⏭️ 跳过", "downgrade_to_info": "ℹ️ 降级为 info", "report_with_note": "📝 报告+标记"}.get(result["action"], result["action"])
                print(f"🛡️  受保护: {result['protection_id']}")
                print(f"   动作: {action_icon}")
                print(f"   原因: {result['reason']}")
                print(f"   标记: {result['note']}")
            else:
                print(f"✅ 未保护: 该位置没有活跃的保护项")
            if not result["protected"] and result.get("protection_id") is None:
                pass

    elif args.action == "list-active":
        result = list_active()
        if args.format == "json":
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            _print_active_text(result)

    elif args.action == "list-expired":
        result = list_expired()
        if args.format == "json":
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            _print_expired_text(result)

    elif args.action == "report":
        report_text = export_report()
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(report_text)
            _log(f"报告已导出至: {args.output}")
        else:
            print(report_text)


def _print_result(result: dict, fmt: str) -> None:
    if fmt == "json":
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        status = result.get("status", "")
        pid = result.get("id", "")
        icons = {"added": "✅", "removed": "✅", "not_found": "❌", "error": "❌"}
        print(f"{icons.get(status, '')} {status}: {pid}")
        if status == "added" and result.get("item"):
            item = result["item"]
            print(f"   文件: {item.get('file', '')}")
            print(f"   标签: {', '.join(item.get('protected_tags', []))}")
            print(f"   动作: {item.get('action', '')}")
            print(f"   过期: {item.get('expires', '')}")


def _print_active_text(result: dict) -> None:
    print(f"\n活跃保护项: {result['count']}")
    print("-" * 60)
    for item in result.get("active", []):
        tags_str = ", ".join(item.get("protected_tags", []))
        action = item.get("action", "")
        action_label = {"skip": "跳过", "downgrade_to_info": "降级", "report_with_note": "标记"}.get(action, action)
        location = item.get("file", "")
        if item.get("function"):
            location += f"::{item.get('function')}()"
        print(f"  {item.get('id')} | {location}")
        print(f"        标签: {tags_str} | 动作: {action_label} | 过期: {item.get('expires', '')}")
    if not result.get("active"):
        print("  *(无)*")
    print()

    if result.get("by_tag"):
        print("按标签分布:")
        for tag, count in sorted(result["by_tag"].items(), key=lambda x: -x[1]):
            print(f"  {tag}: {count}")
        print()


def _print_expired_text(result: dict) -> None:
    print(f"\n已过期保护项: {result['count']}")
    print("-" * 60)
    for item in result.get("expired", []):
        print(f"  {item.get('id')} | {item.get('file', '')}")
        print(f"        原因: {item.get('reason', '')}")
        print(f"        过期于: {item.get('expires', '')}")
    if not result.get("expired"):
        print("  *(无)*")
    print()


if __name__ == "__main__":
    main()
