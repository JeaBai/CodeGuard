#!/usr/bin/env python3
"""
CodeGuard Quality Core — facade 入口（向后兼容）。
实现已拆分至 quality_core_config / utils / collector / classifier。
所有检测子模块的公共依赖，零外部依赖。
"""
from quality_core_config import (  # noqa: F401
    GATE_LEVELS,
    THRESHOLDS,
    ACTIVE_GATE_LEVEL,
    apply_gate_level,
    get_gate_level_from_rules,
    LAYER_PATTERNS,
    SECURITY_RED_FLAGS,
)
from quality_core_utils import (  # noqa: F401
    _log,
    find_source_files,
    compute_cyclomatic_complexity,
    count_lines_of_code,
    get_nesting_depth,
    strip_comments_and_strings,
)
from quality_core_collector import IssueCollector  # noqa: F401
from quality_core_classifier import FileClassifier, should_skip_category  # noqa: F401
