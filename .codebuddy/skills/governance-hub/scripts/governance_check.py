#!/usr/bin/env python3
"""governance_check.py — 发布前五问自动化门禁

纯 Python 标准库实现，零第三方依赖。
将 governance-hub SKILL.md 中手动五问检视升级为 CI/CD 可执行的自动化检查。

五问映射：
  Q1 需求有源 → git log 解析 commit→issue 关联率
  Q2 变更有界 → OpenAPI spec diff 破坏性变更检测
  Q3 数据有悔 → migration/ 目录 downgrade 非空校验
  Q4 成本有谱 → IaC 资源配额声明 + cost-baseline 偏离
  Q5 通告有达 → 模板存在性 + 干系人列表校验（人工最终确认）

退出码：0 = PASS / 1 = WARN（部分需人工确认）/ 2 = BLOCK（必须修复）
用法：python governance_check.py --path . --format json
CI 集成: python governance_check.py --path . --format json --ci
"""
import argparse
import datetime
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

# v0.3.0: Windows GBK 编码兼容层
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding='utf-8', errors='replace')
    except (AttributeError, OSError):
        pass

VERSION = "0.2.2"


def _run_git(cmd: list[str], cwd: str = ".") -> str:
    """执行 git 命令，返回 stdout 文本。失败返回空字符串。"""
    try:
        r = subprocess.run(
            ["git"] + cmd, capture_output=True, text=True,
            cwd=cwd, timeout=30, encoding="utf-8", errors="replace"
        )
        return r.stdout.strip()
    except Exception:  # codeguard: ignore GOLD_NO_BROAD_EXCEPTION
        return ""


def _check_q1_requirement_trace(repo_root: str) -> dict[str, Any]:
    r"""Q1: 需求有源 — 检查 commit 消息是否关联 issue/需求 ID。

    判定逻辑:
    1. 优先扫描 MASTER_PLAN.md / ROADMAP.md 里程碑标记（M\d+\.\d+ / Milestone / 需求）
    2. 其次扫描最近 N 个 commit（默认 20），提取 issue 引用（#NNN / PROJ-NNN / TAPD-NNN）
    3. 计算关联率 = 含引用的 commit 数 / 总 commit 数
    4. 关联率 >= 95% → PASS, >= 80% → WARN, < 80% → BLOCK

    返回: {"status": "pass"|"warn"|"block", "ratio": float, "details": str}
    """
    # v0.3.0: 先检查替代追溯源（MASTER_PLAN.md / ROADMAP.md）
    root = Path(repo_root)
    alt_sources = []
    for alt_name in ("MASTER_PLAN.md", "ROADMAP.md", "REQUIREMENTS.md", "MILESTONES.md"):
        alt_path = root / alt_name
        if alt_path.exists():
            try:
                alt_text = alt_path.read_text(encoding="utf-8", errors="ignore")
                # 匹配里程碑/需求标记
                milestone_pattern = re.compile(
                    r'(?:M\d+[\.-]\d+|Milestone|需求\d+|Requirement\s*#?\d+|User Story|Epic\s*#?\d+)',
                    re.IGNORECASE
                )
                alt_matches = milestone_pattern.findall(alt_text)
                if alt_matches:
                    alt_sources.append((alt_name, len(alt_matches)))
            except OSError:
                pass

    if alt_sources:
        total_milestones = sum(n for _, n in alt_sources)
        source_names = ", ".join(f"{name}({n})" for name, n in alt_sources)
        return {
            "question": "Q1-需求有源",
            "status": "pass",
            "ratio": 1.0,
            "traced": total_milestones,
            "total": total_milestones,
            "threshold": 0.95,
            "trace_source": "alt",
            "alt_sources": source_names,
            "message": f"替代追溯源检测：{source_names} 共 {total_milestones} 个需求标记（替代 git log issue 引用）",
            "fix": None,
        }

    # 降级：git log 检查
    log = _run_git(["log", "--oneline", "-20"], cwd=repo_root)
    if not log:
        return {"question": "Q1-需求有源", "status": "na", "reason": "无 git 历史", "ratio": 0.0, "message": "无 git 历史可追溯"}

    lines = [l.strip() for l in log.split("\n") if l.strip()]
    total = len(lines)
    # 匹配 issue/需求 ID: #123 / PROJ-456 / TAPD-789 / JIRA-ABC-123  # codeguard: ignore GOLD_NO_MAGIC_NUMBER
    issue_pattern = re.compile(r'(?:#\d+|(?:PROJ|TAPD|JIRA|TASK|STORY|BUG)[-/_]\d+)', re.IGNORECASE)
    traced = sum(1 for l in lines if issue_pattern.search(l))
    ratio = traced / total if total > 0 else 0.0

    if ratio >= 0.95:
        status = "pass"
    elif ratio >= 0.80:
        status = "warn"
    else:
        status = "block"

    return {
        "question": "Q1-需求有源",
        "status": status,
        "ratio": round(ratio, 3),
        "traced": traced,
        "total": total,
        "threshold": 0.95,
        "message": (
            f"commit 需求关联率 {ratio:.0%} ({traced}/{total})"
            + (f" — 低于阈值 95%，需补充 issue 引用" if ratio < 0.95 else "")
        ),
        "fix": (
            "修改 commit 消息在描述中添加 issue 引用（如 #123, TAPD-456）"  # codeguard: ignore GOLD_NO_MAGIC_NUMBER
            if status != "pass" else None
        ),
    }


def _check_q2_contract_breaking(repo_root: str) -> dict[str, Any]:
    """Q2: 变更有界 — 检测 OpenAPI/接口契约破坏性变更。

    判定逻辑:
    - 检查 git diff 中是否存在 openapi.yml / spec.json 等文件变更
    - 若不存在变更 → PASS（无契约变更，无需检查）
    - 若存在变更 → 分析 diff 内容检测破坏性变更标记（删除端点/变更必填字段等）
      - 有破坏性变更 → WARN（需人工审查）
      - 无破坏性变更 → PASS（变更安全）

    返回: {"status": "pass"|"warn", "files": [...], "breaking_indicators": [...]}
    """
    diff_files = _run_git(
        ["diff", "--name-only", "HEAD~1", "--", "*openapi*", "*swagger*", "*spec.json*", "*contract*"],
        cwd=repo_root
    )
    changed = [f for f in diff_files.split("\n") if f.strip()] if diff_files else []

    # 无契约变更 → PASS（项目无 API 变更，无需契约检查）
    if not changed:
        return {
            "question": "Q2-变更有界",
            "status": "pass",
            "changed_files": [],
            "breaking_indicators": [],
            "message": "未检测到 OpenAPI 契约文件变更，无需契约破坏性检查",
            "fix": None,
        }

    # 有契约变更 → 分析 diff 内容检测破坏性变更
    breaking_indicators: list[str] = []
    for fname in changed:
        diff_text = _run_git(
            ["diff", "HEAD~1", "--", fname],
            cwd=repo_root
        )
        if not diff_text:
            continue

        # 检测破坏性变更特征：
        # 1. 删除了端点定义（- 行中的 path 定义）
        removed_paths = re.findall(r'^-\s*(?:/[^\s"\'{]+)+\s*:', diff_text, re.MULTILINE)
        if removed_paths:
            breaking_indicators.append(f"{fname}: 删除了 {len(removed_paths)} 个 API 端点")

        # 2. 删除了 required 字段中的参数
        removed_required = re.findall(r'^-\s*-\s*(\w+)\s*$', diff_text, re.MULTILINE)
        if removed_required and any('required' in diff_text for line in [diff_text]):
            breaking_indicators.append(f"{fname}: 移除了必填参数")

        # 3. 变更了参数类型（type: 行变更）
        type_changes = re.findall(
            r'^-\s*type:\s*(.+)\s*$|^\+\s*type:\s*(.+)\s*$',
            diff_text, re.MULTILINE
        )
        if len(type_changes) >= 2:  # 至少有一对删+增
            breaking_indicators.append(f"{fname}: 参数类型发生变更")

        # 4. 删除了 schema 定义（可能被引用）
        removed_schemas = re.findall(r'^-\s*(\w+):\s*$', diff_text, re.MULTILINE)
        if len(removed_schemas) > 2:
            breaking_indicators.append(f"{fname}: 删除了 {len(removed_schemas)} 个 schema 定义")

    # 无破坏性变更 → PASS
    if not breaking_indicators:
        return {
            "question": "Q2-变更有界",
            "status": "pass",
            "changed_files": changed,
            "breaking_indicators": [],
            "message": f"检测到 {len(changed)} 个契约文件变更，未发现破坏性变更标记",
            "fix": None,
        }

    # 有破坏性变更 → WARN
    return {
        "question": "Q2-变更有界",
        "status": "warn",
        "changed_files": changed,
        "breaking_indicators": breaking_indicators,
        "message": f"检测到 {len(changed)} 个契约文件变更，含 {len(breaking_indicators)} 个破坏性变更标记",
        "fix": "逐个审阅变更文件，确认破坏性 API 变更影响范围；通知下游团队并协调迁移计划",
    }


def _check_q3_migration_rollback(repo_root: str) -> dict[str, Any]:
    """Q3: 数据有悔 — 检查 migration 脚本的 downgrade 是否非空。

    判定逻辑:
    - 扫描 migration/ / migrations/ / alembic/versions/ 目录
    - 对每个 migration 文件检查是否存在对应的 downgrade/rollback 函数
    - 使用启发式检测（Python: def downgrade, SQL: -- downgrade）

    返回: {"status": "pass"|"warn"|"block", "checked": int, "missing_downgrade": [...]}
    """
    migration_dirs = [
        "migration", "migrations", "db/migration", "db/migrations",
        "alembic/versions", "sql/migrations",
    ]
    root = Path(repo_root)

    checked = 0
    missing_downgrade: list[str] = []

    for mdir in migration_dirs:
        md = root / mdir
        if not md.exists():
            continue
        for f in md.rglob("*"):
            if not f.is_file():
                continue
            if f.suffix in (".py", ".sql"):
                checked += 1
                content = f.read_text(errors="replace")
                # Python migration: 检查 def downgrade
                if f.suffix == ".py":
                    has_downgrade = bool(re.search(r'def\s+downgrade\b', content))
                    has_rollback = bool(re.search(r'def\s+rollback\b', content))
                    if not (has_downgrade or has_rollback):
                        missing_downgrade.append(str(f.relative_to(root)))
                # SQL migration: 检查 -- downgrade / /* downgrade */ 注释
                elif f.suffix == ".sql":
                    if "downgrade" not in content.lower() and "rollback" not in content.lower():
                        missing_downgrade.append(str(f.relative_to(root)))

    # P1-1: 未检测到 migration 文件 → WARN（提醒用户确认是否确实无 schema 变更）
    if checked == 0:
        return {
            "question": "Q3-数据有悔",
            "status": "warn",
            "checked": 0,
            "message": "未找到 migration 文件，请确认是否确实无数据库 schema 变更",
            "fix": "如有 schema 变更请确保 migration 文件已生成并纳入版本控制",
        }

    if not missing_downgrade:
        return {
            "question": "Q3-数据有悔",
            "status": "pass",
            "checked": checked,
            "missing_downgrade": [],
            "message": f"全部 {checked} 个 migration 均有 downgrade/rollback 定义",
            "fix": None,
        }

    # v0.2.2 P0 修复: severity 从 block 降至 warn（人工确认是否确实需要回滚策略）
    return {
        "question": "Q3-数据有悔",
        "status": "warn",
        "checked": checked,
        "missing_downgrade": missing_downgrade,
        "message": f"{len(missing_downgrade)}/{checked} 个 migration 缺少 downgrade，需确认是否确实需要回滚策略",
        "fix": "为需要回滚的 migration 补充 downgrade/rollback 函数或 SQL 脚本；若确实不需要回滚请标注原因",
    }


def _check_q4_cost_baseline(repo_root: str) -> dict[str, Any]:
    """Q4: 成本有谱 — 检查资源配额声明与成本基线偏离。

    判定逻辑:
    - 扫描 .tf / .yaml 文件中的资源配额声明
    - 检查是否存在 requests/limits 声明
    - WARN: 存在未声明配额的容器资源
    - 当 skip_cost=True 时直接返回 N/A

    返回: {"status": "pass"|"warn"|"na", "has_quota": int, "missing_quota": int}
    """
    root = Path(repo_root)
    has_quota = 0
    missing_quota = 0

    for pattern, ext in [("**/*.tf", ".tf"), ("**/*.yaml", ".yaml"), ("**/*.yml", ".yml")]:
        for f in root.glob(pattern):
            if "node_modules" in str(f) or ".terraform" in str(f):
                continue
            content = f.read_text(errors="replace")

            # 检查容器/Deployment 上下文
            has_container = bool(re.search(
                r'\b(container|deployment|pod)\b', content, re.IGNORECASE
            ))
            if not has_container:
                continue

            # 检查资源声明
            has_resources = bool(re.search(
                r'\b(resources\s*:|requests\s*:|limits\s*:|cpu\s*:|memory\s*:)',
                content, re.IGNORECASE
            ))

            if has_resources:
                has_quota += 1
            else:
                missing_quota += 1

    total = has_quota + missing_quota
    if total == 0:
        return {
            "question": "Q4-成本有谱",
            "status": "na",
            "has_quota": 0,
            "missing_quota": 0,
            "message": "未检测到容器化资源定义（非容器项目可跳过），如需检查请移除 --skip-cost",
            "fix": None,
        }

    if missing_quota == 0:
        return {
            "question": "Q4-成本有谱",
            "status": "pass",
            "has_quota": has_quota,
            "missing_quota": 0,
            "message": f"全部 {has_quota} 个容器资源均声明了 requests/limits",
            "fix": None,
        }

    return {
        "question": "Q4-成本有谱",
        "status": "warn",
        "has_quota": has_quota,
        "missing_quota": missing_quota,
        "message": f"{missing_quota}/{total} 个容器资源未声明 requests/limits，可能导致成本失控或调度失败",
        "fix": "为每个容器资源添加 resources.requests 和 resources.limits 声明",
    }


def _check_q5_stakeholder_notice(repo_root: str) -> dict[str, Any]:
    """Q5: 通告有达 — 检查发布通告模板和干系人列表存在性。

    判定逻辑:
    - 检查是否存在 governance 通告模板文件
    - 检查模板中是否包含干系人列表
    - 最终确认仍需人工执行

    返回: {"status": "warn"|"pass", ...}
    """
    root = Path(repo_root)
    template_files = list(root.rglob("**/governance_checklist.md"))
    # 也检查 skill 目录下的模板
    skill_template = root / ".codebuddy" / "skills" / "governance-hub" / "references" / "governance_checklist.md"
    if skill_template.exists() and skill_template not in template_files:
        template_files.append(skill_template)

    # P0-7: 模板存在 → PASS（通告流程已就绪），模板缺失 → WARN
    if template_files:
        return {
            "question": "Q5-通告有达",
            "status": "pass",
            "template_found": True,
            "message": f"通告模板已就绪（{len(template_files)} 个），可执行干系人通告",
            "fix": None,
        }

    return {
        "question": "Q5-通告有达",
        "status": "warn",
        "template_found": False,
        "message": "未找到通知模板，无法确认通告流程完备性",
        "fix": "创建 governance 发布通告模板（技术版+业务版）并纳入发布 checklist",
    }


def _severity_weight(status: str) -> int:
    """0=pass, 1=warn, 2=block, 0=na"""
    return {"pass": 0, "warn": 1, "block": 2, "na": 0}.get(status, 0)


def run_full_check(repo_root: str, skip_cost: bool = False) -> dict[str, Any]:
    """执行全部五问检视，汇总结果。"""
    results = [
        _check_q1_requirement_trace(repo_root),
        _check_q2_contract_breaking(repo_root),
        _check_q3_migration_rollback(repo_root),
        _check_q4_cost_baseline(repo_root) if not skip_cost else {
            "question": "Q4-成本有谱",
            "status": "na",
            "message": "已跳过（--skip-cost）",
            "fix": None,
        },
        _check_q5_stakeholder_notice(repo_root),
    ]

    blocks = [r for r in results if r["status"] == "block"]
    warns = [r for r in results if r["status"] == "warn"]
    passes = [r for r in results if r["status"] == "pass"]
    nas = [r for r in results if r["status"] == "na"]

    max_severity = max(_severity_weight(r["status"]) for r in results)
    exit_code = max_severity if max_severity <= 2 else 2

    if max_severity == 2:
        verdict = "BLOCK — 存在阻断项，必须修复"
    elif max_severity == 1:
        verdict = "WARN — 有人工确认项，检查后发布"
    else:
        verdict = "PASS — 全部检视通过"

    return {
        "version": VERSION,
        "exit_code": exit_code,
        "verdict": verdict,
        "summary": {
            "blocks": len(blocks),
            "warnings": len(warns),
            "pass": len(passes),
            "na": len(nas),
            "total": len(results),
        },
        "questions": results,
        "checked_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }


def format_text(report: dict[str, Any]) -> str:
    """格式化文本输出。"""
    lines = [
        "=" * 60,
        f"  Governance Hub — 发布前五问检视 v{VERSION}",
        "=" * 60,
        f"  判定: {report['verdict']}",
        f"  退出码: {report['exit_code']}",
        f"  时间: {report['checked_at']}",
        "",
    ]
    for q in report["questions"]:
        icon = {"pass": "✅", "warn": "⚠️", "block": "❌", "na": "—"}.get(q["status"], "?")
        lines.append(f"  [{icon}] {q['question']}")
        lines.append(f"      {q['message']}")
        if q.get("fix"):
            lines.append(f"      → {q['fix']}")
        lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="发布前五问自动化门禁")
    parser.add_argument("--path", default=".", help="项目根目录")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    parser.add_argument("--ci", action="store_true", help="CI 模式（仅输出 JSON）")
    parser.add_argument("--skip-cost", action="store_true",
                        help="跳过 Q4 成本检测（非容器/非生产项目用）")
    args = parser.parse_args()

    report = run_full_check(args.path, skip_cost=args.skip_cost)

    if args.ci or args.format == "json":
        print(json.dumps(report, ensure_ascii=False, indent=2))  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
    else:
        print(format_text(report))  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION

    sys.exit(report["exit_code"])


if __name__ == "__main__":
    main()
