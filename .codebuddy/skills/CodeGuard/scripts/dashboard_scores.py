"""看板多维度评分计算。"""
from __future__ import annotations

# ============================================================
# 评分计算
# ============================================================

def _calc_scores(issues: list[dict], blueprint: dict, coverage: float = 0) -> dict:
    """根据 CodeGuard issue + 蓝图数据计算多维度评分。"""
    high = sum(1 for i in issues if i.get("severity") == "block")
    medium = sum(1 for i in issues if i.get("severity") == "warn")
    low = sum(1 for i in issues if i.get("severity") == "info")

    # 识别安全相关 issue
    security_cats = {"security", "GOLD_NO_SQL_CONCAT", "GOLD_NO_EVAL", "GOLD_NO_OS_SYSTEM",
                     "GOLD_NO_HARDCODED_URL", "k8s", "tf-"}
    high_sec = sum(1 for i in issues
                   if i.get("severity") == "block"
                   and any(c in (i.get("category", "") + i.get("rule", "")) for c in security_cats))
    med_sec = sum(1 for i in issues
                  if i.get("severity") == "warn"
                  and any(c in (i.get("category", "") + i.get("rule", "")) for c in security_cats))

    security = max(0, min(100, 100 - high_sec * 20 - med_sec * 5))
    code_quality = max(0, min(100, 100 - high * 10 - medium * 2 + int(coverage * 0.1)))

    # 架构：依赖图中的循环 + 重复块
    cycles = 0
    dup_blocks = 0
    for i in issues:
        if i.get("category") in ("architecture_cycle", "architecture"):
            cycles += 1
        if i.get("category") == "duplication" and i.get("severity") == "block":
            dup_blocks += 1

    architecture = max(0, min(100, 100 - cycles * 30 - dup_blocks * 5))
    overall = round(security * 0.4 + code_quality * 0.3 + architecture * 0.3)

    def _status(s: int) -> str:
        return "good" if s >= 85 else ("warn" if s >= 60 else "danger")

    def _detail(s: int, label: str) -> str:
        if s >= 90: return f"无{label}问题"
        if s >= 70: return f"{label}基本健康"
        return f"{label}需要关注"

    return {
        "overall_score": overall,
        "dimensions": {
            "security": {"score": security, "status": _status(security),
                         "label": "🔒 安全", "detail": _detail(security, "安全")},
            "code_quality": {"score": code_quality, "status": _status(code_quality),
                             "label": "🧹 代码", "detail": _detail(code_quality, "代码")},
            "architecture": {"score": architecture, "status": _status(architecture),
                             "label": "📐 架构", "detail": _detail(architecture, "架构")},
        },
        "issues": {"high": [i for i in issues if i.get("severity") == "block"][:8],
                   "medium": [i for i in issues if i.get("severity") == "warn"][:8],
                   "low": [i for i in issues if i.get("severity") == "info"][:8]},
    }
