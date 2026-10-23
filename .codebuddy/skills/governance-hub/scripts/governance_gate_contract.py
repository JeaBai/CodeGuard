"""检视 2：契约破坏性变更检测。"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from _governance_core import run_git, OASDIFF_INSTALL_URL  # noqa: E402

# ── 检视 2：契约破坏性变更检测 ─────────────────────────────────

def _match_openapi(text: str) -> bool:
    """快速判断文件内容是否为 OpenAPI/Swagger 规范。"""
    return 'openapi' in text.lower() or 'swagger' in text.lower()


def contract_breaking_check(root: Path) -> list[dict[str, Any]]:
    """扫描 OpenAPI 契约文件，使用 oasdiff 检测破坏性变更。"""
    issues: list[dict[str, Any]] = []
    spec_files: list[Path] = []
    for pattern in ['api/**/*.yaml', 'api/**/*.yml', 'spec/**/*.yaml', 'spec/**/*.yml',
                    'openapi.yaml', 'openapi.yml', 'swagger.yaml', 'swagger.yml',
                    'docs/openapi.yaml', 'docs/openapi.yml']:
        for p in root.glob(pattern):
            if p.is_file():
                text = p.read_text(encoding='utf-8', errors='ignore')[:200]
                if _match_openapi(text):
                    spec_files.append(p)
    if not spec_files:
        issues.append({
            'severity': 'warn', 'rule': 'contract-no-spec',
            'message': '未找到 OpenAPI/Swagger 契约文件',
            'suggestion': '将 API 契约文件放置在 api/ 或 spec/ 目录下',
        })
        return issues
    for spec in spec_files:
        rel = spec.relative_to(root)
        proc = run_git(['show', f'HEAD~1:{rel}'], cwd=root)
        if proc.returncode != 0:
            issues.append({
                'severity': 'warn', 'rule': 'contract-no-base',
                'file': str(rel),
                'message': f'无法获取 {rel} 的上一个版本，可能是新增文件，跳过破坏性比对',
                'suggestion': '确认新契约已在设计评审中通过；首次上线无需版本回退比',
            })
            continue
        tmp_old = root / f'_tmp_gate_{spec.name}.old'
        cleanup = True
        try:
            tmp_old.write_text(proc.stdout, encoding='utf-8')
            oasdiff_proc = subprocess.run(
                ['oasdiff', 'breaking', str(tmp_old), str(spec), '--format', 'text'],
                capture_output=True, text=True, timeout=60, encoding='utf-8',
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            issues.append({
                'severity': 'warn', 'rule': 'contract-no-oasdiff',
                'message': 'oasdiff 工具不可用，跳过契约破坏性变更检测',
                'suggestion': (
                    f'安装 oasdiff（{OASDIFF_INSTALL_URL}，'
                    'go install github.com/tufin/oasdiff/cmd/oasdiff@latest）'
                ),
            })
            cleanup = False
        finally:
            if cleanup:
                tmp_old.unlink(missing_ok=True)
        if not cleanup:
            continue
        if oasdiff_proc.returncode == 0:
            issues.append({
                'severity': 'info', 'rule': 'contract-ok',
                'file': str(rel),
                'message': f'{rel} 未检测到破坏性变更',
                'suggestion': '',
            })
        else:
            breaking_lines = oasdiff_proc.stdout.strip().splitlines()
            change_summary = breaking_lines[0] if breaking_lines else '检测到破坏性 API 变更'
            issues.append({
                'severity': 'block', 'rule': 'contract-breaking',
                'file': str(rel),
                'message': f'{rel} 存在破坏性 API 变更：{change_summary}',
                'suggestion': (
                    f'共 {len(breaking_lines)} 条破坏性变更。'
                    '请添加 API 版本号，并提供迁移指南。'
                    '必须通知 #api-subscribers 频道的下游团队。'
                ),
            })
    return issues
