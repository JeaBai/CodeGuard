"""检视 3：需求追溯完整性 + 自动追溯。"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from _governance_core import run_git, fmt_pct  # noqa: E402

# ── 检视 3：需求追溯完整性 ─────────────────────────────────────

def requirement_trace_check(root: Path, required_ratio: float = 0.8) -> list[dict[str, Any]]:
    """检查当前分支的 commit 是否关联到工单/需求号。"""
    issues: list[dict[str, Any]] = []
    proc = run_git(['log', 'HEAD~20..HEAD', '--pretty=format:%H%x09%s'], cwd=root)
    if proc.returncode != 0 or not proc.stdout.strip():
        issues.append({
            'severity': 'warn', 'rule': 'trace-no-commits',
            'message': '无法获取 git log 或最近 20 次提交为空',
            'suggestion': '确认在 git 仓库内运行且存在提交记录',
        })
        return issues
    commits = [line for line in proc.stdout.splitlines() if line.strip()]
    if not commits:
        return issues
    ticket_pattern = re.compile(
        r'(?:--story=|--bug=|--task=|#\d+|PROJ-\d+|STORY-\d+|TAPD-\d+)', re.I,
    )
    scoped_pattern = re.compile(r'^(?:feat|fix|perf|refactor|docs)\([^)]+\):')
    traced, untraced = [], []
    for commit_line in commits:
        sha, _, subject = commit_line.partition('\t')
        if ticket_pattern.search(subject) or scoped_pattern.match(subject):
            traced.append(subject)
        else:
            untraced.append(subject)
    total = len(commits)
    traced_count = len(traced)
    ratio = traced_count / total if total else 0
    if ratio < required_ratio:
        suffix = (
            '\n'.join(untraced[:5]) +
            (f'\n... 及另外 {len(untraced) - 5} 条' if len(untraced) > 5 else '')
        )
        issues.append({
            'severity': 'block', 'rule': 'trace-insufficient',
            'message': (
                f'需求追溯覆盖率 {fmt_pct(ratio)}（{traced_count}/{total}），'
                f'低于要求门禁 {fmt_pct(required_ratio)}'
            ),
            'suggestion': '以下提交缺少工单关联，请在 commit message 中添加 '
                          '--story=STORY_ID 或 GitHub/TAPD issue 引用：\n' + suffix,
        })
    else:
        issues.append({
            'severity': 'info', 'rule': 'trace-ok',
            'message': f'需求追溯覆盖率 {fmt_pct(ratio)}（{traced_count}/{total}），达标',
            'suggestion': '',
        })
    return issues


# ── 检视 3.5：自动需求追溯（D9 增强：--mode auto-trace） ────────

def _auto_detect_merge_base(root: Path, target_branch: str = 'main') -> str | None:
    """自动检测 PR 的合并基点，用于增量追溯扫描。
    
    优先级：CI_MERGE_REQUEST_DIFF_BASE_SHA → CI_COMMIT_BEFORE_SHA → git merge-base
    """
    import os as _os
    # GitLab CI 预置变量
    ci_base = _os.environ.get('CI_MERGE_REQUEST_DIFF_BASE_SHA', '')
    if ci_base:
        return ci_base
    # GitHub Actions 可以通过 compare API 获取，这里用通用方式
    proc = run_git(['rev-parse', '--verify', f'origin/{target_branch}'], cwd=root)
    if proc.returncode == 0 and proc.stdout.strip():
        target_sha = proc.stdout.strip()
        merge_proc = run_git(['merge-base', 'HEAD', target_sha], cwd=root)
        if merge_proc.returncode == 0 and merge_proc.stdout.strip():
            return merge_proc.stdout.strip()
    # 兜底：最近 20 个 commit
    return None


def auto_trace_check(root: Path, target_branch: str = 'main',
                     required_ratio: float = 0.8) -> list[dict[str, Any]]:
    """自动溯源模式：自动检测合并基点并执行增量需求追溯扫描。
    
    比 requirement_trace_check 更智能：
    - 自动检测 merge-base，只扫描增量提交
    - 支持 CI 环境变量获取差异基点
    - 输出可被 governance-hub 消费的结构化结果
    """
    issues: list[dict[str, Any]] = []
    merge_base = _auto_detect_merge_base(root, target_branch)
    
    if merge_base:
        commit_range = f'{merge_base}..HEAD'
        proc = run_git(['log', commit_range, '--pretty=format:%H%x09%s'], cwd=root)
    else:
        # 兜底：最近 20 次提交
        proc = run_git(['log', 'HEAD~20..HEAD', '--pretty=format:%H%x09%s'], cwd=root)
        commit_range = 'HEAD~20..HEAD'
    
    if proc.returncode != 0 or not proc.stdout.strip():
        issues.append({
            'severity': 'warn', 'rule': 'auto-trace-no-commits',
            'message': f'无法获取 commit range ({commit_range}) 或范围内无提交',
            'suggestion': '确认分支有尚未合并的提交',
        })
        return issues
    
    commits = [line for line in proc.stdout.splitlines() if line.strip()]
    if not commits:
        issues.append({
            'severity': 'info', 'rule': 'auto-trace-empty',
            'message': '当前分支无新增提交，跳过需求追溯',
            'suggestion': '',
        })
        return issues
    
    # 多模式匹配：覆盖常见工单/需求格式
    ticket_pattern = re.compile(
        r'(?:--story=|--bug=|--task=|'
        r'#\d+|'
        r'PROJ-\d+|STORY-\d+|TAPD-\d+|'
        r'JIRA-[A-Z]+-\d+|'
        r'ISSUE-\d+|'
        r'Resolves\s+#?\d+|Closes\s+#?\d+|Fixes\s+#?\d+|'
        r'REQ-[A-Z]+-\d+)',
        re.I,
    )
    scoped_pattern = re.compile(r'^(?:feat|fix|perf|refactor|docs|test|ci|cd|chore|style|build)\([^)]+\):')
    
    traced, untraced = [], []
    ticket_map: dict[str, list[str]] = {}  # 工单 → 关联的 commit subjects
    
    for commit_line in commits:
        sha, _, subject = commit_line.partition('\t')
        matched = False
        for m in ticket_pattern.finditer(subject):
            matched = True
            ticket_id = m.group()
            ticket_map.setdefault(ticket_id, []).append(subject[:80])
        if scoped_pattern.match(subject):
            matched = True
        if matched:
            traced.append(subject)
        else:
            untraced.append(subject)
    
    total = len(commits)
    traced_count = len(traced)
    ratio = traced_count / total if total else 0
    
    # 构造结果
    result = {
        'mode': 'auto-trace',
        'commit_range': commit_range,
        'merge_base_detected': merge_base is not None,
        'total_commits': total,
        'traced': traced_count,
        'untraced': len(untraced),
        'ratio': ratio,
        'required_ratio': required_ratio,
        'ticket_map': {k: len(v) for k, v in ticket_map.items()},
    }
    
    if ratio >= required_ratio:
        issues.append({
            'severity': 'info', 'rule': 'auto-trace-ok',
            'message': (
                f'自动需求追溯通过：覆盖率 {fmt_pct(ratio)}（{traced_count}/{total}），'
                f'关联 {len(ticket_map)} 个工单，检测范围 {commit_range}'
            ),
            'suggestion': '',
            'metadata': result,
        })
    else:
        suffix = '\n'.join(untraced[:5])
        if len(untraced) > 5:
            suffix += f'\n... 及另外 {len(untraced) - 5} 条'
        issues.append({
            'severity': 'block', 'rule': 'auto-trace-insufficient',
            'message': (
                f'自动需求追溯不达标：覆盖率 {fmt_pct(ratio)}（{traced_count}/{total}），'
                f'要求 {fmt_pct(required_ratio)}，检测范围 {commit_range}'
            ),
            'suggestion': f'以下提交缺少工单关联：\n{suffix}',
            'metadata': result,
        })
    
    return issues
