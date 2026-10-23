"""参数流/嵌套层级提取 + 跨文件重复函数检测。"""
from __future__ import annotations

import ast
import os
import re
from collections import defaultdict
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

import quality_core as _core  # noqa: E402
from blueprint_extractor_core import _relpath  # noqa: E402
from blueprint_extractor_api import _format_python_params  # noqa: E402

# ============================================================
# 参数流 / 嵌套层级提取
# ============================================================

def _extract_params_and_nesting(module_files: list[str]) -> tuple[dict, int, int]:
    """提取模块的参数清单和最大嵌套深度。

    Returns:
        (params_dict, max_nesting_per_module, max_allowed_nesting)
    """
    params_dict: dict[str, dict] = {}
    overall_max_nesting = 0

    for fpath in module_files:
        ext = os.path.splitext(fpath)[1].lower()

        try:
            with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except (OSError, UnicodeDecodeError):
            continue

        # 嵌套深度
        file_nesting = 0
        if ext == ".py":
            try:
                tree = ast.parse(content)
                file_nesting = _core.get_nesting_depth(tree)
            except SyntaxError:
                pass
        elif ext in (".js", ".java", ".cs", ".cpp", ".c", ".h"):
            from quality_checks import _compute_nesting_regex
            file_nesting = _compute_nesting_regex(content, ext)
        overall_max_nesting = max(overall_max_nesting, file_nesting)

        # 全局变量/模块级赋值识别
        if ext == ".py":
            _extract_python_globals(content, params_dict)
        elif ext in (".js", ".ts", ".mjs"):
            _extract_js_globals(content, params_dict)

    return params_dict, overall_max_nesting, overall_max_nesting


def _extract_python_globals(content: str, params_dict: dict) -> None:
    """提取 Python 模块级变量赋值（非函数/类范围内）。"""
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and not target.id.startswith("_"):
                    if target.id not in params_dict:
                        params_dict[target.id] = {
                            "scope": "global",
                            "reason": "请确认是否为配置项",
                        }


def _extract_js_globals(content: str, params_dict: dict) -> None:
    """提取 JS/TS 模块级变量声明。"""
    stripped = _core.strip_comments_and_strings(content, ".js")
    # const/let/var 声明在顶层
    var_decl = re.compile(
        r'^(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=',
        re.MULTILINE
    )
    for m in var_decl.finditer(stripped):
        name = m.group(1)
        if not name.startswith("_") and name not in params_dict:
            params_dict[name] = {
                "scope": "global",
                "reason": "请确认是否为配置项",
            }


# ============================================================
# 重复函数检测
# ============================================================

def _collect_file_functions(modules):
    """收集所有文件中的函数。返回 {filepath: [(func_name, norm_body, signature)]}。"""
    file_functions = {}
    for mname, minfo in modules.items():
        for fpath in minfo["files"]:
            ext = os.path.splitext(fpath)[1].lower()
            try:
                with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
            except (OSError, UnicodeDecodeError):
                continue
            funcs = _extract_function_bodies(content, ext)
            if funcs:
                file_functions[fpath] = funcs
    return file_functions


def _build_func_index(file_functions):
    """构建 {normalized_body: {filepath: [func_names]}} 索引。"""
    func_to_files = defaultdict(lambda: defaultdict(list))
    for fpath, funcs in file_functions.items():
        for fname, norm_body, signature in funcs:
            if len(norm_body) < 30:
                continue  # 太短不视为重复
            func_to_files[norm_body][fpath].append(fname)
            func_to_files[f"sig:{signature}"][fpath].append(fname)
    return func_to_files


def _find_consumers(files_list, modules):
    """从文件列表推断消费者模块名。"""
    consumers = []
    seen_modules = set()
    for fpath in files_list:
        for mname, minfo in modules.items():
            if fpath in minfo["files"] and mname not in seen_modules:
                consumers.append(mname)
                seen_modules.add(mname)
    return sorted(consumers)


def _find_signature(file_map, func_name):
    """从 file_map 查找函数签名，兜底返回 func_name。"""
    for _fpath, names in file_map.items():
        if names:
            return f"{names[0]}(...)"
    return func_name


def _build_shared_entry(file_map, modules, seen_sigs):
    """生成单个 shared 条目，重复或无效返回 None。"""
    files_list = list(file_map.keys())
    location_rel = _relpath(files_list[0], "")
    func_name = file_map[files_list[0]][0]
    if func_name in seen_sigs:
        return None
    seen_sigs.add(func_name)

    consumers = _find_consumers(files_list, modules)
    signature = _find_signature(file_map, func_name)
    return {
        "name": func_name,
        "location": location_rel,
        "consumers": consumers,
        "signature": signature,
    }


def _detect_duplicates(modules: dict[str, dict]) -> list[dict]:
    """跨文件重复函数检测，生成 shared_utils 列表。

    基于 quality_dup.py 逻辑但对函数粒度进行归一化比较。

    Returns:
        [{"name": str, "location": str, "consumers": [str], "signature": str}]
    """
    file_functions = _collect_file_functions(modules)
    func_to_files = _build_func_index(file_functions)

    shared = []
    seen_sigs = set()
    for body_key, file_map in func_to_files.items():
        if body_key.startswith("sig:"):
            continue
        if len(file_map) < 2:
            continue
        entry = _build_shared_entry(file_map, modules, seen_sigs)
        if entry is not None:
            shared.append(entry)

    return shared[:50]  # 防止过多输出


def _extract_py_function_bodies(content, results):
    """Python: AST 提取函数体。"""
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        try:
            body = ast.unparse(node.body[:6]) if hasattr(ast, "unparse") else " ".join(
                str(n) for n in node.body[:3]
            )
        except Exception:
            body = ""
        sig = f"{node.name}({_format_python_params(node.args)})"
        results.append((node.name, _normalize_body(body), sig))


_FUNC_PATTERNS = {
    ".js": r'(?:function\s+(\w+)\s*\([^)]*\)\s*\{(.*?)\n\})',
    ".ts": r'(?:function\s+(\w+)\s*\([^)]*\)\s*\{(.*?)\n\})',
    ".go": r'func\s+(?:\(\w+\s+\*?\w+\)\s+)?(\w+)\s*\([^)]*\)\s*\{(.*?)\n\}',
    ".rs": r'fn\s+(\w+)\s*\([^)]*\)\s*\{(.*?)\n\}',
}


def _extract_regex_function_bodies(stripped, ext, results):
    """非 Python：正则提取函数体。"""
    pattern = _FUNC_PATTERNS.get(ext)
    if not pattern:
        return
    for m in re.finditer(pattern, stripped, re.DOTALL):
        name = m.group(1)
        body = m.group(2) if m.lastindex and m.lastindex >= 2 else ""
        if len(body) > 20:
            results.append((name, _normalize_body(body), f"{name}(...)"))


def _extract_function_bodies(content: str, ext: str) -> list[tuple[str, str, str]]:
    """从文件内容提取函数名 + 归一化体 + 签名。

    Returns:
        [(func_name, normalized_body, signature)]
    """
    results: list[tuple[str, str, str]] = []
    stripped = _core.strip_comments_and_strings(content, ext)
    if ext == ".py":
        _extract_py_function_bodies(content, results)
    else:
        _extract_regex_function_bodies(stripped, ext, results)
    return results


def _normalize_body(body: str) -> str:
    """归一化函数体（去空格、去注释）。"""
    body = re.sub(r'\s+', '', body)
    body = re.sub(r'["\'`][^"\'`]*["\'`]', '""', body)
    return body[:200]
