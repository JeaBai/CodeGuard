#!/usr/bin/env python3
"""release_notes_draft.py — Conventional Commits → Release Notes 草稿生成器（governance-hub v0.2.0）

纯 Python 标准库实现，零第三方依赖。
解析 git log 中遵循 Conventional Commits 的提交，按类别产出 Markdown 草稿。

用法：
  python release_notes_draft.py --from v1.2.0 --to HEAD
  python release_notes_draft.py --from HEAD~20 -o RELEASE_NOTES.md

# codeguard: ignore GOLD_NO_PRINT_PRODUCTION
退出码（对齐 CodeGuard 体系）：
  0 = 成功，无破坏性变更
  1 = 成功，但存在破坏性变更（需人工复核）
  2 = git 执行失败 / 参数错误（阻断）
"""
import argparse
import re
import subprocess
import sys
from collections import defaultdict

CC_RE = re.compile(
    r'^(?P<type>feat|fix|perf|refactor|docs|style|test|chore|build|ci)'
    r'(?:\((?P<scope>[^)]*)\))?'
    r'(?P<breaking>!)?:\s*(?P<subject>.+)$'
)

CATEGORIES = [
    ('BREAKING', '💥 破坏性变更（Breaking Changes）'),
    ('feat', '✨ 新功能（Features）'),
    ('fix', '🐛 缺陷修复（Bug Fixes）'),
    ('perf', '⚡ 性能优化（Performance）'),
    ('refactor', '♻️ 重构（Refactoring）'),
    ('docs', '📝 文档（Documentation）'),
    ('other', '🔧 其他（Miscellaneous）'),
]
KNOWN_TYPES = {'feat', 'fix', 'perf', 'refactor', 'docs', 'style', 'test', 'chore', 'build', 'ci'}


def collect_commits(from_ref, to_ref):
    rng = f'{from_ref}..{to_ref}' if from_ref else (to_ref or 'HEAD')
    proc = subprocess.run(
        ['git', 'log', rng, '--pretty=format:%h%x09%s'],
        capture_output=True, text=True, encoding='utf-8', errors='ignore',
    )
    if proc.returncode != 0:
        print(proc.stderr.strip() or 'git log 执行失败：请确认在 git 仓库内运行且引用范围有效',  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
              file=sys.stderr)
        sys.exit(1)
    return [line for line in proc.stdout.splitlines() if line.strip()]


def classify(lines):
    groups = defaultdict(list)
    breaking_footer_hint = []
    for line in lines:
        sha, _, subject = line.partition('\t')
        m = CC_RE.match(subject)
        if m:
            ctype = m.group('type')
            cat = 'BREAKING' if m.group('breaking') else (ctype if ctype in KNOWN_TYPES else 'other')
            scope = f"**{m.group('scope')}**: " if m.group('scope') else ''
            groups[cat].append(f"- {scope}{m.group('subject')} ({sha})")
        else:
            if 'BREAKING' in subject.upper():
                breaking_footer_hint.append(f"- {subject} ({sha})")
            groups['other'].append(f"- {subject} ({sha})")
    return groups, breaking_footer_hint


def render(groups, from_ref, to_ref, breaking_hint):
    md = ['# Release Notes（草稿）', '']
    rng = f"{from_ref or '初始'} → {to_ref or 'HEAD'}"
    md.append(f'> 范围：`{rng}` · 由 governance-hub release_notes_draft.py 自动生成')
    md.append('')
    for key, title in CATEGORIES:
        items = groups.get(key)
        if not items:
            continue
        md.append(f'## {title}')
        md.extend(items)
        md.append('')
    if breaking_hint:
        md.append('## ⚠️ 疑似破坏性变更（提交未使用 ! 标记，请人工复核）')
        md.extend(breaking_hint)
        md.append('')
    md.append('---')
    md.append('> 后续动作：① 为每条破坏性变更补充迁移指南；② 将技术描述转换为业务价值描述（业务版通告）；'
              '③ 通知全部下游团队与干系人（见 governance_checklist.md 双轨模板）。')
    return '\n'.join(md)


def main():
    ap = argparse.ArgumentParser(description='Conventional Commits → Release Notes 草稿生成器')
    ap.add_argument('--from', dest='from_ref', default=None, help='起始引用（不含），如 v1.2.0 或 HEAD~20')
    ap.add_argument('--to', dest='to_ref', default='HEAD', help='结束引用（含），默认 HEAD')
    ap.add_argument('--output', '-o', default=None, help='输出文件路径（缺省打印到 stdout）')
    args = ap.parse_args()

    groups, breaking_hint = classify(collect_commits(args.from_ref, args.to_ref))
    text = render(groups, args.from_ref, args.to_ref, breaking_hint)

    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(text)
        print(f'已写入 {args.output}')  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
    else:
        print(text)  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION

    # 退出码对齐 CodeGuard：有破坏性变更返回 WARN(1)，正常 PASS(0)
    has_breaking = bool(groups.get('BREAKING') or breaking_hint)
    sys.exit(1 if has_breaking else 0)


if __name__ == '__main__':
    main()
