"""通用检测驱动器 — 文件大小/复杂度/嵌套/参数/安全报告。"""
import os
import sys as _sys

_sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'internal'))
from detector_registry import register_detector  # noqa: E402

import quality_core as _core  # noqa: E402
from quality_checks_metrics import (  # noqa: E402
    LANG_CC_PATTERNS,
    LANG_FUNC_DEF_PATTERNS,
    _compute_cc_regex,
    _compute_nesting_regex,
    _compute_function_cc,
    _compute_function_nesting,
    _count_params_regex,
    _count_java_methods,
    _check_language_rules,
)

# ============================================================
# 通用检测驱动器
# ============================================================

@register_detector("generic", "filesize")
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

@register_detector("generic", "complexity")
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


@register_detector("generic", "nesting")
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


@register_detector("generic", "complexity")
def _report_function_cc(functions, filepath, collector):
    """逐函数报告圈复杂度（函数级，置信度 80）"""
    for name, line, cc in functions:
        if cc > _core.THRESHOLDS["cyclomatic_complexity_block"]:
            collector.add("block", "complexity_regex", filepath, line,
                          f"函数 '{name}' 圈复杂度(近似) {cc} > {_core.THRESHOLDS['cyclomatic_complexity_block']}(阻塞)",
                          "拆分为多个小函数", confidence=80)
        elif cc > _core.THRESHOLDS["cyclomatic_complexity_warn"]:
            collector.add("warn", "complexity_regex", filepath, line,
                          f"函数 '{name}' 圈复杂度(近似) {cc} > {_core.THRESHOLDS['cyclomatic_complexity_warn']}(警告)",
                          "考虑拆分", confidence=80)


@register_detector("generic", "nesting")
def _report_function_nesting(functions, filepath, collector):
    """逐函数报告嵌套深度（函数级，置信度 80）"""
    for name, line, depth in functions:
        if depth > _core.THRESHOLDS["max_nesting_block"]:
            collector.add("block", "nesting_regex", filepath, line,
                          f"函数 '{name}' 嵌套深度(近似) {depth} > {_core.THRESHOLDS['max_nesting_block']}(阻塞)",
                          "使用 early return 减少嵌套", confidence=80)
        elif depth > _core.THRESHOLDS["max_nesting_warn"]:
            collector.add("warn", "nesting_regex", filepath, line,
                          f"函数 '{name}' 嵌套深度(近似) {depth} > {_core.THRESHOLDS['max_nesting_warn']}(警告)",
                          "考虑使用 early return", confidence=80)


@register_detector("generic", "params")
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
    except (OSError, UnicodeDecodeError):
        return
    
    loc = _core.count_lines_of_code(content)
    _check_file_size(loc, filepath, collector)
    _check_security_wrapper(content, filepath, collector, file_type)
    
    stripped = _core.strip_comments_and_strings(content, ext)
    
    # 函数级 CC（有函数定义正则的语言优先函数级，否则退回文件级）
    if ext in LANG_FUNC_DEF_PATTERNS:
        _report_function_cc(_compute_function_cc(content, ext, stripped=stripped), filepath, collector)
        if check_nesting:
            _report_function_nesting(_compute_function_nesting(content, ext, stripped=stripped), filepath, collector)
    else:
        _report_complexity(_compute_cc_regex(content, ext, stripped=stripped), filepath, collector)
        if check_nesting:
            _report_nesting(_compute_nesting_regex(content, ext, stripped=stripped), filepath, collector)
    
    _report_params(_count_params_regex(content, ext, stripped=stripped), filepath, collector)
    
    # 语言专属规则（FN 漏检补齐）
    _check_language_rules(content, filepath, collector, ext)
    
    if check_methods:
        method_count = _count_java_methods(content, stripped=stripped)
        if method_count > _core.THRESHOLDS["max_class_methods_warn"]:
            collector.add("warn", "class_size_regex", filepath, 0,
                          f"类方法数(近似) {method_count} > {_core.THRESHOLDS['max_class_methods_warn']}(警告)",
                          "检查是否违反单一职责原则", confidence=75)


# ---- 安全检查包装（避免循环导入：从 quality_security 延迟导入） ----

@register_detector("generic", "security")
def _check_security_wrapper(content, filepath, collector, file_type=None):
    """延迟导入 _check_security 避免循环依赖"""
    from quality_security import _check_security as _sec
    _sec(content, filepath, collector, file_type=file_type)


@register_detector("generic", "exceptions")
def _check_empty_except_wrapper(content, filepath, collector, file_type="source"):
    """延迟导入 _check_empty_except 避免循环依赖"""
    from quality_security import _check_empty_except as _ee
    _ee(content, filepath, collector, file_type)


def _check_empty_except_generic_wrapper(content, filepath, collector, ext):
    """延迟导入 _check_empty_except_generic 避免循环依赖"""
    from quality_security import _check_empty_except_generic as _eeg
    _eeg(content, filepath, collector, ext)
