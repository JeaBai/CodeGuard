#!/usr/bin/env python3
"""
CodeGuard Quality Checks — facade 入口（向后兼容）。
实现已拆分至 quality_checks_metrics / quality_checks_driver / quality_checks_langs。
"""
from quality_checks_metrics import (  # noqa: F401
    _compute_cc_regex,
    _compute_nesting_regex,
    _count_params_regex,
    _count_java_methods,
)
from quality_checks_driver import (  # noqa: F401
    _check_file_size,
    _report_complexity,
    _report_nesting,
    _report_params,
    _check_regex_based_file,
    _check_security_wrapper,
    _check_empty_except_wrapper,
    _check_empty_except_generic_wrapper,
)
from quality_checks_langs import (  # noqa: F401
    check_javascript_file,
    check_java_file,
    check_go_file,
    check_csharp_file,
    check_generic_file,
    check_c_file,
    check_python_file,
)
