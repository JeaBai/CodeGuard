#!/usr/bin/env python3
"""
CodeGuard Quality Checks
=========================
文件级质量检测：圈复杂度、嵌套深度、参数数量、类大小、文件大小。
覆盖 Python (AST精确) + JS/TS/Java/Go/C# (正则近似) 多语言派发。
"""

import ast
import os
import re

import quality_core as _core


# ============================================================
# 语言分支关键词（圈复杂度近似）
# ============================================================

LANG_CC_PATTERNS = {
    ".js": [r'\bif\s*\(', r'\belse\s+if\s*\(', r'\bfor\s*\(', r'\bwhile\s*\(',
            r'\bswitch\s*\(', r'\bcase\s+', r'&&', r'\|\|', r'\?\?', r'\bcatch\s*\('],
    ".ts": [r'\bif\s*\(', r'\belse\s+if\s*\(', r'\bfor\s*\(', r'\bwhile\s*\(',
            r'\bswitch\s*\(', r'\bcase\s+', r'&&', r'\|\|', r'\?\?', r'\bcatch\s*\('],
    ".mjs": [r'\bif\s*\(', r'\belse\s+if\s*\(', r'\bfor\s*\(', r'\bwhile\s*\(',
             r'\bswitch\s*\(', r'\bcase\s+', r'&&', r'\|\|', r'\?\?', r'\bcatch\s*\('],
    ".java": [r'\bif\s*\(', r'\belse\s+if\s*\(', r'\bfor\s*\(', r'\bwhile\s*\(',
              r'\bswitch\s*\(', r'\bcase\s+', r'&&', r'\|\|', r'\bcatch\s*\('],
    ".go": [r'\bif\s+', r'\bfor\s+', r'\bswitch\s+', r'&&', r'\|\|',
            r'\bcase\s+', r'if\s+err\s*!=\s*nil'],
    ".cs": [r'\bif\s*\(', r'\belse\s+if\s*\(', r'\bfor\s*\(', r'\bforeach\s*\(',
            r'\bwhile\s*\(', r'\bswitch\s*\(', r'\bcase\s+', r'&&', r'\|\|', r'\bcatch\b'],
    ".rs": [r'\bif\s+', r'\bfor\s+', r'\bwhile\s+', r'\bmatch\s+', r'&&', r'\|\|'],
    ".cpp": [r'\bif\s*\(', r'\belse\s+if\s*\(', r'\bfor\s*\(', r'\bwhile\s*\(',
             r'\bswitch\s*\(', r'\bcase\s+', r'&&', r'\|\|', r'\bcatch\s*\('],
    ".c": [r'\bif\s*\(', r'\belse\s+if\s*\(', r'\bfor\s*\(', r'\bwhile\s*\(',
           r'\bswitch\s*\(', r'\bcase\s+', r'&&', r'\|\|'],
    ".h": [r'\bif\s*\(', r'\belse\s+if\s*\(', r'\bfor\s*\(', r'\bwhile\s*\(',
           r'\bswitch\s*\(', r'\bcase\s+', r'&&', r'\|\|'],
}

LANG_PARAM_PATTERNS = {
    ".js": re.compile(r'(?:function\s+\w+\s*|=>\s*|\(\s*)\(([^)]*)\)'),
    ".ts": re.compile(r'(?:function\s+\w+\s*|=>\s*|\(\s*)\(([^)]*)\)'),
    ".mjs": re.compile(r'(?:function\s+\w+\s*|=>\s*|\(\s*)\(([^)]*)\)'),
    ".java": re.compile(r'(?:public|private|protected|static|\s)+\w+\s+(\w+)\s*\(([^)]*)\)'),
    ".go": re.compile(r'func\s+(?:\(\w+\s+\*?\w+\)\s+)?(\w+)\s*\(([^)]*)\)'),
    ".cs": re.compile(r'(?:public|private|protected|internal|static|\s)+\w+\s+(\w+)\s*\(([^)]*)\)'),
    ".rs": re.compile(r'fn\s+(\w+)\s*\(([^)]*)\)'),
    ".cpp": re.compile(r'\w+\s+(\w+)\s*\(([^)]*)\)'),
}

LANG_NESTING_KEYWORDS = {
    ".js": r'\b(?:if|for|while|switch|catch|function|class)\b',
    ".ts": r'\b(?:if|for|while|switch|catch|function|class)\b',
    ".mjs": r'\b(?:if|for|while|switch|catch|function|class)\b',
    ".java": r'\b(?:if|for|while|switch|catch|class|try)\b',
    ".cs": r'\b(?:if|for|foreach|while|switch|catch|class|try)\b',
    ".cpp": r'\b(?:if|for|while|switch|catch|class|try)\b',
}


# ============================================================
# 正则近似检测器
# ============================================================

def _compute_cc_regex(content, ext, *, stripped=None):
    """正则近似圈复杂度（基础值=1），先在剥离注释的内容上运行"""
    if stripped is None:
        stripped = _core.strip_comments_and_strings(content, ext)
    patterns = LANG_CC_PATTERNS.get(ext, [])
    cc = 1
    for pattern in patterns:
        cc += len(re.findall(pattern, stripped, re.IGNORECASE))
    return cc


# ---- _compute_nesting_regex 子函数 ----

def _process_nesting_kw_line(current_depth, pending_depth, pending_releases, opens, closes, kw_count, line_content):
    """处理含嵌套关键字的行，返回 (current_depth, pending_depth, pending_releases)"""
    current_depth += pending_depth
    pending_depth = 0
    
    if pending_releases:
        current_depth -= sum(pending_releases)
        pending_releases.clear()
    
    if '{' in line_content:
        current_depth += opens
        current_depth -= closes
    else:
        pending_depth = kw_count
        pending_releases.extend([1] * kw_count)
    
    return current_depth, pending_depth, pending_releases


def _process_nesting_brace_line(current_depth, pending_depth, pending_releases, opens, closes):
    """处理无嵌套关键字的行，返回 (current_depth, pending_depth, pending_releases)"""
    current_depth += pending_depth
    pending_depth = 0
    current_depth += opens - closes
    
    if current_depth <= 0:
        if pending_releases:
            current_depth -= sum(pending_releases)
        current_depth = 0
        pending_depth = 0
        pending_releases.clear()
    
    return current_depth, pending_depth, pending_releases


def _process_pending_release(current_depth, pending_releases, nesting_kw, line_content, opens, closes):
    """处理待释放的嵌套深度"""
    if pending_releases and not re.search(nesting_kw, line_content, re.IGNORECASE) and opens == 0 and closes == 0:
        return current_depth - pending_releases.pop(), pending_releases
    return current_depth, pending_releases


def _compute_nesting_regex(content, ext, *, stripped=None):
    """大括号计数近似最大嵌套深度 — v2.0.10: CC=18→10"""
    if ext not in LANG_NESTING_KEYWORDS:
        return 0
    
    if stripped is None:
        stripped = _core.strip_comments_and_strings(content, ext)
    nesting_kw = LANG_NESTING_KEYWORDS[ext]
    lines = stripped.split('\n')
    max_depth = 0
    current_depth = 0
    pending_depth = 0
    pending_releases = []
    
    for line in lines:
        line_content = line.strip()
        if not line_content or line_content.startswith('//') or line_content.startswith('#'):
            continue
        
        opens = len(re.findall(r'\{', line_content))
        closes = len(re.findall(r'\}', line_content))
        
        current_depth, pending_releases = _process_pending_release(
            current_depth, pending_releases, nesting_kw, line_content, opens, closes)
        
        kw_matches = re.findall(nesting_kw, line_content, re.IGNORECASE)
        kw_count = len(kw_matches)
        
        if kw_count > 0:
            current_depth, pending_depth, pending_releases = _process_nesting_kw_line(
                current_depth, pending_depth, pending_releases, opens, closes, kw_count, line_content)
        else:
            current_depth, pending_depth, pending_releases = _process_nesting_brace_line(
                current_depth, pending_depth, pending_releases, opens, closes)
        
        current_depth = max(0, current_depth)
        max_depth = max(max_depth, current_depth)
    
    return max_depth


def _count_params_regex(content, ext, *, stripped=None):
    """正则提取函数参数数量"""
    if stripped is None:
        stripped = _core.strip_comments_and_strings(content, ext)
    pattern = LANG_PARAM_PATTERNS.get(ext)
    if not pattern:
        return {}
    
    results = {}
    lines = stripped.split('\n')
    for i, line in enumerate(lines, 1):
        for match in pattern.finditer(line):
            groups = match.groups()
            params_str = groups[-1] if groups else ""
            count = 0 if not params_str or params_str.isspace() else params_str.count(',') + 1
            func_name = groups[0] if len(groups) >= 2 and groups[0] else "unknown"
            results[(func_name, i)] = count
    return results


def _count_java_methods(content, *, stripped=None):
    """统计 Java/C# 类方法数"""
    if stripped is None:
        stripped = _core.strip_comments_and_strings(content, ".java")
    method_pattern = re.compile(
        r'(?:public|private|protected|static|final|abstract|synchronized)\s+\S+\s+(\w+)\s*\([^)]*\)\s*(\{|throws)',
        re.IGNORECASE
    )
    return len(method_pattern.findall(stripped))


# ============================================================
# 通用检测驱动器
# ============================================================

def _check_file_size(loc, filepath, collector):
    """通用文件大小检查（置信度 95）"""
    if loc > _core.THRESHOLDS["max_file_lines_block"]:
        collector.add("block", "file_size", filepath, 0,
                      f"文件代码行数 {loc} > {_core.THRESHOLDS['max_file_lines_block']}（阻塞阈值）",
                      "将文件拆分为多个模块", confidence=95)
    elif loc > _core.THRESHOLDS["max_file_lines_warn"]:
        collector.add("warn", "file_size", filepath, 0,
                      f"文件代码行数 {loc} > {_core.THRESHOLDS['max_file_lines_warn']}（警告阈值）",
                      "考虑拆分大文件", confidence=95)


# ---- 共享检测逻辑（消除 _check_regex_based_file 与 check_generic_file 间的重复） ----

def _report_complexity(cc, filepath, collector):
    """圈复杂度检测 + 报告（共享逻辑，消除 3 dup）"""
    if cc > _core.THRESHOLDS["cyclomatic_complexity_block"]:
        collector.add("block", "complexity_regex", filepath, 0,
                      f"圈复杂度(近似) {cc} > {_core.THRESHOLDS['cyclomatic_complexity_block']}(阻塞)",
                      "拆分为多个小函数", confidence=80)
    elif cc > _core.THRESHOLDS["cyclomatic_complexity_warn"]:
        collector.add("warn", "complexity_regex", filepath, 0,
                      f"圈复杂度(近似) {cc} > {_core.THRESHOLDS['cyclomatic_complexity_warn']}(警告)",
                      "考虑拆分", confidence=80)


def _report_nesting(depth, filepath, collector):
    """嵌套深度检测 + 报告（共享逻辑，消除 3 dup）"""
    if depth > _core.THRESHOLDS["max_nesting_block"]:
        collector.add("block", "nesting_regex", filepath, 0,
                      f"嵌套深度(近似) {depth} > {_core.THRESHOLDS['max_nesting_block']}(阻塞)",
                      "使用 early return 减少嵌套", confidence=80)
    elif depth > _core.THRESHOLDS["max_nesting_warn"]:
        collector.add("warn", "nesting_regex", filepath, 0,
                      f"嵌套深度(近似) {depth} > {_core.THRESHOLDS['max_nesting_warn']}(警告)",
                      "考虑使用 early return", confidence=80)


def _report_params(params, filepath, collector):
    """参数数量检测 + 报告（共享逻辑，消除 3 dup）"""
    for (func_name, line), count in params.items():
        if count > _core.THRESHOLDS["max_function_params_block"]:
            collector.add("block", "params_regex", filepath, line,
                          f"函数 '{func_name}' 参数 {count} > {_core.THRESHOLDS['max_function_params_block']}(阻塞)",
                          "封装为参数对象", confidence=80)
        elif count > _core.THRESHOLDS["max_function_params_warn"]:
            collector.add("warn", "params_regex", filepath, line,
                          f"函数 '{func_name}' 参数 {count} > {_core.THRESHOLDS['max_function_params_warn']}(警告)",
                          "考虑使用参数对象", confidence=80)


def _check_regex_based_file(filepath, collector, ext, *, check_nesting=True, check_methods=False):
    """通用正则检测驱动器 — 服务于 JS/TS/Java/Go/C# 的共享检测逻辑"""
    file_type = _core.FileClassifier.classify(filepath)
    if file_type in ("generated", "doc"):
        return
    
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
    except Exception:
        return
    
    loc = _core.count_lines_of_code(content)
    _check_file_size(loc, filepath, collector)
    _check_security_wrapper(content, filepath, collector, file_type)
    
    stripped = _core.strip_comments_and_strings(content, ext)
    
    _report_complexity(_compute_cc_regex(content, ext, stripped=stripped), filepath, collector)
    
    if check_nesting:
        _report_nesting(_compute_nesting_regex(content, ext, stripped=stripped), filepath, collector)
    
    _report_params(_count_params_regex(content, ext, stripped=stripped), filepath, collector)
    
    if check_methods:
        method_count = _count_java_methods(content, stripped=stripped)
        if method_count > _core.THRESHOLDS["max_class_methods_warn"]:
            collector.add("warn", "class_size_regex", filepath, 0,
                          f"类方法数(近似) {method_count} > {_core.THRESHOLDS['max_class_methods_warn']}(警告)",
                          "检查是否违反单一职责原则", confidence=75)


# ---- 安全检查包装（避免循环导入：从 quality_security 延迟导入） ----

def _check_security_wrapper(content, filepath, collector, file_type=None):
    """延迟导入 _check_security 避免循环依赖"""
    from quality_security import _check_security as _sec
    _sec(content, filepath, collector, file_type=file_type)


def _check_empty_except_wrapper(content, filepath, collector, file_type="source"):
    """延迟导入 _check_empty_except 避免循环依赖"""
    from quality_security import _check_empty_except as _ee
    _ee(content, filepath, collector, file_type)


def _check_empty_except_generic_wrapper(content, filepath, collector, ext):
    """延迟导入 _check_empty_except_generic 避免循环依赖"""
    from quality_security import _check_empty_except_generic as _eeg
    _eeg(content, filepath, collector, ext)


# ============================================================
# 语言专用检测器入口
# ============================================================

def check_javascript_file(filepath, collector, ext):
    _check_regex_based_file(filepath, collector, ext, check_nesting=True, check_methods=False)


def check_java_file(filepath, collector):
    _check_regex_based_file(filepath, collector, ".java", check_nesting=True, check_methods=True)


def check_go_file(filepath, collector):
    _check_regex_based_file(filepath, collector, ".go", check_nesting=False, check_methods=False)


def check_csharp_file(filepath, collector):
    _check_regex_based_file(filepath, collector, ".cs", check_nesting=True, check_methods=True)


def check_generic_file(filepath, collector, ext):
    """对非主流语言执行通用质量检测 — v2.0.10: 共享 _report_* 消除 6 dup"""
    file_type = _core.FileClassifier.classify(filepath)
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
    except Exception as e:
        collector.add("info", "parse_error", filepath, 0, f"无法读取文件: {e}")
        return
    
    loc = _core.count_lines_of_code(content)
    _check_file_size(loc, filepath, collector)
    _check_security_wrapper(content, filepath, collector, file_type)
    
    stripped = _core.strip_comments_and_strings(content, ext) if ext in LANG_CC_PATTERNS or ext in LANG_PARAM_PATTERNS else content
    
    if ext in LANG_CC_PATTERNS:
        _report_complexity(_compute_cc_regex(content, ext, stripped=stripped), filepath, collector)
    
    if ext in LANG_PARAM_PATTERNS:
        _report_params(_count_params_regex(content, ext, stripped=stripped), filepath, collector)
    
    if ext in (".py", ".js", ".ts", ".java", ".cs", ".go", ".rs", ".cpp", ".c", ".h"):
        _check_empty_except_generic_wrapper(content, filepath, collector, ext)


# ============================================================
# Python AST 精确检测
# ============================================================

def _check_function(node, filepath, collector, file_type="source"):
    """检测函数质量（AST 精确）"""
    func_name = node.name
    
    cc = _core.compute_cyclomatic_complexity(node)
    if cc > _core.THRESHOLDS["cyclomatic_complexity_block"]:
        collector.add("block", "complexity", filepath, node.lineno,
                      f"函数 '{func_name}' 圈复杂度 {cc} > {_core.THRESHOLDS['cyclomatic_complexity_block']}（阻塞）",
                      "拆分为多个小函数，或使用策略模式", confidence=90)
    elif cc > _core.THRESHOLDS["cyclomatic_complexity_warn"]:
        collector.add("warn", "complexity", filepath, node.lineno,
                      f"函数 '{func_name}' 圈复杂度 {cc} > {_core.THRESHOLDS['cyclomatic_complexity_warn']}（警告）",
                      "考虑拆分为更小的函数", confidence=90)
    
    num_params = len(node.args.args)
    if num_params > _core.THRESHOLDS["max_function_params_block"]:
        collector.add("block", "params", filepath, node.lineno,
                      f"函数 '{func_name}' 参数数量 {num_params} > {_core.THRESHOLDS['max_function_params_block']}（阻塞）",
                      "封装为参数对象或数据类", confidence=92)
    elif num_params > _core.THRESHOLDS["max_function_params_warn"]:
        collector.add("warn", "params", filepath, node.lineno,
                      f"函数 '{func_name}' 参数数量 {num_params} > {_core.THRESHOLDS['max_function_params_warn']}（警告）",
                      "考虑使用参数对象", confidence=92)
    
    depth = _core.get_nesting_depth(node)
    if depth > _core.THRESHOLDS["max_nesting_block"]:
        collector.add("block", "nesting", filepath, node.lineno,
                      f"函数 '{func_name}' 嵌套深度 {depth} > {_core.THRESHOLDS['max_nesting_block']}（阻塞）",
                      "使用 early return 或提取嵌套逻辑为独立函数", confidence=90)
    elif depth > _core.THRESHOLDS["max_nesting_warn"]:
        collector.add("warn", "nesting", filepath, node.lineno,
                      f"函数 '{func_name}' 嵌套深度 {depth} > {_core.THRESHOLDS['max_nesting_warn']}（警告）",
                      "考虑使用 early return 减少嵌套", confidence=90)


def _check_class(node, filepath, collector, file_type="source"):
    """检测类质量（AST 精确）"""
    class_name = node.name
    
    methods = [n for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
               and not n.name.startswith("__")]
    num_methods = len(methods)
    if num_methods > _core.THRESHOLDS["max_class_methods_warn"]:
        collector.add("warn", "class_size", filepath, node.lineno,
                      f"类 '{class_name}' 方法数 {num_methods} > {_core.THRESHOLDS['max_class_methods_warn']}（警告）",
                      "检查是否违反单一职责原则，考虑拆分", confidence=85)
    
    class_lines = node.end_lineno - node.lineno + 1 if node.end_lineno else 0
    if class_lines > _core.THRESHOLDS["max_class_lines_block"]:
        collector.add("block", "class_size", filepath, node.lineno,
                      f"类 '{class_name}' 代码行数 {class_lines} > {_core.THRESHOLDS['max_class_lines_block']}（阻塞）",
                      "拆分为多个职责单一的类", confidence=85)
    elif class_lines > _core.THRESHOLDS["max_class_lines_warn"]:
        collector.add("warn", "class_size", filepath, node.lineno,
                      f"类 '{class_name}' 代码行数 {class_lines} > {_core.THRESHOLDS['max_class_lines_warn']}（警告）",
                      "检查是否违反单一职责原则", confidence=85)


def check_python_file(filepath, collector):
    """对单个 Python 文件执行质量检测"""
    file_type = _core.FileClassifier.classify(filepath)
    
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
    except Exception as e:
        collector.add("info", "parse_error", filepath, 0, f"无法读取文件: {e}")
        return
    
    if file_type in ("generated", "doc"):
        if file_type == "generated":
            collector.add("info", "file_type", filepath, 0,
                         "[GENERATED] 自动生成文件，跳过质量检测",
                         "如需检测生成代码，请在 FileClassifier 中移除该路径")
        return
    
    loc = _core.count_lines_of_code(content)
    _check_file_size(loc, filepath, collector)
    
    try:
        tree = ast.parse(content)
    except SyntaxError as e:
        collector.add("warn", "parse_error", filepath, e.lineno or 0, f"语法错误: {e}")
        return
    
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            _check_function(node, filepath, collector, file_type)
        elif isinstance(node, ast.ClassDef):
            _check_class(node, filepath, collector, file_type)
    
    # 安全检查 + 异常处理检测（通过延迟导入包装）
    _check_security_wrapper(content, filepath, collector, file_type)
    _check_empty_except_wrapper(content, filepath, collector, file_type)
