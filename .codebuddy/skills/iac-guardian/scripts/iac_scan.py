#!/usr/bin/env python3
"""iac_scan.py — IaC 安全与配额最小扫描器（facade 入口，向后兼容）。

实现已拆分至 iac_scan_core / iac_scan_tf / iac_scan_k8s / iac_scan_cis。
退出码：0 = PASS / 1 = WARN / 2 = BLOCK
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from iac_scan_core import (
    TF_EXT,
    YAML_EXT,
    DOCKERFILE_NAMES,
    SKIP_DIRS,
    iter_files,
    add,
)
from iac_scan_tf import scan_tf
from iac_scan_k8s import scan_yaml
from iac_scan_cis import _scan_cis_docker, _scan_cis_k8s_yaml, _scan_cis_terraform

# ---------------- 主流程 ----------------

def scan_directory(root_path: str | Path) -> tuple:
    """扫描目录返回 (issues, exit_code, summary) — MCP/外部导入入口。

    Args:
        root_path: 扫描目标目录

    Returns:
        (issues: list[dict], exit_code: int, summary: dict)
    """
    root = Path(root_path).resolve()
    if not root.exists():
        return [], 0, {"total": 0, "blocks": 0, "warnings": 0, "error": f"路径不存在: {root}"}

    issues = []
    for rel, ext, text in iter_files(root):
        name_lower = Path(rel).name.lower()
        if name_lower in DOCKERFILE_NAMES:
            _scan_cis_docker(rel, text, issues)
        elif ext in TF_EXT:
            scan_tf(rel, text, issues)
            _scan_cis_terraform(rel, text, issues)
        else:
            scan_yaml(rel, text, issues)
            _scan_cis_k8s_yaml(rel, text, issues)

    # P8: Dockerfile 扫描（独立遍历）
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        if p.name.lower() == "dockerfile" or p.name.lower().startswith("dockerfile."):
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
                rel = str(p.relative_to(root))
                try:
                    import iac_scan_extended  # noqa: F401
                    iac_scan_extended.scan_dockerfile(rel, text, issues)
                except ImportError:  # codeguard: ignore GOLD_NO_EMPTY_EXCEPT
                    pass
            except OSError:
                continue

    for it in issues:
        it['dimension'] = _DIMENSION_MAP.get(it.get('rule', ''), 'D8')

    blocks = [i for i in issues if i['severity'] == 'block']
    warns = [i for i in issues if i['severity'] == 'warn']
    exit_code = 2 if blocks else (1 if warns else 0)

    return issues, exit_code, {"total": len(issues), "blocks": len(blocks), "warnings": len(warns)}


# ── D11 维度标记映射 ─────────────────────────────────────────
_DIMENSION_MAP = {
    'tf-public-s3-acl': 'D8',
    'tf-open-cidr': 'D8',
    'tf-iam-wildcard': 'D8',
    'tf-db-no-prevent-destroy': 'D8',
    'tf-s3-no-logging': 'D8',
    'tf-kms-no-rotation': 'D8',
    'tf-iam-no-condition': 'D8',
    'k8s-rbac-wildcard': 'D8',
    'k8s-privileged': 'D8',
    'k8s-host-network': 'D8',
    'k8s-latest-image': 'D8',
    'k8s-run-as-root': 'D8',
    'k8s-no-readonly-root': 'D8',
    'k8s-no-resource-limits': 'D11',
    # P8 扩展规则
    'k8s-no-network-policy': 'D8',
    'k8s-no-seccomp': 'D8',
    'docker-no-healthcheck': 'D8',
    'docker-no-user': 'D8',
    'docker-copy-vs-add': 'D8',
    'tf-rds-no-encryption': 'D8',
    'tf-s3-no-versioning': 'D8',
    'tf-ec2-no-imdsv2': 'D8',
    'generic-env-leak': 'D8',
    # CIS K8s Benchmark v1.7.0
    'cis-k8s-5.1.1': 'D8', 'cis-k8s-5.1.2': 'D8', 'cis-k8s-5.1.3': 'D8',
    'cis-k8s-5.1.4': 'D8', 'cis-k8s-5.1.5': 'D8', 'cis-k8s-5.1.6': 'D8',
    'cis-k8s-5.2.1': 'D8', 'cis-k8s-5.2.2': 'D8', 'cis-k8s-5.2.3': 'D8',
    'cis-k8s-5.2.4': 'D8', 'cis-k8s-5.2.5': 'D8', 'cis-k8s-5.2.6': 'D8',
    'cis-k8s-5.3.1': 'D8', 'cis-k8s-5.3.2': 'D8', 'cis-k8s-5.4.1': 'D8',
    'cis-k8s-5.4.2': 'D8', 'cis-k8s-5.5.1': 'D8', 'cis-k8s-5.6.1': 'D11',
    # CIS Terraform (AWS Foundations Benchmark)
    'cis-tf-1.1': 'D8', 'cis-tf-1.2': 'D8', 'cis-tf-1.3': 'D8',
    'cis-tf-2.1': 'D8', 'cis-tf-2.2': 'D8', 'cis-tf-3.1': 'D8',
    'cis-tf-3.2': 'D8', 'cis-tf-4.1': 'D8', 'cis-tf-4.2': 'D8',
    'cis-tf-4.3': 'D8', 'cis-tf-4.4': 'D8', 'cis-tf-4.5': 'D8',
    'cis-tf-5.1': 'D8', 'cis-tf-5.2': 'D8', 'cis-tf-5.3': 'D8',
    'cis-tf-5.4': 'D8', 'cis-tf-5.5': 'D12', 'cis-tf-5.6': 'D12',
}


def main():
    ap = argparse.ArgumentParser(description='IaC 安全与配额最小扫描器（纯标准库）')
    ap.add_argument('--path', default='.', help='扫描根目录（默认当前目录）')
    ap.add_argument('--format', choices=['text', 'json', 'bridge'], default='text',
                    help='输出格式（bridge 为 governance-hub 消费的标准 JSON）')
    ap.add_argument('--bridge', action='store_true',
                    help='输出 governance-hub 兼容桥接 JSON（等价 --format bridge）')
    ap.add_argument('--output', '-o', default=None,
                    help='桥接 JSON 输出文件路径（ --bridge 模式下可选）')
    args = ap.parse_args()

    if args.bridge:
        args.format = 'bridge'

    issues, exit_code, summary = scan_directory(args.path)
    blocks_count = summary["blocks"]
    warns_count = summary["warnings"]

    # v0.3.0: 未发现 IaC 文件时输出 na 提示
    if summary["total"] == 0:
        payload = {"files_scanned": 0, "verdict": "na",
                   "message": "未发现 IaC 文件（.tf/.yaml/Dockerfile），跳过扫描"}
        if args.format in ("json", "bridge"):
            print(json.dumps(payload, ensure_ascii=False, indent=2))  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
        else:
            print("未发现 IaC 文件 — 跳过扫描")  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
        sys.exit(0)
    blocks = [i for i in issues if i['severity'] == 'block']
    warns = [i for i in issues if i['severity'] == 'warn']

    if args.format == 'bridge':
        from datetime import datetime, timezone
        bridge = {
            'source': 'iac-guardian',
            'version': '0.3.0-beta',
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'exit_code': exit_code,
            'summary': {
                'total': len(issues),
                'blocks': len(blocks),
                'warnings': len(warns),
            },
            'dimension_summary': {
                'D8': len([i for i in issues if i.get('dimension') == 'D8']),
                'D11': len([i for i in issues if i.get('dimension') == 'D11']),
            },
            'findings': issues,
        }
        payload = json.dumps(bridge, ensure_ascii=False, indent=2)
        if args.output:
            Path(args.output).write_text(payload, encoding='utf-8')
            print(f'桥接 JSON 已写入 {args.output}', file=sys.stderr)  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
        else:
            print(payload)  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
    elif args.format == 'json':
        print(json.dumps({  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
            'exit_code': exit_code,
            'summary': {'total': len(issues), 'blocks': len(blocks), 'warnings': len(warns)},
            'issues': issues,
        }, ensure_ascii=False, indent=2))
    else:
        for it in issues:
            print(f"[{it['severity'].upper():5}] {it['rule']} {it['file']}:{it['line']}")  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
            print(f"        {it['message']}")  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
            print(f"        修复: {it['suggestion']}")  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
            sys.stdout.flush()
        print(f'\n扫描完成: {len(blocks)} BLOCK / {len(warns)} WARN → 退出码 {exit_code}')  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
        sys.stdout.flush()

    sys.exit(exit_code)


if __name__ == '__main__':
    main()
