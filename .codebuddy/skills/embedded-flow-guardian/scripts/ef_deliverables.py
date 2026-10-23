#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ef_deliverables.py — 检测器 ① 交付物完整性

回答：这个项目「该有的流程产物」有哪些、缺哪些、哪些已经陈旧失效。

设计依据（见 references/lifecycle.md、references/anti-patterns.md）：
  - 三份最高杠杆产物：需求规格书、ICD、需求追溯矩阵
  - 缺 ICD → 硬软件各自「猜」接口，集成期才暴露
  - 缺兼容矩阵 → 固件错版本烧到错板卡
  - 陈旧文档比没有更糟：会误导人和 AI agent

边界：本检测器只看「产物是否存在/是否新鲜」，不评估产物内容质量，
      内容质量由人工评审或后续模型审查承担。
"""
from __future__ import annotations

import time
from pathlib import Path

import ef_common as C

# 文档陈旧阈值（天）：文档落后于代码超过该值即提示复核
STALE_DOC_DAYS = 180


def scan_deliverables(root: Path, collector, profile: C.ProjectProfile, cfg: dict):
    level = cfg.get("defaultLevel", C.DEFAULT_LEVEL)

    # ---- 1) 交付物存在性 ----
    # 判定采用两级证据：文件名（强）> 标题行（中）。正文「提及」不再单独采信——
    # 否则一份讨论 RTM/ICD 的分析报告会被误判为「项目已具备该交付物」。
    present, missing = [], []
    for item in C.DELIVERABLE_CATALOG:
        hit, evidence = C.find_deliverable(profile, item["keywords"])
        if hit is not None:
            present.append((item, hit, evidence))
        else:
            missing.append(item)

    for item in missing:
        sev = C.severity_for(item["needed"], level)
        collector.add(
            sev,
            f"flow_deliverable_{item['id']}",
            str(root), 0,
            f"缺少交付物：{item['name']}",
            f"{item['why']}｜可从 assets/templates/ 取模板补齐；"
            f"参考 references/lifecycle.md",
            confidence=85,
        )

    # 弱证据提示：仅在「仅命中标题行」时提醒人工确认，避免把目录页当成交付物
    for item, hit, evidence in present:
        if evidence == "heading":
            collector.add(
                "hint", f"flow_deliverable_weak_{item['id']}",
                profile.rel(hit), 0,
                f"{item['name']} 仅通过标题行匹配识别（{profile.rel(hit)}），请人工确认",
                "标题命中可能是目录/综述页；确认是否已有成体系的该交付物",
                confidence=50,
            )

    # ---- 2) 文档时效性（陈旧文档比没有更糟） ----
    stale = []
    if profile.source_files and profile.doc_files:
        newest_src = max((p.stat().st_mtime for p in profile.source_files
                          if _safe_mtime(p)), default=0)
        for p in profile.doc_files:
            m = _safe_mtime(p)
            if not m:
                continue
            age_days = (time.time() - m) / 86400
            lag_days = (newest_src - m) / 86400
            if age_days > STALE_DOC_DAYS and lag_days > STALE_DOC_DAYS:
                stale.append((p, int(age_days)))

    for p, age in sorted(stale, key=lambda x: -x[1])[:8]:
        collector.add(
            "hint", "flow_doc_stale", profile.rel(p), 0,
            f"文档可能已陈旧：{profile.rel(p)}（约 {age} 天未更新，且显著落后于源码）",
            "陈旧的文档会误导人和 AI agent；确认后更新或删除，不要保留「腐烂」文档",
            confidence=55,
        )

    # ---- 3) 交付物齐全度评分（写进 info，供报告汇总） ----
    total = len(C.DELIVERABLE_CATALOG)
    ok = len(present)
    strong = [i["name"] for i, _p, ev in present if ev == "filename"]
    collector.add(
        "info", "flow_deliverable_score", str(root), 0,
        f"交付物齐全度：{ok}/{total}"
        + (f"｜确认具备（文件名证据）：{'、'.join(strong)}" if strong else ""),
        "齐全度不追求 100%；ADR / README 属加分项，需求规格、ICD、RTM、兼容矩阵为核心",
        confidence=90,
    )


def _safe_mtime(p: Path):
    try:
        return p.stat().st_mtime
    except OSError:
        return 0
