#!/usr/bin/env python3
"""
CodeGuard Dashboard Generator — facade 入口（向后兼容）。
实现已拆分至 dashboard_scores / dashboard_data / dashboard_html。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from dashboard_data import _log, _load_json, generate_dashboard_data  # noqa: F401
from dashboard_html import _HTML_TEMPLATE

# ============================================================
# 公共 API：build_html()
# ============================================================

def build_html(data: dict) -> str:
    """将看板数据嵌入 HTML 模板，生成自包含 HTML 文件。"""
    score = data.get("overall_score", 0)
    dims = data.get("dimensions", {})

    return _HTML_TEMPLATE \
        .replace("%PROJECT_NAME%", data.get("project_name", "未知")) \
        .replace("%GENERATED_AT%", data.get("generated_at", "")) \
        .replace("%MODULE_COUNT%", str(data.get("module_count", 0))) \
        .replace("%DEP_EDGES%", str(data.get("dependency_edges", 0))) \
        .replace("%OVERALL_SCORE%", str(score)) \
        .replace("%SCORE_COLOR%", _score_color(score)) \
        .replace("%TREND%", data.get("score_trend", "—")) \
        .replace("%TREND_COLOR%", "var(--green)" if "+" in str(data.get("score_trend", "")) else "var(--dim)") \
        .replace("%TREND_REASON%", data.get("score_trend_reason", "")) \
        .replace("%ISSUE_COUNT%", str(data.get("total_issues", 0))) \
        .replace("%COVERAGE%", str(data.get("test_coverage", 0))) \
        .replace("%COV_COLOR%", _cov_color(data.get("test_coverage", 0))) \
        .replace("%TEST_STATUS%", {"pass": "✅ 通过", "warn": "⚠️ 待补", "fail": "❌ 失败"}.get(data.get("test_status", ""), "")) \
        .replace("%TEST_BG%", {"pass": "#1a3a2a", "warn": "#3a3510", "fail": "#3a1a1a"}.get(data.get("test_status", ""), "#1a3a2a")) \
        .replace("%TEST_FG%", {"pass": "#3fb950", "warn": "#d2991d", "fail": "#f85149"}.get(data.get("test_status", ""), "#3fb950")) \
        .replace("%DASHBOARD_DATA%", json.dumps(data, ensure_ascii=False))


def _score_color(s: int) -> str:
    if s >= 85: return "#3fb950"
    if s >= 60: return "#d2991d"
    return "#f85149"


def _cov_color(c: float) -> str:
    if c >= 80: return "#3fb950"
    if c >= 50: return "#d2991d"
    return "#f85149"


# ============================================================
# 公共 API：generate_dashboard()
# ============================================================

def generate_dashboard(project_path: str, blueprint_path: str = "",
                       codeguard_output: str = "") -> str:
    """生成完整看板 HTML 字符串。"""
    data = generate_dashboard_data(project_path, blueprint_path, codeguard_output)
    return build_html(data)


# ============================================================
# CLI 入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="CodeGuard Dashboard Generator")
    parser.add_argument("--project", default=".", help="项目根目录")
    parser.add_argument("--blueprint", default="", help="architecture_blueprint.json 路径")
    parser.add_argument("--codeguard-output", default="", help="CodeGuard JSON 输出")
    parser.add_argument("--output", default="dashboard.html", help="输出 HTML 文件")
    parser.add_argument("--watch", action="store_true", help="监听变化自动刷新")
    args = parser.parse_args()

    project = os.path.abspath(args.project)

    def _generate():
        html = generate_dashboard(project, args.blueprint, args.codeguard_output)
        out = args.output
        if not os.path.isabs(out):
            out = os.path.join(project, out)
        with open(out, "w", encoding="utf-8") as f:
            f.write(html)
        _log(f"看板已生成: {out}")

    _generate()

    if args.watch:
        _log("监听模式: 每 30 秒刷新...")
        try:
            while True:
                time.sleep(30)
                _generate()
        except KeyboardInterrupt:
            _log("监听已停止")


if __name__ == "__main__":
    main()
