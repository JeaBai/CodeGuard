"""约束文档导出 — export_constraint_doc。"""
from __future__ import annotations

from datetime import datetime

from tag_store import _VALID_ACTIONS, _load_blueprint, _load_tag_defs
from tag_check import check_violation

# ============================================================
# 公共 API：export_constraint_doc()
# ============================================================

def export_constraint_doc(blueprint_path: str) -> str:
    """导出人话版本的约束说明文档（Markdown 格式）。

    Returns:
        完整的 Markdown 文档字符串。
    """
    blueprint = _load_blueprint(blueprint_path)
    defs = _load_tag_defs()
    all_module_tags = defs.get("module_tags", {})
    modules = blueprint.get("modules", [])
    project_name = blueprint.get("project_name", "Unknown")

    lines = []
    lines.append(f"# {project_name} — 架构约束说明文档")
    lines.append("")
    lines.append(f"> 自动生成于: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"> 蓝图版本: {blueprint.get('version', 'N/A')}")
    lines.append(f"> 模块总数: {len(modules)}")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 全局约束")
    lines.append("")
    constraints = blueprint.get("constraints", {})
    if constraints:
        lines.append("| 约束项 | 值 |")
        lines.append("|--------|-----|")
        for key, value in constraints.items():
            lines.append(f"| {key} | {value} |")
    else:
        lines.append("*(无全局约束)*")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 模块约束清单")
    lines.append("")

    for module in modules:
        module_name = module.get("name", "unknown")
        module_path = module.get("path", "")
        tags = module.get("tags", [])

        lines.append(f"### {module_name}")
        lines.append(f"- **路径**: `{module_path}`")
        lines.append(f"- **文件数**: {module.get('file_count', 0)}")
        lines.append(f"- **总行数**: {module.get('total_lines', 0)}")
        lines.append(f"- **嵌套深度**: {module.get('max_nesting', 0)}/{module.get('allowed_nesting', 0)}")
        lines.append("")

        if tags:
            lines.append(f"**标签**: {', '.join(tags)}")
            lines.append("")
            for tag in tags:
                tag_def = all_module_tags.get(tag)
                if tag_def:
                    desc = tag_def.get("ai_constraint", tag_def.get("description", ""))
                    lines.append(f"- **`{tag}`**: {desc}")
                    allows = tag_def.get("allows", [])
                    if allows:
                        lines.append(f"  - 允许: {', '.join(allows)}")
                    forbids = tag_def.get("forbids", [])
                    if forbids:
                        lines.append(f"  - 禁止: {', '.join(forbids)}")
                    if tag == "legacy":
                        params = module.get("params", {})
                        expires = params.get("expires", {}).get("reason", "")
                        if expires:
                            lines.append(f"  - **过期日期**: {expires}")
            lines.append("")
        else:
            lines.append("*(无标签限制)*")
            lines.append("")

        # 依赖信息
        deps = module.get("depends_on", [])
        if deps:
            lines.append(f"**依赖模块**: {', '.join(deps)}")
            lines.append("")

        # 反向依赖
        dep_graph = blueprint.get("dependency_graph", {})
        reverse = [m["name"] for m in modules if module_name in dep_graph.get(m["name"], [])]
        if reverse:
            lines.append(f"**被依赖**: {', '.join(reverse)}")
            lines.append("")

        lines.append("---")
        lines.append("")

    # 操作风险矩阵
    lines.append("## 操作风险矩阵")
    lines.append("")
    lines.append("以下矩阵展示了各操作在各模块标签下的允许状态：")
    lines.append("")
    actions = sorted(_VALID_ACTIONS)
    lines.append("| 模块 | " + " | ".join(actions) + " |")
    lines.append("|------|" + "|".join(["------"] * len(actions)) + "|")

    for module in modules:
        module_name = module.get("name", "")
        row = [module_name]
        for action in actions:
            result = check_violation(blueprint_path, module_name, action)
            icon = "✅" if result["allowed"] else "❌"
            row.append(icon)
        lines.append("| " + " | ".join(row) + " |")

    return "\n".join(lines) + "\n"
