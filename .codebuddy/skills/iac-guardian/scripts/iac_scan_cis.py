"""CIS 扩展检测（Dockerfile / K8s / Terraform）。"""
from __future__ import annotations

import re

from iac_scan_core import add
from iac_scan_tf import _find_resource_body

# ── CIS 扩展检测函数 ──────────────────────────────────────────

def _scan_cis_docker(path, text, issues):
    """Dockerfile CIS 检测（3 条规则，补充 iac_scan_extended.scan_dockerfile）。"""
    lines = text.splitlines()

    # cis-docker: USER 声明检测 (行级)
    has_user = False
    last_cmd_is_from = False
    for line in lines:
        stripped = line.strip()
        if stripped.upper().startswith('FROM '):
            last_cmd_is_from = True
        if stripped.upper().startswith('USER '):
            has_user = True
            break
    if not has_user and any(
        l.strip().upper().startswith('CMD ') or l.strip().upper().startswith('ENTRYPOINT ')
        for l in lines
    ):
        add(issues, 'warn', 'docker-no-user', (path, 1),
            'Dockerfile 缺少 USER 指令，容器将以 root 运行',
            suggestion='在 COPY 后、ENTRYPOINT 前添加 USER <非root>')

    # cis-docker: FROM 基础镜像安全检查（带 digest）
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.upper().startswith('FROM ') and '@sha256:' not in stripped.lower():
            if any(tag in stripped for tag in [':latest', ':3', ':2', ':1', ':bullseye', ':slim']):
                add(issues, 'warn', 'docker-no-user', (path, i),
                    f'FROM 使用了非 pin 镜像标签: {stripped.split()[1] if len(stripped.split()) > 1 else stripped}',
                    suggestion='使用 image@sha256:... 固定基础镜像摘要')


def _scan_cis_k8s_yaml(path, text, issues):
    """CIS K8s Benchmark 扩展检测（追加到现有 scan_yaml 之后）。"""
    lines = text.splitlines()

    # 5.1.2 ServiceAccount automountServiceAccountToken
    if 'ServiceAccount' in text and 'automountServiceAccountToken' not in text:
        pass  # 保留原有检测

    # 5.2.3 allowPrivilegeEscalation（缺失 OR 值为 true 均触发 block）
    if re.search(r'securityContext:', text) and not re.search(r'allowPrivilegeEscalation\s*:\s*false', text):
        for i, line in enumerate(lines, 1):
            if 'securityContext:' in line:
                add(issues, 'block', 'cis-k8s-5.2.3', (path, i),
                    'securityContext 未声明 allowPrivilegeEscalation: false（缺失或为 true）',
                    suggestion='设置 allowPrivilegeEscalation: false')
                break

    # 5.2.2 hostPID/hostIPC
    if re.search(r'\bhostPID\s*:\s*true', text):
        add(issues, 'block', 'cis-k8s-5.2.2', (path, 1),
            'Pod spec 包含 hostPID: true，存在宿主机进程空间暴露风险',
            suggestion='移除 hostPID: true')

    # 5.2.5 seccompProfile
    if re.search(r'kind:\s*(Deployment|Pod|StatefulSet|DaemonSet)', text):
        if not re.search(r'seccompProfile', text):
            add(issues, 'warn', 'cis-k8s-5.2.5', (path, 1),
                '未设置 seccompProfile type: RuntimeDefault',
                suggestion='所有容器设置 seccompProfile: { type: RuntimeDefault }')

    # 5.1.5 anonymous auth (kubeconfig detection)
    if re.search(r'anonymous-auth\s*:\s*true|--anonymous-auth\s*=\s*true', text):
        add(issues, 'block', 'cis-k8s-5.1.5', (path, 1),
            'kube-apiserver/kubelet 启用了匿名认证',
            suggestion='设置 anonymous-auth=false')


def _scan_cis_terraform(path, text, issues):
    """CIS Terraform (AWS Foundations Benchmark) 扩展检测。"""
    # 2.1 CloudTrail multi-region
    for m in re.finditer(r'resource\s+"aws_cloudtrail"\s+"[^"]*"\s*\{', text):
        body = _find_resource_body(text, m.end())
        if 'is_multi_region_trail' not in body or 'enable_log_file_validation' not in body:
            line_no = text[:m.start()].count('\n') + 1
            add(issues, 'warn', 'cis-tf-2.1', (path, line_no),
                'aws_cloudtrail 未启用多区域或文件校验',
                suggestion='设置 is_multi_region_trail=true + enable_log_file_validation=true')

    # 3.1 VPC Flow Logs
    if re.search(r'resource\s+"aws_vpc"', text) and not re.search(r'resource\s+"aws_flow_log"', text):
        add(issues, 'warn', 'cis-tf-3.1', (path, 1),
            'VPC 未配置 Flow Logs',
            suggestion='创建 aws_flow_log 资源并定向到 CloudWatch Logs')

    # 4.2 S3 public access block
    if re.search(r'resource\s+"aws_s3_bucket"', text):
        if not re.search(r'aws_s3_bucket_public_access_block', text):
            add(issues, 'block', 'cis-tf-4.2', (path, 1),
                'S3 bucket 未配置 public_access_block 全量阻断',
                suggestion='附加 aws_s3_bucket_public_access_block 并设置全部阻断为 true')

    # 4.4 RDS publicly_accessible
    for m in re.finditer(r'resource\s+"aws_db_instance"\s+"[^"]*"\s*\{', text):
        body = _find_resource_body(text, m.end())
        if re.search(r'publicly_accessible\s*=\s*true', body):
            line_no = text[:m.start()].count('\n') + 1
            add(issues, 'block', 'cis-tf-4.4', (path, line_no),
                'aws_db_instance publicly_accessible = true',
                suggestion='设置 publicly_accessible = false')

    # 5.3 IMDSv2
    if re.search(r'resource\s+"aws_instance"', text):
        if not re.search(r'metadata_options\s*\{', text):
            add(issues, 'warn', 'cis-tf-5.3', (path, 1),
                'aws_instance 未强制使用 IMDSv2',
                suggestion='设置 metadata_options { http_tokens = "required" }')
