"""MCP 工具注册表 — 从 phases/extended 导入 handler 函数。"""
from mcp_tools_phases import (
    tool_start_feasibility_check,
    tool_create_project_plan,
    tool_daily_progress_check,
    tool_quality_gate_check,
    tool_vision_tracker_scan,
    tool_generate_retrospective,
    tool_knowledge_asset_export,
    tool_weekly_vision_report,
)
from mcp_tools_extended import (
    tool_team_health_check,
    tool_stakeholder_analysis,
    tool_communications_plan,
    tool_manage_experience_library,
    tool_configure_agent_roster,
    tool_sync_adr_decisions,
    tool_extract_knowledge_assets,
    tool_import_from_tencentdb,
)

# ============================================================
# 工具注册表
# ============================================================

TOOL_REGISTRY = {
    "start_feasibility_check": {
        "handler": tool_start_feasibility_check,
        "description": "启动项目可行性研判（第一阶段：判断值不值得做）。包含市场需求、资源能力、风险评估三部分。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_name": {
                    "type": "string",
                    "description": "项目名称",
                },
                "answers": {
                    "type": "string",
                    "description": "JSON格式的用户回答，格式如 {\"1\": \"答案\", \"2\": \"答案\"}",
                },
            },
        },
    },
    "create_project_plan": {
        "handler": tool_create_project_plan,
        "description": "生成项目启动规划书（第二阶段：怎么做想清楚）。包含质量标准、里程碑、技术选型。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_name": {"type": "string", "description": "项目名称"},
                "deadline": {"type": "string", "description": "目标交付日期"},
                "answers": {"type": "string", "description": "JSON格式的用户回答"},
            },
        },
    },
    "daily_progress_check": {
        "handler": tool_daily_progress_check,
        "description": "每日进度自检（第三阶段：不走偏）。快速检查今日完成情况和阻塞点。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "answers": {"type": "string", "description": "JSON格式 {today_done, status, blocker, blocker_plan}"},
            },
        },
    },
    "quality_gate_check": {
        "handler": tool_quality_gate_check,
        "description": "质量门禁检查（第三阶段：质量把关）。检查测试覆盖率、技术债务、反馈模式、质量红线。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "answers": {
                    "type": "string",
                    "description": "JSON格式 {edge_cases, coverage, tech_debt, feedback_pattern, quality_breach}",
                },
            },
        },
    },
    "vision_tracker_scan": {
        "handler": tool_vision_tracker_scan,
        "description": "自动扫描技术趋势和外部视野（第三/五阶段共用）。扫描GitHub Trending、AI工具、框架更新等。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "domain": {"type": "string", "description": "关注的领域/技术栈"},
                "keywords": {"type": "string", "description": "逗号分隔的关键词"},
            },
        },
    },
    "generate_retrospective": {
        "handler": tool_generate_retrospective,
        "description": "生成项目复盘报告（第四阶段：复盘沉淀）。评估目标达成率、经验资产化、续投决策。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_name": {"type": "string", "description": "项目名称"},
                "answers": {"type": "string", "description": "JSON格式的复盘数据"},
            },
        },
    },
    "knowledge_asset_export": {
        "handler": tool_knowledge_asset_export,
        "description": "导出知识沉淀文档（第四阶段：资产化）。整理可复用代码/模板/流程/踩坑记录。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_name": {"type": "string", "description": "项目名称"},
                "assets": {
                    "type": "string",
                    "description": "JSON数组 [{name, type, desc, scenario, location}]",
                },
            },
        },
    },
    "weekly_vision_report": {
        "handler": tool_weekly_vision_report,
        "description": "生成每周视野跟踪报告（第五阶段：防闭门造车）。汇总技术趋势和市场信号。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "domain": {"type": "string", "description": "关注领域"},
                "findings": {"type": "string", "description": "JSON格式的发现数据"},
            },
        },
    },
    "team_health_check": {
        "handler": tool_team_health_check,
        "description": "团队健康检查（PMBOK Team 绩效域）。评估技能矩阵、协作健康度、改进闭环。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_name": {"type": "string", "description": "项目名称"},
                "answers": {"type": "string", "description": "JSON（语义键，空则返回问题清单）: {team_roster, role_gaps, context_switching, morale, conflicts, deep_work_hours, onboarding, last_retro}"},
            },
        },
    },
    "stakeholder_analysis": {
        "handler": tool_stakeholder_analysis,
        "description": "干系人分析（PMBOK Stakeholder 绩效域）。映射干系人权力图谱与参与策略。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_name": {"type": "string", "description": "项目名称"},
                "answers": {"type": "string", "description": "JSON（语义键，空则返回问题清单）: {stakeholders, power_map, attitude, comm_frequency, info_asymmetry, pending_feedback}"},
            },
        },
    },
    "communications_plan": {
        "handler": tool_communications_plan,
        "description": "沟通计划（PMBOK Communications 绩效域）。定义沟通节奏、应急协议、渠道效能。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_name": {"type": "string", "description": "项目名称"},
                "answers": {"type": "string", "description": "JSON（语义键，空则返回问题清单）: {comm_cadence, escalation_path, external_contact, primary_tool, decision_traceability}"},
            },
        },
    },
    # ── v2.3: 对标 TencentDB Agent Memory（v2.2 首次引入） ──
    "manage_experience_library": {
        "handler": tool_manage_experience_library,
        "description": "管理团队经验资产库（对标 TencentDB Agent Memory）。操作：register(登记)/search(搜索)/load(加载)/stats(统计)。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_name": {"type": "string", "description": "项目名称"},
                "action": {"type": "string", "description": "操作: register/search/load/stats"},
                "asset_type": {"type": "string", "description": "资产类型 (register/search 用)"},
                "title": {"type": "string", "description": "资产标题 (register 用)"},
                "content": {"type": "string", "description": "资产内容 (register 用)"},
                "keywords": {"type": "string", "description": "搜索关键词 (search 用)"},
                "asset_id": {"type": "string", "description": "资产ID (load 用)"},
                "visibility": {"type": "string", "description": "可见性: private/team/restricted/agent"},
                "tags": {"type": "string", "description": "逗号分隔标签"},
            },
        },
    },
    "configure_agent_roster": {
        "handler": tool_configure_agent_roster,
        "description": "配置多 Agent 角色矩阵与协作编排（对标 TencentDB Team→Agent→Loadout）。操作：define-role/assign-memory/create-squad/export-manifest/list-roles。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_name": {"type": "string", "description": "项目/团队名称"},
                "action": {"type": "string", "description": "操作: define-role/assign-memory/create-squad/export-manifest/list-roles"},
                "role_name": {"type": "string", "description": "角色名 (define-role/assign-memory 用)"},
                "roles": {"type": "string", "description": "逗号分隔角色列表 (create-squad 用)"},
                "asset_ids": {"type": "string", "description": "逗号分隔经验资产ID (assign-memory 用)"},
                "responsibilities": {"type": "string", "description": "职责描述 (define-role 用)"},
                "skills": {"type": "string", "description": "技能要求 (define-role 用)"},
                "rules": {"type": "string", "description": "协作规则 (create-squad 用)"},
            },
        },
    },
    "sync_adr_decisions": {
        "handler": tool_sync_adr_decisions,
        "description": "将项目关键决策同步到 governance-hub ADR 管理器与经验资产库（横向集成 Tool）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_name": {"type": "string", "description": "项目名称"},
                "answers": {"type": "string", "description": "JSON格式 {decisions: [{title,date,status,decision,rationale}]}"},
            },
        },
    },
    "extract_knowledge_assets": {
        "handler": tool_extract_knowledge_assets,
        "description": "从 CodeGuard 蓝图/复盘结果自动提取可复用经验资产到经验资产库（横向集成 Tool）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_name": {"type": "string", "description": "项目名称"},
                "blueprint_path": {"type": "string", "description": "architecture_blueprint.json 路径"},
            },
        },
    },
    # ── v2.3: TencentDB 桥接导入 ──
    "import_from_tencentdb": {
        "handler": tool_import_from_tencentdb,
        "description": "从本地 TencentDB Agent Memory 数据目录批量导入记忆资产到经验资产库（v2.3 桥接 Tool）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_name": {"type": "string", "description": "项目名称"},
                "tencentdb_path": {"type": "string", "description": "TencentDB 数据目录路径（默认 ~/.openclaw/state/memory-tdai）"},
                "include_types": {"type": "string", "description": "导入类型（conversations,records,scene_blocks，逗号分隔）"},
            },
        },
    },
}
