#!/usr/bin/env python3
"""CodeGuard internal — 共享基础设施 (rules loader + path utils)

该模块消除 constraint_injector.py 与 quality_custom.py 之间
的规则加载逻辑重复（~40 行重复代码），并统一 JSON 加载错误处理。
"""

import json
from pathlib import Path
from typing import Any


RULES_FILE_NAMES = [
    '.code-guardian/rules.json',
    'rules.json',
    '.code-guardian.json',
]

# 统一结构化日志
def _log(msg: str) -> None:
    import sys
    print(f'[codeguard:rules] {msg}', file=sys.stderr)  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION


def resolve_rules_path(root: Path) -> Path | None:
    """在项目根目录查找规则文件。

    搜索优先级：
    1. .code-guardian/rules.json
    2. rules.json
    3. .code-guardian.json

    Returns:
        Path if found, None otherwise.
    """
    for name in RULES_FILE_NAMES:
        candidate = root / name
        if candidate.is_file():
            return candidate
    return None


def load_rules_json(root: Path) -> dict[str, Any]:
    """从项目根目录安全加载规则 JSON 文件。

    统一 constraint_injector.py 与 quality_custom.py 的加载逻辑，
    消除 40 行重复代码 + 统一异常处理。

    Args:
        root: 项目根目录 Path

    Returns:
        dict: 包含 rules, thresholds, ignorePatterns, ignoreFiles 等键。
        文件不存在或解析失败时返回空 dict。

    # codeguard: ignore GOLD_BARE_EXCEPT — 这是加载器，必须容错
    """
    path = resolve_rules_path(root)
    if path is None:
        return {}

    try:
        text = path.read_text(encoding='utf-8')
        data = json.loads(text)
    except FileNotFoundError:
        # 并发删除场景，罕见但可能
        return {}
    except json.JSONDecodeError:
        _log(f'规则文件 {path} JSON 格式错误，已跳过')
        return {}
    except OSError:
        _log(f'无法读取规则文件 {path}')
        return {}

    if not isinstance(data, dict):
        _log(f'规则文件 {path} 格式异常（期望 dict），已跳过')
        return {}

    return data


def check_legacy_rules_formats(root: Path) -> list[str]:
    """检查是否存在旧版 YAML/TOML 规则文件并给出迁移提示。

    Returns:
        旧版文件路径列表（供警告使用）
    """
    legacy = []
    for ext in ('.yaml', '.yml', '.toml'):
        for name in ['.code-guardian/rules', 'rules']:
            p = root / f'{name}{ext}'
            if p.exists():
                legacy.append(str(p))
    return legacy


# ============================================================
# v2.0: 声明式规则-检测器映射
# ============================================================

import re as _re


def load_rules(rules_file: str) -> list[dict]:
    """从JSON文件加载规则定义。

    规则格式:
    {
        "rules": [
            {
                "id": "MISRA-C-8.1",
                "title": "类型显式声明",
                "severity": "high",
                "dialect": "embedded",
                "category": "misra",
                "pattern": "...",
                "detector": "_check_misra_8_1",
                "description": "..."
            }
        ]
    }
    """
    from pathlib import Path as _Path
    p = _Path(rules_file)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding='utf-8'))
    except (json.JSONDecodeError, OSError):
        return []
    if isinstance(data, list):
        return data
    return data.get('rules', [])


def _apply_detector_rule(rule, file_path, content, findings):
    """应用 detector 类型规则，返回 True 表示已处理（无需再走 pattern）。"""
    detector_name = rule.get('detector')
    if not detector_name:
        return False
    dialect = rule.get('dialect', 'generic')
    category = rule.get('category', 'general')
    detectors = _get_detectors_by_name(dialect, category, detector_name)
    if not detectors:
        return False
    for det in detectors:
        try:
            det(file_path, content, findings)
        except Exception:
            pass
    return True


def _apply_pattern_rule(rule, file_path, content, findings):
    """应用 pattern 正则规则。"""
    pattern = rule.get('pattern')
    if not pattern:
        return
    matches = list(_re.finditer(pattern, content))
    for match in matches:
        lineno = content[:match.start()].count('\n') + 1
        findings.append({
            'rule_id': rule.get('id', 'unknown'),
            'severity': rule.get('severity', 'medium'),
            'message': rule.get('title', rule.get('description', '规则违规')),
            'location': f'{file_path}:{lineno}',
            'evidence': match.group(0),
            'description': rule.get('description', ''),
        })


def apply_rules(file_path: str, content: str, rules: list[dict]) -> list[dict]:
    """应用声明式规则到文件内容。

    对于每个规则:
    1. 如果规则指定了detector函数名，尝试从注册器获取并调用
    2. 如果规则只有pattern，使用正则匹配
    """
    findings = []
    for rule in rules:
        if _apply_detector_rule(rule, file_path, content, findings):
            continue
        _apply_pattern_rule(rule, file_path, content, findings)
    return findings


def _get_detectors_by_name(dialect: str, category: str, name: str) -> list:
    """从注册器中按函数名查找检测器。"""
    try:
        from detector_registry import get_detectors
        detectors = get_detectors(dialect, category)
        return [d for d in detectors if d.__name__ == name]
    except ImportError:
        return []


def get_rules_by_dialect(rules: list[dict], dialect: str) -> list[dict]:
    """按方言过滤规则。"""
    return [r for r in rules if r.get('dialect', 'generic') == dialect]


def get_rules_by_category(rules: list[dict], category: str) -> list[dict]:
    """按类别过滤规则。"""
    return [r for r in rules if r.get('category', 'general') == category]
