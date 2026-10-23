"""
MCP 传输层 — MCP 协议适配（stdio + SSE）+ Server 实例创建
被 mcp_server.py CLI 入口调用
"""

import logging
from typing import Any

from mcp_tools import TOOL_REGISTRY

logger = logging.getLogger(__name__)  # codeguard: ignore GOLD_NO_GLOBAL_STATE

MCP_AVAILABLE = False
try:
    from mcp.server import Server
    from mcp.server.models import InitializationCapabilities
    from mcp.server.stdio import stdio_server
    import mcp.types as types

    MCP_AVAILABLE = True
except ImportError:
    logger.debug("mcp 库未安装，MCP Server 模式不可用。安装: pip install mcp")


async def setup_mcp_server() -> "Server":
    """创建并配置 MCP Server 实例"""
    server = Server("project-manager")

    @server.list_tools()
    async def handle_list_tools() -> list["types.Tool"]:
        tools = []
        for name, config in TOOL_REGISTRY.items():
            tools.append(
                types.Tool(
                    name=name,
                    description=config["description"],
                    inputSchema=config["inputSchema"],
                )
            )
        return tools

    @server.call_tool()
    async def handle_call_tool(
        name: str, arguments: dict[str, Any] | None
    ) -> list["types.TextContent"]:
        if name not in TOOL_REGISTRY:
            raise ValueError(f"Unknown tool: {name}")

        handler = TOOL_REGISTRY[name]["handler"]
        args = arguments or {}
        result = await handler(**args)
        return [types.TextContent(type="text", text=result)]

    return server


async def run_stdio():
    """以 stdio 模式运行 MCP Server"""
    if not MCP_AVAILABLE:
        logger.error("mcp 库未安装，无法启动 stdio 模式。安装: pip install mcp")
        print(  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
            "ERROR: mcp package not installed. Run: pip install mcp",
            flush=True,
        )
        return
    server = await setup_mcp_server()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationCapabilities(
                sampling=None,
                experimental=None,
                roots=None,
            ),
        )


async def run_sse(port: int = 8765):  # codeguard: ignore GOLD_NO_MAGIC_NUMBER
    """以 SSE 模式运行 MCP Server（需要 mcp[cli]）"""
    if not MCP_AVAILABLE:
        logger.error("mcp 库未安装，无法启动 SSE 模式。安装: pip install mcp[cli]")
        print(  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
            "ERROR: mcp package not installed. Run: pip install mcp",
            flush=True,
        )
        return

    try:
        from mcp.server.sse import SseServerTransport
        from starlette.applications import Starlette
        from starlette.routing import Route
        import uvicorn

        server = await setup_mcp_server()
        sse = SseServerTransport("/messages/")

        async def handle_sse(request):
            async with sse.connect_sse(
                request.scope, request.receive, request._send
            ) as streams:
                await server.run(
                    streams[0],
                    streams[1],
                    server.create_initialization_options(),
                )

        async def handle_messages(request):
            await sse.handle_post_message(
                request.scope, request.receive, request._send
            )

        app = Starlette(
            routes=[
                Route("/sse", endpoint=handle_sse),
                Route("/messages/", endpoint=handle_messages, methods=["POST"]),
            ]
        )
        print(f"MCP Server (SSE) starting on http://localhost:{port}/sse")  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
        await uvicorn.run(app, host="0.0.0.0", port=port)
    except ImportError:
        logger.debug("SSE 模式需要额外依赖: pip install mcp[cli] uvicorn starlette")
        print(  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
            "ERROR: SSE mode requires additional packages. Run: pip install mcp[cli] uvicorn starlette",
            flush=True,
        )


async def run_stdio_fallback():
    """当 mcp 包未安装时，使用 _mcp_base.MCPBaseServer 提供基本 stdio 服务。

    将 project-manager 的 async tool handler 包装为同步调用，
    通过 asyncio.run() 执行。
    """
    import sys as _sys
    import os as _os
    import json as _json

    # 添加 shared 目录到路径
    _shared_dir = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                                 "..", "..", "..", "shared")
    if _shared_dir not in _sys.path:
        _sys.path.insert(0, _shared_dir)

    from _mcp_base import MCPBaseServer

    # 构建 tools 列表（从 TOOL_REGISTRY 转换为 _mcp_base 格式）
    tools = []
    for name, config in TOOL_REGISTRY.items():
        tools.append(MCPBaseServer.make_tool(
            name=name,
            description=config["description"],
            properties=config.get("inputSchema", {}).get("properties", {}),
            required=config.get("inputSchema", {}).get("required", []),
        ))

    # 构建 tool_handlers（包装 async handler 为同步）
    import asyncio as _asyncio

    def _make_sync_handler(async_handler):
        def sync_handler(args):
            return _asyncio.run(async_handler(**args))
        return sync_handler

    tool_handlers = {}
    for name, config in TOOL_REGISTRY.items():
        tool_handlers[name] = _make_sync_handler(config["handler"])

    resources = []

    server = MCPBaseServer(
        name="project-manager",
        version="3.0.0",
        tools=tools,
        resources=resources,
        tool_handlers=tool_handlers,
    )

    server.run_stdio()
