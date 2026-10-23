from __future__ import annotations

import ast
import os
import re
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

import quality_core as _core  # noqa: E402

from impact_core import _detect_lang, _read_file, _rel

# ============================================================
# 多语言调用者扫描
# ============================================================

def _find_all_callers(all_files: list[str], project_root: str,
                      func_name: str) -> list[dict]:
    """在全项目中查找某函数名的所有调用位置。"""
    results: list[dict] = []
    for fpath in all_files:
        lang = _detect_lang(fpath)
        content = _read_file(fpath)
        if not content:
            continue
        rel_path = _rel(fpath, project_root)

        if lang == "python":
            results.extend(_find_python_callers(content, fpath, rel_path, func_name))
        elif lang == "javascript":
            results.extend(_find_js_callers(content, rel_path, func_name))
        elif lang in ("java", "csharp"):
            results.extend(_find_java_csharp_callers(content, rel_path, func_name))
        elif lang == "go":
            results.extend(_find_go_callers(content, rel_path, func_name))
        elif lang == "rust":
            results.extend(_find_rust_callers(content, rel_path, func_name))

    return results


def _find_python_callers(content: str, fpath: str, rel_path: str,
                         func_name: str) -> list[dict]:
    """Python AST: 遍历所有 Call 节点找匹配的函数调用。"""
    results = []
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return results

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            callee = None
            if isinstance(node.func, ast.Name):
                callee = node.func.id
            elif isinstance(node.func, ast.Attribute):
                callee = node.func.attr

            if callee == func_name:
                line = node.lineno
                # 提取代码片段
                snippet = content.splitlines()[line - 1].strip() if line <= len(content.splitlines()) else ""

                # 判断是否为测试文件
                is_test = ("/test" in rel_path or "/tests/" in rel_path or
                           "test_" in os.path.basename(rel_path))

                results.append({
                    "file": rel_path,
                    "line": line,
                    "type": "test" if is_test else "direct_call",
                    "snippet": snippet[:120],
                    "action_needed": "",
                })
    return results


def _find_js_callers(content: str, rel_path: str, func_name: str) -> list[dict]:
    """JS/TS: 正则匹配函数调用。"""
    results = []
    stripped = _core.strip_comments_and_strings(content, ".js")

    # 直接调用 func_name(...)
    for m in re.finditer(rf'\b{re.escape(func_name)}\s*\(', stripped):
        pos = m.start()
        line_num = stripped[:pos].count("\n") + 1
        snippet = content.splitlines()[line_num - 1].strip() if line_num <= len(content.splitlines()) else ""
        is_test = ".test." in rel_path or ".spec." in rel_path or "/test" in rel_path
        results.append({
            "file": rel_path, "line": line_num,
            "type": "test" if is_test else "direct_call",
            "snippet": snippet[:120], "action_needed": "",
        })
    return results


def _find_java_csharp_callers(content: str, rel_path: str, func_name: str) -> list[dict]:
    results = []
    stripped = _core.strip_comments_and_strings(content, ".java")
    for m in re.finditer(rf'\b{re.escape(func_name)}\s*\(', stripped):
        pos = m.start()
        line_num = stripped[:pos].count("\n") + 1
        snippet = content.splitlines()[line_num - 1].strip() if line_num <= len(content.splitlines()) else ""
        results.append({
            "file": rel_path, "line": line_num, "type": "direct_call",
            "snippet": snippet[:120], "action_needed": "",
        })
    return results


def _find_go_callers(content: str, rel_path: str, func_name: str) -> list[dict]:
    results = []
    stripped = _core.strip_comments_and_strings(content, ".go")
    for m in re.finditer(rf'\b{re.escape(func_name)}\s*\(', stripped):
        pos = m.start()
        line_num = stripped[:pos].count("\n") + 1
        snippet = content.splitlines()[line_num - 1].strip() if line_num <= len(content.splitlines()) else ""
        results.append({
            "file": rel_path, "line": line_num, "type": "direct_call",
            "snippet": snippet[:120], "action_needed": "",
        })
    return results


def _find_rust_callers(content: str, rel_path: str, func_name: str) -> list[dict]:
    results = []
    stripped = _core.strip_comments_and_strings(content, ".rs")
    for m in re.finditer(rf'\b{re.escape(func_name)}\s*\(', stripped):
        pos = m.start()
        line_num = stripped[:pos].count("\n") + 1
        snippet = content.splitlines()[line_num - 1].strip() if line_num <= len(content.splitlines()) else ""
        results.append({
            "file": rel_path, "line": line_num, "type": "direct_call",
            "snippet": snippet[:120], "action_needed": "",
        })
    return results


# ============================================================
# 文件引用扫描
# ============================================================

def _find_file_references(all_files: list[str], project_root: str,
                          target_file: str) -> list[dict]:
    """查找所有 import/require 目标文件的位置。"""
    results = []
    target_rel = _rel(target_file, project_root).lower()
    target_no_ext = os.path.splitext(target_rel)[0]
    # 构建可能的引用模式
    patterns_to_match = [target_rel, target_no_ext,
                         target_rel.replace("/", "."),
                         target_no_ext.replace("/", ".")]

    for fpath in all_files:
        if fpath == target_file:
            continue
        lang = _detect_lang(fpath)
        content = _read_file(fpath)
        if not content:
            continue
        rel_fpath = _rel(fpath, project_root)

        found_lines = _find_import_refs(content, lang, patterns_to_match)
        for line_num, snippet, imp_type in found_lines:
            results.append({
                "file": rel_fpath, "line": line_num,
                "type": imp_type, "snippet": snippet[:120],
                "action_needed": f"需要更新 import 路径"
                if "move" in target_rel.lower() else f"依赖文件 {os.path.basename(target_file)} 可能被移动/删除",
            })

    return results


def _find_import_refs(content: str, lang: str, patterns: list[str]) -> list[tuple[int, str, str]]:
    """在源码中查找 import 引用模式。"""
    results = []
    lines = content.splitlines()

    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("//"):
            continue

        line_lower = stripped.lower()
        for pat in patterns:
            pat_lower = pat.lower().replace("\\", "/")
            pat_dot = pat_lower.replace("/", ".")
            if pat_lower in line_lower or pat_dot in line_lower:
                if any(kw in stripped for kw in ("import", "require", "include", "use", "using")):
                    results.append((i, stripped, "import_ref"))
                    break

    return results


# ============================================================
# 全局变量扫描
# ============================================================

def _find_global_var_refs(all_files: list[str], project_root: str,
                          var_name: str) -> list[dict]:
    """查找所有读取/写入全局变量的位置。"""
    results = []

    for fpath in all_files:
        lang = _detect_lang(fpath)
        content = _read_file(fpath)
        if not content:
            continue
        rel_path = _rel(fpath, project_root)
        lines = content.splitlines()

        if lang == "python":
            results.extend(_find_python_var_refs(content, lines, rel_path, var_name))
        elif lang == "javascript":
            results.extend(_find_js_var_refs(lines, rel_path, var_name))
        else:
            results.extend(_find_generic_var_refs(lines, rel_path, var_name))

    return results


def _find_python_var_refs(content: str, lines: list[str], rel_path: str,
                          var_name: str) -> list[dict]:
    results = []
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return results

    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == var_name:
            line = node.lineno
            snippet = lines[line - 1].strip() if line <= len(lines) else ""
            # 判断读/写
            is_write = False
            for parent in ast.walk(tree):
                for child in ast.iter_child_nodes(parent):
                    if child == node:
                        if isinstance(parent, ast.Assign):
                            is_write = any(t == node for t in parent.targets
                                           if isinstance(t, ast.Name))
                        break

            results.append({
                "file": rel_path, "line": line,
                "type": "variable_write" if is_write else "variable_read",
                "snippet": snippet[:120],
                "action_needed": "需要更新为新的全局配置方式" if is_write else "读取方式可能需要调整",
            })
    return results


def _find_js_var_refs(lines: list[str], rel_path: str, var_name: str) -> list[dict]:
    results = []
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if re.search(rf'\b{re.escape(var_name)}\b', stripped):
            is_write = re.search(rf'{re.escape(var_name)}\s*=', stripped) is not None
            results.append({
                "file": rel_path, "line": i,
                "type": "variable_write" if is_write else "variable_read",
                "snippet": stripped[:120],
                "action_needed": "需要更新为新的全局配置方式" if is_write else "",
            })
    return results


def _find_generic_var_refs(lines: list[str], rel_path: str, var_name: str) -> list[dict]:
    results = []
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if re.search(rf'\b{re.escape(var_name)}\b', stripped):
            is_write = re.search(rf'{re.escape(var_name)}\s*=', stripped) is not None
            results.append({
                "file": rel_path, "line": i,
                "type": "variable_write" if is_write else "variable_read",
                "snippet": stripped[:120],
                "action_needed": "",
            })
    return results
