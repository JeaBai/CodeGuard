"""经验资产操作 — load_to_context / tag / expire / list_by_project / stats。"""
from __future__ import annotations

from datetime import datetime, timezone

from experience_store import (
    _EXPERIENCE_DIR,
    _load_asset,
    _load_index,
    _save_index,
    _save_asset,
)
from experience_api import search

def load_to_context(asset_id: str) -> dict[str, Any]:
    """将资产还原为 AI 可消费的结构化上下文 JSON。

    Args:
        asset_id: 资产 ID

    Returns:
        结构化上下文（含 asset_id/type/title/content/tags/version/source/project）
    """
    asset = _load_asset(asset_id)
    if not asset:
        return {"error": f"资产不存在: {asset_id}", "asset_id": asset_id}

    # 更新最后访问时间
    index = _load_index()
    if asset_id in index:
        index[asset_id]["last_accessed_at"] = datetime.now(timezone.utc).isoformat()
        _save_index(index)

    return {
        "asset_id": asset_id,
        "type": asset.get("asset_type", ""),
        "title": asset.get("title", ""),
        "content": asset.get("content", ""),
        "tags": asset.get("tags", []),
        "version": asset.get("version", "1.0.0"),
        "source": asset.get("source", ""),
        "project": asset.get("project_name", ""),
        "visibility": asset.get("visibility", "private"),
        "_loaded_at": datetime.now(timezone.utc).isoformat(),
        "_truncated": asset.get("_truncated", False),
    }


def tag(asset_id: str, version_tag: str) -> dict[str, Any]:
    """为资产打版本标签。

    Args:
        asset_id: 资产 ID
        version_tag: 版本标签（如 "v1.1.0"）

    Returns:
        {"asset_id": str, "version": str, "status": "tagged"}
    """
    asset = _load_asset(asset_id)
    if not asset:
        return {"error": f"资产不存在: {asset_id}"}

    old_version = asset.get("version", "1.0.0")
    now = datetime.now(timezone.utc).isoformat()
    asset["version"] = version_tag
    asset["updated_at"] = now
    asset["version_history"].append({
        "from": old_version,
        "to": version_tag,
        "at": now,
    })

    index = _load_index()
    if asset_id in index:
        index[asset_id]["version"] = version_tag
        _save_index(index)

    _save_asset(asset_id, asset)
    return {"asset_id": asset_id, "version": version_tag, "previous_version": old_version, "status": "tagged"}


def expire(asset_id: str) -> dict[str, Any]:
    """标记资产为过期。

    Args:
        asset_id: 资产 ID

    Returns:
        {"asset_id": str, "status": "expired"}
    """
    asset = _load_asset(asset_id)
    if not asset:
        return {"error": f"资产不存在: {asset_id}"}

    now = datetime.now(timezone.utc).isoformat()
    asset["status"] = "expired"
    asset["expires_at"] = now
    asset["updated_at"] = now

    index = _load_index()
    if asset_id in index:
        index[asset_id]["status"] = "expired"
        _save_index(index)

    _save_asset(asset_id, asset)
    return {"asset_id": asset_id, "status": "expired", "expired_at": now}


def list_by_project(project_name: str) -> list[dict[str, Any]]:
    """列出某个项目的全部资产。

    Args:
        project_name: 项目名称

    Returns:
        list[asset_metadata]
    """
    return search(project_filter=project_name)


def stats() -> dict[str, Any]:
    """获取经验资产库统计摘要。"""
    index = _load_index()
    total = len(index)
    by_type: dict[str, int] = {}
    by_visibility: dict[str, int] = {}
    by_status: dict[str, int] = {}
    by_project: dict[str, int] = {}

    for aid, meta in index.items():
        t = meta.get("type", "unknown")
        by_type[t] = by_type.get(t, 0) + 1
        v = meta.get("visibility", "private")
        by_visibility[v] = by_visibility.get(v, 0) + 1
        s = meta.get("status", "active")
        by_status[s] = by_status.get(s, 0) + 1
        p = meta.get("project", "unknown")
        by_project[p] = by_project.get(p, 0) + 1

    return {
        "total_assets": total,
        "by_type": by_type,
        "by_visibility": by_visibility,
        "by_status": by_status,
        "by_project": by_project,
        "storage_path": str(_EXPERIENCE_DIR),
    }


# ============================================================
# CLI 入口
# ============================================================
