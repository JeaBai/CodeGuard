"""风险门禁核心 API — classify / check_gate / confirm / diff / execute。"""
from __future__ import annotations

import os
from datetime import datetime

from risk_gate_store import _GATE_MAP, _find_base_risk, _load_config
from risk_gate_integration import (
    _estimate_impact,
    _check_protection,
    _check_lock,
    _check_tag_forbidden,
    _describe_action,
)

# ============================================================
# 公共 API：classify_risk()
# ============================================================

def classify_risk(action: str, file_path: str = "",
                  function_name: str = "", blueprint_path: str = "",
                  project_root: str = ".") -> dict:
    """分类操作风险等级。

    Args:
        action: 操作名 (如 split_function, change_public_api)。
        file_path: 源文件路径。
        function_name: 函数名（可选）。
        blueprint_path: 蓝图路径（可选，用于影响分析）。
        project_root: 项目根目录。

    Returns:
        {level, reason, gate, base_risk, escalated, escalation_reason}
    """
    base_risk = _find_base_risk(action)
    level = base_risk
    escalated = False
    escalate_reasons: list[str] = []

    config = _load_config()
    esc_rules = config.get("escalation_rules", {})

    # 规则1：影响分析 > 阈值 → 升级
    if file_path and blueprint_path:
        try:
            impact_count = _estimate_impact(file_path, function_name, blueprint_path, project_root)
            thresholds = esc_rules.get("impact_count_threshold", {})
            if base_risk == "low" and impact_count > thresholds.get("from_low_to_medium", 3):
                level = "medium"
                escalated = True
                escalate_reasons.append(f"影响 {impact_count} 处调用 (>3)，升级为 medium")
            elif base_risk == "medium" and impact_count > thresholds.get("from_medium_to_high", 10):
                level = "high"
                escalated = True
                escalate_reasons.append(f"影响 {impact_count} 处调用 (>10)，升级为 high")
        except Exception:
            pass

    # 规则2：intent_protection 保护 → 升级为 high
    if file_path:
        try:
            prot_rules = _check_protection(file_path, project_root)
            if prot_rules:
                level = "high"
                escalated = True
                escalate_reasons.append(f"文件受保护: {prot_rules}")
        except Exception:
            pass

    # 规则3：file_lock → 拒绝
    if file_path:
        try:
            lock_info = _check_lock(file_path, project_root)
            if lock_info.get("locked"):
                return {
                    "level": "rejected",
                    "reason": f"文件被 {lock_info.get('locked_by', '?')} 锁定",
                    "gate": "none",
                    "base_risk": base_risk,
                    "escalated": True,
                    "escalation_reasons": [f"文件锁: {lock_info.get('locked_by', '?')}"],
                    "blocked": True,
                }
        except Exception:
            pass

    # 规则4：标签禁止 → 拒绝
    if file_path and blueprint_path:
        try:
            tag_check = _check_tag_forbidden(action, file_path, blueprint_path, project_root)
            if tag_check.get("forbidden"):
                return {
                    "level": "rejected",
                    "reason": tag_check.get("reason", "标签禁止此操作"),
                    "gate": "none",
                    "base_risk": base_risk,
                    "escalated": True,
                    "escalation_reasons": [tag_check.get("reason", "")],
                    "blocked": True,
                }
        except Exception:
            pass

    gate = _GATE_MAP.get(level, "confirm")

    config_desc = ""
    section = {"low": "auto_approve", "medium": "confirm_required", "high": "manual_required"}.get(level, "")
    if section:
        config_desc = config.get(section, {}).get("description", "")

    return {
        "level": level,
        "reason": f"{config_desc} | 操作: {action}" + (f" | 函数: {function_name}" if function_name else ""),
        "gate": gate,
        "base_risk": base_risk,
        "escalated": escalated,
        "escalation_reasons": escalate_reasons,
        "blocked": False,
    }


# ============================================================
# 公共 API：check_gate()
# ============================================================

def check_gate(action: str, file_path: str = "", function_name: str = "",
               blueprint_path: str = "", project_root: str = ".") -> dict:
    """全量门禁检查（含所有升级规则）。

    Returns:
        {allowed, level, gate, next_step, confirmation_message, blocked, escalate_reasons}
    """
    risk = classify_risk(action, file_path, function_name, blueprint_path, project_root)

    if risk.get("blocked"):
        return {
            "allowed": False,
            "level": risk["level"],
            "gate": "none",
            "next_step": f"无法执行: {risk.get('reason', '')}",
            "confirmation_message": "",
            "blocked": True,
            "escalate_reasons": risk.get("escalation_reasons", []),
        }

    level = risk["level"]
    gate = risk["gate"]

    next_step_map = {
        "low": "自动执行 → 跑测试 → 通过则合并。无需用户确认。",
        "medium": "AI 生成确认消息 → 用户确认 → 执行 → 回检",
        "high": "AI 生成 diff 预览 → 人工逐项确认 → 执行",
    }
    next_step = next_step_map.get(gate, next_step_map["medium"])

    confirm_msg = ""
    if gate == "confirm":
        confirm_msg = f"⚠️ 需要确认: {action} 操作于 {file_path}"
        confirm_msg += (f"::{function_name}()" if function_name else "")
        confirm_msg += f" (风险: {level})"
    elif gate == "manual":
        confirm_msg = f"⛔ 需人工审查: {action} 操作于 {file_path}"
        confirm_msg += (f"::{function_name}()" if function_name else "")
        confirm_msg += f" (风险: {level})"

    return {
        "allowed": True,
        "level": level,
        "gate": gate,
        "next_step": next_step,
        "confirmation_message": confirm_msg,
        "base_risk": risk.get("base_risk", ""),
        "escalated": risk.get("escalated", False),
        "escalate_reasons": risk.get("escalation_reasons", []),
        "blocked": False,
    }


# ============================================================
# 公共 API：generate_confirmation()
# ============================================================

def generate_confirmation(action: str, file_path: str = "",
                          function_name: str = "", details: str = "",
                          module: str = "", line_count: int = 0,
                          targets: str = "3 个小函数") -> str:
    """生成人话确认消息（中风险用）。

    Returns:
        格式化的确认消息字符串，含 [同意] [拒绝] [查看详情]。
    """
    module_name = module or os.path.basename(os.path.dirname(file_path) or ".") or "未知"
    fn_name = function_name or os.path.basename(file_path)

    if not details:
        details = _describe_action(action, file_path, function_name)

    parts = []
    if line_count:
        parts.append(
            f"你的「{module_name}」模块有一段 {line_count} 行的函数 `{fn_name}`。"
        )
    else:
        parts.append(f"在「{module_name}」模块中: {details}")

    action_desc = {
        "split_function": f"建议拆成 {targets}。拆分后行为不变。",
        "extract_duplicate_code": "将从多处重复的代码提取为公共函数。",
        "reduce_nesting": "将用 early return 减少嵌套层级。",
        "refactor_error_handling": "将统一错误处理逻辑。",
        "extract_shared_util": "将公共函数提取到 shared_utils。",
        "optimize_complexity": "将拆分高复杂度函数为多个小函数。",
        "rename_function": f"将重命名 `{fn_name}` 并更新所有调用处。",
        "inline_variable": "将内联冗余的中间变量。",
        "reorder_parameters": "将调整函数参数的顺序。",
    }
    parts.append(action_desc.get(action, details))

    parts.append("[同意] [拒绝] [查看详情]")

    return " ".join(parts)


# ============================================================
# 公共 API：generate_diff_preview()
# ============================================================

def generate_diff_preview(action: str, file_path: str,
                          proposed_changes: str = "",
                          risk_info: dict | None = None) -> str:
    """生成 diff 预览（高风险用）。

    Returns:
        格式化的 diff 预览 Markdown 字符串。
    """
    lines = [
        f"# 🔴 高风险变更预览",
        "",
        f"**操作**: {action}",
        f"**文件**: {file_path}",
        f"**时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
    ]

    if risk_info:
        lines.append(f"**风险等级**: {risk_info.get('level', 'N/A').upper()}")
        if risk_info.get("escalation_reasons"):
            lines.append(f"**升级原因**: {', '.join(risk_info['escalation_reasons'])}")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## 变更说明")
    lines.append("")
    lines.append(_describe_action(action, file_path, ""))
    lines.append("")

    if proposed_changes:
        lines.append("## 提议的变更")
        lines.append("")
        lines.append("```diff")
        lines.append(proposed_changes)
        lines.append("```")
        lines.append("")

    lines.append("## 需要的确认")
    lines.append("")
    lines.append("- [ ] 我理解此变更的影响范围")
    lines.append("- [ ] 我已审查所有受影响文件")
    lines.append("- [ ] 回滚计划已准备就绪")
    lines.append("- [ ] 相关测试已通过")
    lines.append("")
    lines.append("---")
    lines.append(f"*请逐项确认后方可执行*")

    return "\n".join(lines)


# ============================================================
# 公共 API：execute_with_gate()
# ============================================================

def execute_with_gate(action: str, file_path: str, callback,
                      function_name: str = "", blueprint_path: str = "",
                      confirm_fn=None, project_root: str = ".") -> dict:
    """带门禁的执行包装器。

    低风险: 直接调 callback
    中风险: 调 confirm_fn 确认后执行
    高风险: 需要用户逐项确认（返回 pending）

    Returns:
        {executed: bool, level: str, result: any, error: str}
    """
    risk = check_gate(action, file_path, function_name, blueprint_path, project_root)

    if risk.get("blocked"):
        return {"executed": False, "level": risk["level"], "result": None,
                "error": risk.get("next_step", "执行被阻止")}

    if risk["gate"] == "auto":
        try:
            result = callback()
            return {"executed": True, "level": "low", "result": result, "error": None}
        except Exception as e:
            return {"executed": False, "level": "low", "result": None, "error": str(e)}

    elif risk["gate"] == "confirm":
        if confirm_fn:
            try:
                confirmed = confirm_fn(risk["confirmation_message"])
                if confirmed:
                    result = callback()
                    return {"executed": True, "level": "medium", "result": result, "error": None}
                return {"executed": False, "level": "medium", "result": None,
                        "error": "用户拒绝确认"}
            except Exception as e:
                return {"executed": False, "level": "medium", "result": None, "error": str(e)}
        return {"executed": False, "level": "medium", "result": None,
                "error": "中风险操作需要用户确认（提供 --confirm 参数）"}

    else:
        return {"executed": False, "level": "high", "result": None,
                "error": "高风险操作需人工逐项确认。请先审查 diff 预览。"}
