#!/usr/bin/env python3
"""
CodeGuard Quality Core
=======================
共享基础设施：阈值定义、工具函数、问题收集器、文件分类器。
所有检测子模块的公共依赖，零外部依赖。
"""

import ast
import os
import re
import sys
from collections import defaultdict
from quality_core_utils import _log  # noqa: E402


# ============================================================
# 配置：阈值定义（基于实证研究验证）
# ============================================================

# ============================================================
# 多级门禁阈值字典（v2.1.0: 铜/银/金三级 + 动态切换）
# ============================================================

GATE_LEVELS = {
    # 金级（gold）：大厂核心系统硬性标准
    # 对齐 McCabe 原论文 CC≤10、Google 内部 style guide 嵌套≤4、
    # 阿里巴巴开发手册方法级 80 行 × 类体扩展
    "gold": {
        "cyclomatic_complexity_warn": 8,
        "cyclomatic_complexity_block": 10,
        "max_function_params_warn": 4,
        "max_function_params_block": 6,
        "max_nesting_warn": 3,
        "max_nesting_block": 4,
        "max_class_lines_warn": 200,
        "max_class_lines_block": 350,
        "max_class_methods_warn": 12,
        "max_interface_methods_warn": 8,
        "duplicate_lines_warn": 5,
        "duplicate_lines_block": 8,
        "cross_file_duplicate_block": 15,
        "max_file_lines_warn": 200,
        "max_file_lines_block": 350,
        "test_coverage_min_pct": 80,
    },
    # 银级（silver）：业务系统中型项目标准
    # 圈复杂度较金级放宽 25%，文件行数放宽 50%
    "silver": {
        "cyclomatic_complexity_warn": 10,
        "cyclomatic_complexity_block": 12,
        "max_function_params_warn": 5,
        "max_function_params_block": 7,
        "max_nesting_warn": 4,
        "max_nesting_block": 5,
        "max_class_lines_warn": 300,
        "max_class_lines_block": 450,
        "max_class_methods_warn": 15,
        "max_interface_methods_warn": 10,
        "duplicate_lines_warn": 6,
        "duplicate_lines_block": 10,
        "cross_file_duplicate_block": 20,
        "max_file_lines_warn": 300,
        "max_file_lines_block": 450,
        "test_coverage_min_pct": 60,
    },
    # 铜级（bronze）：基础扫描/个人项目
    # 最宽松的阈值，仅拦截极端情况
    "bronze": {
        "cyclomatic_complexity_warn": 15,
        "cyclomatic_complexity_block": 20,
        "max_function_params_warn": 8,
        "max_function_params_block": 10,
        "max_nesting_warn": 6,
        "max_nesting_block": 8,
        "max_class_lines_warn": 500,
        "max_class_lines_block": 800,
        "max_class_methods_warn": 20,
        "max_interface_methods_warn": 15,
        "duplicate_lines_warn": 10,
        "duplicate_lines_block": 15,
        "cross_file_duplicate_block": 30,
        "max_file_lines_warn": 500,
        "max_file_lines_block": 800,
        "test_coverage_min_pct": 0,
    },
}

# ============================================================
# 行业维度阈值覆盖 (v3.0.0: web/embedded/safety 三行业分离)
# ============================================================

# 嵌入式行业阈值覆盖: 在标准 gold/silver 基础上覆盖特定阈值
INDUSTRY_THRESHOLDS = {
    "embedded": {
        "gold": {
            "cyclomatic_complexity_warn": 12,
            "cyclomatic_complexity_block": 15,
            "max_nesting_warn": 2,
            "max_nesting_block": 3,
            "max_file_lines_warn": 300,
            "max_file_lines_block": 500,
            "duplicate_lines_warn": 3,
            "duplicate_lines_block": 5,
            "cross_file_duplicate_block": 12,
            "isr_max_lines": 80,
            "stack_array_max_bytes": 256,
        },
        "silver": {
            "cyclomatic_complexity_warn": 15,
            "cyclomatic_complexity_block": 18,
            "max_nesting_warn": 3,
            "max_nesting_block": 4,
            "max_file_lines_warn": 400,
            "max_file_lines_block": 600,
            "duplicate_lines_warn": 5,
            "duplicate_lines_block": 8,
            "isr_max_lines": 120,
            "stack_array_max_bytes": 512,
        },
    },
    # web 行业使用标准 GATE_LEVELS，无需覆盖
    "web": {},
    # safety 行业阈值 (Phase 2, 暂用 embedded gold)
    "safety": {
        "gold": {
            "cyclomatic_complexity_warn": 10,
            "cyclomatic_complexity_block": 12,
            "max_nesting_warn": 2,
            "max_nesting_block": 3,
            "max_file_lines_warn": 250,
            "max_file_lines_block": 400,
            "duplicate_lines_warn": 3,
            "duplicate_lines_block": 5,
            "isr_max_lines": 60,
            "stack_array_max_bytes": 128,
        },
    },
}

# 当前激活的行业维度
ACTIVE_INDUSTRY = "web"

# 默认使用金级阈值（最高标准）
# rules.json 的 _level 字段可动态覆盖为 "gold"/"silver"/"bronze"
THRESHOLDS = dict(GATE_LEVELS["gold"])

# 当前激活的门禁级别
ACTIVE_GATE_LEVEL = "gold"


def apply_gate_level(level, custom_thresholds=None):
    """根据门禁级别动态切换 THRESHOLDS 字典。

    Args:
        level: 门禁级别名称（"gold" / "silver" / "bronze"）
        custom_thresholds: 可选的自定义阈值覆盖字典（来自 rules.json 的 thresholds 块）

    用法：
        # 引擎启动时从 rules.json 读取 _level 字段
        level = rules_data.get("_level", "gold")
        apply_gate_level(level, rules_data.get("thresholds"))
    """
    global THRESHOLDS, ACTIVE_GATE_LEVEL  # codeguard: ignore GOLD_NO_GLOBAL_STATE

    if level not in GATE_LEVELS:
        _log(f"[CodeGuard] 警告: 未知门禁级别 '{level}'，回退为金级 (gold)")
        level = "gold"

    THRESHOLDS.clear()
    THRESHOLDS.update(GATE_LEVELS[level])
    ACTIVE_GATE_LEVEL = level

    # 合并用户自定义阈值覆盖（来自 rules.json thresholds 块）
    if custom_thresholds:
        overridden = {}
        for k, v in custom_thresholds.items():
            if k in THRESHOLDS and THRESHOLDS[k] != v:
                overridden[k] = v
                THRESHOLDS[k] = v
        if overridden:
            _log(f"[CodeGuard] 🔧 自定义阈值覆盖 {len(overridden)} 项: "
                 f"{', '.join(f'{k}={v}' for k, v in sorted(overridden.items()))}")

    _log(f"[CodeGuard] 门禁级别: {level.upper()} (阈值已切换)")


def _apply_custom_thresholds(custom_thresholds):
    """叠加用户自定义阈值，返回被修改的键值对 (用于日志)。"""
    overridden = {}
    for k, v in custom_thresholds.items():
        if k.startswith("_"):
            continue
        if k in THRESHOLDS and THRESHOLDS[k] != v:
            overridden[k] = v
        THRESHOLDS[k] = v
    return overridden


def apply_industry_level(industry, gate_level="gold", custom_thresholds=None):
    """应用行业维度阈值覆盖 (v3.0.0)。

    在标准 gold/silver 阈值基础上，叠加行业特定阈值覆盖。
    例如 embedded 行业会放宽 CC 至 15、收紧嵌套至 3。

    Args:
        industry: 行业维度 ("web" / "embedded" / "safety")
        gate_level: 门禁级别 ("gold" / "silver" / "bronze")
        custom_thresholds: 可选的自定义阈值覆盖 (来自 profile JSON 的 thresholds 块)

    用法:
        # 先调用 apply_gate_level 设置基础阈值
        apply_gate_level("gold")
        # 再叠加行业阈值
        apply_industry_level("embedded", "gold")
    """
    global THRESHOLDS, ACTIVE_INDUSTRY  # codeguard: ignore GOLD_NO_GLOBAL_STATE

    industry_overrides = INDUSTRY_THRESHOLDS.get(industry, {})
    level_overrides = industry_overrides.get(gate_level, {}) if industry_overrides else {}

    ACTIVE_INDUSTRY = industry

    # 叠加行业阈值覆盖
    if level_overrides:
        THRESHOLDS.update(level_overrides)
        _log(f"[CodeGuard] 行业阈值: {industry}/{gate_level} 覆盖 {len(level_overrides)} 项")

    # 叠加用户自定义阈值 (来自 profile JSON)
    if custom_thresholds:
        overridden = _apply_custom_thresholds(custom_thresholds)
        if overridden:
            _log(f"[CodeGuard] 🔧 行业自定义阈值覆盖 {len(overridden)} 项: "
                 f"{', '.join(f'{k}={v}' for k, v in sorted(overridden.items()))}")

    _log(f"[CodeGuard] 行业维度: {industry.upper()} / 门禁级别: {gate_level.upper()}")


def get_industry_from_config(root_path):
    """从 .code-guardian/config.json 或自动检测获取行业配置。

    Returns:
        (industry, gate_level, profile_path)
        - industry: "web" / "embedded" / "safety"
        - gate_level: "gold" / "silver" / "bronze"
        - profile_path: 规则集文件路径 (绝对路径) 或 None
    """
    import json as _json  # codeguard: ignore GOLD_NO_GLOBAL_STATE

    config_dir = os.path.join(root_path, ".code-guardian")
    config_path = os.path.join(config_dir, "config.json")

    industry = "web"
    gate_level = "gold"
    profile_path = None

    # 1. 读取 config.json
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = _json.load(f)
        industry_setting = config.get("industry", "auto")
        gate_level = config.get("gate_level", "gold")
    except (OSError, ValueError, KeyError):
        industry_setting = "auto"
        config = None

    # 2. 解析行业 (auto 时自动检测)
    if industry_setting == "auto":
        try:
            from industry_detector import detect_industry
            industry = detect_industry(root_path)
        except ImportError:
            industry = "web"
    else:
        industry = industry_setting

    # 3. 映射到规则集文件
    profile_map = {
        ("web", "gold"): None,  # 使用现有 rules.json
        ("web", "silver"): "rules-silver.json",
        ("embedded", "gold"): os.path.join("profiles", "embedded-gold.json"),
        ("embedded", "silver"): os.path.join("profiles", "embedded-silver.json"),
    }

    relative_path = profile_map.get((industry, gate_level))
    if relative_path:
        full_path = os.path.join(config_dir, relative_path)
        if os.path.exists(full_path):
            profile_path = full_path

    return industry, gate_level, profile_path


def get_gate_level_from_rules(root_path):
    """从 .code-guardian/rules.json 中读取 _level 字段。

    Returns:
        ("gold"|"silver"|"bronze", thresholds_dict|None)
    """
    import json as _json  # codeguard: ignore GOLD_NO_GLOBAL_STATE
    rules_path = os.path.join(root_path, ".code-guardian", "rules.json")
    try:
        with open(rules_path, "r", encoding="utf-8") as f:
            data = _json.load(f)
        level = data.get("_level", "gold")
        thresholds = data.get("thresholds")
        # 剥离 _comment 字段（不是有效阈值键）
        if thresholds:
            thresholds = {k: v for k, v in thresholds.items() if not k.startswith("_")}
        return level, thresholds if thresholds else None
    except (OSError, ValueError, KeyError):
        return "gold", None


def init_industry_aware(root_path):
    """行业感知集成初始化 (v3.0.0) — 一次性完成门禁+行业配置加载。

    调用顺序:
        1. 从 rules.json 读取门禁级别 (gold/silver/bronze) + 自定义阈值
        2. 从 config.json 读取行业维度 (web/embedded/safety) + 自动检测
        3. 应用基础门禁阈值
        4. 叠加行业特定阈值覆盖
        5. 加载行业规则集 profile (如有)

    Args:
        root_path: 项目根目录

    Returns:
        dict: {
            "industry": "web"|"embedded"|"safety",
            "gate_level": "gold"|"silver"|"bronze",
            "profile_path": str|None,          # 行业规则集文件绝对路径
            "profile_rules": list|None,        # 行业规则集内容 (rules 数组)
            "thresholds_applied": int,         # 实际应用的阈值数量
        }

    用法:
        from quality_core_config import init_industry_aware
        result = init_industry_aware("/path/to/project")
        print(f"行业: {result['industry']}, 门禁: {result['gate_level']}")
    """
    import json as _json  # codeguard: ignore GOLD_NO_GLOBAL_STATE

    # 1. 读取门禁级别 + 自定义阈值
    gate_level, custom_thresholds = get_gate_level_from_rules(root_path)

    # 2. 读取行业维度 + profile 路径
    industry, config_gate_level, profile_path = get_industry_from_config(root_path)

    # config.json 的 gate_level 优先于 rules.json 的 _level
    # (config.json 是用户显式选择，rules.json 是默认值)
    if config_gate_level and config_gate_level != "gold":
        gate_level = config_gate_level

    # 3. 应用基础门禁阈值
    apply_gate_level(gate_level, custom_thresholds)

    # 4. 叠加行业特定阈值
    #    如果 profile 文件包含自定义 thresholds，也一并应用
    profile_thresholds = None
    profile_rules = None
    if profile_path and os.path.exists(profile_path):
        try:
            with open(profile_path, "r", encoding="utf-8") as f:
                profile_data = _json.load(f)
            profile_thresholds = profile_data.get("thresholds")
            if profile_thresholds:
                profile_thresholds = {
                    k: v for k, v in profile_thresholds.items()
                    if not k.startswith("_")
                }
            profile_rules = profile_data.get("rules", [])
        except (OSError, ValueError, KeyError):
            profile_rules = None

    apply_industry_level(industry, gate_level, profile_thresholds)

    # 5. 返回初始化摘要
    return {
        "industry": industry,
        "gate_level": gate_level,
        "profile_path": profile_path,
        "profile_rules": profile_rules,
        "thresholds_applied": len(THRESHOLDS),
    }

# 架构分层关键词映射
LAYER_PATTERNS = {
    "domain": ["domain", "core", "entity", "model", "repository_interface"],
    "application": ["application", "service", "usecase", "use_case", "handler"],
    "infrastructure": ["infrastructure", "infra", "persistence", "database", "db", "http_client", "external"],
    "presentation": ["presentation", "controller", "api", "web", "ui", "rest", "graphql"],
}

# 安全红线模式
SECURITY_RED_FLAGS = [
    (r'(password|passwd|pwd|secret|api_key|apikey|token)\s*=\s*["\'][^"\']+["\']', "硬编码密钥/密码"),
    (r'execute\s*\(\s*["\'].*%\s*.*["\']', "SQL拼接风险"),
    (r'\.execute\s*\(\s*f["\']', "SQL注入风险(f-string)"),
    (r'\beval\s*\(', "eval() 调用风险"),  # v2.1.0: 词边界排除 net.eval() / getLogger（v2.0.14 首次修复）
    (r'\bexec\s*\(', "exec() 调用风险"),  # 同上
    (r'os\.system\s*\(', "os.system() 命令注入风险"),  # codeguard: ignore
    (r'subprocess\.call\s*\(\s*["\'].*\$', "subprocess 命令注入风险"),
    (r'\.debug\(.*password', "日志泄露密码"),
    (r'\.info\(.*token', "日志泄露token"),
]
