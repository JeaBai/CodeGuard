#!/usr/bin/env python3
"""
governance-hub P1-7 测试场景 6：无通告模板
模拟场景：无通知模板文件
期望：Q5 通告有达 → WARN（模板不存在时应警告）
"""

SCENARIO = {
    "name": "no_template",
    "description": "无通告模板 — 期望 Q5 WARN",
    "template_files": [],
    "expected": {
        "Q5": "warn",
        "reason": "模板不存在时应返回 WARN 确保干系人知晓"
    }
}
