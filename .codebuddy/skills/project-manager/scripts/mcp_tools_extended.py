"""
MCP 工具层扩展 — 阶段六~十工具函数（PMBOK 绩效域 + TencentDB 对齐）。
复用 mcp_tools_phases 的 _safe_parse_json。
"""
import json
import os
import sys
from pathlib import Path

from mcp_tools_phases import _safe_parse_json

# ============================================================
# 阶段六-八：团队/干系人/沟通（PMBOK 绩效域）
#
# 契约设计（2026-10-03 重构）：
#   · 对外入参用**语义键**，不再暴露题库内部的题号（原实现直接暴露题号 → 契约泄漏）
#   · `_PHASE_FIELDS` 是「题号 → 语义键」的**唯一映射**，必须与 `mcp_data.PHASE_QUESTIONS`
#     一一对应 —— 由 `tests/test_tool_contract.py` 强制校验（防漏题 / 防漂移）
#   · 未提供 answers 时**返回问题清单**（自描述问答协议），调用方不必猜键名
# ============================================================

_PHASE_FIELDS = {
    # phase6：团队健康（题库 56–63，8 题）
    "phase6_team_health": {
        56: "team_roster",        # 成员人数 / 角色 / 技能矩阵
        57: "role_gaps",          # 关键岗位人力缺口（Bus Factor）
        58: "context_switching",  # 多任务稀释（上下文切换）
        59: "morale",             # 团队士气 1-5
        60: "conflicts",          # 未解决冲突
        61: "deep_work_hours",    # 日均深度工作
        62: "onboarding",         # 新人融入
        63: "last_retro",         # 改进闭环
    },
    # phase7：干系人（题库 64–69，6 题）
    "phase7_stakeholder": {
        64: "stakeholders",       # 干系人清单 / 影响力 / 利益关联
        65: "power_map",          # 最终决策者 / 否决权（权力图谱）
        66: "attitude",           # 态度分类
        67: "comm_frequency",     # 沟通频率与渠道
        68: "info_asymmetry",     # 信息不对称
        69: "pending_feedback",   # 反馈闭环
    },
    # phase8：沟通（题库 70–74，5 题）
    "phase8_communications": {
        70: "comm_cadence",       # 正式沟通节奏
        71: "escalation_path",    # 上报路径与 SLA
        72: "external_contact",   # 外部联络点
        73: "primary_tool",       # 主要沟通工具
        74: "decision_traceability",  # 决策追溯性
    },
}


def _questions(phase: str):
    """从题库导出该阶段问题清单（含语义 key）。**题库是唯一事实源。**"""
    from mcp_data import PHASE_QUESTIONS
    fields = _PHASE_FIELDS[phase]
    out = []
    for section, qs in PHASE_QUESTIONS[phase]["sections"].items():
        for q in qs:
            out.append({
                "id": q["id"],
                "key": fields.get(q["id"], ""),
                "section": section,
                "question": q["question"],
                "purpose": q.get("purpose", ""),
            })
    return out


def _render_questions(phase: str, project_name: str) -> str:
    """空 answers 时返回问题清单 —— 契约自描述，调用方按 key 填答（方案 B）。"""
    from mcp_data import PHASE_QUESTIONS
    lines = [
        f"# {PHASE_QUESTIONS[phase]['name']} — {project_name or '未命名项目'}",
        "",
        "未提供 `answers`。以下是本阶段需要回答的问题，请按 **`key`** 组织 JSON 后再次调用：",
        "",
        "| key | 题号 | 问题 | 用途 |",
        "|---|---|---|---|",
    ]
    for q in _questions(phase):
        lines.append(f"| `{q['key']}` | {q['id']} | {q['question']} | {q['purpose']} |")
    first = _questions(phase)[0]["key"]
    lines += ["", f'示例：`answers=\'{{"{first}": "你的回答"}}\'`']
    return "\n".join(lines)


async def tool_team_health_check(project_name: str = "", answers: str = "{}") -> str:
    """团队健康检查（PMBOK Team 绩效域）。

    题库 phase6（题 56–63，8 题）全覆盖。空 answers → 返回问题清单。
    """
    data = _safe_parse_json(answers, {})
    if not data:
        return _render_questions("phase6_team_health", project_name)
    result = f"# 团队健康评估 — {project_name or '未命名项目'}\n\n"
    result += "## 团队构成与技能矩阵\n\n"
    result += f"- 成员与角色: {data.get('team_roster', '未填写')}\n"
    result += f"- 关键岗位缺口 (Bus Factor): {data.get('role_gaps', '未检测')}\n"
    result += f"- 多任务稀释: {data.get('context_switching', '未检测')}\n\n"
    result += "## 协作健康度\n\n"
    result += f"- 团队士气 (1-5): {data.get('morale', 'N/A')}\n"
    result += f"- 未解决冲突: {data.get('conflicts', '无')}\n"
    result += f"- 日均深度工作: {data.get('deep_work_hours', 'N/A')}\n"
    result += f"- 新人融入: {data.get('onboarding', 'N/A')}\n\n"
    result += "## 改进闭环\n\n"
    result += f"- 上次 retro: {data.get('last_retro', '无记录')}\n"
    return result


async def tool_stakeholder_analysis(project_name: str = "", answers: str = "{}") -> str:
    """干系人分析（PMBOK Stakeholder 绩效域）。

    题库 phase7（题 64–69，6 题）全覆盖。空 answers → 返回问题清单。
    """
    data = _safe_parse_json(answers, {})
    if not data:
        return _render_questions("phase7_stakeholder", project_name)
    result = f"# 干系人分析 — {project_name or '未命名项目'}\n\n"
    result += "## 干系人矩阵\n\n"
    result += f"- 干系人清单（角色/影响力/利益）: {data.get('stakeholders', '未列出')}\n"
    result += f"- 权力图谱（决策者/否决权）: {data.get('power_map', '未映射')}\n"
    result += f"- 态度分类 (积极/中立/阻力): {data.get('attitude', '未评估')}\n\n"
    result += "## 参与策略\n\n"
    result += f"- 沟通频率与渠道: {data.get('comm_frequency', '未设定')}\n"
    result += f"- 信息不对称: {data.get('info_asymmetry', '未检测')}\n"
    result += f"- 未处理反馈: {data.get('pending_feedback', '无')}\n"
    return result


async def tool_communications_plan(project_name: str = "", answers: str = "{}") -> str:
    """沟通计划（PMBOK Communications 绩效域）。

    题库 phase8（题 70–74，5 题）全覆盖。空 answers → 返回问题清单。
    """
    data = _safe_parse_json(answers, {})
    if not data:
        return _render_questions("phase8_communications", project_name)
    result = f"# 沟通计划 — {project_name or '未命名项目'}\n\n"
    result += "## 沟通节奏\n"
    result += f"- 正式沟通节奏: {data.get('comm_cadence', '未定义')}\n\n"
    result += "## 应急协议\n"
    result += f"- 上报路径与 SLA: {data.get('escalation_path', '未定义')}\n"
    result += f"- 外部联络点: {data.get('external_contact', '未指定')}\n\n"
    result += "## 渠道效能\n"
    result += f"- 主要工具: {data.get('primary_tool', '未评估')}\n"
    result += f"- 决策追溯性: {data.get('decision_traceability', '未评估')}\n"
    return result


# ============================================================
# 阶段九-十：团队经验资产库 + 多Agent角色矩阵（v2.3 TencentDB 对齐）
# ============================================================

async def tool_manage_experience_library(project_name: str = "", action: str = "stats", **kwargs) -> str:
    """管理团队经验资产库（对标 TencentDB Agent Memory）"""
    try:
        from experience_library import register, search, stats as lib_stats, load_to_context
    except ImportError:
        return "# 经验资产库\n\n错误: experience_library.py 未找到"

    if action == "register":
        r = register(
            asset_type=kwargs.get("asset_type", "skill"),
            title=kwargs.get("title", ""),
            content=kwargs.get("content", ""),
            tags=kwargs.get("tags", ""),
            visibility=kwargs.get("visibility", "private"),
            project_name=project_name,
            owner=kwargs.get("owner", ""),
            source=kwargs.get("source", ""),
        )
        return json.dumps(r, ensure_ascii=False, indent=2)

    if action == "search":
        results = search(
            keywords=kwargs.get("keywords", ""),
            visibility_filter=kwargs.get("visibility", ""),
            asset_type_filter=kwargs.get("asset_type", ""),
        )
        if not results:
            return f"# 经验资产搜索\n\n未找到匹配资产（搜索: {kwargs.get('keywords', '全部')}）"
        lines = [f"# 经验资产搜索结果 ({len(results)} 条)\n"]
        for a in results:
            lines.append(f"- [{a.get('asset_type', '?')}] **{a.get('title', '?')}** "
                         f"(`{a.get('asset_id', '?')}`) v{a.get('version', '?')} "
                         f"| 可见性: {a.get('visibility', '?')}")
        return "\n".join(lines)

    if action == "load":
        aid = kwargs.get("asset_id", "")
        ctx = load_to_context(aid)
        return json.dumps(ctx, ensure_ascii=False, indent=2)

    # default: stats
    s = lib_stats()
    lines = [f"# 经验资产库统计\n",
             f"- 总资产: {s['total_assets']}",
             f"- 按类型: {s['by_type']}",
             f"- 按可见性: {s['by_visibility']}",
             f"- 按状态: {s['by_status']}"]
    return "\n".join(str(l) for l in lines)


async def tool_configure_agent_roster(project_name: str = "", action: str = "list-roles", **kwargs) -> str:
    """配置多 Agent 角色矩阵（对标 TencentDB Team→Agent→Loadout）"""
    try:
        from agent_roster import (
            define_role, assign_memory, create_squad, export_manifest,
            list_roles as roster_list, _PRESET_ROLES,
        )
    except ImportError:
        return "# Agent 角色矩阵\n\n错误: agent_roster.py 未找到"

    team = project_name or kwargs.get("team", "default")

    if action == "define-role":
        r = define_role(
            role_name=kwargs.get("role_name", ""),
            responsibilities=kwargs.get("responsibilities", ""),
            skill_requirements=kwargs.get("skills", ""),
            team_name=team,
        )
        return json.dumps(r, ensure_ascii=False, indent=2)

    if action == "assign-memory":
        r = assign_memory(
            role_name=kwargs.get("role_name", ""),
            asset_ids=kwargs.get("asset_ids", ""),
            team_name=team,
        )
        return json.dumps(r, ensure_ascii=False, indent=2)

    if action == "create-squad":
        r = create_squad(
            team_name=team,
            roles=kwargs.get("roles", ""),
            collaboration_rules=kwargs.get("rules", ""),
        )
        return json.dumps(r, ensure_ascii=False, indent=2)

    if action == "export-manifest":
        return export_manifest(team, fmt=kwargs.get("format", "markdown"))

    # default: list roles
    r = roster_list(team_name=team if team != "default" else "")
    return json.dumps(r, ensure_ascii=False, indent=2)


async def tool_sync_adr_decisions(project_name: str = "", answers: str = "{}") -> str:
    """将项目关键决策同步到 governance-hub ADR 管理器"""
    data = _safe_parse_json(answers, {})
    adr_entries = data.get("decisions", [])

    # 尝试调用 governance-hub 的 adr_manager
    result = "# ADR 决策同步\n\n"
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent /
                                "governance-hub" / "scripts"))
        from adr_manager import ADRManager
        mgr = ADRManager(data_dir=data.get("data_dir", ".codebuddy/adr"))
    except (ImportError, ModuleNotFoundError):
        result += "⚠️ governance-hub ADR 管理器未安装，决策记录将仅保存在本地经验资产库。\n\n"

    result += f"**项目**: {project_name or '未命名'}\n"
    result += f"**决策数**: {len(adr_entries) if isinstance(adr_entries, list) else 0}\n\n"

    if isinstance(adr_entries, list):
        for i, entry in enumerate(adr_entries, 1):
            result += f"### ADR-{i}: {entry.get('title', '未命名')}\n"
            result += f"- 时间: {entry.get('date', 'N/A')}\n"
            result += f"- 状态: {entry.get('status', 'proposed')}\n"
            result += f"- 决策: {entry.get('decision', 'N/A')}\n"
            result += f"- 理由: {entry.get('rationale', 'N/A')}\n\n"

    # 同步到经验资产库
    try:
        from experience_library import register
        for entry in (adr_entries if isinstance(adr_entries, list) else []):
            register(
                asset_type="decision",
                title=f"ADR: {entry.get('title', '决策')}",
                content=json.dumps(entry, ensure_ascii=False),
                tags="adr,decision",
                visibility="team",
                project_name=project_name,
                source=f"project-manager ADR sync",
            )
        result += "✅ 决策已同步至经验资产库。\n"
    except ImportError:
        pass

    return result


async def tool_extract_knowledge_assets(project_name: str = "", blueprint_path: str = "") -> str:
    """从 CodeGuard 蓝图/复盘结果自动提取可复用经验资产"""
    result = f"# 知识资产自动提取 — {project_name or '未命名项目'}\n\n"

    # 尝试从 module_health 提取可复用模块
    if blueprint_path:
        try:
            sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent /
                                    "CodeGuard" / "scripts"))
            from module_health import analyze_clones
            import json as _json

            with open(blueprint_path, "r", encoding="utf-8") as f:
                blueprint = _json.load(f)

            modules = blueprint.get("modules", {})
            clones = analyze_clones(modules)

            result += f"## 从蓝图提取\n\n"
            result += f"- 模块总数: {len(modules)}\n"
            result += f"- 可复用克隆组: {len(clones)}\n\n"

            # 自动注册高价值克隆为经验资产
            try:
                from experience_library import register
                for c in clones[:3]:
                    locs = c.get("locations", [])
                    if len(locs) >= 2:
                        register(
                            asset_type="skill",
                            title=f"可复用函数: {c.get('signature', 'unnamed')}",
                            content=f"# {c.get('signature', 'unnamed')}\n\n"
                                    f"- 出现次数: {c.get('count', 0)}\n"
                                    f"- 位置: {', '.join(locs)}\n"
                                    f"- Hash类型: {c.get('hash_type', 'N/A')}\n"
                                    f"- 建议提取: {c.get('suggested_extract_to', 'N/A')}",
                            tags="reusable,clone",
                            visibility="team",
                            project_name=project_name,
                            source=f"CodeGuard blueprint auto-extract",
                        )
                result += "✅ 高价值可复用函数已自动登记到经验资产库。\n"
            except ImportError:
                result += "⚠️ experience_library.py 未找到，跳过自动登记。\n"
        except (ImportError, FileNotFoundError, json.JSONDecodeError) as e:
            result += f"⚠️ 蓝图提取失败: {e}\n"

    # 从现有的复盘知识资产导出
    result += "\n## 手动知识入口\n\n"
    result += "手动登记经验资产: `python experience_library.py --action register --type skill --title \"...\" --content \"...\"`\n"
    result += "搜索已有经验: `python experience_library.py --action search --keywords \"...\"`\n"

    return result


# ============================================================
# v2.3: TencentDB 桥接导入 Tool
# ============================================================

async def tool_import_from_tencentdb(
    project_name: str = "",
    tencentdb_path: str = "",
    include_types: str = "conversations,records,scene_blocks",
) -> str:
    """从本地 TencentDB Agent Memory 数据目录批量导入记忆资产。

    读取 ~/.openclaw/state/memory-tdai/ 下的 conversations/records/scene_blocks，
    映射到 experience_library 的 chat_memory/skill/wiki/decision 类型。
    """
    from pathlib import Path as _P

    # 默认路径：TencentDB 本地数据
    if not tencentdb_path:
        tencentdb_path = os.path.expanduser("~/.openclaw/state/memory-tdai")

    td_path = _P(tencentdb_path)
    if not td_path.exists():
        return f"# TencentDB 导入\n\n❌ 数据目录不存在: {tencentdb_path}\n\n请确认 TencentDB Agent Memory 已安装并运行过。数据通常位于 `~/.openclaw/state/memory-tdai/`。"

    requested_types = {t.strip() for t in include_types.split(",") if t.strip()}
    result_lines = [f"# TencentDB 资产导入 — {project_name or '未命名'}\n",
                    f"**数据源**: {tencentdb_path}\n"]

    # 类型→资产映射
    type_map = {
        "conversations": ("chat_memory", "conversation_*.json"),
        "records": ("skill", "memory_record_*.json"),
        "scene_blocks": ("wiki", "scene_*.json"),
    }

    imported = 0
    skipped = 0
    try:
        from experience_library import register
    except ImportError:
        return "# TencentDB 导入\n\n❌ experience_library.py 未找到，无法注册资产。"

    for req_type in requested_types:
        if req_type not in type_map:
            result_lines.append(f"\n⚠️ 未知类型: {req_type}，跳过")
            continue

        asset_type, file_pattern = type_map[req_type]
        subtype_dir = td_path / req_type
        if not subtype_dir.exists():
            result_lines.append(f"\n## {req_type}\n\n目录不存在，跳过")
            continue

        files = list(subtype_dir.glob("*.json"))
        result_lines.append(f"\n## {req_type} ({len(files)} 文件)")

        for f in files[:20]:  # 单次最多 20 条
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                skipped += 1
                continue

            title = data.get("title") or data.get("summary") or f.stem
            content = data.get("content") or json.dumps(data, ensure_ascii=False, indent=2)
            r = register(
                asset_type=asset_type,
                title=f"[TencentDB] {title[:80]}",
                content=content[:4000],
                tags="tencentdb,imported",
                visibility="team",
                project_name=project_name,
                source=f"TencentDB import: {req_type}",
            )
            if r.get("status") == "duplicate":
                skipped += 1
            else:
                imported += 1

    result_lines.append(f"\n---\n✅ 导入完成 — 新增 {imported} 条，跳过 {skipped} 条（重复或解析失败）")
    return "\n".join(result_lines)
