#!/usr/bin/env python3
"""constraint_injector.py — IaC 安全约束注入器（iac-guardian v0.3.0-beta）

纯 Python 标准库实现，零第三方依赖。
在 AI 生成 Terraform / Kubernetes YAML / Dockerfile 之前，将安全规则转化为自然语言约束，
注入 AI prompt 上下文，降低 AI 生成高危配置的概率。

退出码：0 = 成功输出约束 / 1 = 无目标文件类型 / 2 = 参数错误
用法：python constraint_injector.py --target terraform|kubernetes|dockerfile|all [--format text|json]
"""
import argparse
import json
import sys
from pathlib import Path

# ── 约束知识库 ─────────────────────────────────────────────────

CONSTRAINTS = {
    'terraform': [
        {
            'id': 'C-IAC-001',
            'severity': 'MUST',
            'rule': 'S3 bucket ACL 默认私有',
            'constraint': (
                '禁止生成 `acl = "public-read"` 或 `acl = "public-read-write"`。'
                '所有 aws_s3_bucket 资源默认 private ACL，并附加 '
                'aws_s3_bucket_public_access_block 全量阻断公开访问。'
            ),
        },
        {
            'id': 'C-IAC-002',
            'severity': 'MUST',
            'rule': '安全组 ingress 限定最小网段',
            'constraint': (
                '禁止 ingress 规则使用 `cidr_blocks = ["0.0.0.0/0"]`。'
                'SSH(22)/RDP(3389)/数据库端口必须限定为具体 IP 或 VPC 网段。'
                '出口(egress)全开需显式注释原因。'
            ),
        },
        {
            'id': 'C-IAC-003',
            'severity': 'MUST',
            'rule': 'IAM 最小权限原则',
            'constraint': (
                '禁止 IAM policy 使用 `"Action": "*"` 或 `actions = ["*"]` 全权通配符。'
                '必须显式列举所需 Action 与限定 Resource ARN。'
                '附加 Condition 限制来源 IP/MFA/标签。'
            ),
        },
        {
            'id': 'C-IAC-004',
            'severity': 'MUST',
            'rule': '数据库 prevent_destroy 保护',
            'constraint': (
                '所有 aws_db_instance / aws_rds_cluster 资源必须包含 '
                'lifecycle { prevent_destroy = true }。'
                '删除数据库前需显式移除该保护——防止 AI 生成 terraform destroy 类事故。'
            ),
        },
        {
            'id': 'C-IAC-005',
            'severity': 'SHOULD',
            'rule': 'S3 访问日志启用',
            'constraint': (
                '每个 aws_s3_bucket 应附加 aws_s3_bucket_logging 记录所有访问事件。'
                '未启用日志的 S3 在 Cloudflare 273K PDF 泄漏中暴露审计盲区。'
            ),
        },
        {
            'id': 'C-IAC-006',
            'severity': 'SHOULD',
            'rule': 'KMS 密钥自动轮换',
            'constraint': (
                'aws_kms_key 资源应设置 enable_key_rotation = true，'
                '降低长期密钥泄漏的影响面。'
            ),
        },
    ],
    'kubernetes': [
        {
            'id': 'C-IAC-101',
            'severity': 'MUST',
            'rule': 'RBAC 最小权限',
            'constraint': (
                '禁止生成 `verbs: ["*"]` 或 `resources: ["*"]` 全权通配符的 Role/ClusterRole。'
                '必须显式列举所需 verbs 和 resources。禁止 apiGroups: ["*"]。'
            ),
        },
        {
            'id': 'C-IAC-102',
            'severity': 'MUST',
            'rule': '禁止特权容器',
            'constraint': (
                '禁止 `securityContext: { privileged: true }`。'
                '禁止 hostNetwork/hostPID/hostIPC。'
                'CyberArk Shai-Hulud 集群入侵根因即特权容器。'
            ),
        },
        {
            'id': 'C-IAC-103',
            'severity': 'MUST',
            'rule': '容器非 root 运行',
            'constraint': (
                '每个容器 securityContext 必须包含 `runAsNonRoot: true`。'
                '禁止以 UID 0 运行容器。'
            ),
        },
        {
            'id': 'C-IAC-104',
            'severity': 'MUST',
            'rule': '只读根文件系统',
            'constraint': (
                '每个容器 securityContext 必须包含 `readOnlyRootFilesystem: true`。'
                '必要写入路径通过 emptyDir volume 挂载。'
            ),
        },
        {
            'id': 'C-IAC-105',
            'severity': 'MUST',
            'rule': '固定镜像版本标签',
            'constraint': (
                '禁止使用 :latest 标签或无标签镜像。'
                '必须指定语义化版本（如 v1.2.3）或 SHA256 digest。'
                'latest 标签导致发布不可追溯、回滚不可靠。'
            ),
        },
        {
            'id': 'C-IAC-106',
            'severity': 'SHOULD',
            'rule': '声明资源配额',
            'constraint': (
                '每个容器必须声明 resources.requests 和 resources.limits。'
                'CNCF 调查显示 70% 超支源于未声明配额。'
                '默认上限：CPU ≤ 2 核、内存 ≤ 4Gi。'
            ),
        },
    ],
    'dockerfile': [
        {
            'id': 'C-IAC-201',
            'severity': 'MUST',
            'rule': '基础镜像指定 SHA256 digest',
            'constraint': (
                'FROM 必须使用 `image@sha256:...` 固定摘要而非标签。'
                '禁止 FROM ubuntu:latest、FROM python:3 不固定版本。'
                'Oracle/RedHat 供应链研究表明 59% 的容器漏洞来自过时基础镜像。'
            ),
        },
        {
            'id': 'C-IAC-202',
            'severity': 'MUST',
            'rule': '非 root 用户运行',
            'constraint': (
                'Dockerfile 必须包含 USER <非root> 指令。禁止以 root 用户运行容器进程。'
                '应在 COPY 后、ENTRYPOINT 前声明 USER。'
            ),
        },
        {
            'id': 'C-IAC-203',
            'severity': 'SHOULD',
            'rule': '多阶段构建最小镜像',
            'constraint': (
                '必须使用多阶段构建（FROM ... AS builder）分离编译环境和运行环境。'
                '最终镜像只包含运行时依赖，不包含编译器/toolchain。'
            ),
        },
        {
            'id': 'C-IAC-204',
            'severity': 'SHOULD',
            'rule': 'HEALTHCHECK 启用',
            'constraint': (
                '生产镜像必须声明 HEALTHCHECK 指令。'
                'Kubernetes liveness/readiness probe 配合容器层 HEALTHCHECK 双重保活。'
            ),
        },
        {
            'id': 'C-IAC-205',
            'severity': 'SHOULD',
            'rule': 'COPY 而非 ADD',
            'constraint': (
                '优先使用 COPY 而非 ADD。ADD 会自动解压 tar/远程 URL 拉取，'
                '引入不可控的供应链风险。仅解压本地 tar 的显式需求可用 ADD。'
            ),
        },
    ],
}


SCRIPT_DIR = Path(__file__).resolve().parent


def _load_tag_constraints() -> list[dict]:
    """v0.3.0: 从 governance-hub tag_definitions.json 读取活跃标签约束。

    搜索路径：
      1. 同目录 tag_definitions.json（governance-hub 脚本目录）
      2. ../../governance-hub/scripts/tag_definitions.json
      3. ../../../../governance-hub/scripts/tag_definitions.json

    Returns:
        活跃标签约束列表 [{"tag": str, "module": str, "constraint": str}]
    """
    _search_paths = [
        SCRIPT_DIR / "tag_definitions.json",
        SCRIPT_DIR.parent / "governance-hub" / "scripts" / "tag_definitions.json",
        SCRIPT_DIR.parents[3] / "governance-hub" / "scripts" / "tag_definitions.json",
    ]
    for _fp in _search_paths:
        if not _fp.exists():
            continue
        try:
            data = json.loads(_fp.read_text(encoding="utf-8"))
            results = []
            module_tags = data.get("module_tags", {})
            for tag_name, tag_def in module_tags.items():
                constraint_text = tag_def.get("ai_constraint", "")
                if constraint_text:
                    results.append({
                        "tag": tag_name,
                        "module": tag_def.get("description", ""),
                        "constraint": constraint_text,
                    })
            return results
        except (json.JSONDecodeError, OSError, KeyError):
            continue
    return []


def generate_constraints_text(target: str) -> str:
    """生成人类可读的约束文本。"""
    # v0.3.0: 注入 tag_manager 活跃标签约束
    tag_constraints = _load_tag_constraints()

    total = sum(len(v) for k, v in CONSTRAINTS.items() if target == 'all' or target == k)
    lines = ['# IaC 安全约束注入（iac-guardian v0.3.0-beta）',
             f'# 目标：{target.upper()}  约束数：{total}',
             '# 请在生成代码前阅读并遵守以下约束：', '']

    for category, rules in CONSTRAINTS.items():
        if target == 'all' or target == category:
            lines.append(f'## {category.upper()} 约束')
            lines.append('')
            for r in rules:
                lines.append(f'[{r["id"]}] ({r["severity"]}) {r["rule"]}')
                lines.append(f'    {r["constraint"]}')
                lines.append('')
            lines.append('')

    # v0.3.0: 附加 tag_manager 活跃标签约束
    if tag_constraints:
        lines.append('## 模块标签约束（来自 tag_manager）')
        lines.append('')
        for tc in tag_constraints:
            lines.append(f'[{tc["tag"]}] {tc["module"]}: {tc["constraint"]}')
        lines.append('')

    lines.append('# ── 约束注入完成。请基于以上规则生成代码。 ──')
    return '\n'.join(lines)


def generate_constraints_json(target: str) -> str:
    """生成结构化 JSON 约束输出。"""
    if target == 'all':
        rules = [r for v in CONSTRAINTS.values() for r in v]
    else:
        rules = CONSTRAINTS.get(target, [])
    return json.dumps({'generator': 'iac-guardian', 'version': '0.3.0-beta',
                       'target': target, 'constraints': rules}, ensure_ascii=False, indent=2)


def main():
    parser = argparse.ArgumentParser(description='iac-guardian 约束注入器')
    parser.add_argument('--target', choices=['terraform', 'kubernetes', 'dockerfile', 'all'],
                        default='all', help='目标 IaC 类型')
    parser.add_argument('--format', choices=['text', 'json'], default='text',
                        help='输出格式')
    parser.add_argument('-o', '--output', help='输出文件路径（默认 stdout）')
    args = parser.parse_args()

    if args.target not in CONSTRAINTS and args.target != 'all':
        print(f"错误：未知的目标类型 '{args.target}'。", file=sys.stderr)
        sys.exit(2)

    if args.format == 'json':
        output = generate_constraints_json(args.target)
    else:
        output = generate_constraints_text(args.target)

    if args.output:
        Path(args.output).write_text(output, encoding='utf-8')
    else:
        print(output)
    sys.exit(0)


# ============================================================
# v0.4.0: ConstraintInjectorBase 适配层（向后兼容）
# ============================================================

import os as _os
import sys as _sys

_SHARED_DIR = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "..", "..", "shared")
if _SHARED_DIR not in _sys.path:
    _sys.path.insert(0, _SHARED_DIR)

try:
    from constraint_injector_base import ConstraintInjectorBase

    class IacGuardianConstraintInjector(ConstraintInjectorBase):
        """iac-guardian约束注入器 — 继承ConstraintInjectorBase。

        复用现有的 CONSTRAINTS 知识库和 tag 约束加载逻辑。
        """

        def get_constraint_rules(self) -> list:
            """返回iac-guardian约束规则。"""
            rules = []
            for category, constraint_list in CONSTRAINTS.items():
                for c in constraint_list:
                    rules.append({
                        "severity": "critical" if c["severity"] == "MUST" else "medium",
                        "title": c["rule"],
                        "description": c["constraint"],
                        "id": c["id"],
                        "category": category,
                    })
            # 附加 tag 约束
            tag_constraints = _load_tag_constraints()
            for tc in tag_constraints:
                rules.append({
                    "severity": "medium",
                    "title": tc["tag"],
                    "description": tc["constraint"],
                    "category": "tag",
                })
            return rules

        def get_quality_gates(self) -> list:
            """返回iac-guardian质量门禁配置。"""
            return [
                {"name": "no_plaintext_secrets", "category": "security",
                 "pattern": r"(password|secret|token)\s*=\s*[\"'][^\"']+[\"']", "fail_on_match": True,
                 "description": "禁止明文密钥"},
                {"name": "no_wildcard_ingress", "category": "security",
                 "pattern": r"0\.0\.0\.0/0", "fail_on_match": True,
                 "description": "禁止0.0.0.0/0入站规则"},
                {"name": "no_wildcard_actions", "category": "security",
                 "pattern": r'"Action"\s*:\s*"\*"', "fail_on_match": True,
                 "description": "禁止IAM全权通配符"},
            ]

    def inject_constraints(context: dict) -> str:
        """便捷函数：构建约束提示词。"""
        injector = IacGuardianConstraintInjector()
        return injector.build_constraint_prompt(context)

    def check_quality(code: str) -> dict:
        """便捷函数：运行质量门禁检查。"""
        injector = IacGuardianConstraintInjector()
        return injector.run_all_gates(code)

except ImportError:
    pass  # constraint_injector_base 不可用时，保持原有函数式API


if __name__ == '__main__':
    main()
