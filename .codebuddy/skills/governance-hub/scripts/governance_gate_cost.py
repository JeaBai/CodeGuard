"""检视 1：成本基线。"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from _governance_core import load_json_file, fmt_pct, INFRACOST_DOCS_URL  # noqa: E402

# ── 检视 1：成本基线 ───────────────────────────────────────────

def cost_baseline_check(root: Path, threshold_pct: int = 20) -> list[dict[str, Any]]:
    """检查 IaC 项目的月度成本估算是否偏离基线超过阈值。"""
    issues: list[dict[str, Any]] = []
    baseline_paths = [
        root / '.cost-baseline.json',
        root / 'cost' / 'baseline.json',
        root / 'infra' / 'cost' / 'baseline.json',
    ]
    baseline = None
    for bp in baseline_paths:
        if bp.exists():
            baseline = load_json_file(bp)
            break
    if baseline is None:
        issues.append({
            'severity': 'warn', 'rule': 'cost-no-baseline',
            'message': '未找到成本基线文件（.cost-baseline.json），无法执行云成本偏离检视',
            'suggestion': ('在项目根目录创建 .cost-baseline.json，'
                           '格式：{"monthly_estimate_usd": <N>}'),
        })
        return issues
    try:
        proc = subprocess.run(
            ['infracost', 'breakdown', '--path', str(root), '--format', 'json',
             '--no-color', '--log-level', 'error'],
            capture_output=True, text=True, timeout=120, encoding='utf-8',
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        issues.append({
            'severity': 'warn', 'rule': 'cost-no-infracost',
            'message': 'infracost 不可用或执行超时，跳过成本估算比对',
            'suggestion': f'安装 infracost CLI（{INFRACOST_DOCS_URL}）并将其加入 CI 环境',
        })
        return issues
    if proc.returncode != 0:
        issues.append({
            'severity': 'warn', 'rule': 'cost-breakdown-failed',
            'message': f'infracost breakdown 执行失败: {proc.stderr[:200]}',
            'suggestion': '检查 Terraform 配置完整性并重试',
        })
        return issues
    try:
        raw = json.loads(proc.stdout)
        current_monthly = float(raw.get('totalMonthlyCost', 0) or 0)
    except (json.JSONDecodeError, ValueError, TypeError):
        issues.append({
            'severity': 'warn', 'rule': 'cost-parse-error',
            'message': '无法解析 infracost 输出中的月成本估算',
            'suggestion': '检查 infracost 输出格式是否完整',
        })
        return issues
    baseline_monthly = float(baseline.get('monthly_estimate_usd', 0))
    if baseline_monthly <= 0:
        issues.append({
            'severity': 'info', 'rule': 'cost-zero-baseline',
            'message': '基准月度成本为 0，请确认已设定真实基线',
            'suggestion': '更新 .cost-baseline.json 中的 monthly_estimate_usd 为实际基线值',
        })
        return issues
    deviation_pct = abs(current_monthly - baseline_monthly) / baseline_monthly
    if deviation_pct > threshold_pct / 100:
        direction = '增加' if current_monthly > baseline_monthly else '减少'
        sev = 'block' if deviation_pct > 0.5 else 'warn'
        issues.append({
            'severity': sev, 'rule': 'cost-deviation',
            'message': (
                f'月度成本偏离基线 {fmt_pct(deviation_pct)}（{direction}）：'
                f'基线 ${baseline_monthly:.0f} → 当前 ${current_monthly:.0f}'
            ),
            'suggestion': (
                f'偏离超过阈值 {threshold_pct}%，请人工确认是否为预期变更。'
                '若为预期，请更新 .cost-baseline.json'
            ),
        })
    else:
        issues.append({
            'severity': 'info', 'rule': 'cost-ok',
            'message': (
                f'成本基线正常：基线 ${baseline_monthly:.0f} → '
                f'当前 ${current_monthly:.0f}（偏离 {fmt_pct(deviation_pct)}）'
            ),
            'suggestion': '',
        })
    return issues
