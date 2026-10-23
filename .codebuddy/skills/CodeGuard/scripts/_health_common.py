#!/usr/bin/env python3
"""module_health 共享常量与工具函数。
============================================================
从 module_health.py 拆分的共享基础模块，提供配置常量、日志函数。
被 module_health.py / clone_detector.py / health_codeowners.py 共同引用。

导出：
  常量：SCRIPT_DIR, DEFAULT_MAX_FILES, DEFAULT_MAX_LINES,
        UTIL_CORE, UTIL_HUB, UTIL_NORMAL,
        DEFAULT_SINCE_DAYS, GIT_TIMEOUT,
        HOTSPOT_W_COMPLEXITY, HOTSPOT_W_CHURN, HOTSPOT_W_OWNERSHIP,
        HOTSPOT_HOT_THRESHOLD, HOTSPOT_WARM_THRESHOLD,
        CLONE_EXTRACT_MIN_FILES
  函数：_log(msg)
  模块：re（供 clone_detector._body_source_hash 使用）
"""

from __future__ import annotations

import os
import re
import sys

# ============================================================
# 配置
# ============================================================

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# 模块膨胀默认阈值
DEFAULT_MAX_FILES = 10
DEFAULT_MAX_LINES = 2000

# 利用率分级阈值
UTIL_CORE = 6       # >5 引用 → core
UTIL_HUB = 3        # 3-5 引用 → hub
UTIL_NORMAL = 1     # 1-2 引用 → normal

# churn 回溯天数
DEFAULT_SINCE_DAYS = 90

# git 调用超时
GIT_TIMEOUT = 15

# 热点评分权重
HOTSPOT_W_COMPLEXITY = 0.30
HOTSPOT_W_CHURN = 0.40
HOTSPOT_W_OWNERSHIP = 0.30

# 热点阈值
HOTSPOT_HOT_THRESHOLD = 7.0
HOTSPOT_WARM_THRESHOLD = 4.0

# 克隆提取建议阈值
CLONE_EXTRACT_MIN_FILES = 3


# ============================================================
# 日志
# ============================================================

def _log(msg: str) -> None:
    """统一日志到 stderr。"""
    sys.stderr.write(f"[module_health] {msg}\n")
    sys.stderr.flush()
