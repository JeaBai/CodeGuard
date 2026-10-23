#!/usr/bin/env python3
"""_governance_core.py — governance_gate 共享基础设施（常量、工具函数、输出桥接）"""
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# codeguard: ignore GOLD_NO_HARDCODED_URL — 以下为工具文档参考链接
INFRACOST_DOCS_URL = 'https://www.infracost.io/docs/'   # codeguard: ignore GOLD_NO_HARDCODED_URL
OASDIFF_INSTALL_URL = 'https://github.com/tufin/oasdiff'  # codeguard: ignore GOLD_NO_HARDCODED_URL

# ── 标准化 JSON Schema ─────────────────────────────────────────
GATE_OUTPUT_SCHEMA_VERSION = "1.0"
GATE_OUTPUT_FIELDS = frozenset({
    'gate', 'dimension', 'severity', 'rule',
    'file', 'line', 'message', 'suggestion',
})


def normalize_issue(issue: dict[str, Any]) -> dict[str, Any]:
    """补齐缺失字段，确保 issue dict 对齐 GATE_OUTPUT_SCHEMA。"""
    issue.setdefault('file', '')
    issue.setdefault('line', 0)
    issue.setdefault('suggestion', '')
    return issue


# ── 门禁项定义 ─────────────────────────────────────────────────
GATE_ITEMS = {
    'cost-baseline': {
        'id': 'GG_COST_001', 'name': '成本基线检视',
        'dimension': 'D11', 'check': 'cost_baseline_check', 'severity': 'block',
    },
    'contract-breaking': {
        'id': 'GG_CONTRACT_001', 'name': '契约破坏性变更检测',
        'dimension': 'D12', 'check': 'contract_breaking_check', 'severity': 'block',
    },
    'requirement-trace': {
        'id': 'GG_TRACE_001', 'name': '需求追溯完整性检查',
        'dimension': 'D9', 'check': 'requirement_trace_check', 'severity': 'warn',
    },
    'deploy-integrity': {
        'id': 'GG_DEPLOY_001', 'name': '部署完整性检视',
        'dimension': 'D5', 'check': 'deploy_integrity_check', 'severity': 'block',
    },
    'auto-trace': {
        'id': 'GG_TRACE_002', 'name': '自动需求追溯（D9 增强）',
        'dimension': 'D9', 'check': 'auto_trace_check', 'severity': 'block',
    },
}


def load_json_file(path: Path):
    """安全加载 JSON 文件。"""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (json.JSONDecodeError, OSError):
        return None


def run_git(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    """安全执行 git 命令。"""
    try:
        return subprocess.run(
            ['git'] + args, capture_output=True, text=True,
            encoding='utf-8', errors='ignore', cwd=cwd,
        )
    except FileNotFoundError:
        return subprocess.CompletedProcess(['git'], 127, '', 'git 未找到')


def fmt_pct(value: float) -> str:
    """格式化为百分比字符串。"""
    return f'{value * 100:.0f}%'


def parse_lock_versions(lf: Path) -> tuple[set[str], list[str]]:
    """解析单个部署锁文件，提取版本号和目标节点标识。"""
    versions: set[str] = set()
    targets: list[str] = []
    data = load_json_file(lf)
    if data is None:
        return versions, targets
    if isinstance(data, dict):
        ver_key = data.get('version') or data.get('release') or data.get('tag')
        if ver_key:
            versions.add(str(ver_key))
        for t in data.get('targets', []):
            if isinstance(t, str):
                targets.append(t)
            elif isinstance(t, dict) and 'node' in t and 'version' in t:
                targets.append(f'{t["node"]}: {t["version"]}')
                versions.add(str(t['version']))
    return versions, targets


def emit_results(all_issues: list[dict[str, Any]], mode: str,
                 fmt: str, exit_code: int) -> None:
    """输出检视结果（JSON 或 text 格式），统一退出逻辑。"""
    if fmt == 'json':
        blocks_l = [i for i in all_issues if i['severity'] == 'block']
        warns_l = [i for i in all_issues if i['severity'] == 'warn']
        infos_l = [i for i in all_issues if i['severity'] == 'info']
        output = {
            'schema_version': GATE_OUTPUT_SCHEMA_VERSION,
            'timestamp': datetime.now().isoformat(),
            'mode': mode, 'exit_code': exit_code,
            'summary': {
                'total': len(all_issues),
                'blocks': len(blocks_l),
                'warnings': len(warns_l),
                'infos': len(infos_l),
            },
            'issues': all_issues,
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
        sys.stdout.flush()
        return

    if not all_issues:
        print('\u2705 全部治理门禁通过')  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
        sys.exit(0)

    for it in all_issues:
        tag = f"[{it['severity'].upper():5}]"
        dim = it.get('dimension', '')
        rule = it.get('rule', '')
        fname = it.get('file', '')
        loc = fname if fname else rule
        print(f"{tag} {dim} {loc}")  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
        print(f"        {it['message']}")  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
        if it.get('suggestion'):
            print(f"        修复: {it['suggestion']}")  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
        sys.stdout.flush()

    blocks_l = [i for i in all_issues if i['severity'] == 'block']
    warns_l = [i for i in all_issues if i['severity'] == 'warn']
    infos_l = [i for i in all_issues if i['severity'] == 'info']
    print(f'\n治理门禁完成: {len(blocks_l)} BLOCK / {len(warns_l)} WARN / '  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
          f'{len(infos_l)} INFO → 退出码 {exit_code}')
    sys.stdout.flush()


def consume_iac_report(iac_report_path: Path | None) -> list[dict[str, Any]]:
    """加载 iac_scan.py --bridge JSON 输出，返回 D11 相关 issue 列表。"""
    if iac_report_path is None or not iac_report_path.exists():
        return []
    data = load_json_file(iac_report_path)
    if data is None or data.get('source') != 'iac-guardian':
        return []
    findings = data.get('findings', [])
    issues: list[dict[str, Any]] = []
    d11_items = [f for f in findings if f.get('dimension') == 'D11']
    if d11_items:
        for f in d11_items:
            issues.append({
                'severity': f.get('severity', 'warn'),
                'rule': f'iac-{f.get("rule", "unknown")}',
                'gate': 'GG_COST_001', 'dimension': 'D11',
                'message': f'[iac-guardian] {f.get("message", "")}',
                'suggestion': f.get('suggestion', ''),
                'file': f.get('file', ''),
            })
        issues.append({
            'severity': 'info', 'rule': 'iac-bridge-ok',
            'gate': 'GG_COST_001', 'dimension': 'D11',
            'message': f'IaC 桥接：从 iac-guardian 导入 {len(d11_items)} 条 D11 配额 findings',
            'suggestion': '',
        })
    return issues
