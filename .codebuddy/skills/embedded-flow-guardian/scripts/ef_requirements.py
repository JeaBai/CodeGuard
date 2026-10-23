#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ef_requirements.py — 检测器 ② 需求条目化与双向追溯

回答：需求是否「可被追溯」——有没有唯一 ID、能不能从需求走到测试再走回来。

设计依据（见 references/management.md、references/compliance.md）：
  - JSON/CSV 手工矩阵第一次需求变更后即失效 → 提示改用工具或至少固定 ID 规范
  - 逆向需求：仅有一份「任务清单」不能替代需求规格
  - 双向追溯贯穿：需求 ↔ 设计 ↔ 代码 ↔ 测试 ↔ 缺陷
  - 需求全覆盖的常见借口是「需求都在脑子里」，这正是断链的起点

边界：不判断需求内容是否正确、是否完整（那是人工评审的事），
      只判断「需求是否被结构化、是否建立了可核验的链接」。
"""
from __future__ import annotations

import re
from pathlib import Path

import ef_common as C

# 需求 ID 规范：REQ-001 / FR-1 / NFR-02 / SR-100 / 需求-01 / US-3 / SYS-4
REQ_ID_RE = re.compile(
    r"\b(REQ|NFR|FR|SR|US|SYS|SWE|HWE|VAL|PRJ|需求|用例)[-_#\s]?(\d{1,4})\b",
    re.IGNORECASE,
)

# 「任务级」而非「需求级」的征兆：这类文档不能替代需求规格
TASK_LEVEL_HINTS = ["任务清单", "修复任务", "todo", "待办", "工作项",
                    "buglist", "缺陷列表", "问题清单"]

# 测试文件特征
TEST_FILE_HINTS = ["test", "测试", "unit", "验证", "case", "用例", "spec"]


def scan_requirements(root: Path, collector, profile: C.ProjectProfile, cfg: dict):
    level = cfg.get("defaultLevel", C.DEFAULT_LEVEL)

    # ---- 1) 定位需求载体 ----
    req_doc, _ev = C.find_deliverable(profile, ["需求规格", "需求说明", "requirements",
                                                "srs", "产品需求", "需求清单",
                                                "需求文档", "需求基线"])

    if req_doc is None:
        # 无需求文档：提示是否只有任务清单在撑场
        task_doc = None
        for p in profile.doc_files:
            nm = p.name.lower()
            if any(h in nm for h in TASK_LEVEL_HINTS):
                task_doc = p
                break
        if task_doc is not None:
            collector.add(
                C.severity_for("missing", level),
                "flow_req_no_spec",
                profile.rel(task_doc), 0,
                f"仅有任务级文档（{profile.rel(task_doc)}），未发现需求规格书",
                "任务清单不能替代需求基线：任务做完就消失，需求要能回答『系统应当满足什么』。"
                "建议建立需求条目并从 assets/templates/ 取 RTM 模板",
                confidence=80,
            )
        return

    # ---- 2) 需求是否条目化（有唯一 ID） ----
    text = _read(req_doc)
    ids = _extract_req_ids(text)

    if not ids:
        collector.add(
            C.severity_for("weak", level),
            "flow_req_no_ids",
            profile.rel(req_doc), 0,
            f"需求文档未发现唯一需求 ID：{profile.rel(req_doc)}（{len(text)} 字符）",
            "无 ID 就无法建立追溯链接，也无法在变更时做影响分析。"
            "建议统一为 REQ-001 / NFR-01 形式；参考 assets/templates/RTM.csv",
            confidence=70,
        )
        return

    # ---- 3) 追溯：需求 ID 是否在测试中被引用（需求↔测试方向） ----
    test_files = [p for p in _iter_test_files(profile)]
    referenced = set()
    seen_files = 0
    for p in test_files:
        if seen_files >= 300:
            break
        seen_files += 1
        t = _read(p)
        for m in REQ_ID_RE.finditer(t):
            referenced.add(_norm_id(m))

    if test_files and not referenced:
        collector.add(
            C.severity_for("weak", level),
            "flow_req_no_test_link",
            profile.rel(req_doc), 0,
            f"需求已在文档中条目化（{len(ids)} 条），但未发现任何测试引用需求 ID",
            "追溯断裂最常发生在这一环：需求变更多次后链接静默失效。"
            "建议在测试用例/断言处标注所覆盖的需求 ID，并生成 RTM",
            confidence=75,
        )
    elif test_files:
        uncovered = sorted(set(ids) - referenced)
        ratio = 1 - len(uncovered) / max(len(ids), 1)
        if ratio < 0.5:
            collector.add(
                "warn", "flow_req_low_coverage", profile.rel(req_doc), 0,
                f"需求被测试引用的比例偏低：{ratio:.0%}（{len(ids) - len(uncovered)}/{len(ids)}）",
                f"未被引用的需求示例：{'、'.join(uncovered[:5])}"
                + ("……" if len(uncovered) > 5 else ""),
                confidence=65,
            )
        else:
            collector.add(
                "info", "flow_req_coverage", profile.rel(req_doc), 0,
                f"需求↔测试引用率：{ratio:.0%}（{len(ids) - len(uncovered)}/{len(ids)}）",
                "需求关联覆盖率优于「总覆盖率」——前者才证明验证充分性",
                confidence=70,
            )

    # ---- 4) RTM 是否存在 ----
    if C.find_deliverable(profile, ["rtm", "追溯矩阵", "追溯表",
                                    "traceability", "覆盖矩阵"])[0] is None:
        collector.add(
            C.severity_for("missing", level),
            "flow_req_no_rtm",
            str(root), 0,
            f"已条目化 {len(ids)} 条需求，但未发现需求追溯矩阵（RTM）",
            "RTM 是认证必查项，也是变更影响分析的唯一载体；"
            "小团队可用 assets/templates/RTM.csv 起步，但需接受「手工矩阵在首次变更后易失效」",
            confidence=80,
        )


# --------------------------------------------------------------------------
def _extract_req_ids(text: str) -> set[str]:
    return {_norm_id(m) for m in REQ_ID_RE.finditer(text)}


def _norm_id(m) -> str:
    return f"{m.group(1).upper()}-{int(m.group(2)):03d}"


def _iter_test_files(profile: C.ProjectProfile):
    """识别测试相关文件（排除 vendor）。"""
    for p in C.iter_project_files(profile.root, max_files=6000):
        lower = profile.rel(p).lower()
        if any(h in lower for h in TEST_FILE_HINTS):
            yield p


def _read(p: Path, limit: int = 200000) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")[:limit]
    except Exception:
        return ""
