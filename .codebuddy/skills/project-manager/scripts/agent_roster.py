#!/usr/bin/env python3
"""
多 Agent 角色矩阵编排器 (Agent Roster) — project-manager v2.3
=============================================================
对标 TencentDB Agent Memory 的 Team → Agent → Loadout 三层模型：
  Team → 定义协作边界与共享规则
  Agent → 每个角色独立记忆与能力配置
  Loadout → 按需装配经验资产

核心操作：
  define_role(role_name, responsibilities, skill_requirements) → role_config
  assign_memory(role_name, asset_ids) → loadout 配置
  create_squad(team_name, roles, collaboration_rules) → squad_config
  export_manifest(team_name, format) → Markdown/JSON 编排清单
  list_roles() → 已定义角色列表
  remove_role(role_name) → 移除角色

预设角色（对标 TencentDB Scout/Builder/Reviewer）：
  scout      — 需求探索与市场调研
  builder    — 核心开发实现
  reviewer   — 代码审查与质量守护
  test_pilot — 测试验证与 CI/CD
  devops     — 部署运维与基础设施
  architect  — 架构设计与技术选型
  pm_lead    — 项目协调与进度管理

存储位置：.codebuddy/roster/{team_name}.json（运行时自动创建）

设计依据：
  - TencentDB Agent Memory feat/server_team: Team→Agent→Loadout→Squad
  - 零外部依赖，纯 Python 标准库 + JSON 文件系统

用法：
  python agent_roster.py --action define-role --name builder --responsibilities "实现核心功能"
  python agent_roster.py --action assign-memory --role builder --asset-ids "abc123,def456"
  python agent_roster.py --action create-squad --team my_team --roles "scout,builder,reviewer"
  python agent_roster.py --action export-manifest --team my_team
  python agent_roster.py --action list-roles
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ============================================================
# 常量
# ============================================================

_ROSTER_DIR = Path(__file__).resolve().parent.parent / ".codebuddy" / "roster"

# v2.3: Agent 记忆目录
_AGENT_MEMORY_DIR_TEMPLATE = str(_ROSTER_DIR / "{team}" / "agent_memory")

# 预设角色定义（对标 TencentDB Scout/Builder/Reviewer 小队模型）
_PRESET_ROLES: dict[str, dict[str, Any]] = {
    "scout": {
        "role_name": "scout",
        "display_name": "需求侦察兵 (Scout)",
        "description": "负责需求探索、市场调研、用户访谈、竞品分析",
        "responsibilities": [
            "收集和整理用户需求",
            "进行市场与竞品调研",
            "定义 MVP 范围与优先级",
            "产出需求文档与用户故事",
        ],
        "skill_requirements": ["用户研究", "市场分析", "需求文档编写", "优先级排序"],
        "suggested_tools": ["vision_tracker.py", "start_feasibility_check"],
    },
    "builder": {
        "role_name": "builder",
        "display_name": "核心构建者 (Builder)",
        "description": "负责核心功能开发、代码实现、技术方案落地",
        "responsibilities": [
            "编写核心业务逻辑与接口",
            "遵循架构设计与编码规范",
            "编写单元测试",
            "参与代码审查看板",
        ],
        "skill_requirements": ["编码实现", "单元测试", "设计模式", "问题调试"],
        "suggested_tools": ["refactor_queue.py", "quality_gate_check", "template_engine.py"],
    },
    "reviewer": {
        "role_name": "reviewer",
        "display_name": "质量审查官 (Reviewer)",
        "description": "负责代码审查、质量门禁、安全扫描、架构合规检查",
        "responsibilities": [
            "执行代码审查",
            "运行质量与安全扫描",
            "检查架构分层合规",
            "批准或驳回 PR",
        ],
        "skill_requirements": ["代码审查", "安全审计", "架构合规", "测试审查"],
        "suggested_tools": ["CodeGuard/quality_check.py", "governance-hub/governance_check.py"],
    },
    "test_pilot": {
        "role_name": "test_pilot",
        "display_name": "测试飞行员 (Test Pilot)",
        "description": "负责测试策略、自动化测试、CI/CD 流水线、覆盖率门禁",
        "responsibilities": [
            "设计测试策略与用例",
            "编写自动化测试脚本",
            "维护 CI/CD 流水线",
            "执行覆盖率门禁",
        ],
        "skill_requirements": ["测试设计", "自动化测试", "CI/CD", "性能测试"],
        "suggested_tools": ["quality_coverage.py", "daily_progress_check"],
    },
    "devops": {
        "role_name": "devops",
        "display_name": "运维工程师 (DevOps)",
        "description": "负责部署、监控、IaC 安全、成本控制、基础设施管理",
        "responsibilities": [
            "管理部署流水线",
            "监控系统健康与告警",
            "IaC 安全扫描",
            "成本与资源配额管理",
        ],
        "skill_requirements": ["Kubernetes", "Terraform", "CI/CD", "监控告警"],
        "suggested_tools": ["iac-guardian/iac_scan.py", "governance-hub/check_release_readiness"],
    },
    "architect": {
        "role_name": "architect",
        "display_name": "架构师 (Architect)",
        "description": "负责系统架构设计、技术选型、蓝图维护、跨模块协调",
        "responsibilities": [
            "设计系统架构与模块划分",
            "制定技术选型决策",
            "维护架构蓝图",
            "协调跨模块接口设计",
        ],
        "skill_requirements": ["系统设计", "技术选型", "性能优化", "技术写作"],
        "suggested_tools": ["blueprint_generator.py", "create_project_plan", "adr_manager.py"],
    },
    "pm_lead": {
        "role_name": "pm_lead",
        "display_name": "项目负责人 (PM Lead)",
        "description": "负责项目进度、干系人沟通、风险管理、复盘总结",
        "responsibilities": [
            "制定项目计划与里程碑",
            "管理干系人期望与沟通",
            "跟踪进度与风险",
            "组织复盘与知识沉淀",
        ],
        "skill_requirements": ["项目管理", "沟通协调", "风险管理", "复盘引导"],
        "suggested_tools": ["generate_retrospective", "stakeholder_analysis", "communications_plan"],
    },
}


def _ensure_dir() -> None:
    """确保 Roster 目录存在。"""
    _ROSTER_DIR.mkdir(parents=True, exist_ok=True)


def _to_list(value) -> list[str]:
    """类型防御：将 str（逗号分隔）或 list/tuple 归一化为去空格的非空字符串列表。"""
    if isinstance(value, str):
        return [x.strip() for x in value.split(",") if x.strip()]
    if isinstance(value, (list, tuple)):
        return [str(x).strip() for x in value if str(x).strip()]
    return []


def _load_roster(team_name: str) -> dict[str, Any]:
    """加载团队配置。"""
    _ensure_dir()
    path = _ROSTER_DIR / f"{team_name}.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {
        "team_name": team_name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "roles": {},
        "collaboration_rules": {},
    }


def _save_roster(team_name: str, data: dict) -> None:
    """保存团队配置。"""
    _ensure_dir()
    path = _ROSTER_DIR / f"{team_name}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ============================================================
# 公共 API
# ============================================================

def define_role(
    role_name: str,
    responsibilities: str = "",
    skill_requirements: str = "",
    team_name: str = "default",
) -> dict[str, Any]:
    """定义一个新角色或使用预设角色。

    Args:
        role_name: 角色名（可使用预设: scout/builder/reviewer/test_pilot/devops/architect/pm_lead）
        responsibilities: 职责描述（逗号分隔，非预设时必填）
        skill_requirements: 技能要求（逗号分隔）
        team_name: 所属团队

    Returns:
        role_config
    """
    roster = _load_roster(team_name)

    # 使用预设
    if role_name in _PRESET_ROLES:
        preset = dict(_PRESET_ROLES[role_name])
        preset["memory_loadout"] = []
        preset["defined_at"] = datetime.now(timezone.utc).isoformat()
        roster["roles"][role_name] = preset
        _save_roster(team_name, roster)
        return {"role": role_name, "status": "defined", "team": team_name,
                "display_name": preset["display_name"], "from_preset": True}

    # 自定义角色（v2.4: 类型防御 — responsibilities/skill_requirements 支持 str 或 list）
    resp_list = _to_list(responsibilities)
    skill_list = _to_list(skill_requirements)

    role_config = {
        "role_name": role_name,
        "display_name": role_name,
        "description": f"自定义角色: {role_name}",
        "responsibilities": resp_list,
        "skill_requirements": skill_list,
        "suggested_tools": [],
        "memory_loadout": [],
        "defined_at": datetime.now(timezone.utc).isoformat(),
    }
    roster["roles"][role_name] = role_config
    _save_roster(team_name, roster)
    return {"role": role_name, "status": "defined", "team": team_name, "from_preset": False}


def assign_memory(
    role_name: str,
    asset_ids: str = "",
    team_name: str = "default",
) -> dict[str, Any]:
    """为指定角色装配经验资产（对标 Loadout）。

    Args:
        role_name: 角色名
        asset_ids: 逗号分隔的经验资产 ID 列表
        team_name: 所属团队

    Returns:
        loadout 配置
    """
    roster = _load_roster(team_name)
    if role_name not in roster["roles"]:
        return {"error": f"角色 '{role_name}' 在团队 '{team_name}' 中未定义，请先 define-role"}

    aid_list = [a.strip() for a in asset_ids.split(",") if a.strip()]
    roster["roles"][role_name]["memory_loadout"] = aid_list
    _save_roster(team_name, roster)
    return {
        "role": role_name,
        "team": team_name,
        "loadout": aid_list,
        "status": "assigned",
        "message": f"为 {role_name} 装配了 {len(aid_list)} 条经验资产",
    }


def create_squad(
    team_name: str,
    roles: str = "",
    collaboration_rules: str = "",
) -> dict[str, Any]:
    """创建多角色小队协作配置。

    Args:
        team_name: 团队名称
        roles: 逗号分隔的角色名列表
        collaboration_rules: 协作规则描述（如 "scout→builder→reviewer→test_pilot 流水线"）

    Returns:
        squad_config
    """
    roster = _load_roster(team_name)
    role_list = _to_list(roles)

    # 自动定义未注册的预设角色
    for role_name in role_list:
        if role_name not in roster["roles"] and role_name in _PRESET_ROLES:
            define_role(role_name, team_name=team_name)
            roster = _load_roster(team_name)

    unknown = [r for r in role_list if r not in roster["roles"]]
    if unknown:
        return {"error": f"未定义的角色: {', '.join(unknown)}，请先 define-role"}

    roster["squad"] = {
        "members": role_list,
        "size": len(role_list),
        "collaboration_rules": collaboration_rules,
        "formed_at": datetime.now(timezone.utc).isoformat(),
    }
    _save_roster(team_name, roster)

    return {
        "team": team_name,
        "squad": role_list,
        "size": len(role_list),
        "status": "formed",
        "message": f"小队 '{team_name}' 已组建（{len(role_list)} 人: {', '.join(role_list)}）",
    }


def export_manifest(team_name: str, fmt: str = "json") -> str:
    """导出可执行的 Agent 编排清单。

    Args:
        team_name: 团队名称
        fmt: 输出格式 (json/markdown)

    Returns:
        编排清单文本
    """
    roster = _load_roster(team_name)
    squad = roster.get("squad", {}).get("members", [])
    if not squad:
        return json.dumps({"error": f"团队 '{team_name}' 尚未组建小队", "team": team_name},
                          ensure_ascii=False, indent=2)

    if fmt == "markdown":
        return _export_manifest_md(team_name, roster, squad)
    return _export_manifest_json(team_name, roster, squad)


def _export_manifest_md(team_name: str, roster: dict, squad: list[str]) -> str:
    """生成 Markdown 编排清单。"""
    lines = [
        f"# Agent 协作编排清单 — {team_name}",
        "",
        f"**生成时间**: {datetime.now(timezone.utc).isoformat()}",
        f"**小队规模**: {len(squad)} 人",
        f"**协作规则**: {roster.get('squad', {}).get('collaboration_rules', '未设定')}",
        "",
        "## 角色矩阵",
        "",
        "| 角色 | 职责 | 已装配经验 | 建议工具 |",
        "|------|------|-----------|---------|",
    ]
    for role_name in squad:
        role = roster["roles"].get(role_name, {})
        resp = ", ".join(role.get("responsibilities", [])[:2])
        loadout = str(len(role.get("memory_loadout", []))) + "条"
        tools = ", ".join(role.get("suggested_tools", [])[:2])
        lines.append(f"| {role.get('display_name', role_name)} | {resp} | {loadout} | {tools} |")

    lines += [
        "",
        "## 协作流程",
        "",
        "```",
        "scout → builder → reviewer → test_pilot → devops",
        "  │         │          │            │           │",
        "  └─调研──→└─开发──→└─审查──→└─测试──→└─部署",
        "```",
        "",
        "## 经验资产清单",
        "",
    ]
    for role_name in squad:
        role = roster["roles"].get(role_name, {})
        loadout = role.get("memory_loadout", [])
        if loadout:
            lines.append(f"### {role.get('display_name', role_name)}")
            for aid in loadout:
                lines.append(f"- `{aid}`")
            lines.append("")

    return "\n".join(lines)


def _export_manifest_json(team_name: str, roster: dict, squad: list[str]) -> str:
    """生成 JSON 编排清单。"""
    manifest = {
        "team": team_name,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "squad_size": len(squad),
        "collaboration_rules": roster.get("squad", {}).get("collaboration_rules", ""),
        "roles": [],
    }
    for role_name in squad:
        role = roster["roles"].get(role_name, {})
        manifest["roles"].append({
            "name": role_name,
            "display": role.get("display_name", role_name),
            "responsibilities": role.get("responsibilities", []),
            "skill_requirements": role.get("skill_requirements", []),
            "loadout": role.get("memory_loadout", []),
            "suggested_tools": role.get("suggested_tools", []),
        })
    return json.dumps(manifest, ensure_ascii=False, indent=2)


def list_roles(team_name: str = "") -> dict[str, Any]:
    """列出已定义的角色。

    Args:
        team_name: 团队名称（空=预设列表）

    Returns:
        角色列表
    """
    if team_name:
        roster = _load_roster(team_name)
        roles = roster.get("roles", {})
        return {
            "team": team_name,
            "roles": [
                {
                    "name": rn,
                    "display": rc.get("display_name", rn),
                    "loadout_size": len(rc.get("memory_loadout", [])),
                }
                for rn, rc in roles.items()
            ],
        }
    return {
        "preset_roles": [
            {"name": rn, "display": rc["display_name"], "description": rc["description"]}
            for rn, rc in _PRESET_ROLES.items()
        ],
    }


def remove_role(role_name: str, team_name: str = "default") -> dict[str, Any]:
    """移除角色。"""
    roster = _load_roster(team_name)
    if role_name not in roster["roles"]:
        return {"error": f"角色 '{role_name}' 在团队 '{team_name}' 中不存在"}
    del roster["roles"][role_name]
    # 如果角色在小队中，也移除
    squad = roster.get("squad", {}).get("members", [])
    if role_name in squad:
        squad.remove(role_name)
        roster["squad"]["members"] = squad
    _save_roster(team_name, roster)
    return {"role": role_name, "team": team_name, "status": "removed"}


# ============================================================
# v2.3: Agent 结构化记忆持久化
# ============================================================

def _ensure_agent_memory_dir(team_name: str) -> Path:
    """确保 Agent 记忆目录存在。"""
    mem_dir = Path(_AGENT_MEMORY_DIR_TEMPLATE.format(team=team_name))
    mem_dir.mkdir(parents=True, exist_ok=True)
    return mem_dir


def save_agent_memory(role_name: str, team_name: str = "default",
                      memory_data: dict | None = None) -> dict[str, Any]:
    """持久化 Agent 独立记忆。

    Args:
        role_name: 角色名
        team_name: 团队名
        memory_data: 自定义记忆数据（空=使用默认结构）

    Returns:
        {"role": str, "status": "saved", "path": str}
    """
    mem_dir = _ensure_agent_memory_dir(team_name)
    now = datetime.now(timezone.utc).isoformat()

    if memory_data is None:
        # v2.3: 默认记忆结构
        memory_data = {
            "role": role_name,
            "team": team_name,
            "conversation_snippets": [],
            "task_history": [],
            "key_decisions": [],
            "last_active": now,
            "total_invocations": 0,
        }

    memory_data["last_active"] = now
    memory_data.setdefault("total_invocations", 0)

    path = mem_dir / f"{role_name}.json"
    path.write_text(json.dumps(memory_data, ensure_ascii=False, indent=2), encoding="utf-8")

    return {"role": role_name, "team": team_name, "status": "saved", "path": str(path)}


def load_agent_memory(role_name: str, team_name: str = "default") -> dict[str, Any]:
    """恢复 Agent 独立记忆。

    Args:
        role_name: 角色名
        team_name: 团队名

    Returns:
        记忆数据（含 conversation_snippets/task_history/key_decisions 等）
    """
    mem_dir = _ensure_agent_memory_dir(team_name)
    path = mem_dir / f"{role_name}.json"
    if not path.exists():
        return {"role": role_name, "team": team_name, "status": "not_found",
                "message": f"Agent '{role_name}' 尚无记忆记录"}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {**data, "status": "loaded"}
    except (json.JSONDecodeError, OSError):
        return {"role": role_name, "team": team_name, "status": "error",
                "message": "记忆文件损坏"}


def update_agent_stats(role_name: str, team_name: str = "default") -> dict[str, Any]:
    """更新 Agent 使用统计（调用次数 + 最后活跃时间）。

    Args:
        role_name: 角色名
        team_name: 团队名

    Returns:
        更新后的统计
    """
    memory_data = load_agent_memory(role_name, team_name)
    if memory_data.get("status") == "not_found":
        memory_data = {
            "role": role_name, "team": team_name,
            "conversation_snippets": [], "task_history": [], "key_decisions": [],
        }
    now = datetime.now(timezone.utc).isoformat()
    memory_data["last_active"] = now
    memory_data["total_invocations"] = memory_data.get("total_invocations", 0) + 1
    return save_agent_memory(role_name, team_name, memory_data)


# ============================================================
# CLI 入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="多 Agent 角色矩阵编排器 — project-manager v2.2")
    parser.add_argument("--action", required=True, choices=[
        "define-role", "assign-memory", "create-squad",
        "export-manifest", "list-roles", "remove-role",
        "save-memory", "load-memory", "update-stats",  # v2.3
    ])
    parser.add_argument("--name", help="角色名称")
    parser.add_argument("--responsibilities", default="", help="职责（逗号分隔）")
    parser.add_argument("--skills", default="", help="技能要求（逗号分隔）")
    parser.add_argument("--team", default="default", help="团队名称")
    parser.add_argument("--roles", default="", help="角色列表（逗号分隔，create-squad 用）")
    parser.add_argument("--rules", default="", help="协作规则（create-squad 用）")
    parser.add_argument("--role", help="角色名（assign-memory/remove-role 用）")
    parser.add_argument("--asset-ids", default="", help="经验资产 ID 列表（逗号分隔）")
    parser.add_argument("--format", default="json", choices=["json", "markdown"],
                        help="输出格式（export-manifest 用）")
    parser.add_argument("--output", "-o", default="", help="输出文件路径")

    args = parser.parse_args()

    result: Any = {}
    output_text = ""

    if args.action == "define-role":
        if not args.name:
            print("错误: define-role 需要 --name", file=sys.stderr)
            sys.exit(2)
        result = define_role(args.name, args.responsibilities, args.skills, args.team)

    elif args.action == "assign-memory":
        if not args.role:
            print("错误: assign-memory 需要 --role", file=sys.stderr)
            sys.exit(2)
        result = assign_memory(args.role, args.asset_ids, args.team)

    elif args.action == "create-squad":
        result = create_squad(args.team, args.roles, args.rules)

    elif args.action == "export-manifest":
        output_text = export_manifest(args.team, args.format)

    elif args.action == "list-roles":
        result = list_roles(args.team)

    elif args.action == "remove-role":
        if not args.role:
            print("错误: remove-role 需要 --role", file=sys.stderr)
            sys.exit(2)
        result = remove_role(args.role, args.team)

    elif args.action == "save-memory":
        if not args.role:
            print("错误: save-memory 需要 --role", file=sys.stderr)
            sys.exit(2)
        memory = json.loads(args.asset_ids) if args.asset_ids else None
        result = save_agent_memory(args.role, args.team, memory)

    elif args.action == "load-memory":
        if not args.role:
            print("错误: load-memory 需要 --role", file=sys.stderr)
            sys.exit(2)
        result = load_agent_memory(args.role, args.team)

    elif args.action == "update-stats":
        if not args.role:
            print("错误: update-stats 需要 --role", file=sys.stderr)
            sys.exit(2)
        result = update_agent_stats(args.role, args.team)

    if output_text:
        if args.output:
            Path(args.output).write_text(output_text, encoding="utf-8")
            print(f"编排清单已写入 {args.output}", file=sys.stderr)
        elif args.format == "json":
            print(output_text)
        else:
            print(output_text)
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
