#!/usr/bin/env python3
"""
Governance Hub Risk Gate (v1.0.0)
====================================
三级风险门禁系统 — 根据重构操作类型自动分类风险等级，
结合影响分析、文件锁、标签约束升级风险，控制 AI 执行流程。

门禁三层:
  🟢 auto_approve    — 低风险，自动执行
  🟡 confirm_required — 中风险，人话确认后执行
  🔴 manual_required  — 高风险，diff 预览后人工逐项确认

功能：
  classify_risk(action, file, function, blueprint)    分类风险等级
  check_gate(action, file, function, blueprint)       全量门禁检查（含升级规则）
  generate_confirmation(action, details)              生成人话确认消息
  generate_diff_preview(action, file, changes)        生成 diff 预览
  execute_with_gate(action, file, callback, ...)      带门禁的执行包装器

用法：
  python risk_gate.py --action check --type split_function --file src/auth/login.py --function login
  python risk_gate.py --action classify --type change_public_api --file src/auth/login.py
  python risk_gate.py --action confirm --type split_function --details "..."
  python risk_gate.py --action config --show

集成：
  - impact_analyzer: 影响分析件数 → 风险升级
  - tag_manager: 标签约束检查
  - intent_protection: 受保护文件 → 升级为 high
  - refactor_queue: 文件锁检查
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# ============================================================
# 常量
# ============================================================

_SCRIPT_DIR = Path(__file__).resolve().parent
_CONFIG_PATH = _SCRIPT_DIR / "risk_config.json"

_DEFAULT_ACTION_RISK = "medium"

_RISK_LEVELS = {"low": 1, "medium": 2, "high": 3}

_GATE_MAP = {"low": "auto", "medium": "confirm", "high": "manual"}


# ============================================================
# 工具函数
# ============================================================

def _log(msg: str) -> None:
    sys.stderr.write(f"[RiskGate] {msg}\n")
    sys.stderr.flush()


def _load_config() -> dict:
    if not _CONFIG_PATH.exists():
        return _default_config()
    try:
        return json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return _default_config()


def _save_config(data: dict) -> None:
    _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CONFIG_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _default_config() -> dict:
    return {
        "auto_approve": {
            "description": "🟢 低风险", "gate": "自动执行 → 跑测试 → 通过则合并",
            "rules": [{"action": "add_type_annotation", "risk": "low"},
                      {"action": "remove_unused_import", "risk": "low"}],
        },
        "confirm_required": {
            "description": "🟡 中风险", "gate": "人话说明 → 用户确认 → AI 执行 → 回检",
            "rules": [{"action": "split_function", "risk": "medium"}],
        },
        "manual_required": {
            "description": "🔴 高风险", "gate": "生成方案 → diff 预览 → 人工逐项确认",
            "rules": [{"action": "split_module", "risk": "high"}],
        },
        "escalation_rules": {
            "impact_count_threshold": {"from_low_to_medium": 3, "from_medium_to_high": 10},
            "protected_file": {"action": "escalate_to_high", "reason": "文件被 intent_protection 保护"},
            "locked_file": {"action": "reject", "reason": "文件被锁定"},
            "tag_forbidden": {"action": "reject", "reason_prefix": "标签禁止此操作"},
        },
    }


def _find_base_risk(action: str) -> str:
    """根据配置查找操作的基础风险等级。"""
    config = _load_config()
    for section in ("auto_approve", "confirm_required", "manual_required"):
        for rule in config.get(section, {}).get("rules", []):
            if rule.get("action") == action:
                return rule.get("risk", "medium")
    return _DEFAULT_ACTION_RISK
