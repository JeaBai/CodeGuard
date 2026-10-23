#!/usr/bin/env python3
"""quality_mid_check.py — 生成中逐项自查模块（第二层防线，v3.0.0）

对 AI 正在生成的代码片段做轻量、实时的逐项自查，输出置信度评分，
填补三层防线中缺失的"生成中"层（修复 D4/D5）。

与生成后门禁的区别：
  - 针对「代码片段」而非完整文件，O(片段长度) 轻量检测
  - 仅覆盖可用正则/启发式快速判定的规则（安全红线、复杂度、重复代码）
  - 需全局上下文的规则（架构分层/命名一致性）标记为「需生成后门禁确认」

规则元数据来自 quality_rule_registry（单一事实源），置信度取自注册表。
"""

import re

import quality_rule_registry as _registry
from quality_checks_metrics import LANG_CC_PATTERNS

# 无 LANG_CC_PATTERNS 语言（如 Python）的通用控制流关键字
_GENERIC_CC = [r'\bif\b', r'\bfor\b', r'\bwhile\b', r'\bswitch\b',
               r'\bcase\b', r'\bcatch\b', r'&&', r'\|\|']


def _check_security_pattern(code, pattern):
    """安全红线正则检测，命中返回 (False, 证据)，否则 (True, '')。"""
    m = re.search(pattern, code)
    if m:
        line = code[:m.start()].count("\n") + 1
        return False, f"第 {line} 行: {m.group(0)[:60]}"
    return True, ""


def _check_complexity(code, language):
    """近似圈复杂度（基础 1 + 控制流关键字计数），>10 返回违规。"""
    patterns = LANG_CC_PATTERNS.get(language, _GENERIC_CC)
    cc = 1
    for pat in patterns:
        cc += len(re.findall(pat, code, re.IGNORECASE))
    if cc > 10:
        return False, f"圈复杂度近似 {cc} > 10"
    return True, f"圈复杂度近似 {cc}"


def _check_duplication(code):
    """检测连续重复行（≥6 行相同返回违规）。"""
    lines = [ln for ln in code.split("\n") if ln.strip()]
    max_run = 1
    cur = 1
    for i in range(1, len(lines)):
        if lines[i] == lines[i - 1]:
            cur += 1
            if cur > max_run:
                max_run = cur
        else:
            cur = 1
    if max_run >= 6:
        return False, f"连续 {max_run} 行重复"
    return True, ""


def _dispatch(rule_id, code, language):
    """按规则分发到对应自查函数，返回 (passed, evidence)。"""
    if rule_id == "COMPLEXITY_CC":
        return _check_complexity(code, language)
    if rule_id == "DUPLICATE_CODE":
        return _check_duplication(code)
    rule = _registry.get_rule_by_id(rule_id)
    if rule and rule.get("pattern"):
        return _check_security_pattern(code, rule["pattern"])
    # 需全局上下文的规则（架构分层/命名/单一职责），片段级无法精确判定
    return True, "需生成后门禁确认"


def check_snippet(code, language=".py", file_type="source"):
    """对代码片段逐项自查，返回 [{rule_id, passed, confidence, evidence}]。

    Args:
        code: 待自查的代码片段字符串
        language: 语言扩展名（如 .py/.go/.js），用于选择控制流关键字
        file_type: FileClassifier 五类，决定适用规则集合
    """
    results = []
    for r in _registry.RULE_SPECS:
        if file_type not in r["file_types"]:
            continue
        passed, evidence = _dispatch(r["rule_id"], code, language)
        results.append({
            "rule_id": r["rule_id"],
            "passed": passed,
            "confidence": _registry.get_confidence(r["category"]),
            "evidence": evidence,
        })
    return results


def summarize(results):
    """汇总自查结果：通过数、违规数、平均置信度。"""
    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    avg_conf = sum(r["confidence"] for r in results) // total if total else 0
    return {"total": total, "passed": passed, "failed": total - passed,
            "avg_confidence": avg_conf}
