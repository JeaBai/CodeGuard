#!/usr/bin/env python3
"""
governance-hub P1-7 测试场景 4：全通过（干净仓库 + 完整治理资产）
模拟场景：所有治理维度完备 → 期望全 PASS
期望：
  Q1: pass（有需求关联）
  Q2: pass（无 breaking change）
  Q3: pass（migration 有完整 downgrade）
  Q4: pass（容器有配额声明）
  Q5: pass（通告模板就绪）
"""

SCENARIO = {
    "name": "all_pass",
    "description": "完整治理资产 — 期望全 PASS",
    "files": {
        "docs/openapi.yaml": {
            "changed": True,
            "breaking_changes": [],
        },
        "migrations/20260727_add_users.py": {
            "changed": True,
            "has_downgrade": True,
        },
        "deployment/k8s/production.yaml": {
            "changed": True,
            "has_requests": True,
            "has_limits": True,
        },
        "notifications/release.md": {
            "exists": True,
        }
    },
    "expected": {
        "Q1": "pass", "Q2": "pass", "Q3": "pass",
        "Q4": "pass", "Q5": "pass"
    }
}
