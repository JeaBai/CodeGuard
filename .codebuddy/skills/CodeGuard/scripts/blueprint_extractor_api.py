"""多语言公共 API 提取。"""
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

# ============================================================
# 公共 API 提取
# ============================================================

def _extract_public_api(filepath: str) -> list[dict]:
    """多语言公共 API 提取（v1.1.0: 增加 source/file/line/arity 字段）。

    Returns:
        [{"name": str, "params": str, "return_type": str, "file": str, "line": int, "arity": int, "source": str}]
    """
    ext = os.path.splitext(filepath)[1].lower()
    results: list[dict] = []

    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
    except (OSError, UnicodeDecodeError):
        return results

    if ext == ".py":
        results = _extract_python_api(content, filepath)
    elif ext in (".js", ".ts", ".mjs", ".tsx"):
        results = _extract_js_api(content, filepath)
    elif ext == ".java":
        results = _extract_java_api(content, filepath)
    elif ext == ".go":
        results = _extract_go_api(content, filepath)
    elif ext == ".cs":
        results = _extract_csharp_api(content, filepath)
    elif ext == ".rs":
        results = _extract_rust_api(content, filepath)

    return results


def _build_function_entry(node, filepath, source_lines, name_prefix=""):
    """从 ast.FunctionDef 构建 API 条目。"""
    params_str = _format_python_params(node.args)
    return_type = "None"
    if node.returns:
        return_type = ast.unparse(node.returns) if hasattr(ast, "unparse") else "Unknown"
    line_no = node.lineno
    end_line = getattr(node, "end_lineno", line_no)
    source = "\n".join(source_lines[line_no - 1:end_line]) if source_lines else ""
    return {
        "name": f"{name_prefix}{node.name}",
        "params": params_str,
        "return_type": return_type,
        "file": filepath,
        "line": line_no,
        "arity": len(node.args.args),
        "source": source,
    }


def _extract_class_methods(node, filepath, source_lines, results):
    """提取类内方法条目。"""
    for item in node.body:
        if isinstance(item, ast.FunctionDef) and not item.name.startswith("_"):
            results.append(_build_function_entry(item, filepath, source_lines, f"{node.name}."))


def _extract_python_api(content: str, filepath: str = "") -> list[dict]:
    """Python: AST 提取 + source/file/line/arity — v1.1.0 补齐克隆检测数据流。"""
    results: list[dict] = []
    source_lines = content.split("\n") if content else []
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return results

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.FunctionDef) and not node.name.startswith("_"):
            results.append(_build_function_entry(node, filepath, source_lines))
        elif isinstance(node, ast.ClassDef):
            _extract_class_methods(node, filepath, source_lines, results)
    return results


def _format_python_params(args: ast.arguments) -> str:
    """格式化 Python 函数参数列表。"""
    parts = []
    for arg in args.args:
        parts.append(arg.arg)
    if args.vararg:
        parts.append(f"*{args.vararg.arg}")
    for kw in args.kwonlyargs:
        parts.append(kw.arg)
    if args.kwarg:
        parts.append(f"**{args.kwarg.arg}")
    return ", ".join(parts)


def _extract_js_api(content: str, filepath: str = "") -> list[dict]:
    """JS/TS: 正则提取 export 函数/类 + 体捕获（v1.1.0）。"""
    results: list[dict] = []
    stripped = _core.strip_comments_and_strings(content, ".js")

    # export function name(params) { ... } → 捕获函数体
    export_func_body = re.compile(
        r'export\s+(?:async\s+)?function\s+(\w+)\s*\(([^)]*)\)\s*(\{(?:[^{}]|\{[^{}]*\})*\})',
        re.MULTILINE | re.DOTALL,
    )
    for m in export_func_body.finditer(stripped):
        name = m.group(1)
        params = m.group(2).strip()
        body = m.group(3) if m.lastindex and m.lastindex >= 3 else m.group(0)
        arity = len([p for p in params.split(",") if p.strip()]) if params else 0
        line_no = stripped[:m.start()].count("\n") + 1
        results.append({
            "name": name, "params": params, "return_type": "unknown",
            "file": filepath, "line": line_no, "arity": arity,
            "source": body,
        })

    # export const name = (params) =>
    export_arrow = re.compile(
        r'export\s+(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?\(([^)]*)\)',
        re.MULTILINE,
    )
    for m in export_arrow.finditer(stripped):
        name = m.group(1)
        params = m.group(2).strip()
        arity = len([p for p in params.split(",") if p.strip()]) if params else 0
        line_no = stripped[:m.start()].count("\n") + 1
        results.append({
            "name": name, "params": params, "return_type": "unknown",
            "file": filepath, "line": line_no, "arity": arity,
            "source": m.group(0),
        })

    # export class
    export_class = re.compile(r'export\s+(?:default\s+)?class\s+(\w+)', re.MULTILINE)
    for m in export_class.finditer(stripped):
        line_no = stripped[:m.start()].count("\n") + 1
        results.append({
            "name": m.group(1), "params": "", "return_type": "class",
            "file": filepath, "line": line_no, "arity": 0,
            "source": m.group(0),
        })

    return results


def _extract_java_api(content: str, filepath: str = "") -> list[dict]:
    """Java: 正则提取 public 方法 + 体捕获（v1.1.0）。"""
    results: list[dict] = []
    stripped = _core.strip_comments_and_strings(content, ".java")
    public_method_body = re.compile(
        r'public\s+(?:static\s+)?(?:[\w<>\[\]]+\s+)?(\w+)\s*\(([^)]*)\)\s*(\{(?:[^{}]|\{[^{}]*\})*\})',
        re.MULTILINE | re.DOTALL,
    )
    for m in public_method_body.finditer(stripped):
        name = m.group(1)
        params = m.group(2).strip()
        body = m.group(3) if m.lastindex and m.lastindex >= 3 else m.group(0)
        arity = len([p for p in params.split(",") if p.strip()]) if params else 0
        line_no = stripped[:m.start()].count("\n") + 1
        results.append({
            "name": name, "params": params, "return_type": "unknown",
            "file": filepath, "line": line_no, "arity": arity,
            "source": body,
        })
    return results


def _extract_go_api(content: str, filepath: str = "") -> list[dict]:
    """Go: 正则提取首字母大写的导出函数 + 体捕获（v1.1.0）。"""
    results: list[dict] = []
    stripped = _core.strip_comments_and_strings(content, ".go")
    exported_func_body = re.compile(
        r'func\s+(?:\(\w+\s+\*?\w+\)\s+)?([A-Z]\w*)\s*\(([^)]*)\)\s*(\{(?:[^{}]|\{[^{}]*\})*\})',
        re.MULTILINE | re.DOTALL,
    )
    for m in exported_func_body.finditer(stripped):
        name = m.group(1)
        params = m.group(2).strip()
        body = m.group(3) if m.lastindex and m.lastindex >= 3 else m.group(0)
        arity = len([p for p in params.split(",") if p.strip()]) if params else 0
        line_no = stripped[:m.start()].count("\n") + 1
        results.append({
            "name": name, "params": params, "return_type": "unknown",
            "file": filepath, "line": line_no, "arity": arity,
            "source": body,
        })
    return results


def _extract_csharp_api(content: str, filepath: str = "") -> list[dict]:
    """C#: 正则提取 public 方法 + 体捕获（v1.1.0）。"""
    results: list[dict] = []
    stripped = _core.strip_comments_and_strings(content, ".cs")
    public_method_body = re.compile(
        r'public\s+(?:static\s+)?(?:[\w<>\[\]]+\s+)?(\w+)\s*\(([^)]*)\)\s*(\{(?:[^{}]|\{[^{}]*\})*\})',
        re.MULTILINE | re.DOTALL,
    )
    for m in public_method_body.finditer(stripped):
        name = m.group(1)
        params = m.group(2).strip()
        body = m.group(3) if m.lastindex and m.lastindex >= 3 else m.group(0)
        arity = len([p for p in params.split(",") if p.strip()]) if params else 0
        line_no = stripped[:m.start()].count("\n") + 1
        results.append({
            "name": name, "params": params, "return_type": "unknown",
            "file": filepath, "line": line_no, "arity": arity,
            "source": body,
        })
    return results


def _extract_rust_api(content: str, filepath: str = "") -> list[dict]:
    """Rust: 正则提取 pub fn + 体捕获（v1.1.0）。"""
    results: list[dict] = []
    stripped = _core.strip_comments_and_strings(content, ".rs")
    pub_fn_body = re.compile(
        r'pub\s+(?:async\s+)?fn\s+(\w+)\s*\(([^)]*)\)\s*(\{(?:[^{}]|\{[^{}]*\})*\})',
        re.MULTILINE | re.DOTALL,
    )
    for m in pub_fn_body.finditer(stripped):
        name = m.group(1)
        params = m.group(2).strip()
        body = m.group(3) if m.lastindex and m.lastindex >= 3 else m.group(0)
        arity = len([p for p in params.split(",") if p.strip()]) if params else 0
        line_no = stripped[:m.start()].count("\n") + 1
        results.append({
            "name": name, "params": params, "return_type": "unknown",
            "file": filepath, "line": line_no, "arity": arity,
            "source": body,
        })
    return results
