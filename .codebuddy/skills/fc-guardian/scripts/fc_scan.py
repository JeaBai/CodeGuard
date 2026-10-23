#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fc_scan.py — fc-guardian 飞控守护主入口

编排 5 个检测模块，复用 CodeGuard 的 IssueCollector 门禁体系。
独立于 CodeGuard，不修改任何 CodeGuard 文件。

用法:
  python fc_scan.py --path /path/to/fc-project --format text|json
退出码: 0=PASS / 1=WARN / 2=BLOCK
"""
import argparse
import json
import sys
from pathlib import Path

# 复用 CodeGuard 的 quality_core（只读 import，非改写）
SCRIPT_DIR = Path(__file__).resolve().parent
CODEGUARD_DIR = SCRIPT_DIR.parent.parent / "CodeGuard" / "scripts"
if str(CODEGUARD_DIR) not in sys.path:
    sys.path.insert(0, str(CODEGUARD_DIR))

try:
    import quality_core  # 复用 IssueCollector / THRESHOLDS
except ImportError:
    # 降级：独立部署时使用内置轻量 collector
    quality_core = None

try:
    import quality_embedded  # 复用 CodeGuard 嵌入式管理 9 项检测
except ImportError:
    # 降级：独立部署（无 CodeGuard）时跳过嵌入式层
    quality_embedded = None

import fc_common  # 用户源码定位（find_user_sources）

VERSION = "3.0.0"

# 检测模块（延迟 import，避免循环依赖）
from pin_checker import scan_pins
from uart_checker import scan_uarts
from refresh_checker import scan_refresh
from state_machine_checker import scan_state_machine
from flight_safety import scan_flight_safety


def _make_collector():
    """创建 IssueCollector（复用 quality_core 或内置降级）。"""
    if quality_core is not None:
        return quality_core.IssueCollector()
    return _MiniCollector()


class _MiniCollector:
    """内置降级 collector（独立部署且无 CodeGuard 时使用）。"""

    def __init__(self):
        self.issues = []

    def add(self, severity, category, file, line, message, suggestion=None, confidence=None):  # codeguard: ignore GOLD_TOO_MANY_PARAMS — 接口兼容 quality_core.IssueCollector.add
        self.issues.append({
            "severity": severity, "category": category, "file": file,
            "line": line, "message": message, "suggestion": suggestion or "",
            "confidence": confidence or 0,
        })

    def summary(self):
        blocks = sum(1 for i in self.issues if i["severity"] == "block")
        warns = sum(1 for i in self.issues if i["severity"] == "warn")
        info = len(self.issues) - blocks - warns
        return {"blocks": blocks, "warnings": warns, "info": info,
                "total_issues": len(self.issues), "avg_confidence": 0}

    def has_blocks(self):
        return any(i["severity"] == "block" for i in self.issues)

    def has_warns(self):
        return any(i["severity"] == "warn" for i in self.issues)


def scan_embedded(root, collector):
    """嵌入式管理层：对飞控项目 .c/.cpp 复用 CodeGuard 9 项嵌入式检测。

    只读复用 quality_embedded（毫不干涉 CodeGuard），沿用 embedded_* 前缀，
    与 fc_* 前缀并存，报告清晰区分「飞控硬件层」与「嵌入式代码规范层」。
    """
    if quality_embedded is None:
        return
    for src in fc_common.find_user_sources(root):
        if src.suffix in (".c", ".cpp"):
            quality_embedded.check_embedded_c_file(str(src), collector)


# 可扩展检测器调度表（基脚）：未来接入软件/数据大屏/图像算法/端到端只需追加一条
_DETECTORS = [
    ("hardware", scan_pins),
    ("hardware", scan_uarts),
    ("hardware", scan_refresh),
    ("hardware", scan_state_machine),
    ("hardware", scan_flight_safety),
    ("embedded", scan_embedded),
]


def scan_project(root_path):
    """扫描飞控项目，返回 (issues, exit_code, summary)。"""
    root = Path(root_path).resolve()
    if not root.exists():
        return [], 0, {"total": 0, "blocks": 0, "warnings": 0, "error": f"路径不存在: {root}"}

    collector = _make_collector()

    # 按调度表依次执行（硬件层 + 嵌入式层）
    for _layer, detector in _DETECTORS:
        detector(root, collector)

    issues = collector.issues
    blocks = [i for i in issues if i["severity"] == "block"]
    warns = [i for i in issues if i["severity"] == "warn"]
    exit_code = 2 if blocks else (1 if warns else 0)

    return issues, exit_code, {"total": len(issues), "blocks": len(blocks), "warnings": len(warns)}


def _format_text(issues, exit_code, summary):
    lines = [
        "=" * 60,
        f"  fc-guardian 飞控守护检测报告 v{VERSION}",
        "=" * 60,
        f"  判定: {'BLOCK' if exit_code == 2 else ('WARN' if exit_code == 1 else 'PASS')}",
        f"  发现: {summary['total']} 条 (BLOCK={summary['blocks']} WARN={summary['warnings']})",
        "",
    ]
    for i in issues:
        icon = {"block": "❌", "warn": "⚠️", "info": "ℹ️"}.get(i["severity"], "?")
        fname = Path(i["file"]).name
        lines.append(f"  [{icon}] {i['category']} {fname}:{i['line']}")
        lines.append(f"      {i['message']}")
        if i.get("suggestion"):
            lines.append(f"      → {i['suggestion']}")
        lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=f"fc-guardian 飞控守护 v{VERSION}")
    parser.add_argument("--path", default=".", help="飞控项目路径")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    args = parser.parse_args()

    issues, exit_code, summary = scan_project(args.path)

    if args.format == "json":
        print(json.dumps({
            "version": VERSION, "exit_code": exit_code, "summary": summary,
            "issues": issues,
        }, ensure_ascii=False, indent=2))
    else:
        print(_format_text(issues, exit_code, summary))

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
