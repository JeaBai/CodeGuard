#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ef_change.py — 检测器 ④ 变更管理与配置基线

回答：变更是否被「看见」——有没有留痕、有没有基线、能不能回答"改了什么/何时/谁/为什么"。

设计依据（见 references/management.md 2.2、references/engineering.md 3.1）：
  - 变更未留痕 → 返工不可控；基线消失 → 返工爆炸 → 排期崩塌
  - 配置管理范围过窄（只管理源码、需求和设计文档游离在 SCM 之外）是高频失败模式
  - 提交信息应写 why 并关联需求 ID，才能支撑影响分析
  - 手工矩阵第一次变更后即失效 → 基线必须由工具保证

边界：只做只读检查（git log / tag / status），绝不执行任何写操作。
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import ef_common as C

GIT_TIMEOUT = 20


def scan_change(root: Path, collector, profile: C.ProjectProfile, cfg: dict):
    level = cfg.get("defaultLevel", C.DEFAULT_LEVEL)

    # ---- 1) 版本控制存在性 ----
    if not profile.has_git:
        collector.add(
            C.severity_for("missing", level),
            "flow_change_no_vcs",
            str(root), 0,
            "项目未纳入版本控制（未发现 .git）",
            "无版本控制则「可追溯」不成立：无法判断固件来自哪次提交、无法二分定位回归、"
            "无法建立发布基线。建议 git init 并把原理图/PCB/STEP 走 LFS（见 .gitattributes 模板）",
            confidence=95,
        )
        # 无 git 时后续 git 检查跳过，但仍检查变更文档
        _check_changelog(root, collector, profile, level)
        return

    # ---- 2) 基线（tag） ----
    tags = _git(root, ["tag", "--list"])
    if not tags:
        collector.add(
            C.severity_for("weak", level),
            "flow_change_no_baseline",
            str(root), 0,
            "仓库中没有任何 tag（无发布基线）",
            "基线是「可回溯」的锚点：每个出厂固件应唯一对应一个 tag。"
            "建议 Tag 打在 main 的合并提交上，并使用附注标签（git tag -a）",
            confidence=80,
        )
    else:
        collector.add(
            "info", "flow_change_baseline", str(root), 0,
            f"已建立 {len(tags)} 个发布基线（tag）",
            "确认 tag 与出厂固件版本一一对应；Tag 构建应输出纯净版本号",
            confidence=85,
        )

    # ---- 3) 提交与变更规模健康度 ----
    log = _git(root, ["log", "--pretty=format:%H%x09%s", "-n", "200"])
    if log:
        subjects = [l.split("\t", 1)[1] for l in log.splitlines() if "\t" in l]
        if subjects:
            _check_commit_hygiene(root, collector, subjects, level)
            _check_commit_req_link(root, collector, subjects, level)

    # ---- 4) 设计/需求文档是否纳入版本控制 ----
    doc_tracked = _git(root, ["ls-files"])
    if doc_tracked:
        tracked = doc_tracked.splitlines()
        ext_lower = [t.lower() for t in tracked]
        has_doc = any(t.endswith((".md", ".txt", ".csv", ".adoc")) for t in ext_lower)
        has_src = any(t.endswith((".c", ".h", ".cpp", ".hpp")) for t in ext_lower)
        if has_src and not has_doc:
            collector.add(
                C.severity_for("weak", level),
                "flow_change_docs_untracked",
                str(root), 0,
                "仓库已跟踪源码，但未见任何文档类文件被跟踪",
                "仅管理源码、需求与设计文档游离在 SCM 之外，是配置管理范围过窄的典型表现；"
                "文档变更同样需要版本、基线与影响分析",
                confidence=75,
            )
        # 硬件设计资产
        has_hw = any(t.endswith((".schdoc", ".pcbdoc", ".kicad_sch", ".kicad_pcb",
                                 ".step", ".stp", ".brd", ".sch")) for t in ext_lower)
        if has_hw and not profile.has_lfs:
            collector.add(
                C.severity_for("weak", level),
                "flow_change_hw_no_lfs",
                str(root), 0,
                "检测到硬件设计文件被纳入仓库，但未配置 Git LFS",
                "原理图/PCB/STEP 属大二进制且不可合并：裸塞会让仓库迅速膨胀且无法 review。"
                "建议在 .gitattributes 中对这些扩展名启用 filter=lfs diff=lfs merge=lfs -text",
                confidence=78,
            )

    # ---- 5) 变更文档 ----
    _check_changelog(root, collector, profile, level)


# --------------------------------------------------------------------------
def _check_changelog(root, collector, profile, level):
    """变更记录 + CR/ECN 痕迹。"""
    hit, _ev = C.find_deliverable(profile, ["变更记录", "变更日志", "change_log",
                                            "changelog", "change-log",
                                            "ecn", "改动记录"])
    if hit is None:
        collector.add(
            C.severity_for("missing", level),
            "flow_change_no_log",
            str(root), 0,
            "未发现变更记录（changelog / ECN / ECO）",
            "变更记录要能回答「改了什么、何时、谁、为什么」；"
            "建议用 assets/templates/change_log.csv 起步，"
            "安全相关变更须单独标注并触发再评估",
            confidence=80,
        )
    else:
        # 记录条数（粗估）
        try:
            text = hit.read_text(encoding="utf-8", errors="replace")
        except Exception:
            text = ""
        entries = max(text.lower().count("\n") - 1, 0) if hit.suffix.lower() == ".csv" \
            else text.count("\n## ") + text.count("\n### ")
        collector.add(
            "info", "flow_change_log_present", profile.rel(hit), 0,
            f"已发现变更记录：{profile.rel(hit)}（约 {entries} 条）",
            "确认每条变更含：描述 / 影响范围 / 责任人 / 是否安全相关",
            confidence=75,
        )


def _check_commit_hygiene(root, collector, subjects, level):
    """提交信息卫生：过短、WIP、final 类提交。"""
    bad = []
    for s in subjects:
        low = s.strip().lower()
        if low in ("wip", "update", "fix", "fix bug", "临时提交", "更新",
                   "修改", "提交", "test", "tmp", "temp", "aaa", "1234"):
            bad.append(s)
        elif len(s.strip()) < 4:
            bad.append(s)
        elif "final" in low and low.count("final") >= 2:
            bad.append(s)
    ratio = len(bad) / max(len(subjects), 1)
    if ratio > 0.25:
        collector.add(
            C.severity_for("weak", level),
            "flow_change_commit_hygiene",
            str(root), 0,
            f"提交信息质量偏低：{ratio:.0%} 的提交为无信息量描述（WIP/update/修改/…）",
            f"示例：{'；'.join(repr(b) for b in bad[:3])}。"
            "提交信息应写『为什么』而非『什么』，并尽量关联需求 ID——"
            "否则 git bisect / 变更影响分析会失去上下文",
            confidence=68,
        )


def _check_commit_req_link(root, collector, subjects, level):
    """提交是否关联需求 ID（代码 ↔ 需求方向的追溯）。"""
    linked = sum(1 for s in subjects if _has_req_id(s))
    ratio = linked / max(len(subjects), 1)
    if linked == 0:
        collector.add(
            "hint", "flow_change_no_req_link",
            str(root), 0,
            "近 200 次提交中未发现任何需求 ID 关联",
            "在提交信息中带上 REQ-xxx 是最低成本的代码↔需求追溯；"
            "不要求全部，但从安全相关的提交开始建立习惯收益最高",
            confidence=60,
        )
    elif ratio < 0.3:
        collector.add(
            "info", "flow_change_partial_req_link",
            str(root), 0,
            f"提交关联需求 ID 的比例：{ratio:.0%}（{linked}/{len(subjects)}）",
            "可作为度量项跟踪，不要设为强制门禁——过严会诱导伪造关联",
            confidence=65,
        )


def _has_req_id(subject: str) -> bool:
    import re
    return bool(re.search(r"\b(REQ|NFR|FR|SR|US|SYS|需求)[-_#\s]?\d{1,4}\b",
                          subject, re.IGNORECASE))


def _git(root: Path, args):
    """只读执行 git 命令，失败返回空串。"""
    try:
        r = subprocess.run(["git", "-C", str(root)] + args,
                           capture_output=True, text=True,
                           encoding="utf-8", errors="replace",
                           timeout=GIT_TIMEOUT)
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""
