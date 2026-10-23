"""
MCP Server — 项目管理全流程助手 (入口)
符合 MCP (Model Context Protocol) 协议规范
支持 stdio 传输模式，可被 Claude Code / Cursor / VS Code 等客户端调用

启动方式：
    python mcp_server.py                    # stdio 模式
    python mcp_server.py --transport sse --port 8765  # SSE 模式  # codeguard: ignore GOLD_NO_MAGIC_NUMBER

依赖：
    pip install mcp httpx beautifulsoup4

架构（v2.3）：
    mcp_data.py      — 数据层：五阶段检查项库
    mcp_tools.py     — 工具箱层：8 个阶段专用工具
    mcp_transport.py — 传输层：MCP 协议适配
    mcp_server.py    — 入口层：CLI 命令行解析与分发（本文件）
"""

import argparse
import asyncio
import json
import logging
import os
import re
import sys
import time

logging.basicConfig(level=logging.WARNING, format="[%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)  # codeguard: ignore GOLD_NO_GLOBAL_STATE

# ── v2.2: 会话记忆持久化 ─────────────────────────────────────
_SESSION_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "..", ".codebuddy", "session_state.json")
_SESSION_FILE = os.path.normpath(_SESSION_FILE)


def _restore_session() -> dict:
    """从 .codebuddy/session_state.json 恢复上次会话上下文。"""
    if not os.path.exists(_SESSION_FILE):
        return {}
    try:
        with open(_SESSION_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        logger.info("会话恢复: 上次阶段=%s, 活跃任务=%d, 关键决策=%d",
                     data.get("active_phase", "?"),
                     len(data.get("active_tasks", [])),
                     len(data.get("key_decisions", [])))
        return data
    except (json.JSONDecodeError, OSError):
        logger.debug("会话状态文件损坏，跳过恢复")
        return {}


def _save_session(active_phase: str = "", active_tasks: list = None,
                  key_decisions: list = None, unresolved_issues: list = None):
    """保存当前会话上下文。"""
    from datetime import datetime, timezone
    os.makedirs(os.path.dirname(_SESSION_FILE), exist_ok=True)
    state = {
        "last_session": datetime.now(timezone.utc).isoformat(),
        "active_phase": active_phase,
        "active_tasks": active_tasks or [],
        "key_decisions": key_decisions or [],
        "unresolved_issues": unresolved_issues or [],
        "experience_since_last_save": 0,
    }
    try:
        with open(_SESSION_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except OSError:
        logger.debug("会话状态保存失败")


# 启动时恢复
_SESSION_STATE = _restore_session()

# ── v2.3: 指标日志路径 ─────────────────────────────────────
_METRICS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "..", ".codebuddy", "metrics_log.jsonl")
_METRICS_FILE = os.path.normpath(_METRICS_FILE)


def _record_metric(tool_name: str, elapsed_ms: float):
    """写入单条指标到 JSON Lines 文件。"""
    from datetime import datetime, timezone
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "tool": tool_name,
        "elapsed_ms": round(elapsed_ms, 3),
    }
    try:
        os.makedirs(os.path.dirname(_METRICS_FILE), exist_ok=True)
        with open(_METRICS_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass


def _auto_extract(tool_name: str, result: str):
    """v2.3: 自动经验提取管道 — 从复盘/门禁结果中解析关键决策并登记。"""
    if not result:
        return
    try:
        from experience_library import register, dedup_check
    except ImportError:
        return

    if tool_name == "generate_retrospective":
        # 提取复盘要点
        patterns = {
            "做对了什么": r'(?:做对了什么|做得好的|成功经验)[：:]\s*(.+?)(?:\n|$)',
            "做错了什么": r'(?:做错了什么|踩过的坑|失败教训)[：:]\s*(.+?)(?:\n|$)',
            "目标偏差": r'(?:目标达成率|目标偏差)[：:]\s*(\d+)%',
        }
        for label, pat in patterns.items():
            m = re.search(pat, result, re.IGNORECASE)
            if m:
                title = f"[复盘] {label}: {m.group(1)[:60]}"
                content = f"# {label}\n\n{m.group(0)}\n\n来源: 项目复盘报告"
                ck = dedup_check(title, content)
                if not ck["duplicate"]:
                    register(asset_type="lesson", title=title, content=content,
                             tags="retrospective,lesson", visibility="team", source="auto-extract")

    elif tool_name == "quality_gate_check":
        # 提取技术债务
        m = re.search(r'技术债务[：:]\s*(\d+)\s*项', result)
        if m:
            title = f"[门禁] 技术债务共 {m.group(1)} 项"
            content = f"# 技术债务\n\n{m.group(0)}\n\n来源: 质量门禁报告"
            ck = dedup_check(title, content)
            if not ck["duplicate"]:
                register(asset_type="decision", title=title, content=content,
                         tags="quality_gate,tech_debt", visibility="team", source="auto-extract")


def _show_metrics_summary(limit: int = 20):
    """展示最近 N 次调用的统计摘要。"""
    if not os.path.exists(_METRICS_FILE):
        print("暂无指标数据。")  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
        return
    entries = []
    try:
        with open(_METRICS_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    entries.append(json.loads(line))
    except (json.JSONDecodeError, OSError):
        pass
    if not entries:
        print("暂无指标数据。")  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
        return

    recent = entries[-limit:]
    times = [e["elapsed_ms"] for e in recent]
    tools = {}
    for e in recent:
        t = e["tool"]
        tools[t] = tools.get(t, []) + [e["elapsed_ms"]]

    print("=" * 50)  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
    print(f"最近 {len(recent)} 次调用 指标摘要")  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
    print(f"  平均: {sum(times)/len(times):.1f}ms  |  最快: {min(times):.1f}ms  |  最慢: {max(times):.1f}ms")  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
    print("─" * 50)  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
    for t, vals in sorted(tools.items(), key=lambda x: -sum(x[1])/len(x[1])):
        print(f"  [{t}] count={len(vals)} avg={sum(vals)/len(vals):.1f}ms")  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
    print("=" * 50)  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION

# 确保同目录模块可导入
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _print_tool_list():
    """打印所有可用工具列表"""
    from mcp_tools import TOOL_REGISTRY

    print("=" * 60)  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
    print("项目管理全流程 MCP Server — 可用工具列表")  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
    print("=" * 60)  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
    for name, config in TOOL_REGISTRY.items():
        print(f"\n  📌 {name}")  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
        print(f"      {config['description']}")  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
    print("\n" + "=" * 60)  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION


def _run_single_tool(tool_name: str, args_json: str, auto_extract: bool = True):
    """非 MCP 模式直接调用单个工具"""
    from mcp_tools import TOOL_REGISTRY

    if tool_name not in TOOL_REGISTRY:
        print(f"Unknown tool: {tool_name}")  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
        print(f"Available: {', '.join(TOOL_REGISTRY.keys())}")  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
        return
    try:
        params = json.loads(args_json)
    except json.JSONDecodeError:
        logger.debug("CLI 参数 JSON 解析失败，使用空字典")
        params = {}

    # v2.3: 调用计时
    t0 = time.perf_counter()
    result = asyncio.run(TOOL_REGISTRY[tool_name]["handler"](**params))
    elapsed_ms = (time.perf_counter() - t0) * 1000
    _record_metric(tool_name, elapsed_ms)
    logger.info("[PERF] %s took %.1fms", tool_name, elapsed_ms)

    print(result)  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION

    # v2.2: 自动保存会话状态
    phase_map = {
        "start_feasibility_check": "phase1_feasibility",
        "create_project_plan": "phase2_planning",
        "daily_progress_check": "phase3_execution",
        "generate_retrospective": "phase4_retrospective",
        "manage_experience_library": "phase9_experience_library",
        "configure_agent_roster": "phase10_agent_roster",
    }
    _save_session(active_phase=phase_map.get(tool_name, tool_name))

    # v2.3: 自动经验提取管道
    if auto_extract:
        try:
            _auto_extract(tool_name, str(result)[:5000])
        except Exception:
            logger.debug("自动提取管道执行异常，跳过")


def main():
    parser = argparse.ArgumentParser(description="项目管理全流程 MCP Server")
    # ⚠️ --project-root 必须保留：其余 4 个 Skill 的 MCP server 经 shared/_mcp_base.py
    #    统一提供该参数。本 server 是自建 argparse，若缺此参数，客户端按统一方式启动
    #    会被 argparse 直接拒绝（rc=2）→ MCP 服务静默不生效（2026-10-04 修复）。
    parser.add_argument("--project-root", default=".",
                        help="项目根目录（与其他 Skill 的 MCP server 保持一致的启动契约）")
    parser.add_argument("--transport", choices=["stdio", "sse"], default="stdio", help="传输协议 (default: stdio)")
    parser.add_argument("--port", type=int, default=8765, help="SSE 模式端口 (default: 8765)")  # codeguard: ignore GOLD_NO_MAGIC_NUMBER
    parser.add_argument("--list-tools", action="store_true", help="列出所有可用工具（非MCP模式）")
    parser.add_argument("--tool", type=str, help="直接调用指定工具（非MCP模式）")
    parser.add_argument("--args", type=str, default="{}", help="工具参数（JSON格式）")
    parser.add_argument("--no-auto-extract", action="store_true", help="关闭自动经验提取管道（v2.3）")  # v2.3
    parser.add_argument("--metrics", action="store_true", help="显示调用指标摘要（v2.3）")  # v2.3

    args = parser.parse_args()

    # 统一行为：切到项目根目录（与 shared/_mcp_base.py 的 run_stdio 一致），
    # 使三条路径（自建 stdio / SSE / fallback）对相对路径有相同解释。
    import os as _os
    _root = _os.path.abspath(args.project_root)
    if _os.path.isdir(_root):
        _os.chdir(_root)

    if args.metrics:
        _show_metrics_summary()
        return

    if args.list_tools:
        _print_tool_list()
        return

    if args.tool:
        _run_single_tool(args.tool, args.args, auto_extract=not args.no_auto_extract)
        return

    from mcp_transport import run_stdio, run_sse, MCP_AVAILABLE

    if args.transport == "sse":
        if not MCP_AVAILABLE:
            print("错误: SSE 模式需要 mcp 包。请运行: pip install mcp", file=sys.stderr)
            sys.exit(1)
        asyncio.run(run_sse(args.port))
    else:
        if MCP_AVAILABLE:
            asyncio.run(run_stdio())
        else:
            # Fallback: 使用 _mcp_base.py 提供 stdio 服务
            # ⚠️ run_stdio_fallback 是 async def —— 必须用 asyncio.run 驱动，
            #    否则只是创建了一个 coroutine 便返回，服务立刻退出（tools/list 返回 0 个工具）。
            from mcp_transport import run_stdio_fallback
            asyncio.run(run_stdio_fallback())


if __name__ == "__main__":
    main()
