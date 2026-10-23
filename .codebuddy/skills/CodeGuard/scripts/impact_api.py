from __future__ import annotations

import os

from impact_core import (
    _CHANGE_TYPES,
    _collect_files,
    _rel,
    _log,
    _save_report,
    _save_or_return,
    _infer_root,
    _load_blueprint,
)
from impact_callers import (
    _find_all_callers,
    _find_file_references,
    _find_global_var_refs,
)
from impact_deps import _analyze_module_deps

# ============================================================
# 公共 API：analyze_change()
# ============================================================

def analyze_change(file_path: str, function_name: str, change_type: str,
                   project_root: str | None = None) -> dict:
    """分析函数签名变更影响。

    Args:
        file_path: 源文件路径。
        function_name: 函数名。
        change_type: add_param | remove_param | change_return | rename | delete。
        project_root: 项目根目录。

    Returns:
        {change, change_type, impacted_files, impacted_count, breaking, recommendation, alternatives}
    """
    if change_type not in _CHANGE_TYPES:
        return {"error": f"无效变更类型 '{change_type}'，有效值: {sorted(_CHANGE_TYPES)}"}

    file_path = os.path.abspath(file_path)
    if project_root is None:
        project_root = os.path.dirname(file_path)
        for _ in range(5):
            if os.path.isdir(os.path.join(project_root, ".codebuddy")):
                break
            parent = os.path.dirname(project_root)
            if parent == project_root:
                break
            project_root = parent

    rel_file = _rel(file_path, project_root)
    all_files = _collect_files(project_root)
    _log(f"扫描 {len(all_files)} 个文件查找 '{function_name}' 调用者...")

    # 查找所有调用者
    callers = _find_all_callers(all_files, project_root, function_name)

    # 排除自引用（同文件内的调用）
    callers = [c for c in callers if c["file"] != rel_file]

    # 根据变更类型生成建议
    change_desc = f"{rel_file}:{function_name}() {_change_label(change_type)}"
    breaking = change_type in ("remove_param", "delete", "rename", "change_return")
    count = len(callers)

    _fill_action_needed(callers, change_type, function_name)

    recommendation, alternatives = _get_recommendations(
        change_type, function_name, callers, rel_file)

    # 保存报告
    report = _save_report(project_root, {
        "change": change_desc,
        "change_type": change_type,
        "impacted_files": callers,
        "impacted_count": count,
        "breaking": breaking,
        "recommendation": recommendation,
        "alternatives": alternatives,
    }, f"func_change_{function_name}_{change_type}")

    return {"report_file": report, **report} if isinstance(report, dict) else report


def _change_label(ct: str) -> str:
    return {
        "add_param": "新增参数",
        "remove_param": "移除参数",
        "change_return": "修改返回值",
        "rename": "重命名",
        "delete": "删除函数",
    }.get(ct, ct)


def _fill_action_needed(callers: list[dict], change_type: str, func_name: str) -> None:
    for c in callers:
        if change_type == "add_param":
            c["action_needed"] = f"调用处需添加新参数"
        elif change_type == "remove_param":
            c["action_needed"] = f"调用处需移除被删除的参数"
        elif change_type == "change_return":
            c["action_needed"] = f"调用处需适配新的返回值类型"
        elif change_type == "rename":
            c["action_needed"] = f"将 {func_name}() 重命名为新名称"
        elif change_type == "delete":
            c["action_needed"] = f"函数 {func_name}() 将被删除，此处调用需替换"


def _get_recommendations(change_type: str, func_name: str,
                         callers: list[dict], rel_file: str) -> tuple[str, list[str]]:
    count = len(callers)
    test_callers = sum(1 for c in callers if c["type"] == "test")
    non_test = count - test_callers

    if change_type == "delete" and count > 0:
        return ("reject_direct_change", [
            f"影响 {count} 处调用（含 {test_callers} 处测试），建议先标记 deprecated 并给出替代方案",
            "添加 DeprecationWarning 和迁移文档后再删除",
        ])
    elif change_type == "remove_param" and non_test > 5:
        return ("reject_direct_change", [
            f"影响 {non_test} 处非测试调用，建议新增 {func_name}_v2() 或设置默认参数值",
        ])
    elif count == 0:
        return ("approve", [
            "无调用者，变更安全",
        ])
    elif count < 5:
        return ("approve_with_update", [
            f"影响 {count} 处调用，可通过批量替换完成",
            "建议: 使用 IDE 的 rename refactoring 或在所有调用处同步修改",
        ])
    elif change_type == "add_param":
        return ("conditional_approve", [
            f"新增参数影响 {count} 处调用",
            f"给新参数设默认值: {func_name}(..., new_param=None) 保持向后兼容",
        ])
    else:
        return ("manual_review", [
            f"影响 {count} 处调用需人工评估",
            "建议: 先创建 snapshot 再执行变更，变更后对比指标",
        ])


# ============================================================
# 公共 API：analyze_file_move()
# ============================================================

def analyze_file_move(file_path: str, project_root: str | None = None) -> dict:
    """分析文件移动/删除的影响。"""
    file_path = os.path.abspath(file_path)
    if project_root is None:
        project_root = _infer_root(file_path)

    rel_file = _rel(file_path, project_root)
    all_files = _collect_files(project_root)
    _log(f"扫描 {len(all_files)} 个文件查找对 '{rel_file}' 的引用...")

    refs = _find_file_references(all_files, project_root, file_path)
    breaking = len(refs) > 0

    result = {
        "file": rel_file,
        "action": "file_move_or_delete",
        "impacted_files": refs,
        "impacted_count": len(refs),
        "breaking": breaking,
        "recommendation": "reject_direct_move" if breaking > 5
        else ("batch_update" if breaking > 0 else "safe_to_move"),
        "alternatives": [
            "使用 IDE 的 Move Refactoring 自动更新所有 import 路径",
            "先在原位置保留转发 stub，逐步迁移",
        ] if breaking else ["文件未被引用，可安全移动/删除"],
    }

    return _save_or_return(project_root, result, f"file_move_{os.path.basename(rel_file)}")


# ============================================================
# 公共 API：analyze_global_var()
# ============================================================

def analyze_global_var(var_name: str, project_root: str | None = None) -> dict:
    """分析全局变量变更影响。"""
    project_root = project_root or os.getcwd()
    project_root = os.path.abspath(project_root)
    all_files = _collect_files(project_root)
    _log(f"扫描 {len(all_files)} 个文件查找全局变量 '{var_name}' 引用...")

    refs = _find_global_var_refs(all_files, project_root, var_name)
    writes = [r for r in refs if r["type"] == "variable_write"]
    reads = [r for r in refs if r["type"] == "variable_read"]
    breaking = len(writes) > 0

    result = {
        "variable": var_name,
        "impacted_files": refs,
        "total_refs": len(refs),
        "writes": len(writes),
        "reads": len(reads),
        "breaking": breaking,
        "recommendation": "migrate_with_deprecation" if breaking else "safe_to_modify",
        "alternatives": ([
            f"保留 {var_name} 作为旧名称 + 别名指向新变量",
            "使用 property/setter/decorator 包装访问",
        ] if breaking else [
            "可直接修改，所有使用处为只读",
        ]),
    }

    return _save_or_return(project_root, result, f"global_var_{var_name}")


# ============================================================
# 公共 API：analyze_module_dep()  -  依赖变更影响
# ============================================================

def analyze_module_dep(module_name: str, change_type: str,
                       project_root: str | None = None) -> dict:
    """分析模块依赖变更影响（基于蓝图依赖图）。"""
    project_root = project_root or os.getcwd()
    project_root = os.path.abspath(project_root)
    bp = _load_blueprint(project_root)

    if bp is None:
        return {"error": "未找到 architecture_blueprint.json，无法分析模块依赖"}

    result = _analyze_module_deps(module_name, change_type, bp)
    return _save_or_return(project_root, result, f"module_dep_{module_name}_{change_type}")
