#!/usr/bin/env python3
"""
CodeGuard Context Selector (v1.0.0)
====================================
L0-L3 上下文选择逻辑 — 从 context_compressor.py 拆分而来。

本模块承载“按任务选择必要上下文”的全部决策逻辑：
  - _collect_files / _group_by_module: 文件与模块的收集/分组（模块选择）
  - _analyze_python_functions / _analyze_generic_functions: 多语言函数分析，
    为 L2 选择提供函数级数据（公共 API 过滤、调用关系、复杂度等）
  - get_context_for_task: 根据任务描述智能选择需要加载的 L0-L3 上下文
    （关键词匹配 → 模块选择 → 依赖图扩展 → 上下文截断/预估）
  - refresh: 增量刷新某文件所属模块的 L2 文档
  - _print_context_result: CLI 友好打印上下文选择结果

依赖方向（避免循环导入）：
  - 模块级别仅依赖标准库 + quality_core；
  - 对 context_compressor 的依赖（generate_l0 / generate_l2 / _read_blueprint /
    _rel / _log 等核心压缩与共享工具）通过函数内惰性导入获取。
  - 因此 context_compressor 可在模块级别安全地 `from context_selector import ...`。
"""

from __future__ import annotations

import ast
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

# ============================================================
# 内部导入
# ============================================================

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

import quality_core as _core  # noqa: E402

# ============================================================
# 常量（文件扫描 — 与 _collect_files 配套）
# ============================================================

SKIP_DIRS = frozenset({
    ".git", "__pycache__", "node_modules", "venv", ".venv",
    "dist", "build", "target", ".codebuddy", ".idea", ".vscode",
    ".cursor", "vendor", ".terraform",
})

SOURCE_EXTS = frozenset({
    ".py", ".js", ".ts", ".tsx", ".mjs", ".java", ".go", ".cs", ".rs",
    ".cpp", ".c", ".h",
})

# ============================================================
# 工具函数
# ============================================================

def _collect_files(root: str) -> list[str]:
    """收集项目源码文件。"""
    files = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        rel_dir = os.path.relpath(dirpath, root)
        if any(p.startswith(".") for p in rel_dir.split(os.sep) if p):
            continue
        for fname in filenames:
            if os.path.splitext(fname)[1].lower() in SOURCE_EXTS:
                files.append(os.path.join(dirpath, fname))
    return files


def _group_by_module(files: list[str], root: str) -> dict[str, list[str]]:
    """按一级子目录分组文件。"""
    from context_compressor import _rel  # 惰性导入以避免循环依赖
    groups: dict[str, list[str]] = defaultdict(list)
    for f in files:
        rel = _rel(f, root)
        parts = rel.split("/")
        if len(parts) == 1:
            groups["__root__"].append(f)
        else:
            groups[parts[0]].append(f)
    return dict(groups)


# ============================================================
# Python AST 分析（复用 quality_core）
# ============================================================

def _analyze_python_functions(content: str) -> list[dict]:
    """Python AST: 提取函数名+参数+行数+嵌套+复杂度+全局状态读取。"""
    results: list[dict] = []
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return results

    # 预扫描全局变量引用
    global_refs = _find_global_refs(tree)

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        name = node.name
        if name.startswith("_"):
            continue

        lines = node.end_lineno - node.lineno + 1 if node.end_lineno else 0
        try:
            nesting = _core.get_nesting_depth(node)
        except Exception:
            nesting = 0
        try:
            complexity = _core.compute_cyclomatic_complexity(node)
        except Exception:
            complexity = 0

        params = _format_python_params(node.args)
        calls = _find_calls(node)
        called_by = global_refs.get(name, [])

        results.append({
            "name": name,
            "params": params,
            "lines": lines,
            "nesting": nesting,
            "complexity": complexity,
            "calls": sorted(set(calls))[:6],
            "called_by": sorted(set(called_by))[:3],
            "lineno": node.lineno,
        })

    return results


def _format_python_params(args: ast.arguments) -> str:
    parts = [a.arg for a in args.args]
    if args.vararg:
        parts.append(f"*{args.vararg.arg}")
    for kw in args.kwonlyargs:
        parts.append(kw.arg)
    if args.kwarg:
        parts.append(f"**{args.kwarg.arg}")
    return ", ".join(parts)


def _find_calls(node) -> list[str]:
    """提取函数内调用的其他函数名。"""
    calls = []
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            if isinstance(child.func, ast.Name):
                calls.append(child.func.id)
            elif isinstance(child.func, ast.Attribute):
                calls.append(f"{ast.unparse(child.func.value)}."  # type: ignore[attr-defined]
                             f"{child.func.attr}" if hasattr(ast, 'unparse') else child.func.attr)
    return calls


def _find_global_refs(tree: ast.AST) -> dict[str, list[str]]:
    """预扫描：哪些函数被谁调用（构建反向引用）。"""
    refs: dict[str, list[str]] = defaultdict(list)
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        caller = node.name
        for child in ast.walk(node):
            if isinstance(child, ast.Call) and isinstance(child.func, ast.Name):
                refs[child.func.id].append(caller)
    return dict(refs)


def _extract_assign_param(node, params):
    """处理 ast.Assign 节点，提取全局变量。"""
    for target in node.targets:
        if isinstance(target, ast.Name) and not target.id.startswith("_"):
            params[target.id] = {
                "scope": "global",
                "type": "config" if target.id.isupper() else "variable",
            }


def _extract_annassign_param(node, params):
    """处理 ast.AnnAssign 节点，提取带注解全局变量。"""
    if isinstance(node.target, ast.Name) and not node.target.id.startswith("_"):
        params[node.target.id] = {"scope": "global", "type": "annotated"}


def _extract_global_params(content: str) -> dict[str, dict]:
    """提取 Python 模块级全局变量。"""
    params: dict[str, dict] = {}
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return params
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Assign):
            _extract_assign_param(node, params)
        elif isinstance(node, ast.AnnAssign):
            _extract_annassign_param(node, params)
    return params


# ============================================================
# 多语言函数提取（正则近似）
# ============================================================

def _analyze_generic_functions(filepath: str) -> list[dict]:
    """多语言正则提取函数签名+行数估算。"""
    ext = os.path.splitext(filepath)[1].lower()
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
    except (OSError, UnicodeDecodeError):
        return []

    patterns: dict[str, str] = {
        ".js": r'(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*\(([^)]*)\)',
        ".ts": r'(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*\(([^)]*)\)',
        ".java": r'(?:public|private|protected)\s+(?:static\s+)?[\w<>\[\]]+\s+(\w+)\s*\(([^)]*)\)',
        ".go": r'func\s+(?:\(\w+\s+\*?\w+\)\s+)?([A-Z]\w*)\s*\(([^)]*)\)',
        ".cs": r'(?:public|private|protected|internal)\s+(?:static\s+)?[\w<>\[\]]+\s+(\w+)\s*\(([^)]*)\)',
        ".rs": r'pub\s+(?:async\s+)?fn\s+(\w+)\s*\(([^)]*)\)',
    }

    pattern = patterns.get(ext)
    if not pattern:
        return []

    stripped = _core.strip_comments_and_strings(content, ext)
    results = []
    for m in re.finditer(pattern, stripped):
        func_name = m.group(1)
        params = m.group(2).strip() if m.lastindex and m.lastindex >= 2 else ""
        after = stripped[m.start():m.start() + 2000]
        lines = _count_function_lines(after)
        results.append({
            "name": func_name,
            "params": params,
            "lines": lines,
            "nesting": 0,
            "complexity": 0,
            "calls": [],
            "called_by": [],
            "lineno": 1,
        })

    return results


def _count_function_lines(after):
    """统计函数体行数（大括号配对，遇闭合返回）。"""
    brace_depth = 0
    func_started = False
    lines = 0
    for ch in after:
        if ch == "{":
            func_started = True
            brace_depth += 1
        elif ch == "}":
            brace_depth -= 1
            if func_started and brace_depth <= 0:
                break
        elif ch == "\n":
            lines += 1
    return max(1, lines)


# ============================================================
# get_context_for_task: 智能上下文选择
# ============================================================

def _name_matches_task(mname, task_lower):
    """模块名或下划线分词命中任务描述。"""
    return mname in task_lower or any(part in task_lower for part in mname.split("_"))


def _path_matches_task(mpath, task_lower):
    """路径分段命中任务描述。"""
    return any(part in task_lower for part in mpath.split("/") if part)


def _resp_matches_task(resp, task_lower):
    """职责关键词命中任务描述。"""
    return bool(resp) and any(word in task_lower for word in resp.split() if len(word) > 3)


def _match_modules_by_keyword(modules, task_lower):
    """从任务关键词匹配涉及的模块名。"""
    involved = set()
    for m in modules:
        mname = m.get("name", "").lower()
        mpath = m.get("path", "").lower()
        resp = m.get("responsibility", "").lower()
        if _name_matches_task(mname, task_lower):
            involved.add(m.get("name", ""))
        if _path_matches_task(mpath, task_lower):
            involved.add(m.get("name", ""))
        if _resp_matches_task(resp, task_lower):
            involved.add(m.get("name", ""))
    return involved


def _extract_file_refs(modules):
    """从任务描述提取文件引用及匹配的模块名。

    Returns:
        (file_refs, matched_modules)

    注意：原实现中 re.findall 结果赋值后未用于循环（循环遍历初始为空的
    file_refs），文件引用提取实际从未生效。此处保持原行为不变（file_refs 恒为空）。
    """
    file_refs = []
    matched_modules = set()
    for fp in file_refs:
        file_refs.append(fp.strip().rstrip(".,;)"))
        for m in modules:
            if fp.strip().startswith(m.get("path", "")):
                matched_modules.add(m.get("name", ""))
    return file_refs, matched_modules


def _expand_deps(involved, deps, module_names, modules):
    """从依赖图扩展上下游模块。"""
    extended = set(involved)
    for mod_name in list(involved):
        for dep in deps.get(mod_name, []):
            if dep in module_names:
                extended.add(dep)
        for m in modules:
            if mod_name in deps.get(m.get("name", ""), []):
                extended.add(m.get("name", ""))
    return extended


def _count_md_lines(dir_path, names, suffix):
    """统计模块 Markdown 文档的总行数。"""
    if not dir_path or not os.path.isdir(dir_path):
        return 0
    total = 0
    for name in names:
        fpath = os.path.join(dir_path, f"{name}{suffix}")
        if os.path.isfile(fpath):
            try:
                total += len(Path(fpath).read_text(encoding="utf-8").split("\n"))
            except Exception:
                pass
    return total


def get_context_for_task(
    task_description: str,
    blueprint_path: str,
    l1_dir: str | None = None,
    l2_dir: str | None = None,
) -> dict:
    """根据任务描述智能选择需要加载的上下文。

    Returns:
        {
            "l0": str (L0 文本),
            "l1_needed": [str] (需要的 L1 模块名),
            "l2_needed": [str] (需要的 L2 模块名),
            "l3_files": [str] (需要读的源文件),
            "total_estimated_lines": int,
            "reasoning": str,
            "warning": str | None,
        }
    """
    from context_compressor import _read_blueprint, generate_l0  # 惰性导入以避免循环依赖
    bp = _read_blueprint(blueprint_path)
    modules = bp.get("modules", [])
    deps = bp.get("dependency_graph", {})
    module_names = {m.get("name", "") for m in modules}

    # 1. 关键词匹配 + 2. 文件引用提取
    involved = _match_modules_by_keyword(modules, task_description.lower())
    file_refs, ref_modules = _extract_file_refs(modules)
    involved.update(ref_modules)

    # 3. 依赖图扩展上下游
    extended = _expand_deps(involved, deps, module_names, modules)

    # 4. 组装结果与行数估算
    l0_text = generate_l0(blueprint_path)
    l0_lines = l0_text.count("\n") + 1
    l1_needed = sorted(extended)
    l2_needed = sorted(involved)
    l1_lines = _count_md_lines(l1_dir, l1_needed, "_contract.md")
    l2_lines = _count_md_lines(l2_dir, l2_needed, "_detail.md")
    total_estimated = l0_lines + l1_lines + l2_lines + len(file_refs) * 200

    warning = None
    if total_estimated > 3000:
        warning = (
            f"⚠️ 预估上下文 {total_estimated} 行，超过 3000 行建议值。"
            f"当前涉及 {len(involved)} 个模块 + {len(extended) - len(involved)} 个上下游。"
            f"建议缩小任务范围或指定具体模块。"
        )

    reasoning = (
        f"从任务描述中识别到 {len(involved)} 个直接模块: "
        f"{', '.join(sorted(involved)) or '(无)'}。"
        f"扩展上下游后共 {len(extended)} 个模块需加载 L1。"
        f"任务提及 {len(file_refs)} 个文件参考。"
    )

    return {
        "l0": l0_text[:2000],
        "l1_needed": l1_needed,
        "l2_needed": l2_needed,
        "l3_files": file_refs,
        "total_estimated_lines": total_estimated,
        "reasoning": reasoning,
        "warning": warning,
        "involved_modules": sorted(involved),
        "extended_modules": sorted(extended),
    }


# ============================================================
# refresh: 增量刷新 L2
# ============================================================

def _infer_project_root(file_path):
    """向上查找含 .codebuddy 目录的项目根目录。"""
    project_root = os.path.dirname(file_path)
    for _ in range(10):
        if os.path.isdir(os.path.join(project_root, ".codebuddy")):
            break
        parent = os.path.dirname(project_root)
        if parent == project_root:
            break
        project_root = parent
    return project_root


def _infer_blueprint_path(project_root, blueprint_path):
    """推断蓝图文件路径，找不到返回 None。"""
    if blueprint_path:
        return blueprint_path
    candidates = [
        os.path.join(project_root, ".codebuddy", "architecture_blueprint.json"),
        os.path.join(project_root, "architecture_blueprint.json"),
    ]
    return next((p for p in candidates if os.path.isfile(p)), None)


def _find_module_for_file(bp, rel_file):
    """根据相对路径确定文件所属模块名，未命中返回 None。"""
    for m in bp.get("modules", []):
        if rel_file.startswith(m.get("path", "") + "/"):
            return m.get("name", "")
    return None


def refresh(file_path: str, blueprint_path: str | None = None,
            l2_dir: str | None = None) -> dict:
    """当某个文件被修改后，增量更新其 L2 文档。

    自动检测文件所属模块并重新生成该模块的 L2 detail.md。

    Returns:
        {"status": "refreshed" | "not_found", "module": str, "l2_file": str}
    """
    from context_compressor import _log, _read_blueprint, _rel, generate_l2  # 惰性导入以避免循环依赖
    file_path = os.path.abspath(file_path)
    if not os.path.isfile(file_path):
        return {"status": "not_found", "reason": f"文件不存在: {file_path}"}

    # 自动推断项目根目录 + 蓝图路径
    project_root = _infer_project_root(file_path)
    blueprint_path = _infer_blueprint_path(project_root, blueprint_path)
    if not blueprint_path or not os.path.isfile(blueprint_path):
        return {"status": "not_found", "reason": "无法定位 architecture_blueprint.json"}

    # 确定文件所属模块
    bp = _read_blueprint(blueprint_path)
    rel_file = _rel(file_path, project_root)
    module_name = _find_module_for_file(bp, rel_file)
    if not module_name:
        return {"status": "not_found", "reason": f"文件 {rel_file} 不属于任何已知模块"}

    # 重新生成 L2
    l2_text = generate_l2(project_root, module_name, blueprint_path)

    # 默认输出目录
    if not l2_dir:
        l2_dir = os.path.join(project_root, ".codebuddy", "context", "L2_details")

    os.makedirs(l2_dir, exist_ok=True)
    l2_file = os.path.join(l2_dir, f"{module_name}_detail.md")
    with open(l2_file, "w", encoding="utf-8") as f:
        f.write(l2_text)

    _log(f"L2 已刷新: {module_name} → {l2_file}")
    return {"status": "refreshed", "module": module_name, "l2_file": l2_file, "file": rel_file}


# ============================================================
# CLI 输出辅助
# ============================================================

def _print_context_result(r: dict) -> None:
    print("\n" + "=" * 60)
    print(f"  智能上下文选择 — {r.get('reasoning', '')}")
    print("=" * 60)
    print(f"  直接涉及模块: {', '.join(r.get('involved_modules', [])) or '(无)'}")
    print(f"  扩展上下游:   {', '.join(r.get('extended_modules', [])) or '(无)'}")
    print(f"  L1 需加载:    {len(r.get('l1_needed', []))} 个模块组")
    print(f"  L2 需加载:    {len(r.get('l2_needed', []))} 个模块详情")
    print(f"  L3 参考文件:  {len(r.get('l3_files', []))} 个")
    print(f"  预估总行数:   {r.get('total_estimated_lines', 0)}")
    if r.get("warning"):
        print(f"\n  {r['warning']}")
    print("=" * 60)
    print("\n  L0 摘要 (项目级):")
    l0 = r.get("l0", "")
    # 只打印 L0 的前 15 行
    l0_lines = l0.split("\n")[:15]
    for line in l0_lines:
        print(f"  {line}")
    if len(l0.split("\n")) > 15:
        print("  ...")
    print()
