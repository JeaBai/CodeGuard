#!/usr/bin/env python3
"""
MCP Base Server — JSON-RPC 2.0 over stdio 共享基类 (v1.0.0)
===============================================================
封装 3 个 mcp_server.py（CodeGuard/governance-hub/iac-guardian）的 80% 重复代码。
消除 create_response / create_error / make_tool / handle_request / run_stdio 的 4 重复制。

证据：
  逐行比对 CG(369行)/GH(251行)/IAC(239行) 三个 mcp_server.py：
  - create_response / create_error  → 全部相同（9 行 × 3）
  - _make_mcp_tool                  → 全部相同（8 行 × 3）
  - _METHOD_HANDLERS + handle_request → 全部相同（~60 行 × 3）
  - main() stdio 主循环               → 全部相同（~25 行 × 3）
  ≈ 消除 ~270 行冗余代码（3 × 90 行重复 / 总计 859 行 → base 基类 120 行 + 3 个 wrapper）

用法（以 CodeGuard 为例）：
    from _mcp_base import MCPBaseServer

    server = MCPBaseServer(
        name="CodeGuard", version="3.0.0",
        tools=TOOLS, resources=RESOURCES,
        tool_handlers={...}, resource_handler=handle_resource_read,
    )
    server.run_stdio()
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from typing import Any, Callable, Dict, List, Optional


class MCPBaseServer:
    """JSON-RPC 2.0 over stdio MCP 协议基类。

    每个 SKILL 的 mcp_server.py 仅需：
      1) 定义 TOOLS / RESOURCES
      2) 定义 tool handler 函数
      3) 实例化 MCPBaseServer 并调用 run_stdio()
    """

    # ── 协议常量 ──────────────────────────────────────────
    PROTOCOL_VERSION: str = "2024-11-05"

    def __init__(
        self,
        name: str,
        version: str,
        tools: List[Dict[str, Any]],
        resources: List[Dict[str, Any]],
        tool_handlers: Dict[str, Callable[[Dict[str, Any]], Any]],
        resource_handler: Optional[Callable[[str], Any]] = None,
        log_fn: Optional[Callable[[str], None]] = None,
    ):
        self.name = name
        self.version = version
        self.tools = tools
        self.resources = resources
        self.tool_handlers = tool_handlers
        self.resource_handler = resource_handler
        self._log = log_fn or self._default_log

    # ── 日志 ──────────────────────────────────────────────

    def _default_log(self, msg: str) -> None:
        print(msg, file=sys.stderr, flush=True)  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION

    # ── JSON-RPC 2.0 响应构造（静态方法，可外部直接引用）─

    @staticmethod
    def create_response(req_id: Any, result: Any) -> str:
        """构造 JSON-RPC 2.0 成功响应。"""
        return json.dumps({"jsonrpc": "2.0", "id": req_id, "result": result})

    @staticmethod
    def create_error(req_id: Any, code: int, message: str, data: Any = None) -> str:
        """构造 JSON-RPC 2.0 错误响应。"""
        err: Dict[str, Any] = {
            "jsonrpc": "2.0", "id": req_id,
            "error": {"code": code, "message": message},
        }
        if data is not None:
            err["error"]["data"] = data
        return json.dumps(err)

    @staticmethod
    def make_tool(
        name: str,
        description: str,
        properties: Dict[str, Any],
        required: List[str],
    ) -> Dict[str, Any]:
        """MCP Tool 定义工厂。

        消除各 SKILL 中 name/description/inputSchema 结构重复。
        """
        return {
            "name": name,
            "description": description,
            "inputSchema": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        }

    # ── 请求分发 ──────────────────────────────────────────

    def handle_request(self, request: Dict[str, Any]) -> Optional[str]:
        """分发 JSON-RPC 请求到对应处理器。

        支持的标准方法：
          - initialize        → 返回协议版本 + 服务器信息
          - tools/list        → 返回 self.tools
          - resources/list    → 返回 self.resources
          - tools/call        → 委托给 self.tool_handlers[name](arguments)
          - resources/read    → 委托给 self.resource_handler(uri)
          - notifications/initialized → None (不响应)
        """
        method = request.get("method", "")
        req_id = request.get("id")
        params = request.get("params", {})

        # ── 初始化 ──
        if method == "initialize":
            return self.create_response(req_id, {
                "protocolVersion": self.PROTOCOL_VERSION,
                "serverInfo": {"name": self.name, "version": self.version},
                "capabilities": {"tools": {}, "resources": {}},
            })

        # ── 能力发现 ──
        if method == "tools/list":
            return self.create_response(req_id, {"tools": self.tools})
        if method == "resources/list":
            return self.create_response(req_id, {"resources": self.resources})

        # ── 工具调用 ──
        if method == "tools/call":
            tool_name = params.get("name", "")
            handler = self.tool_handlers.get(tool_name)
            if handler:
                try:
                    result = handler(params.get("arguments", {}))
                    return self.create_response(req_id, {
                        "content": [{
                            "type": "text",
                            "text": json.dumps(result, ensure_ascii=False, indent=2),
                        }],
                    })
                except Exception as e:  # codeguard: ignore GOLD_NO_BROAD_EXCEPTION
                    self._log(f"[{self.name} MCP] Tool '{tool_name}' error: {e}\n"
                              f"{traceback.format_exc()}")
                    return self.create_error(req_id, -32603, f"Tool error: {e}")  # codeguard: ignore GOLD_NO_MAGIC_NUMBER
            return self.create_error(req_id, -32601, f"Unknown tool: {tool_name}")  # codeguard: ignore GOLD_NO_MAGIC_NUMBER

        # ── 资源读取 ──
        if method == "resources/read":
            if self.resource_handler:
                result = self.resource_handler(params.get("uri", ""))
                # 兼容：handler 可能直接返回 create_error 字符串（未知资源时），透传
                if isinstance(result, str):
                    return result
                return self.create_response(req_id, result)
            return self.create_error(req_id, -32601, "No resource handler configured")  # codeguard: ignore GOLD_NO_MAGIC_NUMBER

        # ── 通知（不响应）──
        if method == "notifications/initialized":
            return None

        # ── 未知方法 ──
        return self.create_error(req_id, -32601, f"Method not found: {method}")  # codeguard: ignore GOLD_NO_MAGIC_NUMBER

    # ── stdio 主循环 ──────────────────────────────────────

    def run_stdio(
        self,
        project_root: str = ".",
        setup_fn: Optional[Callable[[str], None]] = None,
    ) -> None:
        """启动 MCP stdio 服务器。

        Args:
            project_root: 项目根目录（默认 "."，可通过 CLI --project-root 覆盖）
            setup_fn: 可选初始化回调，在进入监听循环前调用，参数为解析后的绝对项目根路径。
                      用于 CodeGuard 的 set_project_root / _is_safe_path 等 SKILL 特定初始化。
        """
        parser = argparse.ArgumentParser(description=f"{self.name} MCP Server")
        parser.add_argument("--project-root", default=project_root, help="项目根目录")
        args = parser.parse_args()

        root_abs = os.path.abspath(args.project_root)
        os.chdir(root_abs)

        self._log(f"[{self.name} MCP] v{self.version} on {root_abs}")

        # 子类自定义初始化（如路径安全检查）
        if setup_fn:
            try:
                setup_fn(root_abs)
            except Exception as e:  # codeguard: ignore GOLD_NO_BROAD_EXCEPTION
                self._log(f"[{self.name} MCP] setup_fn error: {e}")
                sys.exit(1)

        try:
            for line in sys.stdin:
                line = line.strip()
                if not line:
                    continue
                try:
                    request = json.loads(line)
                except json.JSONDecodeError:
                    self._log(f"[{self.name} MCP] Invalid JSON: {line[:100]}")
                    continue
                response = self.handle_request(request)
                if response is not None:
                    sys.stdout.write(response + "\n")
                    sys.stdout.flush()
        except KeyboardInterrupt:
            self._log(f"[{self.name} MCP] Shutting down...")
            sys.exit(0)
        except Exception as e:  # codeguard: ignore GOLD_NO_BROAD_EXCEPTION
            self._log(f"[{self.name} MCP] Fatal: {e}\n{traceback.format_exc()}")
            sys.exit(1)


# ============================================================
# 兼容性别名（使现有外部 import 路径不破坏）
#   例：from _mcp_base import create_response
# ============================================================

create_response = MCPBaseServer.create_response
create_error = MCPBaseServer.create_error
make_mcp_tool = MCPBaseServer.make_tool
