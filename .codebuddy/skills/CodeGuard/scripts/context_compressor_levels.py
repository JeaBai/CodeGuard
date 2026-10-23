"""L1/L2 生成 — 模块组 contract.md 与单模块 detail.md。"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from context_selector import (  # noqa: E402
    _collect_files,
    _analyze_python_functions,
    _analyze_generic_functions,
)
from context_compressor_core import _read_blueprint, _rel  # noqa: E402

# ============================================================
# L1: 模块组级 contract.md
# ============================================================

def generate_l1(project_path: str, module_name: str, blueprint_path: str) -> str:
    """为指定模块组生成 L1 contract.md (≤200行)。

    Returns:
        Markdown 格式的 L1 文档。
    """
    project_path = os.path.abspath(project_path)
    bp = _read_blueprint(blueprint_path)
    modules = bp.get("modules", [])
    deps = bp.get("dependency_graph", {})

    # 查找模块信息
    mod_info = None
    for m in modules:
        if m.get("name") == module_name:
            mod_info = m
            break
    if mod_info is None:
        return f"# 模块组: {module_name}\n\n*(不在蓝图中)*\n"

    # 上下游依赖
    forward_deps = deps.get(module_name, [])
    reverse_deps = [m.get("name", "") for m in modules
                    if module_name in deps.get(m.get("name", ""), [])]

    tags = mod_info.get("tags", [])
    api_list = mod_info.get("public_api", [])
    constraints = bp.get("constraints", {})

    lines = [
        f"# 模块组: {module_name}", "",
        "## 职责",
        mod_info.get("responsibility", "TODO: 待补充"), "",
        "## 公共 API", "",
        "| 函数 | 参数 | 返回值 |",
        "|------|------|--------|",
    ]

    for api in api_list[:30]:
        lines.append(
            f"| {api.get('name', '')} | {api.get('params', '')} | "
            f"{api.get('return_type', '')} |"
        )
    if len(api_list) > 30:
        lines.append(f"| ... | (+{len(api_list) - 30} 个) | |")

    lines.extend([
        "", "## 依赖关系", "",
        f"- **依赖**: {', '.join(forward_deps) if forward_deps else '(无)'}",
        f"- **被依赖**: {', '.join(reverse_deps) if reverse_deps else '(无)'}", "",
    ])

    if tags:
        tag_meanings = {
            "frozen": "禁止结构性修改",
            "no_split": "禁止拆分文件",
            "allow_split": "允许拆分",
            "leaf_only": "禁止新增外部依赖",
            "shared_util": "公共复用单元",
            "global_config": "全局配置项保留",
            "test_only": "仅测试用",
            "legacy": "遗留代码暂不修改",
            "core": "核心模块修改需测试",
        }
        lines.extend(["## 标签约束", ""])
        for tag in tags:
            meaning = tag_meanings.get(tag, "")
            lines.append(f"- **{tag}**: {meaning}")
        lines.append("")

    lines.extend([
        "## 全局约束（本模块适用）", "",
        f"- 最大复杂度: {constraints.get('max_complexity', 'N/A')}",
        f"- 最大函数行数: {constraints.get('max_function_lines', 'N/A')}",
        f"- 最大嵌套深度: {mod_info.get('allowed_nesting', 'N/A')}",
        f"- 最大文件数: {constraints.get('max_files_per_module', 'N/A')}",
        f"- 禁止重复函数: {constraints.get('forbid_duplicate_functions', 'N/A')}",
        f"- 必须提取共享: {constraints.get('require_shared_util_extraction', 'N/A')}",
        "", "## 已知问题", "",
    ])

    # 从质量角度列出问题
    nesting = mod_info.get("max_nesting", 0)
    allowed = mod_info.get("allowed_nesting", 0)
    if nesting > 6:
        lines.append(f"- **嵌套深度超标**: {nesting} (允许 {allowed})")
    if mod_info.get("file_count", 0) > constraints.get("max_files_per_module", 99):
        lines.append(f"- **文件数超标**: {mod_info['file_count']} (允许 {constraints['max_files_per_module']})")

    params = mod_info.get("params", {})
    global_params = {k: v for k, v in params.items()
                     if isinstance(v, dict) and v.get("scope") == "global"}
    if global_params:
        lines.append(f"- **全局变量**: {', '.join(global_params.keys())}")

    if not lines[-5:][0].startswith("- "):
        lines.append("- *(暂无已知问题)*")

    lines.extend(["", "---", f"*L1 上下文 — 操作 {module_name} 时加载*", ""])
    return "\n".join(lines)


# ============================================================
# L2: 单模块级 detail.md
# ============================================================

def generate_l2(project_path: str, module_name: str, blueprint_path: str) -> str:
    """为指定模块生成 L2 detail.md (≤100行/模块)。

    Returns:
        Markdown 格式的 L2 文档。
    """
    project_path = os.path.abspath(project_path)
    bp = _read_blueprint(blueprint_path)

    # 查找模块
    mod_info = None
    for m in bp.get("modules", []):
        if m.get("name") == module_name:
            mod_info = m
            break
    if mod_info is None:
        return f"# 模块详情: {module_name}\n\n*(不在蓝图中)*\n"

    # 收集实际文件
    mod_path = os.path.join(project_path, mod_info.get("path", ""))
    all_files = _collect_files(project_path) if os.path.isdir(mod_path) else []
    module_files = [f for f in all_files
                    if _rel(f, project_path).startswith(mod_info.get("path", "") + "/")]

    # 限制分析文件数
    module_files = module_files[:20]

    lines = [
        f"# 模块详情: {module_name}", "",
        f"- **路径**: {mod_info.get('path', '')}",
        f"- **文件数**: {mod_info.get('file_count', 0)}",
        f"- **总行数**: {mod_info.get('total_lines', 0)}",
        f"- **嵌套深度**: {mod_info.get('max_nesting', 0)}/{mod_info.get('allowed_nesting', 0)}", "",
    ]

    tags = mod_info.get("tags", [])
    if tags:
        lines.append(f"**标签**: {', '.join(tags)}")
        lines.append("")

    # 依赖
    deps = bp.get("dependency_graph", {}).get(module_name, [])
    if deps:
        lines.append(f"**依赖**: {', '.join(deps)}")
        lines.append("")

    lines.extend(["---", "", "## 函数清单", ""])

    # 分析每个文件
    total_funcs = 0
    for fpath in module_files:
        rel_path = _rel(fpath, project_path)
        ext = os.path.splitext(fpath)[1].lower()
        funcs = (_analyze_python_functions(open(fpath, "r", encoding="utf-8", errors="ignore").read())
                 if ext == ".py" else _analyze_generic_functions(fpath))

        if funcs and total_funcs < 40:
            lines.append(f"### {os.path.basename(rel_path)}")
            for func in funcs[:8]:
                total_funcs += 1
                complexity_str = f"CC={func['complexity']}" if func['complexity'] else ""
                nesting_str = f"nest={func['nesting']}" if func['nesting'] else ""
                metrics = ", ".join(filter(None, [complexity_str, nesting_str]))
                metrics_str = f" ({metrics})" if metrics else ""
                lines.append(
                    f"- **{func['name']}**({func['params']}) "
                    f"— {func['lines']}行{metrics_str}"
                )
                if func.get("calls"):
                    lines.append(f"  调用: {', '.join(func['calls'][:4])}")
                if func.get("called_by"):
                    lines.append(f"  被调用: {', '.join(func['called_by'])}")

    if not module_files:
        lines.append("*(无源文件)*")

    # 参数流
    lines.extend(["", "---", "", "## 参数流", ""])
    params = mod_info.get("params", {})
    if params:
        lines.append("| 参数 | scope | 说明 |")
        lines.append("|------|-------|------|")
        for pname, pinfo in list(params.items())[:20]:
            scope = pinfo.get("scope", "unknown") if isinstance(pinfo, dict) else "unknown"
            reason = pinfo.get("reason", "") if isinstance(pinfo, dict) else str(pinfo)
            lines.append(f"| {pname} | {scope} | {reason[:50]} |")
    else:
        lines.extend([
            "| 参数 | scope | 说明 |",
            "|------|-------|------|",
            "| — | — | (暂无参数记录) |",
        ])

    # 已知问题
    lines.extend(["", "---", "", "## 已知问题", ""])
    issues = []
    nesting = mod_info.get("max_nesting", 0)
    if nesting > 6:
        issues.append(f"嵌套深度 {nesting} 超标")
    if mod_info.get("file_count", 0) > (bp.get("constraints", {}).get("max_files_per_module", 99)):
        issues.append(f"文件数 {mod_info['file_count']} 超标")
    lines.append("\n".join(f"- {i}" for i in issues) if issues else "*(暂无已知问题)*")

    lines.extend(["", "---", f"*L2 上下文 — 修改 {module_name} 时加载*", ""])
    return "\n".join(lines)
