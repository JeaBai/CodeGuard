"""风险门禁内部集成 — 影响估算 / 保护检查 / 锁检查 / 标签检查。"""
from __future__ import annotations

import json
import os
import sys

from risk_gate_store import _SCRIPT_DIR

# ============================================================
# 内部集成函数
# ============================================================

def _estimate_impact(file_path: str, function_name: str,
                     blueprint_path: str, project_root: str) -> int:
    """通过 impact_analyzer 估算影响件数。"""
    if not function_name or not os.path.isfile(file_path):
        return 0

    # 尝试导入 impact_analyzer（同目录）
    cg_scripts = [
        os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(project_root))),
                     "CodeGuard", "scripts"),
    ]
    # 实际的 CodeGuard 路径
    cg_path = os.path.join(os.path.dirname(_SCRIPT_DIR), "..", "..", "CodeGuard", "scripts")
    cg_path = os.path.normpath(cg_path)
    if cg_path not in sys.path:
        sys.path.insert(0, cg_path)

    try:
        import impact_analyzer
        result = impact_analyzer.analyze_change(file_path, function_name, "delete", project_root)
        return result.get("impacted_count", 0)
    except Exception:
        # 降级：简单正则扫描
        return _estimate_impact_fallback(file_path, function_name, project_root)


def _estimate_impact_fallback(file_path: str, func_name: str,
                              project_root: str) -> int:
    """正则降级：扫描全项目调用处。"""
    import re
    count = 0
    skip_dirs = {".git", "node_modules", "__pycache__",
                 "venv", ".venv", ".codebuddy", ".idea"}
    for dirpath, dirnames, filenames in os.walk(project_root):
        dirnames[:] = [d for d in dirnames if d not in skip_dirs and not d.startswith(".")]
        for fname in filenames:
            if not fname.endswith((".py", ".js", ".ts", ".java", ".go", ".cs", ".rs")):
                continue
            if os.path.join(dirpath, fname) == file_path:
                continue
            try:
                with open(os.path.join(dirpath, fname), "r", encoding="utf-8",
                          errors="ignore") as f:
                    content = f.read()
                if re.search(rf'\b{re.escape(func_name)}\s*\(', content):
                    count += 1
            except OSError:
                pass
    return count


def _check_protection(file_path: str, project_root: str) -> str:
    """检查文件是否被 intent_protection 保护。"""
    protection_file = os.path.join(
        os.path.dirname(_SCRIPT_DIR), "scripts", "intent_protection.json"
    )
    if not os.path.isfile(protection_file):
        return ""

    try:
        data = json.loads(open(protection_file, "r", encoding="utf-8").read())
        for item in data.get("protected_items", []):
            if item.get("status") != "active":
                continue
            prot_file = item.get("file", "")
            if file_path.endswith(prot_file) or prot_file.endswith(file_path):
                return f"{item.get('id', '?')}: {item.get('reason', '')}"
    except (json.JSONDecodeError, OSError):
        pass
    return ""


def _check_lock(file_path: str, project_root: str) -> dict:
    """检查文件锁（refactor_queue）。"""
    lock_file = os.path.join(project_root, ".codebuddy", "file_locks.json")
    if not os.path.isfile(lock_file):
        return {}
    try:
        locks = json.loads(open(lock_file, "r", encoding="utf-8").read())
        rel = file_path.replace("\\", "/")
        for lock_path, info in locks.items():
            if lock_path in rel or rel in lock_path:
                return {"locked": True, "locked_by": info.get("locked_by", ""),
                        "locked_at": info.get("locked_at", "")}
    except (json.JSONDecodeError, OSError):
        pass
    return {}


def _check_tag_forbidden(action: str, file_path: str,
                         blueprint_path: str, project_root: str) -> dict:
    """检查模块标签是否禁止该操作。"""
    if not os.path.isfile(blueprint_path):
        return {}

    # 动作 → 标签 forbids 映射
    forbidden_map: dict[str, list[str]] = {
        "split_module": ["frozen", "no_split"],
        "split_function": ["frozen", "no_split"],
        "change_public_api": ["frozen", "shared_util"],
        "delete_file": ["frozen", "shared_util", "core"],
        "add_dependency": ["leaf_only", "frozen"],
        "move_file": ["frozen", "no_split"],
        "merge_modules": ["frozen", "no_split"],
        "cross_module_dependency_change": ["leaf_only", "frozen"],
        "delete_function": ["shared_util", "core"],
        "rename_function": ["shared_util"],
        "global_var_change": ["global_config"],
    }

    forbids = forbidden_map.get(action, [])
    if not forbids:
        return {}

    try:
        bp = json.loads(open(blueprint_path, "r", encoding="utf-8").read())
        for m in bp.get("modules", []):
            mpath = m.get("path", "")
            if mpath and (mpath in file_path or file_path.startswith(mpath)):
                tags = m.get("tags", [])
                conflicting = [t for t in forbids if t in tags]
                if conflicting:
                    return {"forbidden": True,
                            "reason": f"模块 {m.get('name', '')} 的标签 {conflicting} 禁止 {action}"}
    except (json.JSONDecodeError, OSError):
        pass
    return {}


def _describe_action(action: str, file_path: str, func: str) -> str:
    fname = os.path.basename(file_path)
    base = {
        "split_function": f"在 {fname} 中拆分函数",
        "extract_duplicate_code": f"从 {fname} 提取重复代码",
        "reduce_nesting": f"减少 {fname} 中的嵌套深度",
        "refactor_error_handling": f"重构 {fname} 的错误处理",
        "split_module": f"拆分模块 {fname}",
        "change_public_api": f"修改 {fname} 的公共 API",
        "delete_file": f"删除文件 {fname}",
        "add_dependency": f"给 {fname} 新增依赖",
        "extract_shared_util": f"从 {fname} 提取共享函数",
        "optimize_complexity": f"优化 {fname} 的圈复杂度",
        "rename_function": f"重命名 {func or fname} 函数",
        "reorder_parameters": f"调整 {func or fname} 参数顺序",
    }
    return base.get(action, f"执行 {action} 操作于 {fname}")
