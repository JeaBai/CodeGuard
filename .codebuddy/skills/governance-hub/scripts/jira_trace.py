#!/usr/bin/env python3
"""jira_trace.py — Jira API 联动：PR ↔ 需求关联率自动统计

governance-hub Roadmap P1-2: Jira API 联动
基于 Jira REST API 自动获取 issue 列表，与 git commit 交叉比对，
输出需求关联率报告。

认证: JIRA_TOKEN 环境变量（Jira API Token）或 JIRA_USER:JIRA_TOKEN
    JIRA_BASE_URL 环境变量（如 https://your-domain.atlassian.net）  # codeguard: ignore GOLD_NO_HARDCODED_URL

用法:
  python jira_trace.py --project PROJ --range 30d
  python jira_trace.py --project PROJ --jql 'project=PROJ AND status=Done' --format json
"""
import argparse
import json
import os
import re
import subprocess
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

VERSION = "0.1.0"


def _get_jira_auth() -> tuple[str, str] | None:
    """从环境变量获取 Jira 认证信息。"""
    base_url = os.environ.get("JIRA_BASE_URL", "")
    token = os.environ.get("JIRA_TOKEN", "")
    if not base_url or not token:
        # 尝试 Basic Auth 方式
        user = os.environ.get("JIRA_USER", "")
        if user and token:
            return (f"{base_url.rstrip('/')}/rest/api/3", f"{user}:{token}")
        return None
    return (f"{base_url.rstrip('/')}/rest/api/3", token)


def _jira_request(api_base: str, auth: str, endpoint: str, params: dict = None) -> list:
    """发送 Jira API GET 请求，返回 JSON 响应。"""
    url = f"{api_base}/{endpoint.lstrip('/')}"
    if params:
        query = "&".join(f"{k}={urllib.parse.quote(str(v))}" for k, v in params.items())
        url += f"?{query}"

    req = urllib.request.Request(url)
    req.add_header("Accept", "application/json")
    if "@" in auth:
        # Basic Auth
        import base64
        encoded = base64.b64encode(auth.encode()).decode()
        req.add_header("Authorization", f"Basic {encoded}")
    else:
        # Bearer Token
        req.add_header("Authorization", f"Bearer {auth}")

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        print(f"[jira_trace] HTTP {e.code}: {e.reason}", file=sys.stderr)  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
        return []
    except Exception as e:  # codeguard: ignore GOLD_NO_BROAD_EXCEPTION
        print(f"[jira_trace] 请求失败: {e}", file=sys.stderr)  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
        return []


def _run_git(cmd: list[str], cwd: str = ".") -> str:
    try:
        r = subprocess.run(["git"] + cmd, capture_output=True, text=True,
                           cwd=cwd, timeout=30, encoding="utf-8", errors="replace")
        return r.stdout.strip()
    except Exception:  # codeguard: ignore GOLD_NO_BROAD_EXCEPTION
        return ""


def fetch_jira_issues(api_base: str, auth: str, project: str, jql: str = "",
                      max_results: int = 100) -> list[dict]:
    """获取 Jira issue 列表。"""
    if jql:
        query = jql
    else:
        query = f"project={project} ORDER BY updated DESC"

    params = {"jql": query, "maxResults": max_results, "fields": "key,summary,status,issuetype"}
    result = _jira_request(api_base, auth, "search", params)
    return result.get("issues", []) if isinstance(result, dict) else []


def trace_commits_against_jira(project_root: str, project_key: str,
                                time_range: str = "30d") -> dict:
    """交叉比对 git commit 与 Jira issue。

    Returns:
        {jira_total, traced_commits, missing_issues, trace_rate, issues_map}
    """
    # 获取 commit 日志
    log = _run_git(["log", "--oneline", f"--since={time_range}"], cwd=project_root)
    commits = [l.strip() for l in log.split("\n") if l.strip()]

    # 从 commit 消息提取 Jira issue key
    jira_pattern = re.compile(rf'\b({project_key}-\d+)\b', re.IGNORECASE)
    referenced = set()
    commit_to_issues = {}

    for i, commit in enumerate(commits):
        matches = jira_pattern.findall(commit)
        for m in matches:
            key = m.upper()
            referenced.add(key)
            if key not in commit_to_issues:
                commit_to_issues[key] = []
            commit_to_issues[key].append(commit)

    # 尝试连接 Jira（如果有凭证）
    auth_info = _get_jira_auth()
    jira_issues = {}
    jira_total = 0

    if auth_info:
        api_base, auth = auth_info
        issues = fetch_jira_issues(api_base, auth, project_key)
        jira_issues = {
            i["key"]: {
                "summary": i["fields"]["summary"],
                "status": i["fields"]["status"]["name"],
                "type": i["fields"]["issuetype"]["name"],
            }
            for i in issues
        }
        jira_total = len(issues)

        # 关联状态
        traced_in_jira = referenced & set(jira_issues.keys())
        missing = referenced - set(jira_issues.keys())
    else:
        traced_in_jira = referenced
        missing = set()

    return {
        "version": VERSION,
        "project_key": project_key,
        "time_range": time_range,
        "total_commits": len(commits),
        "referenced_issues": len(referenced),
        "traced_in_jira": len(traced_in_jira),
        "missing_in_jira": len(missing),
        "trace_rate": round(len(referenced) / len(commits), 3) if commits else 0.0,
        "jira_total": jira_total,
        "jira_connected": auth_info is not None,
        "issues_detail": {
            k: {"summary": jira_issues.get(k, {}).get("summary", "N/A"),
                "status": jira_issues.get(k, {}).get("status", "UNKNOWN"),
                "commits": commit_to_issues.get(k, [])}
            for k in sorted(referenced)
        },
        "missing_issues": sorted(missing),
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


def main():
    parser = argparse.ArgumentParser(description=f"Jira PR↔需求关联率统计 v{VERSION}")
    parser.add_argument("--path", default=".", help="项目根目录")
    parser.add_argument("--project", required=True, help="Jira 项目 Key（如 PROJ）")
    parser.add_argument("--range", default="30d", help="时间范围（如 30d/90d）")
    parser.add_argument("--jql", default="", help="自定义 JQL（覆盖默认 project 过滤）")
    parser.add_argument("--format", choices=["json", "table"], default="table")
    args = parser.parse_args()

    result = trace_commits_against_jira(args.path, args.project, args.range)

    if args.format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
    else:
        print(f"\n{'='*60}")  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
        print(f"  Jira 需求追溯报告 — {args.project}")  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
        print(f"{'='*60}")  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
        print(f"  Commits: {result['total_commits']}")  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
        print(f"  引用 Jira Issue: {result['referenced_issues']} ({result['trace_rate']:.0%})")  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
        if result["jira_connected"]:
            print(f"  Jira 总计: {result['jira_total']} issues")  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
            print(f"  在 Jira 中找到: {result['traced_in_jira']}")  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
            print(f"  未在 Jira 找到: {result['missing_in_jira']}")  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
        else:
            print(f"  Jira 未连接（设置 JIRA_BASE_URL + JIRA_TOKEN 可启用自动关联）")  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
        print(f"\n  关联明细:")  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
        for key, detail in result["issues_detail"].items():
            print(f"    [{key}] {detail['status']:10} {detail['summary'][:50]}")  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
            for c in detail["commits"][:2]:
                print(f"        → {c[:80]}")  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
        print()  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION

    return 0 if result["trace_rate"] >= 0.8 else 1


if __name__ == "__main__":
    sys.exit(main())
