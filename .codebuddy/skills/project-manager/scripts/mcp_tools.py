"""
MCP 工具层 — facade 入口（向后兼容）。
实现已拆分至 mcp_tools_phases / mcp_tools_extended / mcp_tools_registry。
外部 `from mcp_tools import TOOL_REGISTRY` / `tool_xxx` 用法保持不变。
"""
from mcp_tools_phases import (  # noqa: F401
    _safe_parse_json,
    tool_start_feasibility_check,
    tool_create_project_plan,
    tool_daily_progress_check,
    tool_quality_gate_check,
    tool_vision_tracker_scan,
    tool_generate_retrospective,
    tool_knowledge_asset_export,
    tool_weekly_vision_report,
)
from mcp_tools_extended import (  # noqa: F401
    tool_team_health_check,
    tool_stakeholder_analysis,
    tool_communications_plan,
    tool_manage_experience_library,
    tool_configure_agent_roster,
    tool_sync_adr_decisions,
    tool_extract_knowledge_assets,
    tool_import_from_tencentdb,
)
from mcp_tools_registry import TOOL_REGISTRY  # noqa: F401
