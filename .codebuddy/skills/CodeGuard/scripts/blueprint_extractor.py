#!/usr/bin/env python3
"""
CodeGuard Blueprint Extractor — facade 入口（向后兼容）。
实现已拆分至 blueprint_extractor_core / deps / api / dups。
"""
from blueprint_extractor_core import (  # noqa: F401
    _collect_files,
    _extract_modules,
    _get_quality_arch,
)
from blueprint_extractor_deps import _build_dependency_graph  # noqa: F401
from blueprint_extractor_api import _extract_public_api  # noqa: F401
from blueprint_extractor_dups import (  # noqa: F401
    _extract_params_and_nesting,
    _detect_duplicates,
)
