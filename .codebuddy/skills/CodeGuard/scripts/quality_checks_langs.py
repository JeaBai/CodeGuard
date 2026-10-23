"""语言专用检测器入口 — JS/Java/Go/C#/通用/C方言/Python。"""
import ast
import os
import re
import sys as _sys

_sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'internal'))
from detector_registry import get_detectors  # noqa: E402

import quality_core as _core
from quality_checks_metrics import (
    LANG_CC_PATTERNS,
    LANG_PARAM_PATTERNS,
    LANG_NESTING_KEYWORDS,
    LANG_FUNC_DEF_PATTERNS,
    _compute_cc_regex,
    _compute_nesting_regex,
    _compute_function_cc,
    _compute_function_nesting,
    _count_params_regex,
    _check_language_rules,
)
from quality_checks_driver import (
    _check_file_size,
    _check_security_wrapper,
    _check_empty_except_wrapper,
    _check_empty_except_generic_wrapper,
    _check_regex_based_file,
    _report_complexity,
    _report_nesting,
    _report_params,
    _report_function_cc,
    _report_function_nesting,
)

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
    except Exception as e:  # codeguard: ignore GOLD_NO_BROAD_EXCEPTION — 文件读取异常统一处理
        collector.add("info", "parse_error", filepath, 0, f"无法读取文件: {e}")
        return
    
    loc = _core.count_lines_of_code(content)
    _check_file_size(loc, filepath, collector)
    _check_security_wrapper(content, filepath, collector, file_type)
    
    stripped = _core.strip_comments_and_strings(content, ext) if ext in LANG_CC_PATTERNS or ext in LANG_PARAM_PATTERNS else content
    
    if ext in LANG_FUNC_DEF_PATTERNS:
        # 函数级 CC（Rust 等有多函数文件，避免文件级累加误报）
        _report_function_cc(_compute_function_cc(content, ext, stripped=stripped), filepath, collector)
    elif ext in LANG_CC_PATTERNS:
        _report_complexity(_compute_cc_regex(content, ext, stripped=stripped), filepath, collector)
    
    if ext in LANG_PARAM_PATTERNS:
        _report_params(_count_params_regex(content, ext, stripped=stripped), filepath, collector)
    
    if ext in (".py", ".js", ".ts", ".java", ".cs", ".go", ".rs", ".cpp", ".c", ".h"):
        _check_empty_except_generic_wrapper(content, filepath, collector, ext)

    # 语言专属规则（Rust unsafe/transmute/FFI 等 FN 漏检补齐）
    _check_language_rules(content, filepath, collector, ext)


# ============================================================
# C/C++ 方言分流检测（v2.2.0）
# ============================================================

# C/C++ 函数定义正则（返回类型 + 函数名 + (参数) + {）
_C_FUNC_DEF_RE = re.compile(
    r'(?:^|\n)\s*'
    r'(?:static\s+|inline\s+|__inline\s+|volatile\s+|extern\s+|'
    r'__attribute__\s*\(\([^)]*\)\)\s+|__declspec\([^)]*\)\s*)*'
    r'(?:void|int|char|short|long|float|double|bool|size_t|'
    r'unsigned\s+(?:int|char|short|long)|signed\s+(?:int|char)|'
    r'uint\d+_t|int\d+_t|struct\s+\w+|enum\s+\w+|'
    r'[A-Za-z_]\w*)\s*\*?\s*'
    r'([A-Za-z_]\w*)\s*\([^;{}]*\)\s*\{'
)


def _compute_c_function_cc(content, ext):
    """C/C++ 函数级圈复杂度（正则近似）— 用 C 专用函数定义正则分割。

    Returns: [(func_name, line, cc), ...]
    """
    stripped = _core.strip_comments_and_strings(content, ext)
    patterns = LANG_CC_PATTERNS.get(ext, [])
    results = []
    for m in _C_FUNC_DEF_RE.finditer(stripped):
        name = m.group(1)
        start = m.end() - 1  # '{' 位置
        line = stripped[:m.start()].count("\n") + 1
        depth = 1
        i = start + 1
        while i < len(stripped) and depth > 0:
            if stripped[i] == "{":
                depth += 1
            elif stripped[i] == "}":
                depth -= 1
            i += 1
        body = stripped[start:i]
        cc = 1
        for pat in patterns:
            cc += len(re.findall(pat, body, re.IGNORECASE))
        results.append((name, line, cc))
    return results


def check_c_file(filepath, collector):
    """C/C++ 文件检测入口 — C 方言分流（v2.2.0）。

    通用 C/C++ 与嵌入式 C 在文件分类层分流，各走各的规则集：
      - generic  : 函数级 CC（替代文件级累加）+ 参数 + 嵌套 + 空 except
      - embedded : 文件大小 + 安全 + 嵌入式专用规则（ISR/volatile/内存/栈/递归/goto）
    """
    ext = os.path.splitext(filepath)[1].lower()
    file_type = _core.FileClassifier.classify(filepath)
    if file_type in ("generated", "doc"):
        return

    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
    except (OSError, UnicodeDecodeError):
        return

    # 方言判定（显式 rules.json 覆盖优先，其次自动信号检测）
    try:
        from quality_c_dialect import detect_c_dialect, get_explicit_dialect
        dialect = detect_c_dialect(filepath, content, explicit=get_explicit_dialect())
    except ImportError:
        dialect = "generic"

    # 基础检测（两方言共享）：文件大小 + 安全
    loc = _core.count_lines_of_code(content)
    _check_file_size(loc, filepath, collector)
    _check_security_wrapper(content, filepath, collector, file_type)

    if dialect == "embedded":
        # 嵌入式：不做通用 CC/参数/嵌套（避免文件级误报），走嵌入式专用规则
        try:
            import quality_embedded
            quality_embedded.check_embedded_c_file(filepath, collector, dialect)
        except ImportError:
            pass
        return

    # 通用 C/C++：函数级 CC + 参数 + 嵌套 + 空 except + 语言规则
    _report_function_cc(_compute_c_function_cc(content, ext), filepath, collector)

    stripped = _core.strip_comments_and_strings(content, ext)
    if ext in LANG_PARAM_PATTERNS:
        _report_params(_count_params_regex(content, ext, stripped=stripped), filepath, collector)

    if ext in LANG_NESTING_KEYWORDS:
        _report_nesting(_compute_nesting_regex(content, ext, stripped=stripped), filepath, collector)

    if ext in (".cpp", ".c", ".h"):
        _check_empty_except_generic_wrapper(content, filepath, collector, ext)

    # 语言专属规则（goto / new / 多继承 等 FN 漏检补齐）
    _check_language_rules(content, filepath, collector, ext)

    # 从注册器加载额外 generic 检测器（插件化扩展点）
    extra_detectors = get_detectors("generic")
    _called_categories = {'filesize', 'complexity', 'nesting', 'params', 'security', 'exceptions'}
    for detector in extra_detectors:
        if hasattr(detector, '_detector_category') and detector._detector_category in _called_categories:
            continue  # 已通过原有逻辑调用
        try:
            detector(filepath, collector)
        except Exception:
            pass  # 插件检测器异常不影响主流程


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
    except Exception as e:  # codeguard: ignore GOLD_NO_BROAD_EXCEPTION — 文件读取异常统一处理
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
