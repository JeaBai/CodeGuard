#!/usr/bin/env python3
"""iac_scan.py — IaC 安全与配额最小扫描器（iac-guardian v0.3.0-beta）

纯 Python 标准库实现，零第三方依赖。
检测 Terraform / Kubernetes YAML 中 AI 生成配置的高频高危模式。

退出码：0 = PASS / 1 = WARN / 2 = BLOCK
用法：python iac_scan.py --path . [--format text|json]

# codeguard: ignore GOLD_NO_PRINT_PRODUCTION
--------------------------------------------------------------------------
规则 ↔ 实证事故拦截链映射（来源：docs/skill-architecture-review.md §六）
--------------------------------------------------------------------------
规则 1  tf-public-s3-acl        → 事故 #1  Cloudflare 273K PDF 泄漏 (2025)
规则 2  tf-open-cidr            → 事故 #1  Cloudflare WAF 修复触发全网段开放
规则 3  tf-iam-wildcard         → 事故 #5  CyberArk Shai-Hulud 集群入侵 (2025)
规则 4  tf-db-no-prevent-destroy→ 事故 #3  PocketOS AI 9秒删库 (2026)
规则 4  tf-db-no-prevent-destroy→ 事故 #4  GitLab 2017 删库（五种备份全失效）
规则 5  tf-s3-no-logging        → 事故 #1  Cloudflare S3 审计日志缺失
规则 6  tf-kms-no-rotation      → 通用合规 KMS 密钥轮换最佳实践
规则 7  tf-iam-no-condition     → 事故 #5  IAM 缺条件键扩大攻击面
规则 8  k8s-rbac-wildcard       → 事故 #5  RBAC 通配符导致全权授予
规则 9  k8s-privileged          → 事故 #5  CyberArk Shai-Hulud 容器 root 提权
规则 10 k8s-host-network        → 事故 #5  宿主机网络共享导致横向移动
规则 11 k8s-latest-image        → 通用供应链 镜像不可追溯/不可回滚
规则 12 k8s-run-as-root         → 事故 #5  root 运行容器为攻击向量入口
规则 13 k8s-no-readonly-root    → 事故 #5  文件写入提权面未约束
规则 14 k8s-no-resource-limits  → 事故 #8  CNCF 过度配置超支 (2024)
规则 14 k8s-no-resource-limits  → D11 成本 超配 Pod 35%→10% 治理目标
--------------------------------------------------------------------------
缺口：事故 #2 Knight Capital (2012, $440M) — 8台部署漏1台
  防御建议 → governance-hub deploy-integrity 检视 (P1-2, Phase 2)
--------------------------------------------------------------------------"""
import argparse
import json
import re
import sys
from pathlib import Path

# v0.3.0: Windows GBK 编码兼容层
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding='utf-8', errors='replace')
    except (AttributeError, OSError):
        pass

TF_EXT = {'.tf'}
YAML_EXT = {'.yaml', '.yml'}
DOCKERFILE_NAMES = {'dockerfile', 'dockerfile.prod', 'dockerfile.dev', 'dockerfile.test'}
SKIP_DIRS = {'.git', 'node_modules', '.terraform', 'vendor', '__pycache__'}


def iter_files(root: Path):
    """遍历目标目录，产出 (相对路径, 文本内容)。"""
    for p in sorted(root.rglob('*')):
        if not p.is_file():
            continue
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        ext = p.suffix.lower()
        name_lower = p.name.lower()
        if ext not in TF_EXT and ext not in YAML_EXT and name_lower not in DOCKERFILE_NAMES:
            continue
        try:
            text = p.read_text(encoding='utf-8', errors='ignore')
        except OSError:
            continue
        yield str(p.relative_to(root)), ext, text


def add(issues, severity, rule, location, message, *, suggestion=''):
    path, line = location
    issues.append({
        'severity': severity, 'rule': rule, 'file': path, 'line': line,
        'message': message, 'suggestion': suggestion,
    })
