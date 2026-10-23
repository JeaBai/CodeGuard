#!/usr/bin/env python3
"""
governance-hub P1-7 测试场景 5：纯非容器项目
模拟场景：项目无 K8s/IaC 配置（如纯前端/CLI 工具）
期望：Q4 成本有谱 → WARN（提示无法确认成本基线，而非静默 pass）
"""

SCENARIO = {
    "name": "no_k8s_config",
    "description": "无容器化定义 — 期望 Q4 WARN（非 pass）",
    "files": {},
    "expected": {
        "Q4": "warn",
        "reason": "未检测到容器化定义时应警告而非默认通过"
    }
}
