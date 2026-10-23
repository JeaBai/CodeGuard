"""
MCP 工具层 — 8 个阶段专用工具函数 + TOOL_REGISTRY
被 mcp_transport.py 和 mcp_server.py CLI 引用
"""

import json
import logging
import sys
from datetime import date
from pathlib import Path
from typing import Any

from mcp_data import PHASE_QUESTIONS

logger = logging.getLogger(__name__)  # codeguard: ignore GOLD_NO_GLOBAL_STATE


# ============================================================
# 通用解析辅助
# ============================================================

def _safe_parse_json(raw: str, default: Any = None) -> Any:
    """安全解析 JSON 字符串，解析失败时返回默认值并记录日志"""
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        logger.debug("JSON 解析失败，使用默认值 %s，原始输入: %s", default, repr(raw[:80]))
        return default if default is not None else {}


# ============================================================
# 阶段一：可行性研判
# ============================================================

async def tool_start_feasibility_check(project_name: str = "", answers: str = "{}") -> str:
    """启动项目可行性研判（第一阶段）"""
    questions = PHASE_QUESTIONS["phase1_feasibility"]
    user_answers = _safe_parse_json(answers, {})

    result = f"# 项目可行性评估报告\n\n"
    result += f"**项目名称**：{project_name or '未命名项目'}\n"
    result += f"**评估日期**：{date.today().isoformat()}\n"
    result += f"**评估阶段**：{questions['name']}\n\n"

    result += "## 决策矩阵\n\n"
    result += "| 维度 | 得分(1-5) | 说明 |\n"
    result += "|------|-----------|------|\n"
    dimensions = [
        ("需求真实性", "target user pain points are real and urgent"),
        ("市场空间", "market size and growth potential"),
        ("资源匹配度", "resources and capabilities match requirements"),
        ("风险可控性", "risks are identifiable and manageable"),
    ]
    total = 0
    for dim_name, _ in dimensions:
        score = user_answers.get(dim_name, 3)
        total += score
        desc = user_answers.get(f"{dim_name}_desc", "")
        result += f"| {dim_name} | {score} | {desc} |\n"
    result += f"| **综合得分** | **{total}/20** | {'✅ ≥15 建议启动' if total >= 15 else '⚠️ 10-14 需补充调研' if total >= 10 else '❌ <10 建议暂缓'} |\n\n"

    result += "## 调研问题清单\n\n"
    for section_name, items in questions["sections"].items():
        result += f"### {section_name}\n\n"
        for item in items:
            answer = user_answers.get(str(item["id"]), "（未填写）")
            result += f"- [{item['id']}] **{item['question']}**\n"
            result += f"  - 目的：{item['purpose']}\n"
            result += f"  - 回答：{answer}\n\n"

    return result


# ============================================================
# 阶段二：启动规划
# ============================================================

async def tool_create_project_plan(
    project_name: str = "",
    deadline: str = "",
    answers: str = "{}",
) -> str:
    """生成项目启动规划书（第二阶段）"""
    questions = PHASE_QUESTIONS["phase2_planning"]
    user_answers = _safe_parse_json(answers, {})

    result = f"# 项目启动规划书\n\n"
    result += f"**项目名称**：{project_name or '未命名项目'}\n"
    result += f"**目标交付日期**：{deadline or '待定'}\n"
    result += f"**规划日期**：{date.today().isoformat()}\n\n"

    result += "## 质量标准定义\n\n"
    result += "| 维度 | 定义 |\n"
    result += "|------|------|\n"
    result += f"| 高质量定义 | {user_answers.get('12', '待定义')} |\n"
    result += f"| 最低验收标准 | {user_answers.get('13', '待定义')} |\n"
    result += f"| 非功能需求 | {user_answers.get('14', '待定义')} |\n"
    result += f"| UX标准 | {user_answers.get('15', '待定义')} |\n\n"

    result += "## 里程碑计划\n\n"
    result += "| 里程碑 | 日期 | 交付物 | 验收标准 |\n"
    result += "|--------|------|--------|----------|\n"
    result += "| M1: 基础搭建 | | | |\n"
    result += "| M2: 核心功能 | | | |\n"
    result += "| M3: 集成测试 | | | |\n"
    result += "| M4: MVP发布 | | | |\n\n"

    result += "## 技术选型决策矩阵\n\n"
    result += "| 方案 | 优势 | 劣势 | 社区活跃度 | 学习曲线 | 维护成本 | 推荐 |\n"
    result += "|------|------|------|-----------|----------|----------|------|\n"
    result += f"| {user_answers.get('20_choice', '待定')} | | | | | | |\n\n"

    result += "## 偏差预警机制\n\n"
    result += f"- 延期10%预警线：{user_answers.get('19', '待定义')}\n"
    result += "- 应急响应负责人：待指定\n\n"

    result += "## 完整调研清单\n\n"
    for section_name, items in questions["sections"].items():
        result += f"### {section_name}\n\n"
        for item in items:
            answer = user_answers.get(str(item["id"]), "（未填写）")
            result += f"- [{item['id']}] **{item['question']}** → {answer}\n"
        result += "\n"

    return result


# ============================================================
# 阶段三：执行跟踪
# ============================================================

async def tool_daily_progress_check(answers: str = "{}") -> str:
    """每日进度自检（第三阶段日常）"""
    today = date.today().isoformat()
    user_answers = _safe_parse_json(answers, {})

    result = f"# 每日进度检查 — {today}\n\n"
    result += "## 今日完成\n\n"
    result += f"- {user_answers.get('today_done', '请记录今日完成事项')}\n\n"
    result += "## 进度状态\n\n"
    status = user_answers.get("status", "待评估")
    status_emoji = {"提前": "🟢", "正常": "🟡", "滞后": "🔴"}.get(status, "⚪")
    result += f"- 状态：{status_emoji} {status}\n\n"
    result += "## 阻塞识别\n\n"
    result += f"- 当前阻塞点：{user_answers.get('blocker', '无')}\n"
    result += f"- 解决计划：{user_answers.get('blocker_plan', '—')}\n\n"
    result += "## 自检问题\n\n"
    result += "- [ ] 今天完成了什么？跟计划比是提前还是滞后？\n"
    result += "- [ ] 当前最大的阻塞点是什么？能否在今天内解决？\n\n"
    result += "---\n*提示：使用 `quality_gate_check` 工具进行完整质量门禁检查*\n"

    return result


async def tool_quality_gate_check(answers: str = "{}") -> str:
    """质量门禁检查（第三阶段周检）"""
    user_answers = _safe_parse_json(answers, {})
    today = date.today().isoformat()
    result = f"# 质量门禁检查报告 — {today}\n\n"

    checks = [
        ("自测覆盖率", "是否遗漏边界情况？", user_answers.get("edge_cases", "未检查")),
        ("测试完整性", f"核心路径覆盖率: {user_answers.get('coverage', '未测量')}%", user_answers.get("coverage_detail", "")),
        ("技术债务", "是否有临时方案未偿还？", user_answers.get("tech_debt", "未检查")),
        ("反馈模式", "用户反馈中的重复问题", user_answers.get("feedback_pattern", "无新问题")),
        ("质量红线", "是否因赶进度牺牲质量？", user_answers.get("quality_breach", "未检查")),
    ]

    all_pass = True
    for name, detail, status_str in checks:
        is_fail = "否" in str(status_str) or "未" in str(status_str)
        if is_fail:
            all_pass = False
        icon = "✅" if not is_fail else "⚠️"
        result += f"### {icon} {name}\n"
        result += f"- {detail}\n"
        result += f"- 状态：{status_str}\n\n"

    result += f"\n## 综合判定\n\n"
    result += f"{'✅ 全部通过 — 质量门禁放行' if all_pass else '⚠️ 存在问题 — 请修复后重新检查'}\n"

    return result


async def tool_vision_tracker_scan(domain: str = "", keywords: str = "") -> str:
    """自动扫描技术趋势 & 视野跟踪"""
    today = date.today().isoformat()
    week_num = today.isocalendar()[1]

    result = f"# 每周视野跟踪报告 — W{week_num} ({today})\n\n"
    result += f"**关注领域**：{domain or '通用技术'}\n"
    result += f"**关键词**：{keywords or '未指定'}\n\n"

    result += "## 🔭 技术趋势扫描\n\n"
    result += "### GitHub Trending 信号\n\n"
    result += (
        "> ⚠️ 自动扫描需要网络连接。以下为推荐手动检查项：\n\n"
        "1. 访问 https://github.com/trending 查看当日热门项目\n"  # codeguard: ignore GOLD_NO_HARDCODED_URL
        "2. 过滤与你的领域相关的项目\n"
        "3. 关注 Star 增长速度和社区讨论活跃度\n\n"
    )

    result += "### AI/工具迭代信号\n\n"
    result += (
        "推荐检查来源：\n"
        "- Hacker News (https://news.ycombinator.com/)\n"  # codeguard: ignore GOLD_NO_HARDCODED_URL
        "- Product Hunt (https://www.producthunt.com/)\n"  # codeguard: ignore GOLD_NO_HARDCODED_URL
        "- 各技术栈官方博客和 Changelog\n"
        "- Twitter/X 技术 KOL 动态\n\n"
    )

    result += "### 框架/平台更新预警\n\n"
    result += (
        "推荐关注：\n"
        "- 所用语言/框架的 Release Notes\n"
        "- 云平台服务变更公告\n"
        "- 安全漏洞披露 (CVE)\n\n"
    )

    result += "## 💬 用户/市场信号\n\n"
    result += "| 检查项 | 状态 | 发现 |\n"
    result += "|--------|------|------|\n"
    result += "| 竞品动态 | 待检查 | |\n"
    result += "| 用户社区讨论 | 待检查 | |\n"
    result += "| 新替代方案 | 待检查 | |\n"
    result += "| 口碑变化 | 待检查 | |\n\n"

    result += "## 🧠 认知破圈自检\n\n"
    result += "- [ ] 今天是否读了反对我既有观点的内容？\n"
    result += "- [ ] 我的信息源是否过于同质化？\n"
    result += "- [ ] 是否需要关注相邻领域的发展？\n\n"

    result += "---\n"
    result += "*提示：可使用联网搜索工具自动填充以上内容。建议每周固定30分钟执行此扫描。*\n"

    return result


# ============================================================
# 阶段四：复盘沉淀
# ============================================================

async def tool_generate_retrospective(
    project_name: str = "",
    answers: str = "{}",
) -> str:
    """生成项目复盘报告（第四阶段）"""
    user_answers = _safe_parse_json(answers, {})

    result = f"# 项目复盘报告\n\n"
    result += f"**项目名称**：{project_name or '未命名项目'}\n"
    result += f"**复盘日期**：{date.today().isoformat()}\n\n"

    result += "## 📊 目标达成率\n\n"
    result += f"- 目标达成情况：{user_answers.get('38', '待评估')}\n"
    result += f"- 偏差分析：{user_answers.get('38_detail', '')}\n\n"

    result += "## ✅ 经验资产化\n\n"
    result += "### 做对了（下次复用）\n"
    result += f"{user_answers.get('39_good', '待整理')}\n\n"
    result += "### 做错了（下次避免）\n"
    result += f"{user_answers.get('39_bad', '待整理')}\n\n"

    result += "## ⏱️ 时间偏差分析\n\n"
    result += "| 环节 | 预估 | 实际 | 偏差 | 原因 |\n"
    result += "|------|------|------|------|------|\n"
    result += f"| | | | | |\n\n"

    result += "## 💬 用户反馈总结\n\n"
    result += f"- 超出预期：{user_answers.get('41_exceed', '待整理')}\n"
    result += f"- 低于预期：{user_answers.get('41_below', '待整理')}\n\n"

    result += "## 🔮 续投决策\n\n"
    result += f"- 是否做V2.0：{user_answers.get('42', '待决策')}\n"
    result += f"- 依据：{user_answers.get('42_reason', '')}\n\n"

    result += "## 🗂️ 知识沉淀\n\n"
    result += f"- 可复用资产：{user_answers.get('43', '待整理')}\n"
    result += f"- 踩坑记录：{user_answers.get('44', '待整理')}\n"
    result += f"- 工具链升级：{user_answers.get('45', '无')}\n"
    result += f"- 核心经验：{user_answers.get('46', '待提炼')}\n\n"

    result += "---\n*以上为复盘报告框架，请补充具体数据和反思。*\n"
    return result


async def tool_knowledge_asset_export(project_name: str = "", assets: str = "[]") -> str:
    """导出知识沉淀文档（第四阶段）"""
    asset_list = _safe_parse_json(assets, [])

    result = f"# 知识沉淀文档 — {project_name or '未命名项目'}\n\n"
    result += f"**导出日期**：{date.today().isoformat()}\n\n"

    result += "## 📦 可复用资产清单\n\n"
    if asset_list:
        for i, asset in enumerate(asset_list, 1):
            result += f"### {i}. {asset.get('name', '未命名')}\n"
            result += f"- 类型：{asset.get('type', '代码/模板/流程/文档')}\n"
            result += f"- 描述：{asset.get('desc', '')}\n"
            result += f"- 复用场景：{asset.get('scenario', '')}\n"
            result += f"- 存储位置：{asset.get('location', '待归档')}\n\n"
    else:
        result += "（请添加可复用资产信息）\n\n"

    result += "## 🕳️ 踩坑记录\n\n"
    result += "| # | 坑描述 | 原因 | 解决方案 | 预防措施 |\n"
    result += "|---|--------|------|----------|----------|\n"
    result += "| 1 | | | | |\n\n"

    result += "## 🔧 工具链/Prompt库升级\n\n"
    result += "- 新增工具：\n"
    result += "- 升级工具：\n"
    result += "- 新增Prompt模板：\n"
    result += "- 废弃工具：\n\n"

    result += "## 💡 核心经验（一句话）\n\n"
    result += "> 如果让另一个人来做这个项目，我最想告诉他的是：\n\n"
    result += "（待填写）\n"

    return result


# ============================================================
# 阶段五：视野跟踪
# ============================================================

async def tool_weekly_vision_report(domain: str = "", findings: str = "{}") -> str:
    """生成每周视野跟踪报告（第五阶段）"""
    today = date.today().isoformat()
    week_num = today.isocalendar()[1]
    user_findings = _safe_parse_json(findings, {})

    result = f"# 每周视野跟踪周报 — W{week_num} ({today})\n\n"
    result += f"**关注领域**：{domain or '通用'}\n\n"

    result += "## 🔭 技术趋势\n\n"
    for q_id, label in [("47", "GitHub Trending"), ("48", "AI新工具"), ("49", "框架更新"), ("50", "行业动态")]:
        result += f"### {label}\n"
        result += f"{user_findings.get(q_id, '（本周未扫描）')}\n\n"

    result += "## 💬 市场信号\n\n"
    for q_id, label in [("52", "用户社区"), ("53", "新竞品"), ("54", "口碑分析"), ("55", "改进方向")]:
        result += f"### {label}\n"
        result += f"{user_findings.get(q_id, '（本周未扫描）')}\n\n"

    result += "## 🧠 认知破圈自检\n\n"
    result += f"- 是否读了反对观点的内容：{user_findings.get('51', '否')}\n"
    result += f"- 信息源多样性评估：{user_findings.get('info_diversity', '待评估')}\n"
    result += f"- 下周关注重点：{user_findings.get('next_focus', '待定')}\n\n"

    result += "## 📈 信号强度仪表\n\n"
    result += "| 信号类型 | 强度 | 建议行动 |\n"
    result += "|----------|------|----------|\n"
    result += "| 技术转向信号 | 低/中/高 | |\n"
    result += "| 市场变化信号 | 低/中/高 | |\n"
    result += "| 竞争威胁信号 | 低/中/高 | |\n"
    result += "| 机会窗口信号 | 低/中/高 | |\n"

    return result
