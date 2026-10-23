#!/usr/bin/env python3
"""
CodeGuard MCP Server — JSON-RPC 2.0 over stdio (v3.0.0)
========================================================
跨平台通用，支持 Claude Code、Cursor、VS Code、CodeBuddy 等所有 MCP 客户端。
v3.0.0: 新增行业分离 (web/embedded/safety) + get_industry 工具 + execute_rules 返回行业信息。

暴露的 MCP Tool：
  1. review_file       — 对单个文件执行质量检测
  2. review_diff       — 对 git diff 变更执行增量检测
  3. execute_rules     — 列出所有活跃规则 (含行业规则集)
  4. inject_constraints — 生成架构约束提示（注入 AI 上下文）
  5. get_industry      — 查询当前项目行业维度配置 (v3.0.0)

暴露的 MCP Resource：
  - codeguard://rules/default     — 默认规则集
  - codeguard://config/project    — 项目自定义配置
"""

import json
import os
import sys
from pathlib import Path
from typing import Any

# ── 路径设置 ──────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

_SHARED_DIR = SCRIPT_DIR.parent.parent.parent / "shared"
if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))

import quality_check
from _mcp_base import MCPBaseServer

# ============================================================
# MCP 协议常量
# ============================================================

PROTOCOL_VERSION = MCPBaseServer.PROTOCOL_VERSION
SERVER_NAME = "CodeGuard"
SERVER_VERSION = "3.0.0"
make_mcp_tool = MCPBaseServer.make_tool  # 本地别名，保持 TOOLS 定义简洁

# ============================================================
# MCP Tool Schema
# ============================================================

TOOLS = [
    make_mcp_tool(
        "review_file",
        "对单个文件执行完整质量检测，返回所有发现的问题及置信度分数。"
        "检测范围：圈复杂度、嵌套深度、参数数量、安全红线、异常处理、架构分层。"
        "置信度：90-100=AST精确 / 80-89=剥离后正则 / 70-79=原始正则 / 60-69=启发式",
        {
            "file_path": {"type": "string", "description": "要检测的文件绝对路径"},
            "mode": {"type": "string", "enum": ["personal", "team"],
                     "description": "检测模式：personal(个人)、team(团队，含命名一致性检查)",
                     "default": "personal"},
        },
        ["file_path"]
    ),
    make_mcp_tool(
        "review_diff",
        "对 git 变更文件执行增量检测。自动识别 4 种变更来源："
        "已提交变更(diff HEAD)、未暂存(diff)、已暂存(diff --cached)、未跟踪(ls-files --others)。"
        "适合 CI/CD 流水线和 pre-commit hook。",
        {
            "project_root": {"type": "string", "description": "项目根目录路径", "default": "."},
            "mode": {"type": "string", "enum": ["personal", "team"],
                     "description": "检测模式", "default": "personal"},
        },
        ["project_root"]
    ),
    make_mcp_tool(
        "execute_rules",
        "列出当前项目所有活跃的质量规则，包括通用规则和团队自定义规则。"
        "每条规则包含：id、描述、严重性(block/warn/info)、适用范围、置信度来源。",
        {
            "project_root": {"type": "string", "description": "项目根目录路径", "default": "."},
        },
        ["project_root"]
    ),
    make_mcp_tool(
        "inject_constraints",
        "分析项目结构并生成架构约束提示，用于注入到 AI 对话上下文。"
        "输出格式支持 prompt（完整约束文本）和 checklist（轻量检查清单）。"
        "format 省略时按项目复杂度自动分档：常规任务→checklist（Token 净节省 ~50%），"
        "复杂任务（源码文件多/存在架构蓝图/多层分层）→prompt（完整架构全景）。"
        "file_type 指定目标文件类型（source/test/config/generated/migration/doc），"
        "约束与清单按文件类型差异化过滤（对齐 FileClassifier）。"
        "基于首因/近因效应设计，对抗 LLM 的 'Lost in the Middle' 问题。",
        {
            "project_root": {"type": "string", "description": "项目根目录路径", "default": "."},
            "format": {"type": "string", "enum": ["prompt", "checklist", "json"],
                       "description": "输出格式。省略时按项目复杂度自动分档"},
            "file_type": {"type": "string",
                          "enum": ["source", "test", "config", "generated", "migration", "doc"],
                          "description": "目标文件类型，约束按类型差异化过滤", "default": "source"},
        },
        ["project_root"]
    ),
    make_mcp_tool(
        "get_industry",
        "查询当前项目的行业维度配置 (v3.0.0)。"
        "返回行业类型 (web/embedded/safety)、门禁级别 (gold/silver/bronze)、"
        "规则集路径、行业规则数和已应用阈值数。"
        "用于诊断行业自动检测是否正确、确认嵌入式/安全关键规则集是否已加载。",
        {
            "project_root": {"type": "string", "description": "项目根目录路径", "default": "."},
        },
        ["project_root"]
    ),
]

RESOURCES = [
    {"uri": "codeguard://rules/default", "name": "CodeGuard 默认规则集",
     "description": "所有内置的通用质量规则（SOLID、分层架构、安全红线、度量阈值等）",
     "mimeType": "application/json"},
    {"uri": "codeguard://config/project", "name": "项目自定义配置",
     "description": "当前项目 .code-guardian 目录下的所有自定义规则和配置",
     "mimeType": "application/json"},
]

# ============================================================
# 路径安全（CodeGuard 特有）
# ============================================================

_PROJECT_ROOT: str | None = None


def set_project_root(path: str) -> None:
    global _PROJECT_ROOT
    _PROJECT_ROOT = os.path.abspath(path)


def _is_safe_path(file_path: str) -> bool:
    """检查文件路径是否在项目根目录内（防止路径遍历攻击）"""
    if _PROJECT_ROOT is None:
        return True
    try:
        real_file = os.path.realpath(os.path.abspath(file_path))
        real_root = os.path.realpath(_PROJECT_ROOT)
        return os.path.commonpath([real_file, real_root]) == real_root
    except (ValueError, OSError):
        return False


# ============================================================
# Tool 处理器
# ============================================================

# 文件扩展名 → 检测函数映射表（消除长 if/elif 链）
_EXT_DISPATCH = {
    ".py": lambda fp, c: quality_check.check_python_file(fp, c),
    ".js": lambda fp, c: quality_check.check_javascript_file(fp, c, ".js"),
    ".ts": lambda fp, c: quality_check.check_javascript_file(fp, c, ".ts"),
    ".mjs": lambda fp, c: quality_check.check_javascript_file(fp, c, ".mjs"),
    ".java": lambda fp, c: quality_check.check_java_file(fp, c),
    ".go": lambda fp, c: quality_check.check_go_file(fp, c),
    ".cs": lambda fp, c: quality_check.check_csharp_file(fp, c),
    ".c": lambda fp, c: quality_check.check_c_file(fp, c),
    ".cpp": lambda fp, c: quality_check.check_c_file(fp, c),
    ".h": lambda fp, c: quality_check.check_c_file(fp, c),
    ".hpp": lambda fp, c: quality_check.check_c_file(fp, c),
    ".cc": lambda fp, c: quality_check.check_c_file(fp, c),
    ".cxx": lambda fp, c: quality_check.check_c_file(fp, c),
}


def _run_file_check(file_path: str, collector, ext: str) -> None:
    """根据文件扩展名分派到对应的检测函数。"""
    checker = _EXT_DISPATCH.get(ext)
    if checker:
        checker(file_path, collector)
    else:
        quality_check.check_generic_file(file_path, collector, ext)


def _format_issues(collector) -> list:
    """格式化 IssueCollector 的结果为 MCP 响应列表。"""
    return [{"severity": i["severity"], "category": i["category"],
             "file": i["file"], "line": i["line"],
             "message": i["message"], "suggestion": i.get("suggestion", ""),
             "confidence": i.get("confidence", 0)} for i in collector.issues]


def handle_review_file(params: dict) -> dict:
    """处理 review_file 请求"""
    file_path = params.get("file_path", "")
    mode = params.get("mode", "personal")

    if not file_path or not os.path.isfile(file_path):
        return MCPBaseServer.create_error(None, -32602, f"Invalid file_path: {file_path}")  # codeguard: ignore GOLD_NO_MAGIC_NUMBER
    if not _is_safe_path(file_path):
        return MCPBaseServer.create_error(None, -32602, "Access denied: file_path is outside project root")  # codeguard: ignore GOLD_NO_MAGIC_NUMBER

    file_type = quality_check.FileClassifier.classify(file_path)
    if file_type in ("generated", "doc"):
        return {"issues": [], "file_type": file_type,
                "summary": {"total_issues": 0, "blocks": 0, "warnings": 0, "info": 0, "avg_confidence": 0},
                "exit_code": 0, "note": f"跳过 {file_type} 类型文件"}

    collector = quality_check.IssueCollector()
    ext = os.path.splitext(file_path)[1].lower()
    _run_file_check(file_path, collector, ext)

    if mode == "team":
        quality_check.check_naming_consistency([file_path], collector)

    return {
        "issues": _format_issues(collector),
        "file_type": file_type,
        "summary": collector.summary(),
        "exit_code": 2 if collector.has_blocks() else (1 if collector.has_warns() else 0)
    }


def handle_review_diff(params: dict) -> dict:
    """处理 review_diff 请求"""
    project_root = params.get("project_root", ".")
    root_path = os.path.abspath(project_root)
    if not os.path.isdir(root_path):
        return MCPBaseServer.create_error(None, -32602, f"Invalid project_root: {root_path}")  # codeguard: ignore GOLD_NO_MAGIC_NUMBER

    collector = quality_check.run_quality_check(root_path, mode="diff")
    return {
        "issues": [{"severity": i["severity"], "category": i["category"],
                    "file": i["file"], "line": i["line"],
                    "message": i["message"], "suggestion": i.get("suggestion", ""),
                    "confidence": i.get("confidence", 0)} for i in collector.issues],
        "summary": collector.summary(),
        "exit_code": 2 if collector.has_blocks() else (1 if collector.has_warns() else 0)
    }


def handle_execute_rules(params: dict) -> dict:
    """处理 execute_rules 请求"""
    import constraint_injector
    from quality_core_config import init_industry_aware
    project_root = params.get("project_root", ".")
    root_path = os.path.abspath(project_root)

    # 初始化行业感知配置 (v3.0.0)
    industry_info = init_industry_aware(root_path)

    skill_rules = constraint_injector.load_skill_rules()
    custom_rules = constraint_injector.load_custom_rules(root_path)

    all_rules = []
    for r in skill_rules:
        all_rules.append({"id": r["id"], "name": r["name"], "description": r["description"],
                          "severity": r["severity"], "source": "builtin",
                          "confidence": "90-95" if r["severity"] == "block" else "80-85"})
    if custom_rules.get("has_custom"):
        for r in custom_rules["rules"]:
            all_rules.append({"id": r.get("id", "?"), "name": r.get("name", r.get("description", "")),
                              "description": r.get("description", ""),
                              "severity": r.get("severity", "warn"), "source": "custom",
                              "confidence": "85-95", "target": r.get("target", "all"),
                              "pattern": r.get("pattern", "")})

    # 追加行业规则集规则 (v3.0.0)
    if industry_info.get("profile_rules"):
        for r in industry_info["profile_rules"]:
            all_rules.append({"id": r.get("id", "?"), "name": r.get("name", ""),
                              "description": r.get("description", ""),
                              "severity": r.get("severity", "warn"),
                              "source": f"industry:{industry_info['industry']}",
                              "confidence": "90-95"})

    return {
        "total_rules": len(all_rules),
        "builtin_rules": len(skill_rules),
        "custom_rules": len(custom_rules.get("rules", [])),
        "industry_rules": len(industry_info.get("profile_rules") or []),
        "industry": industry_info["industry"],
        "gate_level": industry_info["gate_level"],
        "profile_path": industry_info.get("profile_path"),
        "rules": all_rules,
    }


_SRC_EXTS = (".py", ".js", ".ts", ".java", ".go", ".rs", ".cpp", ".c", ".h", ".cs")


def _infer_complexity(root_path, structure):
    """根据项目规模/架构信号推断注入档位（CI-01 Token 经济化策略）。

    Returns:
        "prompt"   — 复杂任务（需完整架构全景）
        "checklist" — 常规任务（轻量，最小化上下文占用）

    复杂信号（满足任一即判为复杂）：
      1. 源码文件数 > 50（大型项目）
      2. 存在 architecture_blueprint.json（已有架构全景）
      3. 分层目录数 >= 3（domain/application/infrastructure 等）
    """
    root = Path(root_path)
    src_count = 0
    for ext in _SRC_EXTS:
        try:
            src_count += len(list(root.rglob(f"*{ext}")))
        except OSError:  # codeguard: ignore GOLD_NO_EMPTY_EXCEPT — 遍历失败跳过
            pass
    if src_count > 50:
        return "prompt"
    if (root / "architecture_blueprint.json").exists():
        return "prompt"
    if len(structure.get("layer_dirs", {})) >= 3:
        return "prompt"
    return "checklist"


def handle_inject_constraints(params: dict) -> dict:
    """处理 inject_constraints 请求（v3.0.0: 自动分档 + 文件类型差异化）。"""
    import constraint_injector
    project_root = params.get("project_root", ".")
    fmt = params.get("format")
    file_type = params.get("file_type", "source")

    root_path = os.path.abspath(project_root)
    structure = constraint_injector.detect_project_structure(root_path)
    custom_rules = constraint_injector.load_custom_rules(root_path)
    skill_rules = constraint_injector.load_skill_rules(file_type)

    # 自动分档：未显式指定 format 时按复杂度推断
    auto_tiered = fmt is None
    if fmt is None:
        fmt = _infer_complexity(root_path, structure)

    if fmt == "prompt":
        content = constraint_injector.generate_constraint_prompt(
            structure, custom_rules, skill_rules, file_type=file_type)
    elif fmt == "checklist":
        content = constraint_injector.generate_quick_checklist(structure, file_type)
    else:
        content = json.dumps({"structure": structure, "skill_rules": skill_rules,
                              "custom_rules": custom_rules}, ensure_ascii=False, indent=2)

    return {"format": fmt, "content": content, "project_type": structure["type"],
            "languages": structure["languages"],
            "file_type": file_type,
            "has_custom_rules": custom_rules.get("has_custom", False),
            "auto_tiered": auto_tiered}


def handle_get_industry(params: dict) -> dict:
    """处理 get_industry 请求 (v3.0.0) — 查询项目行业维度配置"""
    from quality_core_config import init_industry_aware
    project_root = params.get("project_root", ".")
    root_path = os.path.abspath(project_root)

    if not os.path.isdir(root_path):
        return MCPBaseServer.create_error(None, -32602, f"Invalid project_root: {root_path}")  # codeguard: ignore GOLD_NO_MAGIC_NUMBER

    result = init_industry_aware(root_path)

    return {
        "industry": result["industry"],
        "gate_level": result["gate_level"],
        "profile_path": result.get("profile_path"),
        "industry_rules_count": len(result.get("profile_rules") or []),
        "thresholds_applied": result["thresholds_applied"],
        "active_industry": result["industry"],
    }


def handle_resource_read(uri: str) -> Any:
    """处理 resources/read 请求"""
    if uri == "codeguard://rules/default":
        import constraint_injector
        rules = constraint_injector.load_skill_rules()
        content = json.dumps({"type": "builtin_rules", "rules": rules}, ensure_ascii=False, indent=2)
        return {"contents": [{"uri": uri, "mimeType": "application/json", "text": content}]}
    elif uri == "codeguard://config/project":
        return {"contents": [{"uri": uri, "mimeType": "application/json",
                "text": json.dumps({"note": "No project configuration loaded. Run inject_constraints with a project_root to populate."}, ensure_ascii=False)}]}
    return MCPBaseServer.create_error(None, -32602, f"Unknown resource: {uri}")  # codeguard: ignore GOLD_NO_MAGIC_NUMBER


# ============================================================
# 启动
# ============================================================

def main():
    server = MCPBaseServer(
        name=SERVER_NAME,
        version=SERVER_VERSION,
        tools=TOOLS,
        resources=RESOURCES,
        tool_handlers={
            "review_file": handle_review_file,
            "review_diff": handle_review_diff,
            "execute_rules": handle_execute_rules,
            "inject_constraints": handle_inject_constraints,
            "get_industry": handle_get_industry,
        },
        resource_handler=handle_resource_read,
        log_fn=quality_check._log,
    )
    server.run_stdio(setup_fn=set_project_root)


if __name__ == "__main__":
    main()
