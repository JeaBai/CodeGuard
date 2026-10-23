#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ef_scan.py — embedded-flow-guardian 主入口

编排 6 个流程检测器，复用 CodeGuard 的 IssueCollector 门禁体系。
独立于 CodeGuard / fc-guardian，不修改任何既有 SKILL 文件。

用法:
  python ef_scan.py --path /path/to/project --format text|json
  python ef_scan.py --path . --level gold
  python ef_scan.py --path . --config .ef-guardian.json
  python ef_scan.py --path . --module-level "<核心目录>/**=gold"

退出码: 0=PASS / 1=WARN / 2=BLOCK

位置声明：本 SKILL 位于「流程层」，与既有 SKILL 的边界如下——
  CodeGuard          → 代码层（复杂度/重复/安全/嵌入式规范 9 项）
  fc-guardian        → 飞控硬件层（引脚/串口/刷新率/状态机/安全）
  iac-guardian       → 基础设施层（Terraform/K8s）
  governance-hub     → 发布治理层（需求关联率/迁移回滚/成本基线）
  project-manager    → 队列与看板
  embedded-flow-guardian（本 SKILL）→ 流程与交付物层
                       （交付物/需求追溯/版本绑定/变更管理/发布准出/自动化基线）
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import ef_common as C  # noqa: E402
from ef_deliverables import scan_deliverables  # noqa: E402
from ef_requirements import scan_requirements  # noqa: E402
from ef_compat import scan_compat  # noqa: E402
from ef_change import scan_change  # noqa: E402
from ef_release import scan_release  # noqa: E402
from ef_ci import scan_ci  # noqa: E402

VERSION = C.VERSION
NAME = "embedded-flow-guardian"

# 可扩展检测器调度表（基脚）
# 未来接入 OTA 合规、供应链、器件生命周期(EOL)等只需在表尾追加一条 (layer, detector)
_DETECTORS = [
    ("deliverables", scan_deliverables),
    ("requirements", scan_requirements),
    ("compat", scan_compat),
    ("change", scan_change),
    ("release", scan_release),
    ("automation", scan_ci),
]


def scan_project(root_path: str, cfg: dict):
    """扫描项目流程健康度，返回 (issues, exit_code, summary, profile_desc)。"""
    root = Path(root_path).resolve()
    if not root.exists():
        return [], 0, {"total": 0, "blocks": 0, "warnings": 0,
                       "error": f"路径不存在: {root}"}, {}

    profile = C.ProjectProfile(root)
    collector = C.make_collector()

    for _layer, detector in _DETECTORS:
        try:
            detector(root, collector, profile, cfg)
        except Exception as exc:  # 单检测器失败不应中断整体扫描
            collector.add(
                "info", "flow_detector_error", str(root), 0,
                f"检测器 {detector.__name__} 执行异常：{exc}",
                "该检测器结果不可用，其余检测器不受影响",
                confidence=0,
            )

    issues = collector.issues
    blocks = [i for i in issues if i["severity"] == "block"]
    warns = [i for i in issues if i["severity"] == "warn"]
    exit_code = 2 if blocks else (1 if warns else 0)

    summary = {
        "total": len(issues),
        "blocks": len(blocks),
        "warnings": len(warns),
        "info": len(issues) - len(blocks) - len(warns),
        "exit_code": exit_code,
    }
    return issues, exit_code, summary, profile.describe()


def _fmt_detect(names, evidence) -> str:
    """把检测结果连同证据一并呈现——标签必须可审计，不能只给结论。"""
    if not names:
        return "无"
    parts = []
    for n in names:
        ev = (evidence or {}).get(n) or []
        if ev:
            parts.append(f"{n}（证据：{ev[0]}）")
        else:
            parts.append(n)
    return "、".join(parts)


def _format_text(issues, exit_code, summary, profile_desc, cfg):
    judge = {2: "BLOCK", 1: "WARN", 0: "PASS"}.get(exit_code, "?")
    level = cfg.get("defaultLevel", C.DEFAULT_LEVEL)
    ev = profile_desc.get("evidence") or {}
    lines = [
        "=" * 68,
        f"  {NAME} 嵌入式研发流程守护检测报告 v{VERSION}",
        "=" * 68,
        f"  判定: {judge}",
        f"  发现: {summary['total']} 条 "
        f"(BLOCK={summary['blocks']} WARN={summary['warnings']} INFO={summary.get('info', 0)})",
        f"  门禁: 默认 {level}"
        + (f" | 分级 {len(cfg.get('moduleLevels') or {})} 条" if cfg.get("moduleLevels") else ""),
        "",
        "  ── 项目画像（附证据路径，可复核） ──",
        f"  构建: {_fmt_detect(profile_desc.get('build_systems'), ev)}",
        f"  CI: {_fmt_detect(profile_desc.get('ci_systems'), ev)}",
        f"  静态分析: {_fmt_detect(profile_desc.get('static_analysis'), ev)}",
        f"  单测框架: {_fmt_detect(profile_desc.get('test_frameworks'), ev)}",
        f"  覆盖率: {_fmt_detect(profile_desc.get('coverage_tools'), ev)}",
        f"  Git: {'有' if profile_desc.get('has_git') else '无'}"
        f" | LFS: {'有' if profile_desc.get('has_lfs') else '无'}",
        f"  自研源码 {profile_desc.get('source_count', 0)} 个"
        f"（已排除厂商/参考代码树） | 文档 {profile_desc.get('doc_count', 0)} 个",
        "",
    ]

    order = {"block": 0, "warn": 1, "info": 2}
    for i in sorted(issues, key=lambda x: order.get(x["severity"], 3)):
        icon = {"block": "[X]", "warn": "[!]", "info": "[i]"}.get(i["severity"], "[?]")
        loc = i["file"] if i.get("line") in (0, None) else f"{i['file']}:{i['line']}"
        lines.append(f"  {icon} {i['category']}  {loc}")
        lines.append(f"      {i['message']}")
        if i.get("suggestion"):
            for seg in str(i["suggestion"]).split("\n"):
                lines.append(f"      → {seg}")
        lines.append("")

    if not issues:
        lines.append("  未发现问题。")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description=f"{NAME} 嵌入式研发流程守护 v{VERSION}")
    parser.add_argument("--path", default=".", help="项目根目录")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    parser.add_argument("--config", default=None, help="门禁配置文件路径")
    parser.add_argument("--level", choices=[C.LEVEL_GOLD, C.LEVEL_SILVER],
                        default=None, help="覆盖默认门禁级别")
    parser.add_argument("--module-level", action="append", default=[],
                        metavar="GLOB=LEVEL",
                        help='按模块指定门禁级别，可重复，如 "<核心目录>/**=gold"')
    parser.add_argument("--report", default=None,
                        help="将 JSON 结果落盘到指定文件（分段落盘）")
    args = parser.parse_args()

    root = Path(args.path).resolve()
    cfg = C.load_config(root, args.config)

    # 命令行覆盖优先于配置文件
    if args.level:
        cfg["defaultLevel"] = args.level
    if args.module_level:
        mods = dict(cfg.get("moduleLevels") or {})
        for item in args.module_level:
            if "=" in item:
                glob, lv = item.rsplit("=", 1)
                glob, lv = glob.strip(), lv.strip()
                if lv in (C.LEVEL_GOLD, C.LEVEL_SILVER):
                    mods[glob] = lv
        cfg["moduleLevels"] = mods

    issues, exit_code, summary, profile_desc = scan_project(str(root), cfg)

    if args.report:
        try:
            Path(args.report).write_text(json.dumps({
                "version": VERSION, "exit_code": exit_code,
                "summary": summary, "config": cfg,
                "profile": profile_desc, "issues": issues,
            }, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            print(f"[warn] 结果落盘失败: {exc}", file=sys.stderr)

    if args.format == "json":
        print(json.dumps({
            "version": VERSION, "name": NAME, "exit_code": exit_code,
            "summary": summary, "config": cfg, "profile": profile_desc,
            "issues": issues,
        }, ensure_ascii=False, indent=2))
    else:
        print(_format_text(issues, exit_code, summary, profile_desc, cfg))

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
