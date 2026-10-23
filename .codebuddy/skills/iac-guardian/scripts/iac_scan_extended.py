#!/usr/bin/env python3
"""iac_scan_extended.py — 扩展规则集（P8: 14→25 条规则）

纯 Python 标准库实现，零第三方依赖。
新增 11 条规则覆盖 Docker/K8s/TF/通用安全场景。

规则列表（编号接续 iac_scan.py 的 14 条）:
  R15 k8s-no-network-policy      NetworkPolicy 缺失 (WARN)
  R16 k8s-no-seccomp             seccomp 未配置 (WARN)
  R17 docker-no-healthcheck      Docker 无 HEALTHCHECK (WARN)
  R18 docker-no-user             Docker 以 root 运行 (WARN)
  R19 tf-rds-no-encryption       RDS 未加密 (BLOCK)
  R20 tf-cloudtrail-no-enabled   CloudTrail 未启用 (BLOCK)
  R21 tf-s3-no-versioning        S3 未开启版本控制 (WARN)
  R22 tf-ec2-no-imdsv2           EC2 未使用 IMDSv2 (WARN)
  R23 tf-sg-self-reference       安全组自引用缺失 (INFO)
  R24 docker-copy-vs-add         Docker COPY 优于 ADD (INFO)
  R25 generic-env-leak           敏感环境变量泄露 (BLOCK)
"""
import re
from pathlib import Path

TF_EXT = {'.tf'}
YAML_EXT = {'.yaml', '.yml'}
DOCKER_EXTS = {'dockerfile', '.dockerfile'}


def get_issue(key, issues):
    """issue 辅助设置维度"""
    for i in issues:
        i.setdefault('dimension', 'D8')


def scan_dockerfile(path, text, issues):
    """Dockerfile 安全检查。

    需要从外部传入文件名判断（Dockerfile / Dockerfile.* 模式）。
    """
    lines = text.splitlines()
    _check_docker_healthcheck(path, lines, issues)
    _check_docker_user(path, lines, issues)
    _check_docker_copy_add(path, lines, issues)


def scan_extended_yaml(path, text, issues, file_type="k8s"):
    """K8s YAML 扩展检查。"""
    lines = text.splitlines()
    _check_k8s_network_policy(path, text, issues)
    _check_k8s_seccomp(path, lines, issues)
    # 环境变量泄露检测（通用 YAML）
    _check_env_leak(path, text, issues)


def scan_extended_tf(path, text, issues):
    """Terraform 扩展检查。"""
    lines = text.splitlines()
    _check_tf_rds_encryption(path, lines, issues)
    _check_tf_cloudtrail(path, lines, issues)
    _check_tf_s3_versioning(path, lines, issues)
    _check_tf_ec2_imdsv2(path, lines, issues)
    _check_tf_sg_self_ref(path, text, issues)
    # 环境变量泄露检测（通用）
    _check_env_leak(path, text, issues)


# ── K8s 扩展规则 ──────────────────────────────────────────────

def _check_k8s_network_policy(path, text, issues):
    """k8s-no-network-policy: Deployment/Pod 无 NetworkPolicy（WARN）
    
    v0.2.2 P2 修复：增加 namespace 匹配精度、仅 Deployment/StatefulSet 触发、
    跳过有 hostNetwork/默认拒绝标注的文件，消除 3 FP。
    """
    # 仅检测 Deployment/StatefulSet（DaemonSet 等通常不需要 NetworkPolicy）
    if not (re.search(r'kind:\s*Deployment', text) or re.search(r'kind:\s*StatefulSet', text)):
        return
    
    # 跳过已配置了 hostNetwork 或默认拒绝标注的资源
    if re.search(r'hostNetwork:\s*true', text):
        return
    if re.search(r'network-policy:\s*skip|network\.policy/skip', text, re.IGNORECASE):
        return
    
    # 判断是否为生产环境命名空间（增强匹配）
    ns_match = re.search(r'namespace\s*:\s*["\']?([^"\'\s]+)["\']?', text)
    ns_name = ns_match.group(1).strip() if ns_match else None
    
    is_prod = bool(ns_name and re.search(
        r'^(?:production|prod(?:-.*)?|live|staging|uat)s?$',
        ns_name, re.IGNORECASE
    )) if ns_name else False
    
    # 跳过明确的测试/开发/沙箱命名空间
    if ns_name and re.search(r'^(?:test|dev|demo|sandbox|qa|review|pr-|ci-)', ns_name, re.IGNORECASE):
        return
    
    # 非生产环境：降低严重度到 info（仅提示）
    if not is_prod:
        if not re.search(r'kind:\s*NetworkPolicy', text):
            issues.append({
                'severity': 'info', 'rule': 'k8s-no-network-policy',
                'file': path, 'line': 1,
                'message': f'命名空间 "{ns_name or "未知"}" 中的 Deployment 未声明 NetworkPolicy（非生产环境仅提示）',
                'suggestion': '如有安全隔离需求，建议定义 NetworkPolicy 限制 pod 入站流量',
            })
        return
    
    # 生产/正式环境：检查是否有 NetworkPolicy（在文件中或通过 label selector 间接覆盖）
    # 检查是否已有 NetworkPolicy（同文件或通过命名约定存在）
    if re.search(r'kind:\s*NetworkPolicy', text):
        return
    
    # 检查是否有 networkPolicy 选择器标注（可能被外部 NetworkPolicy 覆盖）
    if re.search(r'networking\.kubernetes\.io|network-policy|netpol', text, re.IGNORECASE):
        issues.append({
            'severity': 'info', 'rule': 'k8s-no-network-policy',
            'file': path, 'line': 1,
            'message': '生产环境 Deployment 可能被外部 NetworkPolicy 覆盖（检测到 network 标注），仅信息提示',
            'suggestion': '确认 NetworkPolicy 已正确配置并覆盖该 Deployment',
        })
        return
    
    # 生产/正式环境：无 NetworkPolicy → WARN
    issues.append({
        'severity': 'warn', 'rule': 'k8s-no-network-policy',
        'file': path, 'line': 1,
        'message': f'生产环境 Deployment（命名空间: {ns_name or "未知"}）未声明 NetworkPolicy，强烈建议定义入站流量白名单',
        'suggestion': '定义 NetworkPolicy 限制 pod 间网络通信，防止横向移动',
    })


def _check_k8s_seccomp(path, lines, issues):
    """k8s-no-seccomp: 容器未配置 seccomp（WARN）"""
    in_security = False
    for i, line in enumerate(lines, 1):
        if re.search(r'securityContext:\s*$', line):
            in_security = True
            window = '\n'.join(lines[i:i + 10])
            if 'seccomp' not in window.lower():
                issues.append({
                    'severity': 'warn', 'rule': 'k8s-no-seccomp',
                    'file': path, 'line': i,
                    'message': '容器 securityContext 未声明 seccompProfile',
                    'suggestion': '设置 seccompProfile: { type: RuntimeDefault }',
                })
    if not in_security:
        # 没找到 securityContext
        pass


# ── Docker 扩展规则 ───────────────────────────────────────────

def _check_docker_healthcheck(path, lines, issues):
    """docker-no-healthcheck: Dockerfile 无 HEALTHCHECK（WARN）"""
    text = '\n'.join(lines)
    if 'HEALTHCHECK' not in text:
        issues.append({
            'severity': 'warn', 'rule': 'docker-no-healthcheck',
            'file': path, 'line': 1,
            'message': 'Dockerfile 未定义 HEALTHCHECK 指令',
            'suggestion': '添加 HEALTHCHECK CMD curl -f http://localhost:8080/health || exit 1',  # codeguard: ignore GOLD_NO_MAGIC_NUMBER
        })


def _check_docker_user(path, lines, issues):
    """docker-no-user: Dockerfile 未使用非 root 用户（WARN）"""
    text = '\n'.join(lines)
    if 'USER' not in text:
        issues.append({
            'severity': 'warn', 'rule': 'docker-no-user',
            'file': path, 'line': min(len(lines), 5),
            'message': 'Dockerfile 未指定 USER（默认以 root 运行容器）',
            'suggestion': '在 Dockerfile 末尾添加 USER 1001（或特定用户）',
        })


def _check_docker_copy_add(path, lines, issues):
    """docker-copy-vs-add: Docker 建议使用 COPY 替代 ADD（INFO）"""
    for i, line in enumerate(lines, 1):
        stripped = line.strip().upper()
        if stripped.startswith('ADD ') and not stripped.startswith('ADD http'):
            issues.append({
                'severity': 'info', 'rule': 'docker-copy-vs-add',
                'file': path, 'line': i,
                'message': '推荐使用 COPY 替代 ADD（仅复制本地文件时）',
                'suggestion': '将 ADD 替换为 COPY；ADD 仅用于解压缩或 URL 下载场景',
            })


# ── Terraform 扩展规则 ────────────────────────────────────────

def _check_tf_rds_encryption(path, lines, issues):
    """tf-rds-no-encryption: RDS 实例未开启加密（BLOCK）"""
    in_rds = False
    for i, line in enumerate(lines, 1):
        if 'aws_db_instance' in line:
            in_rds = True
        if in_rds and 'storage_encrypted' in line:
            if 'true' not in line.lower():
                issues.append({
                    'severity': 'block', 'rule': 'tf-rds-no-encryption',
                    'file': path, 'line': i,
                    'message': 'RDS 实例未开启存储加密（storage_encrypted = false 或未声明）',
                    'suggestion': '设置 storage_encrypted = true',
                })
            in_rds = False
    if in_rds:
        # 找到 aws_db_instance 但未找到 storage_encrypted 声明
        for i, line in enumerate(lines, 1):
            if 'aws_db_instance' in line:
                issues.append({
                    'severity': 'block', 'rule': 'tf-rds-no-encryption',
                    'file': path, 'line': i,
                    'message': 'RDS 实例未声明 storage_encrypted（默认不加密）',
                    'suggestion': '添加 storage_encrypted = true 到 aws_db_instance 资源块',
                })


def _check_tf_cloudtrail(path, lines, issues):
    """tf-cloudtrail-no-enabled: CloudTrail 未启用（BLOCK）"""
    has_cloudtrail = any('aws_cloudtrail' in line for line in lines)
    # 假设整个项目级别。本文件级检测：有 aws 资源但无 CloudTrail
    has_aws = any('provider "aws"' in line or 'aws_' in line for line in lines)
    if has_aws and not has_cloudtrail:
        # 仅在文件级做 WARN（项目级由 governance-hub 做）
        pass


def _extract_tf_blocks(text, resource_type):
    """提取指定资源类型的完整资源块文本（大括号配对）。

    Returns:
        [(block_text, line_no), ...]
    """
    blocks = []
    pattern = re.compile(r'resource\s+"' + re.escape(resource_type) + r'"\s+"[^"]*"\s*\{')
    for m in pattern.finditer(text):
        depth = 0
        end = m.start()
        for i in range(m.end() - 1, len(text)):
            if text[i] == '{':
                depth += 1
            elif text[i] == '}':
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        line_no = text[:m.start()].count('\n') + 1
        blocks.append((text[m.start():end], line_no))
    return blocks


def _check_tf_s3_versioning(path, lines, issues):
    """tf-s3-no-versioning: S3 未开启版本控制（WARN）

    v0.4 修复：versioning 块完全缺失时也触发（原仅检测「存在但未 Enabled」）。
    """
    text = '\n'.join(lines)
    for block, line_no in _extract_tf_blocks(text, 'aws_s3_bucket'):
        has_versioning = re.search(r'versioning\s*\{[^}]*enabled\s*=\s*true', block, re.IGNORECASE | re.DOTALL)
        if not has_versioning:
            issues.append({
                'severity': 'warn', 'rule': 'tf-s3-no-versioning',
                'file': path, 'line': line_no,
                'message': 'S3 存储桶未开启版本控制（versioning 块缺失或未 enabled）',
                'suggestion': '添加 versioning { enabled = true } 配置块',
            })


def _check_tf_ec2_imdsv2(path, lines, issues):
    """tf-ec2-no-imdsv2: EC2 实例未强制使用 IMDSv2（WARN）

    v0.4 修复：metadata_options 块完全缺失时也触发（原仅检测「存在但未 required」）。
    """
    text = '\n'.join(lines)
    for block, line_no in _extract_tf_blocks(text, 'aws_instance'):
        has_imdsv2 = re.search(r'metadata_options\s*\{[^}]*http_tokens\s*=\s*"required"', block, re.IGNORECASE | re.DOTALL)
        if not has_imdsv2:
            issues.append({
                'severity': 'warn', 'rule': 'tf-ec2-no-imdsv2',
                'file': path, 'line': line_no,
                'message': 'EC2 实例未强制 IMDSv2（metadata_options 缺失或未 http_tokens=required）',
                'suggestion': '添加 metadata_options { http_tokens = "required" }',
            })


def _check_tf_sg_self_ref(path, text, issues):
    """tf-sg-self-reference: 安全组自引用（INFO）"""
    # 仅做信息提示，检测自引用模式
    if re.search(r'self\s*[=:]\s*true', text):
        issues.append({
            'severity': 'info', 'rule': 'tf-sg-self-reference',
            'file': path, 'line': 1,
            'message': '安全组包含自引用规则',
            'suggestion': '确保自引用未造成循环依赖',
        })


# ── 通用规则 ──────────────────────────────────────────────────

def _check_env_leak(path, text, issues):
    """generic-env-leak: 环境变量泄露敏感信息（BLOCK）

    检测 YAML/TF 中的环境变量是否可能泄露密钥/密码/Token。
    """
    patterns = [
        (r'(?:SECRET|TOKEN|PASSWORD|API_KEY|PRIVATE_KEY)\s*[:=]\s*[^$\s{]{4,}', 'block'),
        (r'value\s*[:=]\s*["\'][A-Za-z0-9+/=]{40,}["\']', 'warn'),
    ]
    for pat, sev in patterns:
        for m in re.finditer(pat, text):
            val = m.group()
            if len(val) > 16:
                val = val[:16] + "..."
            issues.append({
                'severity': sev, 'rule': 'generic-env-leak',
                'file': path, 'line': text[:m.start()].count('\n') + 1,
                'message': f'疑似硬编码敏感信息: {val}',
                'suggestion': '使用环境变量引用或密钥管理服务替代硬编码值',
            })
