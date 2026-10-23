"""经验资产核心 API — register / search。"""
from __future__ import annotations

from datetime import datetime, timezone

from experience_store import (
    _VALID_TYPES,
    _VALID_VISIBILITIES,
    _compute_fingerprint,
    dedup_check,
    _generate_id,
    _load_index,
    _save_index,
    _save_asset,
    _load_asset,
    _fts_search,
)

# ============================================================
# 公共 API
# ============================================================

def register(
    asset_type: str,
    title: str,
    content: str,
    tags: str = "",
    visibility: str = "private",
    project_name: str = "",
    owner: str = "",
    source: str = "",
) -> dict[str, Any]:
    """登记一条经验到资产库。

    Args:
        asset_type: 资产类型 (chat_memory/skill/wiki/code_graph/decision/lesson)
        title: 资产标题
        content: 资产内容 (Markdown/JSON)
        tags: 逗号分隔标签
        visibility: 可见性 (private/team/restricted/agent)
        project_name: 来源项目
        owner: 所有者标识
        source: 来源描述（如 "governance-hub ADR #12"）

    Returns:
        {"asset_id": str, "status": "registered"}
    """
    if asset_type not in _VALID_TYPES:
        return {"error": f"无效资产类型 '{asset_type}'，有效值: {', '.join(sorted(_VALID_TYPES))}"}
    if visibility not in _VALID_VISIBILITIES:
        return {"error": f"无效可见性 '{visibility}'，有效值: {', '.join(sorted(_VALID_VISIBILITIES))}"}

    # v2.3: 内容指纹去重
    fp = _compute_fingerprint(content)
    dup = dedup_check(title, content)
    if dup["duplicate"]:
        return {
            "asset_id": dup["existing_id"],
            "status": "duplicate",
            "message": f"内容重复，已存在资产 '{dup.get('existing_title', '?')}' (ID: {dup['existing_id']})",
            "fingerprint": fp,
        }

    asset_id = _generate_id(title, content, project_name)
    tag_list = [t.strip() for t in tags.split(",") if t.strip()]

    now = datetime.now(timezone.utc).isoformat()
    data = {
        "asset_id": asset_id,
        "asset_type": asset_type,
        "title": title,
        "content": content,
        "tags": tag_list,
        "visibility": visibility,
        "project_name": project_name,
        "owner": owner,
        "source": source,
        "status": "active",
        "version": "1.0.0",
        "created_at": now,
        "updated_at": now,
        "expires_at": None,
        "version_history": [],
    }

    index = _load_index()
    # v2.3: 将指纹写入索引
    index[asset_id] = {
        "title": title,
        "type": asset_type,
        "tags": tag_list,
        "visibility": visibility,
        "project": project_name,
        "status": "active",
        "version": "1.0.0",
        "created_at": now,
        "fingerprint": fp,
    }
    _save_index(index)
    _save_asset(asset_id, data)

    return {
        "asset_id": asset_id,
        "status": "registered",
        "message": f"经验资产 '{title}' 已登记（ID: {asset_id}, 类型: {asset_type}, 可见性: {visibility}）",
    }


def search(
    keywords: str = "",
    visibility_filter: str = "",
    asset_type_filter: str = "",
    tag_filter: str = "",
    project_filter: str = "",
    status_filter: str = "active",
    use_fts: bool = False,  # v2.3: SQLite FTS5 全文检索
) -> list[dict[str, Any]]:
    """按条件搜索经验资产。

    Args:
        keywords: 空格分隔关键词（在标题和标签中搜索）
        visibility_filter: 可见性过滤（空=不过滤）
        asset_type_filter: 类型过滤（空=不过滤）
        tag_filter: 标签过滤
        project_filter: 项目过滤
        status_filter: 状态过滤（默认 active）
        use_fts: 使用 SQLite FTS5 全文检索（默认 False 保持向后兼容）

    Returns:
        list[asset_metadata]
    """
    # v2.3: FTS5 快速路径
    if use_fts and keywords:
        matched_ids = _fts_search(keywords)
        index = _load_index()
        results = []
        for aid in matched_ids:
            if aid not in index:
                continue
            meta = index[aid]
            if visibility_filter and meta.get("visibility") != visibility_filter:
                continue
            if asset_type_filter and meta.get("type") != asset_type_filter:
                continue
            if project_filter and meta.get("project") != project_filter:
                continue
            if status_filter and meta.get("status") != status_filter:
                continue
            asset = _load_asset(aid)
            results.append(asset if asset else {**meta, "asset_id": aid, "_load_failed": True})
        return results

    # 原有路径：JSON index 线性扫描
    index = _load_index()
    keywords_lower = keywords.lower()
    kw_list = keywords_lower.split() if keywords_lower else []

    results = []
    for aid, meta in index.items():
        # 状态过滤
        if status_filter and meta.get("status") != status_filter:
            continue

        # 可见性过滤
        if visibility_filter and meta.get("visibility") != visibility_filter:
            continue

        # 类型过滤
        if asset_type_filter and meta.get("type") != asset_type_filter:
            continue

        # 项目过滤
        if project_filter and meta.get("project") != project_filter:
            continue

        # 标签过滤
        if tag_filter:
            asset_tags = meta.get("tags", [])
            if tag_filter not in asset_tags:
                continue

        # 关键词搜索
        if kw_list:
            search_text = f"{meta.get('title', '')} {' '.join(meta.get('tags', []))}".lower()
            if not all(kw in search_text for kw in kw_list):
                continue

        # 加载完整资产内容
        asset = _load_asset(aid)
        results.append(asset if asset else {**meta, "asset_id": aid, "_load_failed": True})

    return results
