#!/usr/bin/env python3
"""governance-hub MCP Server — JSON-RPC 2.0 over stdio (v3.0.0)

v0.3.0: 引入 _mcp_base.py 共享基类消除 JSON-RPC 协议重复代码。

MCP Tool:
  1. release_notes        — 基于 Conventional Commits 生成 Release Notes
  2. trace_requirements   — 需求追溯完整性检查（D9）
  3. check_release_readiness — 发布前五问自动化检视

MCP Resource:
  - governance://checklist/default — 发布前五问检视细则

用法: python mcp_server.py --project-root .
"""

import json
import os
import subprocess
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

from _mcp_base import MCPBaseServer

# ============================================================
# MCP 协议常量
# ============================================================

SERVER_NAME = "governance-hub"
SERVER_VERSION = "3.0.0"
make_mcp_tool = MCPBaseServer.make_tool

# ============================================================
# MCP Tool Schema
# ============================================================

TOOLS = [
    make_mcp_tool(
        "release_notes",
        "基于 Conventional Commits 规范从 git 历史生成 Release Notes 草稿。"
        "按 💥破坏性变更 / ✨新功能 / 🐛修复 / ⚡性能 / ♻️重构 / 📝文档 / 🔧其他 分类。"
        "输入 from/to 指定提交范围（支持 tag/HEAD/HEAD~N）。",
        {
            "from_ref": {"type": "string", "description": "起始引用（如 v1.0.0 / HEAD~20）", "default": "HEAD~20"},
            "to_ref": {"type": "string", "description": "结束引用（如 HEAD）", "default": "HEAD"},
            "output_file": {"type": "string", "description": "可选输出文件路径", "default": ""},
        },
        ["from_ref", "to_ref"],
    ),
    make_mcp_tool(
        "trace_requirements",
        "对当前分支执行需求追溯完整性检查。"
        "扫描 commit 消息中的 issue 引用（#NNN / PROJ-NNN / TAPD-NNN），计算关联率。"
        "关联率 ≥ 95% = PASS, ≥ 80% = WARN, < 80% = BLOCK。",
        {"sample_size": {"type": "integer", "description": "检查的 commit 数量", "default": 20}},
        [],
    ),
    make_mcp_tool(
        "check_release_readiness",
        "执行发布前五问自动化检视（Q1 需求有源 / Q2 变更有界 / Q3 数据有悔 / Q4 成本有谱 / Q5 通告有达）。"
        "退出码：0=PASS / 1=WARN / 2=BLOCK。",
        {"path": {"type": "string", "description": "项目根目录", "default": "."}},
        ["path"],
    ),
]

RESOURCES = [
    {"uri": "governance://checklist/default", "name": "发布前五问检视细则",
     "description": "Q1-Q5 详细检视标准、阻断条件与修复指引",
     "mimeType": "application/json"},
]

# ============================================================
# Tool 处理器
# ============================================================

def _run_script(script_name: str, args: list) -> tuple:
    """运行本地脚本，返回 (stdout, exit_code)。"""
    script_path = SCRIPT_DIR / script_name
    python = sys.executable
    cmd = [python, str(script_path)] + args
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=60)
        return r.stdout.strip(), r.returncode
    except Exception as e:  # codeguard: ignore GOLD_NO_BROAD_EXCEPTION
        return f"脚本执行失败: {e}", 1


def handle_release_notes(params: dict) -> dict:
    """生成 Release Notes。"""
    from_ref = params.get("from_ref", "HEAD~20")
    to_ref = params.get("to_ref", "HEAD")
    output = params.get("output_file", "")

    args = ["--from", from_ref, "--to", to_ref]
    if output:
        args += ["-o", output]

    stdout, exit_code = _run_script("release_notes_draft.py", args)
    return {"exit_code": exit_code, "notes": stdout, "from": from_ref, "to": to_ref,
            "output_file": output if output else None}


def handle_trace_requirements(params: dict) -> dict:
    """需求追溯检查。"""
    stdout, exit_code = _run_script("governance_gate.py", ["--mode", "auto-trace", "--format", "json"])

    if stdout and stdout.startswith("{"):
        try:
            result = json.loads(stdout)
            return {"exit_code": exit_code, "summary": result.get("summary", {}),
                    "details": result}
        except json.JSONDecodeError:  # codeguard: ignore GOLD_NO_EMPTY_EXCEPT
            pass

    return {"exit_code": exit_code, "raw_output": stdout, "note": "非 JSON 输出"}


def handle_check_release_readiness(params: dict) -> dict:
    """五问自动化检视。"""
    path = params.get("path", ".")
    stdout, exit_code = _run_script("governance_check.py", ["--path", path, "--format", "json"])

    if stdout and stdout.startswith("{"):
        try:
            result = json.loads(stdout)
            return result
        except json.JSONDecodeError:  # codeguard: ignore GOLD_NO_EMPTY_EXCEPT
            pass

    return {"exit_code": exit_code, "raw_output": stdout}


def handle_resource_read(uri: str) -> Any:
    """读取 MCP Resource。"""
    if uri == "governance://checklist/default":
        checklist = {
            "Q1-需求有源": "本版全部 PR 是否关联需求 ID（目标 ≥95%）？",
            "Q2-变更有界": "OpenAPI/接口契约是否存在破坏性变更？",
            "Q3-数据有悔": "迁移脚本 downgrade 是否非空且经回滚演练？",
            "Q4-成本有谱": "新增工作负载是否声明 requests/limits？成本偏离 ≤10%？",
            "Q5-通告有达": "是否产出技术版+业务版通告并发送全部干系人？",
        }
        return {"contents": [{"uri": uri, "mimeType": "application/json",
                "text": json.dumps(checklist, ensure_ascii=False, indent=2)}]}
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
            "release_notes": handle_release_notes,
            "trace_requirements": handle_trace_requirements,
            "check_release_readiness": handle_check_release_readiness,
        },
        resource_handler=handle_resource_read,
    )
    server.run_stdio()


if __name__ == "__main__":
    main()
