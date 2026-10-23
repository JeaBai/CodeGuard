#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fc-guardian MCP Server — JSON-RPC 2.0 over stdio (v3.0.0)
==========================================================
跨平台通用，支持 Claude Code、Cursor、VS Code、CodeBuddy 等所有 MCP 客户端。

补齐 SKILL适配整改计划 P0（阻断项）：fc-guardian 此前只有本地脚本、无 MCP 能力，
导致 5 个 Skill 的 MCP 覆盖为 4/5、声明一致性为 2/4。

设计约束（沿用计划 §4 的风险条款）：
  · **复用 `shared/_mcp_base.py`**，不新造协议层 —— 与 CodeGuard / governance-hub /
    iac-guardian 共用同一套 JSON-RPC 2.0 实现（协议版本由基类统一提供）。
  · **零修改边界**：本 server 只**只读 import** `fc_scan`（其内部再只读复用 CodeGuard 的
    `quality_embedded`），**不反向修改 CodeGuard 任何文件**。

暴露的 MCP Tool：
  1. fc_scan        — 对飞控项目执行硬件层 + 嵌入式层全量检测
                      （入参 path / format，出参 exit_code + summary + issues）

暴露的 MCP Resource：
  - fcguardian://detectors   — 当前启用的检测器清单与分层
"""

import json
import sys
from pathlib import Path
from typing import Any

# ── 路径设置 ──────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

# 与 CodeGuard 同一口径：skills/<name>/scripts → 上三级 → <root>/shared
_SHARED_DIR = SCRIPT_DIR.parent.parent.parent / "shared"
if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))

import fc_scan  # noqa: E402  本 Skill 的检测入口
from _mcp_base import MCPBaseServer  # noqa: E402  共享协议基类

# ============================================================
# MCP 协议常量
# ============================================================

PROTOCOL_VERSION = MCPBaseServer.PROTOCOL_VERSION
SERVER_NAME = "fc-guardian"
SERVER_VERSION = "3.0.0"
make_mcp_tool = MCPBaseServer.make_tool  # 本地别名，保持 TOOLS 定义简洁

# ============================================================
# MCP Tool Schema
# ============================================================

TOOLS = [
    make_mcp_tool(
        "fc_scan",
        "对飞控项目执行 fc-guardian 全量检测，覆盖硬件层与嵌入式规范层。"
        "硬件层：引脚冲突/复用/悬空（.ioc）、串口波特率/DMA/中断一致性、"
        "控制循环刷新率/delay 阻塞、arming/failsafe 状态机完整性、"
        "看门狗/电机解锁/传感器校准安全。"
        "嵌入式层：复用 CodeGuard 的嵌入式规范 9 项（动态内存/递归/goto/ISR 安全/"
        "volatile 寄存器/局部大数组/ISR 优先级/看门狗/电源管理）。"
        "退出码语义：0=PASS / 1=WARN / 2=BLOCK。",
        {
            "path": {
                "type": "string",
                "description": "飞控项目根目录（默认当前工作目录）",
                "default": ".",
            },
            "format": {
                "type": "string",
                "enum": ["summary", "json"],
                "description": "summary=仅统计与判定；json=附完整 issues 列表",
                "default": "summary",
            },
        },
        ["path"],
    ),
]

# ============================================================
# MCP Resource
# ============================================================

RESOURCES = [
    {
        "uri": "fcguardian://detectors",
        "name": "已启用检测器清单",
        "description": "fc-guardian 当前注册的检测器（按硬件层 / 嵌入式层分组）",
        "mimeType": "application/json",
    },
]


# ============================================================
# Tool Handlers
# ============================================================

def handle_fc_scan(params: dict) -> dict:
    """执行 fc-guardian 全量检测。

    直接复用 `fc_scan.scan_project()`，保证 MCP 与 CLI 两条入口**判定完全一致**
    （避免"MCP 结果与命令行结果不同"这类一致性缺陷）。
    """
    path = params.get("path") or "."
    fmt = params.get("format") or "summary"

    issues, exit_code, summary = fc_scan.scan_project(path)

    result: dict[str, Any] = {
        "exit_code": exit_code,
        "verdict": {0: "PASS", 1: "WARN", 2: "BLOCK"}.get(exit_code, "UNKNOWN"),
        "summary": summary,
        "scanned_path": str(Path(path).resolve()),
    }
    if fmt == "json":
        result["issues"] = issues
    else:
        # summary 模式：只给分类计数，避免把大列表灌进上下文
        by_cat: dict[str, int] = {}
        for it in issues:
            by_cat[it.get("category", "?")] = by_cat.get(it.get("category", "?"), 0) + 1
        result["by_category"] = dict(sorted(by_cat.items(), key=lambda kv: -kv[1]))
        if summary.get("error"):
            result["error"] = summary["error"]
    return result


def _detector_catalog() -> list:
    """从 fc_scan 的调度表导出检测器清单（单一事实源，避免文档与实现漂移）。"""
    out = []
    for layer, fn in getattr(fc_scan, "_DETECTORS", []):
        doc = (fn.__doc__ or "").strip().splitlines()
        out.append({
            "layer": layer,
            "entry": fn.__name__,
            "module": getattr(fn, "__module__", ""),
            "summary": doc[0] if doc else "",
        })
    return out


def handle_resource_read(uri: str) -> Any:
    if uri == "fcguardian://detectors":
        payload = {
            "server": SERVER_NAME,
            "version": SERVER_VERSION,
            "protocol_version": PROTOCOL_VERSION,
            "detectors": _detector_catalog(),
            "note": "嵌入式层为只读复用 CodeGuard 的 quality_embedded（零修改边界）",
        }
        return {"contents": [{
            "uri": uri,
            "mimeType": "application/json",
            "text": json.dumps(payload, ensure_ascii=False, indent=2),
        }]}
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
            "fc_scan": handle_fc_scan,
        },
        resource_handler=handle_resource_read,
    )
    # 基类负责 --project-root 解析与 chdir；fc_scan 的 path 默认 "." 即项目根
    server.run_stdio()


if __name__ == "__main__":
    main()
