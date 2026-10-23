#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""工具契约一致性测试 —— project-manager

## 为什么需要它

2026-10-03 查出 PMBOK 三域工具**客观上不可调用**，成因是**契约泄漏实现细节**：
实现直接读取题库内部题号（`data.get('58')`），而契约层（schema / references）不声明键名，
调用方只能猜。同时**漏了 3 题**（56/57/65）、**错配 2 处标签**（58↔57、64↔65）——
这些**都不会报错**，只让报告静默缺失或串位。

本测试把「题库 ↔ 语义键 ↔ 工具实现 ↔ schema」四者的一致性**固化下来**，
使上述三类缺陷**无法再复发**（这正是《模块化与接口设计手册》§6「契约测试」的落地）。

## 防的四类问题

| 断言 | 防什么 |
|---|---|
| `_PHASE_FIELDS` 题号集合 == 题库题号集合 | **漏题**（题库加了题，实现没跟上） |
| 工具读取的 key ⊆ 声明键 | **拼写漂移**（键名写错 → 静默取值失败） |
| 空 answers → 返回问题清单 | **静默失效复发**（应自描述，而不是回全占位） |
| 填满所有键 → 报告零占位 | **静默缺失**（声明了键但报告没用上） |

运行：
    python tests/test_tool_contract.py
    python tests/test_tool_contract.py -v
"""
from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import mcp_data as D            # noqa: E402
import mcp_tools_extended as E  # noqa: E402
import mcp_tools_registry as R  # noqa: E402

# 阶段 → 对应工具（本测试覆盖范围）
PHASE_TOOLS = {
    "phase6_team_health": "team_health_check",
    "phase7_stakeholder": "stakeholder_analysis",
    "phase8_communications": "communications_plan",
}

PLACEHOLDERS = ("未检测", "未评估", "未映射", "未设定", "未定义", "未指定",
                "未列出", "未填写", "N/A", "无记录")


def _bank_ids(phase: str):
    """题库中该阶段的所有题号（唯一事实源）。"""
    p = D.PHASE_QUESTIONS[phase]
    return {q["id"] for sec in p.get("sections", {}).values() for q in sec}


def _render(phase: str):
    tool = PHASE_TOOLS[phase]
    return asyncio.run(getattr(E, f"tool_{tool}")("测试项目", "{}"))


def _render_filled(phase: str, placeholder="有值"):
    import json
    tool = PHASE_TOOLS[phase]
    answers = json.dumps({k: placeholder for k in E._PHASE_FIELDS[phase].values()})
    return asyncio.run(getattr(E, f"tool_{tool}")("测试项目", answers))


# ---------------------------------------------------------- 一、零漏题
def test_no_missing_questions():
    """声明的题号集合必须**等于**题库题号集合 —— 防漏题（曾漏 56/57/65）。"""
    bad = []
    for phase in PHASE_TOOLS:
        decl, bank = set(E._PHASE_FIELDS[phase]), _bank_ids(phase)
        if decl != bank:
            bad.append(f"{phase}: 声明={sorted(decl)} 题库={sorted(bank)} "
                       f"缺={sorted(bank - decl)} 多={sorted(decl - bank)}")
    assert not bad, "题号与题库不一致 →\n  " + "\n  ".join(bad)


def test_field_keys_unique():
    """同一阶段内语义键不得重复（重复会导致多个题写同一个键 → 静默串位）。"""
    for phase, fields in E._PHASE_FIELDS.items():
        vals = list(fields.values())
        dup = {v for v in vals if vals.count(v) > 1}
        assert not dup, f"{phase} 语义键重复: {sorted(dup)}"


# ---------------------------------------------------------- 二、零漂移
def test_tool_reads_only_declared_keys():
    """工具读取的 key 必须都在声明内 —— 防拼写漂移（读错了 key 会静默取默认值）。"""
    for phase, tool in PHASE_TOOLS.items():
        src = Path(SCRIPTS / "mcp_tools_extended.py").read_text(encoding="utf-8")
        m = re.search(rf"async def tool_{tool}\(.*?(?=\nasync def |\Z)", src, re.S)
        assert m, f"未找到 tool_{tool}"
        body = m.group(0)
        if "return _render_questions(" in body:
            body = body.split("return _render_questions(")[1].split("\n", 1)[-1]
        read = set(re.findall(r"data\.get\('([^']+)'", body))
        declared = set(E._PHASE_FIELDS[phase].values())
        extra = read - declared
        assert not extra, f"{tool} 读取了未声明的键: {sorted(extra)}"
        unused = declared - read
        assert not unused, f"{tool} 声明了但未使用的键: {sorted(unused)}"


# ------------------------------------------------- 三、空 answers 须自描述
def test_empty_answers_returns_question_list():
    """空 answers → 必须返回**问题清单**而非占位报告 —— 防\"静默失效\"复发。"""
    for phase in PHASE_TOOLS:
        out = _render(phase)
        assert "未提供 `answers`" in out or "需要回答的问题" in out, \
            f"{phase}: 空 answers 未返回问题清单，仍返回报告 → 调用方会误以为成功"
        for key in E._PHASE_FIELDS[phase].values():
            assert f"`{key}`" in out, f"{phase}: 问题清单缺 key `{key}`"


def test_question_list_covers_bank():
    """问题清单须覆盖题库**全部**题目（题号 + 问题文本）。"""
    for phase in PHASE_TOOLS:
        out = _render(phase)
        p = D.PHASE_QUESTIONS[phase]
        for sec in p["sections"].values():
            for q in sec:
                assert f"| {q['id']} |" in out, f"{phase}: 问题清单缺题号 {q['id']}"


# ---------------------------------------------------------- 四、零静默缺失
def test_filled_report_has_no_placeholder():
    """填满所有键 → 报告不得出现占位词 —— 防\"声明了键但报告没用上\"。"""
    for phase in PHASE_TOOLS:
        out = _render_filled(phase)
        hit = [w for w in PLACEHOLDERS if w in out]
        assert not hit, f"{phase}: 已填全部键，报告仍含占位词 {hit} → 有键未被渲染"


# ---------------------------------------------------------- 五、schema 一致
def test_schema_declares_same_keys():
    """schema 说明里的键集合须与声明一致 —— 防\"文档与代码不一致\"。"""
    for phase, tool in PHASE_TOOLS.items():
        desc = R.TOOL_REGISTRY[tool]["inputSchema"]["properties"]["answers"]["description"]
        declared = set(E._PHASE_FIELDS[phase].values())
        listed = set(re.findall(r"[a-z_]{3,}", desc))
        missing = declared - listed
        assert not missing, f"{tool} 的 schema 未列出: {sorted(missing)}"


# ------------------------------------------------------------- runner
def main():
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    verbose = "-v" in sys.argv
    passed, failed = 0, []
    print("=" * 68)
    print("  工具契约一致性测试（题库 ↔ 语义键 ↔ 实现 ↔ schema）")
    print("=" * 68)
    for name, fn in tests:
        try:
            fn()
            passed += 1
            print(f"  ✅ {name}")
        except AssertionError as e:
            failed.append(name)
            print(f"  ❌ {name}\n       {e}")
        except Exception as e:                       # noqa: BLE001
            failed.append(name)
            print(f"  ❌ {name}\n       {type(e).__name__}: {e}")
        if verbose:
            print(f"       ({fn.__doc__ or ''})")
    print("-" * 68)
    print(f"  {passed}/{len(tests)} 通过" + (f"，{len(failed)} 失败" if failed else " ✅"))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
