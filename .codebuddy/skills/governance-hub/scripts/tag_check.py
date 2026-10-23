"""标签违规检查 — check_violation。"""
from __future__ import annotations

from tag_store import (
    _VALID_ACTIONS,
    _load_blueprint,
    _find_module,
    _load_tag_defs,
)

# ============================================================
# 公共 API：check_violation()
# ============================================================

def check_violation(blueprint_path: str, module_name: str, action: str) -> dict:
    """检查某操作是否被模块标签允许。

    Args:
        blueprint_path: 蓝图文件路径。
        module_name: 模块名称。
        action: 操作动词，可选值见 _VALID_ACTIONS。

    Returns:
        {"allowed": bool, "reason": str, "blocked_by_tag": str | None}
    """
    if action not in _VALID_ACTIONS:
        return {
            "allowed": False,
            "reason": f"未知操作 '{action}'，有效值: {sorted(_VALID_ACTIONS)}",
            "blocked_by_tag": None,
        }

    blueprint = _load_blueprint(blueprint_path)
    module = _find_module(blueprint, module_name)
    if module is None:
        return {
            "allowed": False,
            "reason": f"模块 '{module_name}' 不存在于蓝图中",
            "blocked_by_tag": None,
        }

    tags = module.get("tags", [])
    if not tags:
        return {"allowed": True, "reason": "无标签限制", "blocked_by_tag": None}

    defs = _load_tag_defs()
    all_module_tags = defs.get("module_tags", {})

    # 操作 → 标签 forbids 关键词映射
    ACTION_FORBID_KEYWORDS = {
        "split_file": ["文件拆分", "创建新文件", "拆分"],
        "merge_files": ["文件合并", "合并"],
        "change_api": ["公共 API 变更", "改变参数签名", "破坏性 API 变更"],
        "add_dependency": ["新增依赖", "新增 import", "新增模块间依赖", "引入第三方库"],
        "copy_function": ["复制", "复制到其他文件"],
        "new_global_var": ["新增模块级全局变量"],
        "rename_export": ["重命名", "删除"],
        "move_code": ["移动文件", "移动函数", "移动代码"],
        "add_file": ["创建新文件"],
        "delete_file": ["删除"],
    }

    # 额外检查（正向约束）
    ACTION_ALLOW_KEYWORDS = {
        "split_file": ["文件拆分", "创建新文件"],
        "merge_files": ["文件合并"],
        "change_api": ["公共 API 变更"],
        "add_dependency": ["新增依赖", "新增 import"],
        "copy_function": ["复制"],
    }

    # 遍历所有标签，检查是否有 forbids 匹配
    for tag in tags:
        tag_def = all_module_tags.get(tag, {})
        forbids = tag_def.get("forbids", [])
        forbid_keywords = ACTION_FORBID_KEYWORDS.get(action, [])

        for forbid in forbids:
            for kw in forbid_keywords:
                if kw in forbid:
                    return {
                        "allowed": False,
                        "reason": f"模块 '{module_name}' 有 '{tag}' 标签: {forbid}",
                        "blocked_by_tag": tag,
                    }

    # 额外检查：shared_util 的 copy_function 是明确禁止的
    if action == "copy_function" and "shared_util" in tags:
        return {
            "allowed": False,
            "reason": "模块有 'shared_util' 标签，禁止复制函数。应从 shared_utils import 调用。",
            "blocked_by_tag": "shared_util",
        }

    # 检查核心模块操作是否需要额外审核
    if "core" in tags and action in ("change_api", "delete_file", "move_code"):
        return {
            "allowed": True,
            "reason": f"操作允许，但模块 '{module_name}' 有 'core' 标签。需要回归测试 + code review。",
            "blocked_by_tag": None,
        }

    return {"allowed": True, "reason": "操作未被任何标签禁止", "blocked_by_tag": None}
