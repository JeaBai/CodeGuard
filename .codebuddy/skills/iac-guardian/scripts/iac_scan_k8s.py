"""Kubernetes YAML 检测规则。"""
from __future__ import annotations

import re

from iac_scan_core import add

# ---------------- Kubernetes YAML 检测 ----------------

def _check_k8s_per_line(path, lines, in_rbac, issues):
    """逐行 K8s 安全检测（rbac/privileged/hostNetwork/latestImage/runAsRoot）。

    v0.2.3 P1 修复：增加 container 级 securityContext 检测、indent-agnostic 全文扫描、
    空 securityContext 告警，消除 3 FN。
    """
    # 全文预检：container 级 securityContext（不依赖 securityContext: 行冒泡）
    _check_k8s_container_run_as_root(path, '\n'.join(lines), issues)

    for i, line in enumerate(lines, 1):
        if in_rbac and re.match(r'^\s*-\s*"\*"\s*$', line):
            add(issues, 'block', 'k8s-rbac-wildcard', (path, i), 'RBAC 出现 "*" 通配项（verbs/resources/apiGroups 全权授予）',
                suggestion='resources/verbs 显式列举：resources: ["pods"], verbs: ["get", "list"]')
        elif in_rbac and re.search(r'\b(?:verbs|resources|apiGroups|nonResourceURLs)\s*:\s*\[[^\]]*"\*"', line):
            add(issues, 'block', 'k8s-rbac-wildcard', (path, i), 'RBAC 内联数组含 "*" 通配（verbs/resources/apiGroups 全权授予）',
                suggestion='resources/verbs 显式列举：resources: ["pods"], verbs: ["get", "list"]')

        if re.search(r'privileged:\s*true', line):
            add(issues, 'block', 'k8s-privileged', (path, i), '容器启用 privileged 特权模式，等同于宿主机 root',
                suggestion='移除 privileged；确需特殊能力时用 securityContext.capabilities.add 细粒度授权')

        if re.search(r'hostNetwork:\s*true', line):
            add(issues, 'warn', 'k8s-host-network', (path, i), 'hostNetwork: true 使 Pod 共享宿主机网络命名空间',
                suggestion='仅在 ingress/监控等必要场景使用，并注释原因')

        if re.search(r'image:\s*\S+(:latest)?\s*$', line) and \
           re.search(r'image:\s*[^\s:]+(\s*|:latest\s*)$', line):
            add(issues, 'block', 'k8s-latest-image', (path, i), '镜像使用 latest 或无标签，发布不可追溯、回滚不可靠',
                suggestion='固定镜像版本标签（语义化版本或 digest）')

        if re.search(r'securityContext:\s*($|\{)', line):
            window = '\n'.join(lines[i:i + 8])
            has_run_as_non_root = 'runAsNonRoot' in window
            has_run_as_user = 'runAsUser' in window
            has_allow_priv_esc = 'allowPrivilegeEscalation' in window
            runs_as_root = ('runAsUser: 0' in window or
                           'runAsUser:\n        0' in window.replace(' ', '') or
                           'runAsUser:              0' in window.replace(' ', ''))
            
            # v0.2.3: 空 securityContext（行尾无内容或仅 {}）默认以 root 运行
            stripped_window = ''.join(window.split())
            if stripped_window in ('securityContext:', 'securityContext:{}'):
                add(issues, 'block', 'k8s-run-as-root', (path, i),
                    'securityContext 为空，容器默认以 root 运行',
                    suggestion='设置 securityContext: { runAsNonRoot: true, runAsUser: 10001, allowPrivilegeEscalation: false }')  # codeguard: ignore GOLD_NO_MAGIC_NUMBER
                continue
            
            if not has_run_as_non_root and not has_run_as_user:
                add(issues, 'block', 'k8s-run-as-root', (path, i),
                    'securityContext 未声明 runAsNonRoot/runAsUser，容器可能以 root 运行',
                    suggestion='设置 securityContext: { runAsNonRoot: true, runAsUser: 10001 }')  # codeguard: ignore GOLD_NO_MAGIC_NUMBER
            elif runs_as_root and (not has_allow_priv_esc or 'allowPrivilegeEscalation: true' in window):
                add(issues, 'block', 'k8s-run-as-root', (path, i),
                    '容器以 root (runAsUser: 0) 运行，且 allowPrivilegeEscalation 未关闭',
                    suggestion='设置 runAsUser 为非 0 值，并添加 allowPrivilegeEscalation: false')
            elif 'runAsNonRoot: false' in window:
                add(issues, 'block', 'k8s-run-as-root', (path, i),
                    'securityContext 显式声明 runAsNonRoot: false，容器将以 root 运行',
                    suggestion='设置 runAsNonRoot: true，或将 runAsUser 设为非 0 值')
            elif has_run_as_user and not has_run_as_non_root:
                add(issues, 'block', 'k8s-run-as-root', (path, i),
                    'securityContext 有 runAsUser 但未声明 runAsNonRoot，无法确认非 root 策略',
                    suggestion='添加 runAsNonRoot: true 以显式声明非 root 运行策略')


def _check_k8s_container_run_as_root(path, text, issues):
    """v0.2.3: 全文扫描 container 级 securityContext，消除 indent-agnostic 漏报。

    在 K8s YAML 中，容器可以有自己的 securityContext，独立于 Pod 级。
    此函数不依赖分行 window，直接在全文搜索 container 上下文中的
    securityContext 块，检查是否包含 runAsNonRoot/runAsUser 声明。
    """
    # 检测所有 securityContext 块（任意缩进层级）
    for m in re.finditer(r'^\s+securityContext:\s*$', text, re.MULTILINE):
        start = m.start()
        # 获取缩进级别
        indent = len(m.group(0)) - len(m.group(0).lstrip())
        # 从 securityContext 行开始，收集该块内容直到缩进回归或文件结束
        block_lines = []
        for line in text[m.end():].split('\n'):
            if line.strip() == '':
                continue
            line_indent = len(line) - len(line.lstrip())
            if line_indent <= indent:
                break
            block_lines.append(line)
        block = '\n'.join(block_lines)
        
        # 检查是否有 runAsNonRoot 或 runAsUser 声明
        has_run_as_non_root = 'runAsNonRoot' in block
        has_run_as_user = 'runAsUser' in block
        
        if not has_run_as_non_root and not has_run_as_user:
            # 空块也报告
            if block.strip() == '' or block.strip() == '{}':
                line_no = text[:start].count('\n') + 1
                add(issues, 'block', 'k8s-run-as-root', (path, line_no),
                    'container 级 securityContext 为空，容器默认以 root 运行',
                    suggestion='在 container.securityContext 中设置 runAsNonRoot: true 和 runAsUser')
                continue
            
            line_no = text[:start].count('\n') + 1
            add(issues, 'block', 'k8s-run-as-root', (path, line_no),
                'container 级 securityContext 未声明 runAsNonRoot/runAsUser',
                suggestion='在 container.securityContext 中设置 runAsNonRoot: true, runAsUser: 10001')  # codeguard: ignore GOLD_NO_MAGIC_NUMBER


def _check_k8s_readonly_root(path, lines, issues):
    """k8s-no-readonly-root: 缺 readOnlyRootFilesystem（BLOCK）"""
    for i, line in enumerate(lines, 1):
        if re.search(r'securityContext:\s*$', line):
            window = '\n'.join(lines[i:i + 8])
            if 'readOnlyRootFilesystem' not in window:
                add(issues, 'block', 'k8s-no-readonly-root', (path, i), 'securityContext 未声明 readOnlyRootFilesystem: true',
                    suggestion='设置 securityContext: { readOnlyRootFilesystem: true }，'
                    '必要写入路径挂 emptyDir')


def _check_k8s_resource_limits(path, text, issues):
    """k8s-no-resource-limits: Deployment 缺 resources（WARN）"""
    if re.search(r'kind:\s*Deployment', text) and 'limits' not in text:
        add(issues, 'warn', 'k8s-no-resource-limits', (path, 1), 'Deployment 未声明 resources.requests/limits',
            suggestion='为每个容器声明 requests/limits；配额上限由 finops-quota CI 门禁兜底')


def scan_yaml(path, text, issues):
    """Kubernetes YAML 安全扫描入口。"""
    lines = text.splitlines()
    in_rbac = bool(re.search(r'kind:\s*(Cluster)?Role\b', text))
    _check_k8s_per_line(path, lines, in_rbac, issues)
    _check_k8s_readonly_root(path, lines, issues)
    _check_k8s_resource_limits(path, text, issues)

    # P8 扩展规则（R15-R16, R25）
    try:
        import iac_scan_extended  # noqa: F401
        iac_scan_extended.scan_extended_yaml(path, text, issues)
    except ImportError:  # codeguard: ignore GOLD_NO_EMPTY_EXCEPT
        pass
