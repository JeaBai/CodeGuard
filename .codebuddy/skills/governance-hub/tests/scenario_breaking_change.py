#!/usr/bin/env python3
"""
governance-hub P1-7 测试场景 1：OpenAPI 破坏性变更
模拟场景：有 OpenAPI spec 变更 + breaking change 检测
期望：Q2 变更有界 → PASS（检测到变更且有破坏性评估）
"""

import json
import os

# 模拟 governance_check 所需的上下文
SCENARIO = {
    "name": "breaking_change",
    "description": "OpenAPI 存在 breaking change — 期望 Q2 PASS",
    "files": {
        "docs/openapi.yaml": {
            "changed": True,
            "breaking_changes": ["/users POST 移除了必填字段 email"],
        }
    },
    "expected": {
        "Q2": "pass",
        "reason": "检测到契约变更且有破坏性分析"
    }
}


def simulate():
    """生成场景报告"""
    print(f"[Scenario 1] {SCENARIO['description']}")
    print(f"  期望 Q2: {SCENARIO['expected']['Q2']}")


if __name__ == "__main__":
    simulate()
