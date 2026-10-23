#!/usr/bin/env python3
"""
经验资产库管理器 (Experience Library) — project-manager v2.3
=============================================================
对标 TencentDB Agent Memory 四种记忆资产统一登记机制：
  Chat Memory / Skill / Wiki / CodeGraph → 统一为 Experience Asset

核心操作：
  register(asset_type, title, content, tags, visibility, project_name) → asset_id
  search(keywords, visibility_filter, asset_type_filter) → list[asset]
  load_to_context(asset_id) → context_json (供 AI 消费的结构化上下文)
  tag(asset_id, version_tag) → 版本快照
  expire(asset_id) → 标记过期
  list_by_project(project_name) → 项目资产清单
  stats() → 统计摘要

可见性分级（对标 TencentDB 四级）：
  private   — 仅 Owner 可读
  team      — 团队成员可读
  restricted — 通过 ACL 精确授权
  agent     — 同团队 Agent 定向装配

存储位置：.codebuddy/experience/{asset_id}.json（运行时自动创建目录）

设计依据：
  - TencentDB Agent Memory feat/server_team: Memory Hub → Asset Bag → Loadout
  - 零外部依赖，纯 Python 标准库 + JSON 文件系统
  - 单文件 ≤ 10KB，≤ 100 条目时线性扫描足够

用法：
  python experience_library.py --action register --type skill --title "..." --content "..." --tags "..."
  python experience_library.py --action search --keywords "..."
  python experience_library.py --action stats
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ============================================================
# 常量
# ============================================================

def _resolve_experience_dir() -> Path:
    """解析经验资产目录。**必须落在技能目录之外。**

    为什么（2026-10-03 修正）：
      原路径 `<skill>/.codebuddy/experience/` 在**技能目录内** —— 升版本 / 重新部署 /
      覆盖安装会整体替换技能目录，导致**记忆静默丢失**。
      运行产物落在技能目录内是既有反模式（同类问题：inventory.json / plan.json）。

    取值顺序：
      1. 环境变量 `PM_EXPERIENCE_DIR`（显式覆盖，便于测试与自定义）
      2. 用户级 `~/.codebuddy/project-manager/experience/`（默认；跨项目复用得以保留）
      3. **兼容**：若旧位置已有数据且新位置尚不存在 → 继续沿用旧位置并告警，
         避免"升级后历史记忆凭空消失"

    > 注意：本目录只是**检索/注入的缓存层**，不是记忆的真相源 ——
    > 真相源是 TencentDB（跨团队记忆复用）。详见 `references/tool-contract-analysis.md` §三。
    """
    import os as _os
    env = _os.environ.get("PM_EXPERIENCE_DIR")
    if env:
        return Path(env).expanduser().resolve()
    new_dir = Path(_os.path.expanduser("~/.codebuddy/project-manager/experience"))
    legacy = Path(__file__).resolve().parent.parent / ".codebuddy" / "experience"
    try:
        if legacy.is_dir() and any(legacy.iterdir()) and not new_dir.exists():
            import sys as _sys
            print(f"[project-manager] ⚠️ 沿用旧经验库位置（技能目录内，升级有丢失风险）: {legacy}\n"
                  f"[project-manager]    建议迁移到 {new_dir}，或设置 PM_EXPERIENCE_DIR",
                  file=_sys.stderr, flush=True)
            return legacy
    except OSError:
        pass
    return new_dir


_EXPERIENCE_DIR = _resolve_experience_dir()
_INDEX_FILE = _EXPERIENCE_DIR / "index.json"
_SQLITE_DB = _EXPERIENCE_DIR / "assets.db"

_VALID_TYPES = frozenset({"chat_memory", "skill", "wiki", "code_graph", "decision", "lesson"})
_VALID_VISIBILITIES = frozenset({"private", "team", "restricted", "agent"})
_MAX_ASSET_SIZE_KB = 10

# v2.3: SQLite FTS5 连接缓存（惰性初始化）
_sqlite_conn: sqlite3.Connection | None = None


def _ensure_dir() -> None:
    """确保经验资产目录存在。"""
    _EXPERIENCE_DIR.mkdir(parents=True, exist_ok=True)


def _generate_id(title: str, content: str, project_name: str) -> str:
    """生成唯一资产 ID：基于标题+内容+项目的 SHA256 前 12 位。"""
    payload = f"{title}|{content[:200]}|{project_name}|{datetime.now(timezone.utc).isoformat()}"
    return hashlib.sha256(payload.encode()).hexdigest()[:12]


def _load_index() -> dict[str, Any]:
    """加载资产索引（{asset_id: metadata}）。"""
    _ensure_dir()
    if _INDEX_FILE.exists():
        try:
            return json.loads(_INDEX_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_index(index: dict) -> None:
    """保存资产索引。"""
    _ensure_dir()
    _INDEX_FILE.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_asset(asset_id: str) -> dict[str, Any] | None:
    """加载单条资产。"""
    path = _EXPERIENCE_DIR / f"{asset_id}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _save_asset(asset_id: str, data: dict) -> None:
    """保存单条资产。"""
    _ensure_dir()
    path = _EXPERIENCE_DIR / f"{asset_id}.json"
    payload = json.dumps(data, ensure_ascii=False, indent=2)
    if len(payload.encode("utf-8")) > _MAX_ASSET_SIZE_KB * 1024:
        # 截断 content 字段
        data["_truncated"] = True
        data["content"] = data.get("content", "")[:4000] + "\n...(已截断)"
        payload = json.dumps(data, ensure_ascii=False, indent=2)
    path.write_text(payload, encoding="utf-8")


# ============================================================
# v2.3: SQLite FTS5 全文检索后端
# ============================================================

def _ensure_sqlite() -> sqlite3.Connection:
    """惰性初始化 SQLite 数据库（含 FTS5 虚拟表）。"""
    global _sqlite_conn
    if _sqlite_conn is not None:
        return _sqlite_conn
    _ensure_dir()
    conn = sqlite3.connect(str(_SQLITE_DB))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS assets (
            asset_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            type TEXT NOT NULL,
            content TEXT NOT NULL,
            tags TEXT,
            visibility TEXT,
            project TEXT,
            status TEXT,
            version TEXT,
            created_at TEXT,
            fingerprint TEXT
        )
    """)
    conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS assets_fts USING fts5(
            title, content, tags,
            content='assets', content_rowid='rowid'
        )
    """)
    # 创建触发器保持 FTS 同步
    conn.executescript("""
        CREATE TRIGGER IF NOT EXISTS assets_ai AFTER INSERT ON assets BEGIN
            INSERT INTO assets_fts(rowid, title, content, tags) VALUES
                (new.rowid, new.title, new.content, new.tags);
        END;
        CREATE TRIGGER IF NOT EXISTS assets_ad AFTER DELETE ON assets BEGIN
            INSERT INTO assets_fts(assets_fts, rowid, title, content, tags) VALUES
                ('delete', old.rowid, old.title, old.content, old.tags);
        END;
        CREATE TRIGGER IF NOT EXISTS assets_au AFTER UPDATE ON assets BEGIN
            INSERT INTO assets_fts(assets_fts, rowid, title, content, tags) VALUES
                ('delete', old.rowid, old.title, old.content, old.tags);
            INSERT INTO assets_fts(rowid, title, content, tags) VALUES
                (new.rowid, new.title, new.content, new.tags);
        END;
    """)
    conn.commit()
    _sqlite_conn = conn
    return conn


def _sync_json_to_sqlite() -> int:
    """增量同步：将 JSON index 中未入库的资产写入 SQLite。返回新增数。"""
    conn = _ensure_sqlite()
    index = _load_index()
    existing = {row["asset_id"] for row in conn.execute("SELECT asset_id FROM assets").fetchall()}
    added = 0
    for aid, meta in index.items():
        if aid in existing:
            continue
        asset = _load_asset(aid)
        if not asset:
            continue
        conn.execute("""
            INSERT OR IGNORE INTO assets(asset_id, title, type, content, tags, visibility, project, status, version, created_at, fingerprint)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            aid,
            meta.get("title", ""),
            meta.get("type", ""),
            asset.get("content", ""),
            ", ".join(meta.get("tags", [])),
            meta.get("visibility", "private"),
            meta.get("project", ""),
            meta.get("status", "active"),
            meta.get("version", "1.0.0"),
            meta.get("created_at", ""),
            meta.get("fingerprint", ""),
        ))
        added += 1
    if added:
        conn.commit()
    return added


def _fts_search(keywords: str) -> list[str]:
    """使用 SQLite FTS5 MATCH 全文检索。返回匹配的 asset_id 列表。"""
    conn = _ensure_sqlite()
    _sync_json_to_sqlite()
    # 为 FTS5 构造 AND 查询
    fts_query = " AND ".join(f'"{kw}"' for kw in keywords.split() if kw)
    if not fts_query:
        return []
    try:
        rows = conn.execute(
            "SELECT asset_id FROM assets_fts WHERE assets_fts MATCH ? ORDER BY rank LIMIT 50",
            (fts_query,)
        ).fetchall()
        return [r["asset_id"] for r in rows]
    except sqlite3.OperationalError:
        # FTS5 查询语法错误时降级
        return []


# ============================================================
# v2.3: 内容指纹去重
# ============================================================

def _normalize_for_fingerprint(text: str) -> str:
    """归一化策略：去空白、去标点、小写化。"""
    text = text.lower()
    text = re.sub(r'\s+', ' ', text)
    text = re.sub(r'[^\w\s]', '', text)
    return text.strip()


def _compute_fingerprint(content: str) -> str:
    """SHA256 前 20 位 hex（80-bit 指纹）。"""
    normalized = _normalize_for_fingerprint(content)
    return hashlib.sha256(normalized.encode()).hexdigest()[:20]


def dedup_check(title: str, content: str) -> dict[str, Any]:
    """公共预检 API：检查内容指纹是否已存在。

    Returns:
        {"duplicate": bool, "existing_id": str | None}
    """
    fp = _compute_fingerprint(content)
    index = _load_index()
    for aid, meta in index.items():
        if meta.get("fingerprint") == fp:
            return {"duplicate": True, "existing_id": aid, "existing_title": meta.get("title", ""),
                    "fingerprint": fp}
    return {"duplicate": False, "existing_id": None, "fingerprint": fp}


# ============================================================
# v2.3: 导入导出
# ============================================================

def backup_to_json(output_path: str = "") -> dict[str, Any]:
    """导出全部资产到 JSON 文件。

    Returns:
        {"status": "backed_up", "path": str, "count": int}
    """
    index = _load_index()
    all_assets = []
    for aid in index:
        asset = _load_asset(aid)
        if asset:
            all_assets.append(asset)

    if not output_path:
        output_path = str(_EXPERIENCE_DIR / f"backup_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json")
    Path(output_path).write_text(json.dumps(all_assets, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"status": "backed_up", "path": output_path, "count": len(all_assets)}


def restore_from_json(input_path: str, skip_duplicates: bool = True) -> dict[str, Any]:
    """从 JSON 导入资产。

    Returns:
        {"status": "restored", "imported": int, "skipped": int, "duplicates": int}
    """
    try:
        data = json.loads(Path(input_path).read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, FileNotFoundError) as e:
        return {"error": f"导入失败: {e}"}

    if not isinstance(data, list):
        return {"error": "JSON 格式错误：期望资产数组"}

    imported = 0
    skipped = 0
    duplicates = 0
    index = _load_index()

    for item in data:
        aid = item.get("asset_id", "")
        if not aid:
            skipped += 1
            continue

        if aid in index and skip_duplicates:
            duplicates += 1
            continue

        # 去重检查
        content = item.get("content", "")
        fp = _compute_fingerprint(content)
        is_dup = False
        for existing_id, meta in index.items():
            if existing_id != aid and meta.get("fingerprint") == fp:
                duplicates += 1
                is_dup = True
                break
        if is_dup:
            continue

        _save_asset(aid, item)
        index[aid] = {
            "title": item.get("title", ""),
            "type": item.get("asset_type", item.get("type", "")),
            "tags": item.get("tags", []),
            "visibility": item.get("visibility", "private"),
            "project": item.get("project_name", item.get("project", "")),
            "status": item.get("status", "active"),
            "version": item.get("version", "1.0.0"),
            "created_at": item.get("created_at", ""),
            "fingerprint": fp,
        }
        imported += 1

    _save_index(index)
    return {"status": "restored", "imported": imported, "skipped": skipped, "duplicates": duplicates}
