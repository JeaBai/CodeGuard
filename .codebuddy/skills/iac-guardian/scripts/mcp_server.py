#!/usr/bin/env python3
"""iac-guardian MCP Server — JSON-RPC 2.0 over stdio (v3.0.0)

v0.3.0: 引入 _mcp_base.py 共享基类消除 JSON-RPC 协议重复代码。

MCP Tool:
  1. scan_iac          — 扫描指定路径 IaC 文件，返回安全与配额发现
  2. list_rules        — 列出全部 14 条活跃规则及级别
  3. inject_constraints — 生成 IaC 约束提示注入到 AI 上下文

MCP Resource:
  - iac://rules/default — 默认 IaC 规则集

用法: python mcp_server.py --project-root .
"""

import json
import os
import sys
from pathlib import Path
from typing import Any

# ── 路径设置 ──────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

_SHARED_DIR = SCRIPT_DIR.parent.parent.parent / "shared"
if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))

import iac_scan
from _mcp_base import MCPBaseServer

# ============================================================
# MCP 协议常量
# ============================================================

SERVER_NAME = "iac-guardian"
SERVER_VERSION = "3.0.0"
make_mcp_tool = MCPBaseServer.make_tool

# ============================================================
# MCP Tool Schema
# ============================================================

TOOLS = [
    make_mcp_tool(
        "scan_iac",
        "扫描指定目录中的 Terraform / Kubernetes YAML / Dockerfile 文件，检测安全漏洞与资源配额缺失。"
        "覆盖 50 条规则（14 核心 + 36 CIS K8s/Terraform 扩展）：公网暴露（S3/安全组/RDS）、RBAC 通配符、"
        "特权容器、资源配额、latest 镜像、CIS Kubernetes v1.7.0、CIS AWS Foundations。"
        "退出码：0=PASS / 1=WARN / 2=BLOCK。",
        {"path": {"type": "string", "description": "要扫描的目录路径", "default": "."}},
        ["path"],
    ),
    make_mcp_tool(
        "list_rules",
        "列出 iac-guardian 全部 50 条活跃安全规则（14 核心 + 36 CIS）。每条包含：规则 ID、严重性 (block/warn)、"
        "覆盖维度 (D8/D11/D12)、检测对象和实证事故引用。",
        {},
        [],
    ),
    make_mcp_tool(
        "inject_constraints",
        "生成 IaC 安全约束提示文本，用于注入到 AI 对话上下文。"
        "输出 8 条核心约束：禁止公开 ACL / 安全组全开 / RBAC 通配符 / 缺失配额 / latest 镜像 / 特权容器等。"
        "基于首因效应设计，在 AI 生成 IaC 代码前置入上下文。",
        {"format": {"type": "string", "enum": ["prompt", "checklist", "json"],
                    "description": "输出格式", "default": "checklist"}},
        [],
    ),
]

RESOURCES = [
    {"uri": "iac://rules/default", "name": "iac-guardian 规则集",
     "description": "全部 14 条 IaC 安全规则定义（含实证事故引用与修复指引）",
     "mimeType": "application/json"},
]

# ============================================================
# 14 条规则常量
# ============================================================

_IAC_RULES = [
    {"id": "tf-public-s3-acl", "severity": "block", "dimension": "D8", "description": "S3/OSS 对象存储禁止公开 ACL", "fix": "添加 public access block 配置"},
    {"id": "tf-open-cidr", "severity": "block", "dimension": "D8", "description": "安全组禁止对 0.0.0.0/0 开放非 80/443 端口", "fix": "限定 CIDR 或安全组来源"},
    {"id": "tf-iam-wildcard", "severity": "block", "dimension": "D8", "description": "IAM Policy 禁止 Action:* + Resource:* 组合", "fix": "按最小权限显式列举"},
    {"id": "tf-db-no-prevent-destroy", "severity": "warn", "dimension": "D8", "description": "数据库类资源必须 lifecycle prevent_destroy=true", "fix": "添加 lifecycle { prevent_destroy = true }"},
    {"id": "tf-s3-no-logging", "severity": "warn", "dimension": "D8", "description": "S3 存储桶必须启用访问日志与审计", "fix": "启用 logging 配置"},
    {"id": "tf-kms-no-rotation", "severity": "warn", "dimension": "D8", "description": "KMS 密钥必须启用自动轮换", "fix": "设置 enable_key_rotation = true"},
    {"id": "tf-iam-no-condition", "severity": "warn", "dimension": "D8", "description": "IAM Policy 缺少条件键限定", "fix": "添加 Condition 块限定访问来源"},
    {"id": "k8s-rbac-wildcard", "severity": "block", "dimension": "D8", "description": "RBAC 禁止 * 通配 verbs/resources", "fix": "按最小权限显式列举"},
    {"id": "k8s-privileged", "severity": "block", "dimension": "D8", "description": "禁止 privileged: true 特权容器", "fix": "移除 privileged: true"},
    {"id": "k8s-host-network", "severity": "warn", "dimension": "D8", "description": "禁止 hostNetwork: true 宿主机网络", "fix": "移除 hostNetwork 配置"},
    {"id": "k8s-latest-image", "severity": "warn", "dimension": "D8", "description": "禁止使用 :latest 或无标签镜像", "fix": "使用具体版本号标签"},
    {"id": "k8s-run-as-root", "severity": "warn", "dimension": "D8", "description": "容器必须以非 root 用户运行", "fix": "设置 runAsNonRoot: true"},
    {"id": "k8s-no-readonly-root", "severity": "block", "dimension": "D8", "description": "securityContext 必须声明 readOnlyRootFilesystem", "fix": "设置 readOnlyRootFilesystem: true"},
    {"id": "k8s-no-resource-limits", "severity": "warn", "dimension": "D11", "description": "容器必须声明 resources.requests/limits", "fix": "为每个容器添加 resources 声明"},
    # CIS K8s Benchmark v1.7.0 (18 条)
    {"id": "cis-k8s-5.1.1", "severity": "block", "dimension": "D8", "description": "ClusterRoleBinding cluster-admin 审计", "fix": "移除非必要 cluster-admin 绑定", "citation": "CIS K8s v1.7.0 §5.1.1"},
    {"id": "cis-k8s-5.1.2", "severity": "block", "dimension": "D8", "description": "ServiceAccount 禁止自动挂载 Token", "fix": "automountServiceAccountToken: false", "citation": "CIS K8s v1.7.0 §5.1.2"},
    {"id": "cis-k8s-5.1.3", "severity": "warn", "dimension": "D8", "description": "禁止使用 default ServiceAccount", "fix": "创建专用 ServiceAccount", "citation": "CIS K8s v1.7.0 §5.1.3"},
    {"id": "cis-k8s-5.1.4", "severity": "warn", "dimension": "D8", "description": "ClusterRoleBinding 过多，建议命名空间级 RoleBinding", "fix": "迁移到 RoleBinding", "citation": "CIS K8s v1.7.0 §5.1.4"},
    {"id": "cis-k8s-5.1.5", "severity": "block", "dimension": "D8", "description": "未禁用匿名认证", "fix": "anonymous-auth=false", "citation": "CIS K8s v1.7.0 §5.1.5"},
    {"id": "cis-k8s-5.1.6", "severity": "block", "dimension": "D8", "description": "kube-apiserver insecure-port 未禁用", "fix": "insecure-port=0", "citation": "CIS K8s v1.7.0 §5.1.6"},
    {"id": "cis-k8s-5.2.1", "severity": "block", "dimension": "D8", "description": "未实施 Pod Security Standards restricted", "fix": "Pod Security Admission enforce: restricted", "citation": "CIS K8s v1.7.0 §5.2.1"},
    {"id": "cis-k8s-5.2.2", "severity": "block", "dimension": "D8", "description": "Pod 包含 hostPID/hostIPC", "fix": "移除 hostPID/hostIPC", "citation": "CIS K8s v1.7.0 §5.2.2"},
    {"id": "cis-k8s-5.2.3", "severity": "block", "dimension": "D8", "description": "未设置 allowPrivilegeEscalation: false", "fix": "设置 allowPrivilegeEscalation: false", "citation": "CIS K8s v1.7.0 §5.2.3"},
    {"id": "cis-k8s-5.2.4", "severity": "warn", "dimension": "D8", "description": "添加高危 Linux capability", "fix": "仅保留最小 capabilities 集合", "citation": "CIS K8s v1.7.0 §5.2.4"},
    {"id": "cis-k8s-5.2.5", "severity": "warn", "dimension": "D8", "description": "未设置 seccompProfile RuntimeDefault", "fix": "seccompProfile: { type: RuntimeDefault }", "citation": "CIS K8s v1.7.0 §5.2.5"},
    {"id": "cis-k8s-5.2.6", "severity": "warn", "dimension": "D8", "description": "未配置 AppArmor/seccompProfile", "fix": "配置 AppArmor 注解", "citation": "CIS K8s v1.7.0 §5.2.6"},
    {"id": "cis-k8s-5.3.1", "severity": "warn", "dimension": "D8", "description": "命名空间未配置默认拒绝 NetworkPolicy", "fix": "创建默认拒绝 NetworkPolicy", "citation": "CIS K8s v1.7.0 §5.3.1"},
    {"id": "cis-k8s-5.3.2", "severity": "warn", "dimension": "D8", "description": "存在无 NetworkPolicy 的命名空间", "fix": "为每个命名空间创建 NetworkPolicy", "citation": "CIS K8s v1.7.0 §5.3.2"},
    {"id": "cis-k8s-5.4.1", "severity": "block", "dimension": "D8", "description": "Secret 含 Base64 明文密钥", "fix": "使用外部密钥管理", "citation": "CIS K8s v1.7.0 §5.4.1"},
    {"id": "cis-k8s-5.4.2", "severity": "warn", "dimension": "D8", "description": "etcd 未配置静态加密", "fix": "启用 etcd encryption at rest", "citation": "CIS K8s v1.7.0 §5.4.2"},
    {"id": "cis-k8s-5.5.1", "severity": "warn", "dimension": "D8", "description": "未配置 ImagePolicyWebhook", "fix": "启用镜像签名验证准入控制", "citation": "CIS K8s v1.7.0 §5.5.1"},
    {"id": "cis-k8s-5.6.1", "severity": "warn", "dimension": "D11", "description": "命名空间未设置 ResourceQuota", "fix": "创建 ResourceQuota 限制 cpu/memory", "citation": "CIS K8s v1.7.0 §5.6.1"},
    # CIS Amazon Web Services Foundations (18 条)
    {"id": "cis-tf-1.1", "severity": "block", "dimension": "D8", "description": "IAM 根账户存在 AccessKey", "fix": "删除根账户 AccessKey", "citation": "CIS AWS Foundations §1.1"},
    {"id": "cis-tf-1.2", "severity": "block", "dimension": "D8", "description": "IAM 用户未强制 MFA", "fix": "所有 IAM 用户强制 MFA 或 SSO", "citation": "CIS AWS Foundations §1.2"},
    {"id": "cis-tf-1.3", "severity": "warn", "dimension": "D8", "description": "使用 IAM AccessKey 而非角色", "fix": "迁移到 IAM Role + STS AssumeRole", "citation": "CIS AWS Foundations §1.3"},
    {"id": "cis-tf-2.1", "severity": "block", "dimension": "D8", "description": "CloudTrail 未全地域启用", "fix": "is_multi_region_trail=true", "citation": "CIS AWS Foundations §2.1"},
    {"id": "cis-tf-2.2", "severity": "block", "dimension": "D8", "description": "CloudTrail 未启用 KMS SSE", "fix": "配置 kms_key_id", "citation": "CIS AWS Foundations §2.2"},
    {"id": "cis-tf-3.1", "severity": "block", "dimension": "D8", "description": "VPC 未启用 Flow Logs", "fix": "创建 aws_flow_log", "citation": "CIS AWS Foundations §3.1"},
    {"id": "cis-tf-3.2", "severity": "warn", "dimension": "D8", "description": "default Security Group 入站全开", "fix": "删除 default SG 入站规则", "citation": "CIS AWS Foundations §3.2"},
    {"id": "cis-tf-4.1", "severity": "block", "dimension": "D8", "description": "S3 bucket 未启用 SSE 加密", "fix": "配置 server_side_encryption", "citation": "CIS AWS Foundations §4.1"},
    {"id": "cis-tf-4.2", "severity": "block", "dimension": "D8", "description": "S3 未配置 public_access_block 全量阻断", "fix": "附加 public_access_block", "citation": "CIS AWS Foundations §4.2"},
    {"id": "cis-tf-4.3", "severity": "block", "dimension": "D8", "description": "RDS 未启用 StorageEncrypted", "fix": "storage_encrypted=true", "citation": "CIS AWS Foundations §4.3"},
    {"id": "cis-tf-4.4", "severity": "block", "dimension": "D8", "description": "RDS publicly_accessible=true", "fix": "publicly_accessible=false", "citation": "CIS AWS Foundations §4.4"},
    {"id": "cis-tf-4.5", "severity": "warn", "dimension": "D8", "description": "RDS 未启用 deletion_protection", "fix": "deletion_protection=true", "citation": "CIS AWS Foundations §4.5"},
    {"id": "cis-tf-5.1", "severity": "block", "dimension": "D8", "description": "EBS 未启用 encrypted", "fix": "encrypted=true", "citation": "CIS AWS Foundations §5.1"},
    {"id": "cis-tf-5.2", "severity": "warn", "dimension": "D8", "description": "EBS 快照可公开访问", "fix": "移除公开权限", "citation": "CIS AWS Foundations §5.2"},
    {"id": "cis-tf-5.3", "severity": "warn", "dimension": "D8", "description": "EC2 未强制 IMDSv2", "fix": "metadata_options http_tokens=required", "citation": "CIS AWS Foundations §5.3"},
    {"id": "cis-tf-5.4", "severity": "block", "dimension": "D8", "description": "EC2 自动分配 public IP", "fix": "associate_public_ip_address=false", "citation": "CIS AWS Foundations §5.4"},
    {"id": "cis-tf-5.5", "severity": "warn", "dimension": "D12", "description": "未启用 GuardDuty", "fix": "创建 aws_guardduty_detector", "citation": "CIS AWS Foundations §5.5"},
    {"id": "cis-tf-5.6", "severity": "warn", "dimension": "D12", "description": "未启用 Security Hub", "fix": "创建 aws_securityhub_account", "citation": "CIS AWS Foundations §5.6"},
]

_IAC_CONSTRAINTS = """IaC 安全约束（生成前注入）：
1. S3/OSS 对象存储禁止公开 ACL；必须附加 public access block
2. 安全组 ingress 禁止对 0.0.0.0/0 开放非 80/443 端口；22/3389/数据库端口必须限定 CIDR
3. RBAC 禁止 * 通配 verbs/resources/apiGroups；按最小权限显式列举
4. IAM Policy 禁止 Action:* + Resource:* 组合
5. 每个容器必须声明 resources.requests 与 resources.limits（成本与调度前提）
6. 数据库类资源必须 lifecycle { prevent_destroy = true }
7. 容器必须 runAsNonRoot、禁止 privileged: true、镜像禁止 latest 标签
8. 所有资源必须携带 team/cost-center/env 成本标签"""

# ============================================================
# Tool 处理器
# ============================================================

def handle_scan_iac(params: dict) -> dict:
    """扫描 IaC 目录。"""
    scan_path = params.get("path", ".")
    issues, exit_code, summary = iac_scan.scan_directory(scan_path)
    return {
        "exit_code": exit_code,
        "summary": summary,
        "issues": issues,
        "verdict": "BLOCK" if exit_code == 2 else ("WARN" if exit_code == 1 else "PASS"),
    }


def handle_list_rules(params: dict) -> dict:
    """列出全部规则。"""
    return {"total_rules": len(_IAC_RULES), "rules": _IAC_RULES}


def handle_inject_constraints(params: dict) -> dict:
    """生成 IaC 约束注入文本。"""
    fmt = params.get("format", "checklist")
    if fmt == "prompt":
        content = _IAC_CONSTRAINTS
    elif fmt == "json":
        content = json.dumps({"constraints": _IAC_CONSTRAINTS.split("\n"), "rules": _IAC_RULES}, ensure_ascii=False, indent=2)
    else:
        checklist_lines = ["IaC 安全自检清单（生成前逐项确认）："]
        for r in _IAC_RULES:
            icon = "❌" if r["severity"] == "block" else "⚠️"
            checklist_lines.append(f"- [{icon}] {r['description']} → {r['fix']}")
        content = "\n".join(checklist_lines)
    return {"format": fmt, "content": content, "rules_count": len(_IAC_RULES)}


def handle_resource_read(uri: str) -> Any:
    """读取 MCP Resource。"""
    if uri == "iac://rules/default":
        return {"contents": [{"uri": uri, "mimeType": "application/json",
                "text": json.dumps({"rules": _IAC_RULES}, ensure_ascii=False, indent=2)}]}
    return MCPBaseServer.create_error(None, -32602, f"Unknown resource: {uri}")  # codeguard: ignore GOLD_NO_MAGIC_NUMBER


# ============================================================
# 启动
# ============================================================

def main():
    server = MCPBaseServer(
        name=SERVER_NAME,
        version=SERVER_VERSION,
        tools=TOOLS,
        resources=RESOURCES,
        tool_handlers={
            "scan_iac": handle_scan_iac,
            "list_rules": handle_list_rules,
            "inject_constraints": handle_inject_constraints,
        },
        resource_handler=handle_resource_read,
    )
    server.run_stdio()


if __name__ == "__main__":
    main()
