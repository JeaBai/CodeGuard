"""检视 4：部署完整性（Knight Capital 防御）。"""
from __future__ import annotations

from pathlib import Path
from typing import Any
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from _governance_core import load_json_file, parse_lock_versions  # noqa: E402

# ── 检视 4：部署完整性（Knight Capital 防御） ──────────────────

def deploy_integrity_check(root: Path) -> list[dict[str, Any]]:
    """检查部署完整性：查找部署清单并验证目标节点版本一致性。

    Knight Capital (2012, $440M) 事故根因：8 台服务器仅更新 7 台，
    新旧代码混跑导致 45 分钟内损失 4.4 亿美元。
    """
    issues: list[dict[str, Any]] = []
    lock_patterns = ['deploy.lock', '.deploy.lock', 'deploy.json',
                     'deployment.lock', '.deployment.lock']
    lock_files: list[Path] = []
    for pattern in lock_patterns:
        for p in root.glob(f'**/{pattern}'):
            if p.is_file():
                lock_files.append(p)
    if not lock_files:
        issues.append({
            'severity': 'info', 'rule': 'deploy-no-lock',
            'message': '未找到部署锁文件（deploy.lock / deploy.json），跳过部署完整性检视',
            'suggestion': ('建议在 CI/CD 部署任务中生成 deploy.lock，'
                           '记录每个目标节点的版本号'),
        })
        return issues
    all_versions: set[str] = set()
    all_targets: list[str] = []
    for lf in lock_files:
        data = load_json_file(lf)
        if data is None:
            issues.append({
                'severity': 'warn', 'rule': 'deploy-lock-parse',
                'file': str(lf.relative_to(root)),
                'message': f'部署锁文件 {lf.name} 无法解析为有效 JSON',
                'suggestion': '检查 deploy.lock 格式是否完整',
            })
            continue
        versions, targets = parse_lock_versions(lf)
        all_versions.update(versions)
        all_targets.extend(targets)
    if len(all_versions) > 1:
        issues.append({
            'severity': 'block', 'rule': 'deploy-version-mismatch',
            'message': (f'部署完整性异常：{len(all_versions)} 个不匹配的版本号 '
                        f'({", ".join(sorted(all_versions))})'),
            'suggestion': ('立即停止发布，确认所有目标节点版本一致 '
                           '（参照 Knight Capital 2012: 8 台仅更新 7 台→$440M）'),
        })
    elif len(all_versions) == 1:
        ver = next(iter(all_versions))
        issues.append({
            'severity': 'info', 'rule': 'deploy-ok',
            'message': f'部署完整性检查通过：{len(all_targets)} 节点，统一版本 {ver}',
            'suggestion': '',
        })
    return issues
