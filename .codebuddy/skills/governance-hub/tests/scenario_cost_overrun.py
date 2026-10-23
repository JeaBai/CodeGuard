#!/usr/bin/env python3
"""
governance-hub P1-7 测试场景 3：成本基线偏差超限
模拟场景：有容器化定义但无 requests/limits → 成本失控
期望：Q4 成本有谱 → WARN（缺失 resource limits）
"""

SCENARIO = {
    "name": "cost_no_limits",
    "description": "K8s deployment 缺 resource limits — 期望 Q4 WARN",
    "files": {
        "deployment/k8s/production.yaml": {
            "changed": True,
            "has_requests": False,
            "has_limits": False,
        }
    },
    "expected": {
        "Q4": "warn",
        "reason": "容器存在但无配额声明 → 成本不可控"
    }
}
