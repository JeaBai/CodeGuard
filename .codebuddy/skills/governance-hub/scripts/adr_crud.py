"""ADR 核心 CRUD — create / list / get / update。"""
from __future__ import annotations

from datetime import datetime, timezone

from adr_store import (
    _VALID_STATUSES,
    _VALID_STATUS_TRANSITIONS,
    _get_decision_dir,
    _next_id,
    _slugify,
    _load_adr,
    _save_adr,
    _list_adr_files,
    _parse_json_field,
    _log,
)

# ============================================================
# 公共 API：create_adr()
# ============================================================

def create_adr(  # noqa: PLR0913
    title: str,
    context: str,
    decision: str,
    consequences: dict | None = None,
    files_changed: list[str] | None = None,
    rollback_plan: str = "",
    tests_required: list[str] | None = None,
    tags_affected: dict | None = None,
    session_id: str = "",
    project_root: str | None = None,
) -> dict:
    """创建新的架构决策记录。"""
    dec_dir = _get_decision_dir(project_root)
    adr_id = _next_id(dec_dir)
    slug = _slugify(title)
    filepath = dec_dir / f"{adr_id}-{slug}.json"

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    adr = {
        "id": adr_id,
        "date": now,
        "title": title,
        "context": context,
        "decision": decision,
        "consequences": consequences or {"positive": [], "negative": []},
        "tags_affected": tags_affected or {"added": {}, "removed": {}},
        "files_changed": files_changed or [],
        "rollback_plan": rollback_plan,
        "tests_required": tests_required or [],
        "metrics_before": {},
        "metrics_after": {},
        "status": "proposed",
        "verified_by": [],
        "session_id": session_id,
        "supersedes": None,
        "superseded_by": None,
    }

    _save_adr(filepath, adr)
    _log(f"创建 ADR: {adr_id} — {title}")
    return {"status": "created", "id": adr_id, "file": str(filepath)}


# ============================================================
# 公共 API：list_adrs()
# ============================================================

def list_adrs(status_filter: str | None = None,
              project_root: str | None = None) -> dict:
    """列出所有 ADR，可按状态过滤。"""
    dec_dir = _get_decision_dir(project_root)
    files = _list_adr_files(dec_dir)

    result_list = []
    status_counts: dict[str, int] = {}

    for fpath in files:
        adr = _load_adr(fpath)
        if adr is None:
            continue
        s = adr.get("status", "unknown")
        status_counts[s] = status_counts.get(s, 0) + 1

        if status_filter and s != status_filter:
            continue
        result_list.append({
            "id": adr.get("id", ""),
            "title": adr.get("title", ""),
            "status": s,
            "date": adr.get("date", ""),
            "decision": (adr.get("decision", "") or "")[:80],
            "files_changed": adr.get("files_changed", []),
        })

    return {"adrs": result_list, "total": len(result_list), "status_counts": status_counts}


# ============================================================
# 公共 API：get_adr()
# ============================================================

def get_adr(adr_id: str, project_root: str | None = None) -> dict | None:
    """获取单条 ADR 完整内容。"""
    dec_dir = _get_decision_dir(project_root)
    for fpath in _list_adr_files(dec_dir):
        if fpath.stem.startswith(adr_id):
            adr = _load_adr(fpath)
            if adr:
                return adr
    return None


# ============================================================
# 公共 API：update_adr()
# ============================================================

def update_adr(adr_id: str, project_root: str | None = None, **fields) -> dict:
    """更新 ADR 字段（支持状态转换校验）。"""
    dec_dir = _get_decision_dir(project_root)
    for fpath in _list_adr_files(dec_dir):
        if not fpath.stem.startswith(adr_id):
            continue
        adr = _load_adr(fpath)
        if adr is None:
            continue

        # 状态转换校验
        if "status" in fields:
            new_status = fields["status"]
            if new_status not in _VALID_STATUSES:
                return {"status": "invalid_transition", "id": adr_id,
                        "message": f"无效状态 '{new_status}'"}
            old_status = adr.get("status", "proposed")
            allowed = _VALID_STATUS_TRANSITIONS.get(old_status, frozenset())
            if new_status != old_status and new_status not in allowed:
                return {"status": "invalid_transition", "id": adr_id,
                        "message": f"不允许 {old_status} → {new_status}"}

        # 更新字段（JSON 字符串字段自动解析）
        for key, value in fields.items():
            if key in ("metrics_after", "metrics_before", "consequences", "tags_affected"):
                if isinstance(value, str):
                    parsed = _parse_json_field(value, key)
                    if parsed is not None:
                        value = parsed
            if value is not None:
                adr[key] = value

        _save_adr(fpath, adr)
        _log(f"更新 ADR: {adr_id}")
        return {"status": "updated", "id": adr_id, "adr": adr}

    return {"status": "not_found", "id": adr_id}
