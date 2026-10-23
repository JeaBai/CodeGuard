"""ADR 上下文与时间线 — active_context / supersede / rollback / timeline。"""
from __future__ import annotations

import json
from datetime import datetime

from adr_store import (
    _STATUS_ICONS,
    _get_decision_dir,
    _list_adr_files,
    _load_adr,
    _save_adr,
    _format_date,
    _log,
)
from adr_crud import get_adr

# ============================================================
# 公共 API：get_active_context()
# ============================================================

def get_active_context(project_root: str | None = None) -> str:
    """获取所有已实施且未被替代的 ADR 摘要 — AI 会话恢复核心函数。

    每次 AI 会话开始时调用此函数恢复上下文。
    """
    dec_dir = _get_decision_dir(project_root)
    files = _list_adr_files(dec_dir)

    # 收集被替代的 ID
    superseded_ids: set[str] = set()
    all_adrs: list[dict] = []
    for fpath in files:
        adr = _load_adr(fpath)
        if adr is None:
            continue
        all_adrs.append(adr)
        if adr.get("superseded_by"):
            superseded_ids.add(adr.get("id", ""))

    # 过滤活跃 ADR
    active = [a for a in all_adrs
              if a.get("status") == "implemented"
              and a.get("id", "") not in superseded_ids]

    if not active:
        return "=== 活跃架构决策 (0 条) ===\n\n(暂无活跃的架构决策记录)"

    lines = [f"=== 活跃架构决策 ({len(active)} 条) ===", ""]

    for adr in active:
        aid = adr.get("id", "?")
        title = adr.get("title", "")
        decision = adr.get("decision", "")
        files_changed = adr.get("files_changed", [])
        tags = adr.get("tags_affected", {})
        date = _format_date(adr.get("date", ""))

        lines.append(f"[{aid}] {title}")
        d = decision[:100]
        lines.append(f"  决策: {d}{'...' if len(decision) > 100 else ''}")

        if files_changed:
            display = files_changed[:3]
            suffix = f" (+{len(files_changed) - 3})" if len(files_changed) > 3 else ""
            lines.append(f"  影响文件: {', '.join(display)}{suffix}")

        constraints: list[str] = []
        for module, tag_list in tags.get("added", {}).items():
            constraints.append(f"{module}={','.join(tag_list)}")
        for module, tag_list in tags.get("removed", {}).items():
            constraints.append(f"{module} -{','.join(tag_list)}")
        if constraints:
            lines.append(f"  约束: {', '.join(constraints)}")

        lines.append(f"  状态: implemented ({date})")
        lines.append("")

    return "\n".join(lines)


# ============================================================
# 公共 API：supersede_adr()
# ============================================================

def supersede_adr(old_id: str, new_id: str, reason: str = "",
                  project_root: str | None = None) -> dict:
    """标记旧 ADR 被新 ADR 替代。"""
    dec_dir = _get_decision_dir(project_root)
    old_file = new_file = None

    for fpath in _list_adr_files(dec_dir):
        if fpath.stem.startswith(old_id):
            old_file = fpath
        if fpath.stem.startswith(new_id):
            new_file = fpath

    if old_file is None:
        return {"status": "not_found", "id": old_id}
    if new_file is None:
        return {"status": "not_found", "id": new_id}

    old_adr = _load_adr(old_file)
    if old_adr is None:
        return {"status": "error", "message": f"无法加载 {old_id}"}
    old_adr["status"] = "superseded"
    old_adr["superseded_by"] = new_id
    if reason:
        old_adr.setdefault("notes", "")
        old_adr["notes"] += f" [→ {new_id}: {reason}]"
    _save_adr(old_file, old_adr)

    new_adr = _load_adr(new_file)
    if new_adr:
        new_adr["supersedes"] = old_id
        _save_adr(new_file, new_adr)

    _log(f"ADR {old_id} → {new_id}: {reason}")
    return {"status": "superseded", "old_id": old_id, "new_id": new_id}


# ============================================================
# 公共 API：get_rollback_info()
# ============================================================

def get_rollback_info(adr_id: str, project_root: str | None = None) -> dict:
    """获取回滚信息。"""
    adr = get_adr(adr_id, project_root)
    if adr is None:
        return {"adr_id": adr_id, "error": "ADR 不存在"}

    return {
        "adr_id": adr_id,
        "title": adr.get("title", ""),
        "status": adr.get("status", "unknown"),
        "rollback_plan": adr.get("rollback_plan", "(无回滚计划)"),
        "files_changed": adr.get("files_changed", []),
        "tests_required": adr.get("tests_required", []),
        "metrics_before": adr.get("metrics_before", {}),
        "metrics_after": adr.get("metrics_after", {}),
    }


# ============================================================
# 公共 API：export_timeline()
# ============================================================

def export_timeline(project_root: str | None = None) -> str:
    """导出 ADR 时间线 Markdown 文档。"""
    dec_dir = _get_decision_dir(project_root)
    files = _list_adr_files(dec_dir)

    if not files:
        return "# ADR 时间线\n\n*(暂无架构决策记录)*\n"

    all_adrs: list[dict] = []
    for fpath in files:
        adr = _load_adr(fpath)
        if adr:
            all_adrs.append(adr)
    all_adrs.sort(key=lambda a: a.get("date", ""))

    # 按状态分组
    status_groups: dict[str, list[dict]] = {}
    for a in all_adrs:
        s = a.get("status", "unknown")
        status_groups.setdefault(s, []).append(a)

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        "# ADR 时间线", "",
        f"> 生成时间: {now_str}",
        f"> ADR 总数: {len(all_adrs)}", "",
        "## 统计摘要", "",
        "| 状态 | 数量 |",
        "|------|------|",
    ]
    order = ["proposed", "in_review", "implemented", "superseded", "rejected", "rolled_back"]
    for s in order:
        cnt = len(status_groups.get(s, []))
        if cnt > 0:
            icon = _STATUS_ICONS.get(s, "")
            lines.append(f"| {icon} {s} | {cnt} |")
    lines.append("")

    # 活跃 ADR 表格
    active = [a for a in all_adrs
              if a.get("status") == "implemented" and not a.get("superseded_by")]
    if active:
        lines.extend(["---", "", "## ✅ 活跃架构决策", ""])
        lines.append("| ID | 标题 | 日期 | 影响文件 |")
        lines.append("|-----|------|------|----------|")
        for a in active:
            aid = a.get("id", "")
            title = (a.get("title", "") or "")[:50]
            d = _format_date(a.get("date", ""))
            files = a.get("files_changed", [])[:2]
            fs = ", ".join(files) if files else "—"
            lines.append(f"| {aid} | {title} | {d} | {fs} |")
        lines.append("")

    # 完整时间线
    lines.extend(["---", "", "## 📅 完整时间线", ""])
    for adr in all_adrs:
        aid = adr.get("id", "?")
        title = adr.get("title", "")
        date = _format_date(adr.get("date", ""))
        status = adr.get("status", "proposed")
        icon = _STATUS_ICONS.get(status, "")

        lines.append(f"### {icon} [{aid}] {title} ({date})")
        lines.extend([
            "", f"- **背景**: {adr.get('context', '')}",
            f"- **决策**: {adr.get('decision', '')}", "",
        ])

        cons = adr.get("consequences", {})
        if cons.get("positive"):
            lines.append(f"- **积极影响**: {', '.join(cons['positive'])}")
        if cons.get("negative"):
            lines.append(f"- **消极影响**: {', '.join(cons['negative'])}")
        lines.append("")

        files = adr.get("files_changed", [])
        if files:
            lines.append(f"- **变更文件**: {', '.join(files)}")

        tags = adr.get("tags_affected", {})
        if tags.get("added"):
            lines.append(f"- **新增标签**: `{json.dumps(tags['added'], ensure_ascii=False)}`")
        if tags.get("removed"):
            lines.append(f"- **移除标签**: `{json.dumps(tags['removed'], ensure_ascii=False)}`")

        rb = adr.get("rollback_plan", "")
        if rb:
            lines.append(f"- **回滚方案**: {rb}")

        before = adr.get("metrics_before", {})
        after = adr.get("metrics_after", {})
        if before and after:
            diffs = [f"{k}: {before[k]} → {after.get(k, '?')}" for k in before]
            lines.append(f"- **指标变化**: {', '.join(diffs)}")

        vfy = adr.get("verified_by", [])
        if vfy:
            lines.append(f"- **验证方式**: {', '.join(vfy)}")

        sp = adr.get("supersedes")
        sby = adr.get("superseded_by")
        if sp:
            lines.append(f"- **替代**: {sp}")
        if sby:
            lines.append(f"- **被替代**: {sby}")

        lines.append("")

    lines.extend(["---", "*由 Governance Hub ADR Manager v1.0.0 自动生成*", ""])
    return "\n".join(lines)
