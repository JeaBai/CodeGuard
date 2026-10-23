#!/usr/bin/env python3
"""rvi_calc.py — 需求偏差率 (RVI) 度量脚本

governance-hub Roadmap P1-1: RVI 度量（NASA SWE-200 口径）
基于 git 历史分析实际变更是否对应用户需求，计算需求偏差率。

RVI (Requirement Volatility Index) = 未关联需求的 commit / 总 commit 数
参考: NASA SWE-200 — Software Engineering Requirements Management

用法:
  python rvi_calc.py --path . --range 90d    # 最近 90 天
  python rvi_calc.py --path . --range 30d --format json
  python rvi_calc.py --path . --range all --target-branch main
"""
import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

VERSION = "0.1.0"


def _run_git(cmd: list[str], cwd: str = ".") -> str:
    """执行 git 命令。"""
    try:
        r = subprocess.run(
            ["git"] + cmd, capture_output=True, text=True,
            cwd=cwd, timeout=60, encoding="utf-8", errors="replace"
        )
        return r.stdout.strip()
    except Exception:  # codeguard: ignore GOLD_NO_BROAD_EXCEPTION
        return ""


def calculate_rvi(project_root: str, time_range: str = "90d",
                  target_branch: str = "HEAD") -> dict:
    """计算需求偏差率（RVI）。

    Args:
        project_root: 项目根目录
        time_range: 时间范围（如 30d/90d/all）
        target_branch: 目标分支

    Returns:
        RVI 报告 dict
    """
    # 获取 commit 日志
    if time_range == "all":
        log_cmd = ["log", "--oneline", target_branch]
    else:
        log_cmd = ["log", "--oneline", f"--since={time_range}", target_branch]

    log = _run_git(log_cmd, cwd=project_root)
    if not log:
        return {"rvi": 0.0, "error": "无 git 历史", "total_commits": 0}

    commits = [l.strip() for l in log.split("\n") if l.strip()]
    total = len(commits)

    # 匹配需求/issue 引用模式
    patterns = [
        r'#\d+',                           # GitHub #123
        r'(?:PROJ|TAPD|JIRA|TASK|STORY|BUG|RQM|REQ)[-/_]\d+',  # ALM tools
        r'(?:fix|close|resolve|address|implement|support|ref #)\s*#?\d+',  # keywords
        r'(?:需求|任务|缺陷|用户故事|特性|功能)#?\d+',  # Chinese requirement refs
    ]
    combined = re.compile('|'.join(f'({p})' for p in patterns), re.IGNORECASE)

    traced = sum(1 for c in commits if combined.search(c))
    untraced = total - traced

    rvi = round(untraced / total, 3) if total > 0 else 0.0

    # 分类统计
    categories = {"feat": 0, "fix": 0, "docs": 0, "chore": 0, "refactor": 0, "other": 0}
    for c in commits:
        msg_lower = c.lower()
        if "feat" in msg_lower or "feature" in msg_lower:
            categories["feat"] += 1
        elif "fix" in msg_lower or "bug" in msg_lower:
            categories["fix"] += 1
        elif "docs" in msg_lower or "doc:" in msg_lower:
            categories["docs"] += 1
        elif "chore" in msg_lower or "build" in msg_lower or "ci" in msg_lower:
            categories["chore"] += 1
        elif "refactor" in msg_lower or "refac" in msg_lower:
            categories["refactor"] += 1
        else:
            categories["other"] += 1

    # NASA SWE-200 基准
    if rvi <= 0.10:
        health = "HEALTHY"
        verdict = "PASS"
    elif rvi <= 0.25:
        health = "CAUTION"
        verdict = "WARN"
    else:
        health = "CRITICAL"
        verdict = "BLOCK"

    return {
        "version": VERSION,
        "rvi": rvi,
        "health": health,
        "verdict": verdict,
        "total_commits": total,
        "traced_commits": traced,
        "untraced_commits": untraced,
        "trace_ratio": round(traced / total, 3) if total > 0 else 0.0,
        "time_range": time_range,
        "categories": categories,
        "standard": "NASA SWE-200 (RVI ≤ 10% = HEALTHY)",
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


def main():
    parser = argparse.ArgumentParser(description=f"RVI 需求偏差率度量 v{VERSION}")
    parser.add_argument("--path", default=".", help="项目根目录")
    parser.add_argument("--range", default="90d", help="时间范围 (30d/90d/all)")
    parser.add_argument("--target-branch", default="HEAD", help="目标分支")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    args = parser.parse_args()

    result = calculate_rvi(args.path, args.range, args.target_branch)

    if args.format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
    else:
        print(f"RVI 需求偏差率: {result['rvi']:.1%}")  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
        print(f"健康度: {result['health']}")  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
        print(f"{result['total_commits']} commits → {result['traced_commits']} 关联需求 ({result['trace_ratio']:.0%})")  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
        print(f"未关联: {result['untraced_commits']} ({result['rvi']:.0%})")  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
        print(f"分类: feat={result['categories']['feat']} fix={result['categories']['fix']} other={result['categories']['other']}")  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
        print(f"\n标准: {result['standard']}")  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
        print(f"判定: {result['verdict']}")  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION

    exit_map = {"PASS": 0, "WARN": 1, "BLOCK": 2}
    return exit_map.get(result["verdict"], 0)


if __name__ == "__main__":
    sys.exit(main())
