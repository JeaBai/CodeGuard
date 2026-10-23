"""依赖图构建与循环检测。"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

import quality_core as _core  # noqa: E402
from blueprint_extractor_core import _relpath, _get_quality_arch  # noqa: E402

# ============================================================
# 依赖分析
# ============================================================

def _build_module_files(modules, root):
    """构建 {module_name: set(normalized_path)} 映射。"""
    module_names = set(modules.keys())
    module_files = {m: set() for m in module_names}
    for mname, minfo in modules.items():
        for fpath in minfo["files"]:
            module_files[mname].add(_relpath(fpath, root).lower())
    return module_files


def _extract_module_imports(qa, content, file_lang, ext):
    """剥除 docstring/惰性导入后提取模块级 import 列表。"""
    content = _core.strip_comments_and_strings(content, ext)
    if ext == ".py":
        content = re.sub(
            r'^[ \t]+(?:from\s+\S+\s+import\s+\S+|import\s+\S+)',
            lambda m: ' ' * len(m.group()), content, flags=re.MULTILINE,
        )
    imports = []
    for pattern, lang in qa.MULTILANG_IMPORT_PATTERNS:
        if lang == file_lang:
            for match in pattern.finditer(content):
                imp = match.group(1) or (
                    match.group(2) if match.lastindex and match.lastindex >= 2 else None
                )
                if imp:
                    imports.append(imp)
            break
    return imports


def _map_import_to_module(imp, module_files, mname):
    """将 import 字符串映射到目标模块名，未命中返回 None。"""
    imp_lower = imp.lower().replace(".", "/")
    for target_mod, target_files in module_files.items():
        if target_mod == mname:
            continue
        target_lower = target_mod.lower()
        if (imp_lower == target_lower or
                target_lower in imp_lower.split("/") or
                any(imp_lower.endswith(os.path.splitext(f)[0]) for f in target_files)):
            return target_mod
    return None


def _build_dependency_graph(root: str, modules: dict[str, dict]) -> tuple[dict[str, list[str]], list[list[str]]]:
    """基于文件级 import 构建模块间依赖图。

    Returns:
        (dependency_graph: {module_name: [dep_module_names]}, cycles: [[module_names]])
    """
    qa = _get_quality_arch()
    module_names = set(modules.keys())
    module_files = _build_module_files(modules, root)

    module_deps: dict[str, set] = {m: set() for m in module_names}
    for mname, minfo in modules.items():
        for fpath in minfo["files"]:
            try:
                with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
            except (OSError, UnicodeDecodeError):
                continue

            file_lang = qa._detect_file_lang(fpath)
            ext = os.path.splitext(fpath)[1].lower()
            for imp in _extract_module_imports(qa, content, file_lang, ext):
                target = _map_import_to_module(imp, module_files, mname)
                if target:
                    module_deps[mname].add(target)

    dependency_graph = {m: sorted(deps) for m, deps in module_deps.items()}
    cycles = _detect_module_cycles(dependency_graph)
    return dependency_graph, cycles


def _dfs_cycles(graph, start, cycles, visited_all):
    """从 start 出发 DFS 查找环。"""
    def dfs(node, path, visiting):
        if node in visiting:
            cycle_start = path.index(node)
            cycles.append(path[cycle_start:])
            return
        if node in visited_all:
            return
        visiting.add(node)
        path.append(node)
        for neighbor in graph.get(node, []):
            if neighbor != node:
                dfs(neighbor, list(path), set(visiting))
        visiting.discard(node)
        visited_all.add(node)

    dfs(start, [], set())


def _dedupe_cycles(cycles):
    """去重并保留长度 ≥2 的环。"""
    unique = []
    seen = set()
    for cycle in cycles:
        key = tuple(sorted(cycle))
        if key not in seen and len(cycle) >= 2:
            seen.add(key)
            unique.append(cycle)
    return unique


def _detect_module_cycles(graph: dict[str, list[str]]) -> list[list[str]]:
    """在模块级依赖图中检测循环（DFS）。"""
    cycles: list[list[str]] = []
    visited_all = set()
    for start in sorted(graph.keys()):
        if start not in visited_all:
            _dfs_cycles(graph, start, cycles, visited_all)
    return _dedupe_cycles(cycles)
