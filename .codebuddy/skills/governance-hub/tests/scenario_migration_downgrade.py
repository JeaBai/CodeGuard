#!/usr/bin/env python3
"""
governance-hub P1-7 测试场景 2：数据库 migration 有 downgrade 为空
模拟场景：有 migration 文件但 downgrade 为空 → 撤不回
期望：Q3 数据有悔 → WARN（downgrade 不完整）
"""

SCENARIO = {
    "name": "migration_empty_downgrade",
    "description": "migration downgrade 为空 — 期望 Q3 WARN",
    "files": {
        "migrations/20260727_add_users.py": {
            "changed": True,
            "has_downgrade": False,
        }
    },
    "expected": {
        "Q3": "warn",
        "reason": "migration 存在但回滚逻不完整"
    }
}
