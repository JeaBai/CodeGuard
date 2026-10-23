"""标签核心 API — list / apply / remove / get_constraints / validate。"""
from __future__ import annotations

from datetime import datetime

from tag_store import (
    _VALID_MODULE_TAGS,
    _load_tag_defs,
    _load_blueprint,
    _save_blueprint,
    _find_module,
    _log,
)

# ============================================================
# 公共 API：list_tags()
# ============================================================

def list_tags() -> dict:
    """列出所有可用标签及说明。

    Returns:
        {
            "module_tags": {tag_name: {description, allows, forbids, ...}},
            "param_tags": {tag_name: {description, scope, ...}},
            "action_verbs": {verb: description},
        }
    """
    defs = _load_tag_defs()
    _meta = defs.get("_meta", {})
    return {
        "_meta": _meta,
        "module_tags": {
            tag: {
                "description": info.get("description", ""),
                "allows": info.get("allows", []),
                "forbids": info.get("forbids", []),
                "severity_hint": info.get("severity_hint", "info"),
                "conflicts_with": info.get("conflicts_with", []),
            }
            for tag, info in defs.get("module_tags", {}).items()
        },
        "param_tags": defs.get("param_tags", {}),
        "action_verbs": defs.get("action_verbs", {}),
    }


# ============================================================
# 公共 API：apply_tag() / remove_tag()
# ============================================================

def apply_tag(blueprint_path: str, module_name: str, tag: str) -> dict:
    """给模块打标签。

    Returns:
        {"status": "applied" | "already_exists" | "error", "message": str, "module": str, "tags": [str]}
    """
    if tag not in _VALID_MODULE_TAGS:
        return {"status": "error", "message": f"无效标签 '{tag}'，有效值: {sorted(_VALID_MODULE_TAGS)}"}

    blueprint = _load_blueprint(blueprint_path)
    module = _find_module(blueprint, module_name)
    if module is None:
        return {"status": "error", "message": f"模块 '{module_name}' 不存在于蓝图中"}

    tags = module.get("tags", [])
    if tag in tags:
        return {"status": "already_exists", "message": f"标签 '{tag}' 已存在", "module": module_name, "tags": tags}

    # 冲突检查
    defs = _load_tag_defs()
    tag_conflicts = defs.get("module_tags", {}).get(tag, {}).get("conflicts_with", [])
    for existing_tag in tags:
        if existing_tag in tag_conflicts:
            return {
                "status": "error",
                "message": f"标签冲突: '{tag}' 与已存在的 '{existing_tag}' 冲突",
                "module": module_name,
                "tags": tags,
            }

    tags.append(tag)
    module["tags"] = tags

    # 记录用户手动修改
    overrides = blueprint.setdefault("user_overrides", {})
    modified_modules = overrides.setdefault("tags_modified_modules", [])
    if module_name not in modified_modules:
        modified_modules.append(module_name)
    overrides["last_manual_edit"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")

    _save_blueprint(blueprint, blueprint_path)
    return {"status": "applied", "message": f"已为 '{module_name}' 添加标签 '{tag}'", "module": module_name, "tags": tags}


def remove_tag(blueprint_path: str, module_name: str, tag: str) -> dict:
    """移除模块标签。

    Returns:
        {"status": "removed" | "not_found" | "error", "message": str, "module": str, "tags": [str]}
    """
    if tag not in _VALID_MODULE_TAGS:
        return {"status": "error", "message": f"无效标签 '{tag}'，有效值: {sorted(_VALID_MODULE_TAGS)}"}

    blueprint = _load_blueprint(blueprint_path)
    module = _find_module(blueprint, module_name)
    if module is None:
        return {"status": "error", "message": f"模块 '{module_name}' 不存在于蓝图中"}

    tags = module.get("tags", [])
    if tag not in tags:
        return {"status": "not_found", "message": f"标签 '{tag}' 不存在", "module": module_name, "tags": tags}

    tags.remove(tag)
    module["tags"] = tags

    # 更新 user_overrides
    overrides = blueprint.setdefault("user_overrides", {})
    overrides["last_manual_edit"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")

    _save_blueprint(blueprint, blueprint_path)
    return {"status": "removed", "message": f"已从 '{module_name}' 移除标签 '{tag}'", "module": module_name, "tags": tags}


# ============================================================
# 公共 API：get_constraints()
# ============================================================

def get_constraints(blueprint_path: str, module_name: str) -> dict:
    """获取某模块当前所有标签的合并约束。

    Returns:
        {
            "module": str,
            "tags": [str],
            "merged_constraints": {
                "allows": [str],
                "forbids": [str],
                "ai_constraint_text": [str],
                "severity": str,
                "conflict_matrix": {tag: [conflicting_tags]},
            }
        }
    """
    blueprint = _load_blueprint(blueprint_path)
    module = _find_module(blueprint, module_name)
    if module is None:
        return {"module": module_name, "error": f"模块 '{module_name}' 不存在"}

    tags = module.get("tags", [])
    defs = _load_tag_defs()
    all_module_tags = defs.get("module_tags", {})

    allows = []
    forbids = []
    ai_texts = []
    conflict_matrix = {}
    max_severity = "info"

    severity_rank = {"block": 3, "warn": 2, "info": 1}

    for tag in tags:
        tag_def = all_module_tags.get(tag, {})
        if not tag_def:
            continue
        allows.extend(tag_def.get("allows", []))
        forbids.extend(tag_def.get("forbids", []))
        ai_texts.append(f"[{tag}] {tag_def.get('ai_constraint', '')}")
        conflict_matrix[tag] = tag_def.get("conflicts_with", [])

        sev = tag_def.get("severity_hint", "info")
        if severity_rank.get(sev, 0) > severity_rank.get(max_severity, 0):
            max_severity = sev

    return {
        "module": module_name,
        "tags": tags,
        "merged_constraints": {
            "allows": sorted(set(allows)),
            "forbids": sorted(set(forbids)),
            "ai_constraint_text": ai_texts,
            "severity": max_severity,
            "conflict_matrix": conflict_matrix,
        },
    }


# ============================================================
# 公共 API：validate_tags()
# ============================================================

def validate_tags(blueprint_path: str) -> dict:
    """检查蓝图所有模块的标签冲突。

    Returns:
        {
            "status": "valid" | "conflicts_found",
            "conflicts": [{"module": str, "tag": str, "conflicts_with": str}],
            "expired_legacy": [str],
            "warnings": [str],
        }
    """
    blueprint = _load_blueprint(blueprint_path)
    defs = _load_tag_defs()
    all_module_tags = defs.get("module_tags", {})
    modules = blueprint.get("modules", [])

    conflicts = []
    expired_legacy = []
    warnings = []

    for module in modules:
        module_name = module.get("name", "unknown")
        tags = module.get("tags", [])

        # 检查标签白名单
        for tag in tags:
            if tag not in _VALID_MODULE_TAGS:
                warnings.append(f"模块 '{module_name}': 无效标签 '{tag}'（已自动跳过）")

        valid_tags = [t for t in tags if t in _VALID_MODULE_TAGS]

        # 检查标签间冲突
        for i, tag1 in enumerate(valid_tags):
            tag_def = all_module_tags.get(tag1, {})
            conflicting = tag_def.get("conflicts_with", [])
            for tag2 in valid_tags[i + 1:]:
                if tag2 in conflicting:
                    conflicts.append({
                        "module": module_name,
                        "tag": tag1,
                        "conflicts_with": tag2,
                    })

        # 检查 legacy 过期
        if "legacy" in valid_tags:
            params = module.get("params", {})
            expires = params.get("expires", {}).get("reason", "")
            if expires:
                try:
                    expire_date = datetime.strptime(expires[:10], "%Y-%m-%d")
                    if expire_date < datetime.now():
                        expired_legacy.append(
                            f"模块 '{module_name}': legacy 标签已于 {expires[:10]} 过期"
                        )
                except ValueError:
                    pass
            else:
                warnings.append(
                    f"模块 '{module_name}': legacy 标签缺少 expires 字段（建议格式: YYYY-MM-DD）"
                )

    return {
        "status": "valid" if not conflicts else "conflicts_found",
        "conflicts": conflicts,
        "expired_legacy": expired_legacy,
        "warnings": warnings,
        "total_modules": len(modules),
    }
