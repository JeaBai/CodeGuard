#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""quality_modular 测试 —— 模块化与接口设计检测器（CodeGuard v3.1.0）

设计要点：
  · **零依赖**：环境无 pytest，用内置简易 runner 直跑；函数仍命名 `test_*`，可被 pytest 接管。
  · **双向验证**：违例样本必须"全中"，干净样本必须"零误报" —— 只测前者会漏掉误报。
  · **对齐校验**：规则须登记在 `quality_rule_registry.RULE_SPECS`（三层防线共用的事实源），
    本测试强制校验，防止检测器与注册表脱节。
  · **误报回归**：每个踩过的坑都有具名测试，防止回归。

运行：
    python tests/test_modularity.py
    python tests/test_modularity.py -v
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
FIXTURES = HERE / "fixtures"
sys.path.insert(0, str(SCRIPTS))

import quality_core as core            # noqa: E402
import quality_core_collector as cc    # noqa: E402
import quality_modular as M            # noqa: E402
import quality_rule_registry as R      # noqa: E402

# 本模块负责的 9 条规则（与 RULE_SPECS 中 MOD_* 一致）
MOD_RULES = {
    "MOD_CROSS_HARDCODE", "MOD_PRIVATE_ACCESS", "MOD_DUP_STEMS",
    "MOD_NO_INTERFACE_DOC", "MOD_NO_TIMEOUT", "MOD_NO_TEST_SPLIT",
    "MOD_NO_CONTRACT_TEST", "MOD_NO_LOCKFILE", "MOD_FLOATING_DEP",
}
# 本模块使用的 category（别人不得重复占用，否则得去重）
MOD_CATEGORIES = {"modularity", "modularity_doc", "resilience",
                  "contract", "test_strategy", "reproducibility"}


def _scan(name):
    """对样本跑一次检测，返回 (issues, categories)。"""
    root = str((FIXTURES / name).resolve())
    files = core.find_source_files(root)
    col = cc.IssueCollector()
    M.check_modularity(files, col, root)
    cats = {i.get("category") for i in col.issues}
    return col.issues, cats


# ---------------------------------------------------------------- 检测能力
def test_violating_all_rules_detected():
    """违例样本：本模块负责的 6 类问题必须全部命中（漏判 = 防线失效）。"""
    _, cats = _scan("violating")
    missed = MOD_CATEGORIES - cats
    assert not missed, f"漏判类别: {sorted(missed)}（应全部命中）"


def test_violating_no_foreign_category():
    """只应产出本模块的类别，不得越界污染其他检测器的 category。"""
    _, cats = _scan("violating")
    extra = cats - MOD_CATEGORIES
    assert not extra, f"越界产出类别: {sorted(extra)}"


def test_clean_zero_false_positive():
    """干净样本：本模块必须零发现（误报会让团队弃用门禁）。"""
    issues, cats = _scan("clean")
    mine = [i for i in issues if i.get("category") in MOD_CATEGORIES]
    assert not mine, ("干净样本出现误报: "
                      + "; ".join(f"{i['category']}@{i.get('file')}" for i in mine))


# ------------------------------------------------------- 与三层防线的对齐
def test_rules_registered_in_registry():
    """9 条规则须登记在 RULE_SPECS —— 否则生成前注入/生成中自查拿不到它们。"""
    ids = {s["rule_id"] for s in R.RULE_SPECS}
    missing = MOD_RULES - ids
    assert not missing, f"未登记进 RULE_SPECS: {sorted(missing)}"


def test_categories_have_confidence():
    """使用的 category 须在 CONFIDENCE_BASE 中有定义（否则退化到默认 80）。"""
    for c in MOD_CATEGORIES:
        assert c in R.CONFIDENCE_BASE, f"category {c!r} 未在 CONFIDENCE_BASE 登记"


def test_issue_shape_complete():
    """每条发现须字段齐全 —— 缺 fix 等于只报错不给解法。"""
    issues, _ = _scan("violating")
    mine = [i for i in issues if i.get("category") in MOD_CATEGORIES]
    assert mine, "违例样本未产出任何本模块发现"
    for it in mine:
        for k in ("severity", "category", "file", "line", "message"):
            assert k in it, f"{it.get('category')} 缺字段 {k}"
        assert it["message"], "message 不得为空"


# ------------------------------------------------- 误报回归（附注真实踩坑经过）
def test_regression_minified_vendor_not_flagged():
    """回归：压缩/第三方产物不得当自研源码扫。

    真实踩坑：`echarts.min.js` / `mermaid.min.js` 内部的绝对路径被报成
    "跨模块硬编码"。样本内含 `moduleA/vendor.min.js`（绝对路径 + 超长行），须被过滤。
    """
    issues, _ = _scan("clean")
    hit = [i for i in issues
           if i.get("category") == "modularity" and "min.js" in str(i.get("file", ""))]
    assert not hit, "压缩产物被误判为跨模块硬编码"


def test_regression_cross_language_stem_not_flagged():
    """回归：跨语言同名不构成 import 歧义。

    真实踩坑：`mixer.c`（固件）与 `mixer.py`（仿真）撞名被报 MOD_DUP_STEMS。
    样本内含 moduleA/helper.py 与 moduleB/helper.c，应被忽略。
    """
    issues, _ = _scan("clean")
    dup = [i for i in issues if i.get("category") == "modularity"
           and "同名脚本" in str(i.get("message", ""))]
    assert not dup, "跨语言同名被误判为 import 歧义"


def test_regression_same_language_stem_still_detected():
    """反向保证：**同语言**同名仍须检出（别把规则修没了）。"""
    issues, _ = _scan("violating")
    dup = [i for i in issues if "同名脚本" in str(i.get("message", ""))]
    assert dup, "同语言同名（helper.py × 2）漏判了"


# ---------------------------------------------------------------- runner
def main():
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    verbose = "-v" in sys.argv
    passed, failed = 0, []
    print("=" * 68)
    print("  quality_modular 测试（CodeGuard 模块化与接口设计检测器）")
    print("=" * 68)
    for name, fn in tests:
        try:
            fn()
            passed += 1
            print(f"  ✅ {name}")
        except AssertionError as e:
            failed.append((name, str(e)))
            print(f"  ❌ {name}\n       {e}")
        except Exception as e:                       # noqa: BLE001
            failed.append((name, f"{type(e).__name__}: {e}"))
            print(f"  ❌ {name}\n       {type(e).__name__}: {e}")
        if verbose:
            print(f"       ({fn.__doc__ or ''})")
    print("-" * 68)
    print(f"  {passed}/{len(tests)} 通过"
          + (f"，{len(failed)} 失败" if failed else " ✅"))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
