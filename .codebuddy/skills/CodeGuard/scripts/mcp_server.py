#!/usr/bin/env python3
"""
CodeGuard MCP Server — JSON-RPC 2.0 over stdio
================================================
使 CodeGuard 跨平台通用，支持 Claude Code、Cursor、VS Code、CodeBuddy 等所有 MCP 客户端。

MCP 协议版本：2024-11-05
传输层：stdio (Streamable HTTP 可选)
Python 依赖：无（零外部依赖，纯标准库实现）

暴露的 MCP Tool：
  1. review_file     — 对单个文件执行质量检测
  2. review_diff     — 对 git diff 变更执行增量检测
  3. execute_rules   — 列出所有活跃规则
  4. inject_constraints — 生成架构约束提示（注入 AI 上下文）

暴露的 MCP Resource：
  - codeguard://rules/default     — 默认规则集
  - codeguard://config/project    — 项目自定义配置

用法：
  直接运行 (stdio 模式):
    python mcp_server.py

  作为 MCP 客户端配置 (Claude Code):
  {
    "mcpServers": {
      "codeguard": {
        "command": "python",
        "args": ["path/to/mcp_server.py", "--project-root", "."]
      }
    }
  }

基于 @mrzadexinho/codeguard 的 MCP 工具设计参考（MIT License）。
"""

import argparse
import json
import os
import sys
import traceback
from pathlib import Path

# 添加同级目录以便 import quality_check 和 constraint_injector
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import quality_check
import constraint_injector


# ============================================================
# MCP 协议常量
# ============================================================

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "CodeGuard"
SERVER_VERSION = "2.0.0"

# ============================================================
# JSON-RPC 2.0 消息处理
# ============================================================

def create_response(request_id, result):
    return json.dumps({
        "jsonrpc": "2.0",
        "id": request_id,
        "result": result
    })

def create_error(request_id, code, message, data=None):
    err = {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}
    if data:
        err["error"]["data"] = data
    return json.dumps(err)

def create_notification(method, params=None):
    msg = {"jsonrpc": "2.0", "method": method}
    if params:
        msg["params"] = params
    return json.dumps(msg)


# ============================================================
# Tool 定义
# ============================================================

TOOLS = [
    {
        "name": "review_file",
        "description": "对单个文件执行完整质量检测，返回所有发现的问题及置信度分数。"
                       "检测范围：圈复杂度、嵌套深度、参数数量、安全红线、异常处理、架构分层。"
                       "置信度：90-100=AST精确 / 80-89=剥离后正则 / 70-79=原始正则 / 60-69=启发式",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "要检测的文件绝对路径"
                },
                "mode": {
                    "type": "string",
                    "enum": ["personal", "team"],
                    "description": "检测模式：personal(个人)、team(团队，含命名一致性检查)",
                    "default": "personal"
                }
            },
            "required": ["file_path"]
        }
    },
    {
        "name": "review_diff",
        "description": "对 git 变更文件执行增量检测。自动识别 4 种变更来源："
                       "已提交变更(diff HEAD)、未暂存(diff)、已暂存(diff --cached)、未跟踪(ls-files --others)。"
                       "适合 CI/CD 流水线和 pre-commit hook。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_root": {
                    "type": "string",
                    "description": "项目根目录路径",
                    "default": "."
                },
                "mode": {
                    "type": "string",
                    "enum": ["personal", "team"],
                    "description": "检测模式",
                    "default": "personal"
                }
            },
            "required": ["project_root"]
        }
    },
    {
        "name": "execute_rules",
        "description": "列出当前项目所有活跃的质量规则，包括通用规则和团队自定义规则。"
                       "每条规则包含：id、描述、严重性(block/warn/info)、适用范围、置信度来源。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_root": {
                    "type": "string",
                    "description": "项目根目录路径",
                    "default": "."
                }
            },
            "required": ["project_root"]
        }
    },
    {
        "name": "inject_constraints",
        "description": "分析项目结构并生成架构约束提示，用于注入到 AI 对话上下文。"
                       "输出格式支持 prompt（完整约束文本）和 checklist（轻量检查清单）。"
                       "基于首因/近因效应设计，对抗 LLM 的 'Lost in the Middle' 问题。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_root": {
                    "type": "string",
                    "description": "项目根目录路径",
                    "default": "."
                },
                "format": {
                    "type": "string",
                    "enum": ["prompt", "checklist", "json"],
                    "description": "输出格式",
                    "default": "checklist"
                }
            },
            "required": ["project_root"]
        }
    }
]

RESOURCES = [
    {
        "uri": "codeguard://rules/default",
        "name": "CodeGuard 默认规则集",
        "description": "所有内置的通用质量规则（SOLID、分层架构、安全红线、度量阈值等）",
        "mimeType": "application/json"
    },
    {
        "uri": "codeguard://config/project",
        "name": "项目自定义配置",
        "description": "当前项目 .code-guardian 目录下的所有自定义规则和配置",
        "mimeType": "application/json"
    }
]


# ============================================================
# Tool 处理器
# ============================================================

# project_root 由 main() 在启动时设置
_PROJECT_ROOT = None

def set_project_root(path):
    """设置项目根目录（由 main() 调用）"""
    global _PROJECT_ROOT
    _PROJECT_ROOT = os.path.abspath(path)

def _is_safe_path(file_path):
    """检查文件路径是否在项目根目录内（防止路径遍历攻击）"""
    if _PROJECT_ROOT is None:
        return True  # 未设置项目根目录时允许（向后兼容 CLI 模式）
    try:
        real_file = os.path.realpath(os.path.abspath(file_path))
        real_root = os.path.realpath(_PROJECT_ROOT)
        return os.path.commonpath([real_file, real_root]) == real_root
    except Exception:
        return False


def handle_review_file(params):
    """处理 review_file 请求"""
    file_path = params.get("file_path", "")
    mode = params.get("mode", "personal")
    
    if not file_path or not os.path.isfile(file_path):
        return create_error(None, -32602, f"Invalid file_path: {file_path}")
    
    # 路径沙箱检查（防止目录遍历攻击）
    if not _is_safe_path(file_path):
        return create_error(None, -32602, f"Access denied: file_path is outside project root")
    
    # 文件类型感知：先分类，按类型决定检测策略（v2.0.2: 修复 file_type 未传递）
    file_type = _classify_file(file_path)
    
    # 生成代码/文档：直接跳过，返回空结果
    if file_type in ("generated", "doc"):
        return {
            "issues": [],
            "file_type": file_type,
            "summary": {"total_issues": 0, "blocks": 0, "warnings": 0, "info": 0, "avg_confidence": 0},
            "exit_code": 0,
            "note": f"跳过 {file_type} 类型文件"
        }
    
    # 单文件检测
    collector = quality_check.IssueCollector()
    
    # 手动派发单文件检测
    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".py":
        quality_check.check_python_file(file_path, collector)
    elif ext in (".js", ".ts", ".mjs"):
        quality_check.check_javascript_file(file_path, collector, ext)
    elif ext == ".java":
        quality_check.check_java_file(file_path, collector)
    elif ext == ".go":
        quality_check.check_go_file(file_path, collector)
    elif ext == ".cs":
        quality_check.check_csharp_file(file_path, collector)
    else:
        quality_check.check_generic_file(file_path, collector, ext)
    
    # 架构检测和重复检测需要多文件，单文件跳过
    if mode == "team":
        quality_check.check_naming_consistency([file_path], collector)
    
    return {
        "issues": [
            {"severity": i["severity"], "category": i["category"],
             "file": i["file"], "line": i["line"],
             "message": i["message"], "suggestion": i.get("suggestion", ""),
             "confidence": i.get("confidence", 0)}
            for i in collector.issues
        ],
        "file_type": file_type,
        "summary": collector.summary(),
        "exit_code": 2 if collector.has_blocks() else (1 if collector.has_warns() else 0)
    }


def handle_review_diff(params):
    """处理 review_diff 请求"""
    project_root = params.get("project_root", ".")
    mode = params.get("mode", "personal")
    
    root_path = os.path.abspath(project_root)
    if not os.path.isdir(root_path):
        return create_error(None, -32602, f"Invalid project_root: {root_path}")
    
    collector = quality_check.run_quality_check(root_path, mode="diff")
    custom_rules = quality_check.load_custom_quality_rules(root_path)
    if custom_rules:
        quality_check.check_custom_rules(
            quality_check.get_changed_files(root_path), custom_rules, collector
        )
    
    return {
        "issues": [
            {"severity": i["severity"], "category": i["category"],
             "file": i["file"], "line": i["line"],
             "message": i["message"], "suggestion": i.get("suggestion", ""),
             "confidence": i.get("confidence", 0)}
            for i in collector.issues
        ],
        "summary": collector.summary(),
        "exit_code": 2 if collector.has_blocks() else (1 if collector.has_warns() else 0)
    }


def handle_execute_rules(params):
    """处理 execute_rules 请求"""
    project_root = params.get("project_root", ".")
    root_path = os.path.abspath(project_root)
    
    # 默认规则
    skill_rules = constraint_injector.load_skill_rules()
    
    # 自定义规则
    custom_rules = constraint_injector.load_custom_rules(root_path)
    
    all_rules = []
    for r in skill_rules:
        all_rules.append({
            "id": r["id"],
            "name": r["name"],
            "description": r["description"],
            "severity": r["severity"],
            "source": "builtin",
            "confidence": "90-95" if r["severity"] == "block" else "80-85"
        })
    
    if custom_rules.get("has_custom"):
        for r in custom_rules["rules"]:
            all_rules.append({
                "id": r.get("id", "?"),
                "name": r.get("name", r.get("description", "")),
                "description": r.get("description", ""),
                "severity": r.get("severity", "warn"),
                "source": "custom",
                "confidence": "85-95",
                "target": r.get("target", "all"),
                "pattern": r.get("pattern", "")
            })
    
    return {
        "total_rules": len(all_rules),
        "builtin_rules": len(skill_rules),
        "custom_rules": len(custom_rules.get("rules", [])),
        "rules": all_rules
    }


def handle_inject_constraints(params):
    """处理 inject_constraints 请求"""
    project_root = params.get("project_root", ".")
    fmt = params.get("format", "checklist")
    
    root_path = os.path.abspath(project_root)
    structure = constraint_injector.detect_project_structure(root_path)
    custom_rules = constraint_injector.load_custom_rules(root_path)
    skill_rules = constraint_injector.load_skill_rules()
    
    if fmt == "prompt":
        content = constraint_injector.generate_constraint_prompt(structure, custom_rules, skill_rules)
    elif fmt == "checklist":
        content = constraint_injector.generate_quick_checklist(structure)
    else:
        content = json.dumps({
            "structure": structure,
            "skill_rules": skill_rules,
            "custom_rules": custom_rules
        }, ensure_ascii=False, indent=2)
    
    return {
        "format": fmt,
        "content": content,
        "project_type": structure["type"],
        "languages": structure["languages"],
        "has_custom_rules": custom_rules.get("has_custom", False)
    }


# ============================================================
# Resource 处理器
# ============================================================

def handle_resource_read(uri):
    """处理 resources/read 请求"""
    if uri == "codeguard://rules/default":
        rules = constraint_injector.load_skill_rules()
        content = json.dumps({"type": "builtin_rules", "rules": rules}, ensure_ascii=False, indent=2)
        return {"contents": [{"uri": uri, "mimeType": "application/json", "text": content}]}
    
    elif uri == "codeguard://config/project":
        return {"contents": [{"uri": uri, "mimeType": "application/json", "text": json.dumps({
            "note": "No project configuration loaded. Run inject_constraints with a project_root to populate."
        }, ensure_ascii=False)}]}
    
    return create_error(None, -32602, f"Unknown resource: {uri}")


# ============================================================
# 文件类型分类
# ============================================================

def _classify_file(file_path):
    """识别文件类型：source / test / config / generated / migration / doc"""
    path_lower = file_path.lower()
    name = os.path.basename(path_lower)
    
    # 测试文件
    if any(p in path_lower for p in ["/test/", "/tests/", "/spec/", "/__tests__/"]):
        return "test"
    if name.startswith("test_") or name.endswith("_test.py") or name.endswith(".test.js") or name.endswith(".spec.js"):
        return "test"
    
    # 配置文件
    if any(name.endswith(ext) for ext in [".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf"]):
        if not any(p in path_lower for p in ["/src/", "/lib/"]):
            return "config"
    
    # 生成代码
    if any(kw in name for kw in ["generated", "_pb2", "_grpc", ".pb.", "auto_generated"]):
        return "generated"
    if any(kw in path_lower for kw in ["/generated/", "/gen/", "/out/", "/dist/", "/build/"]):
        return "generated"
    
    # 数据库迁移
    if "migration" in path_lower or "migrate" in path_lower or path_lower.endswith(".sql"):
        return "migration"
    
    # 文档
    if any(p in path_lower for p in ["/docs/", "/doc/", "/documentation/"]):
        return "doc"
    if name.endswith(".md"):
        return "doc"
    
    return "source"


# ============================================================
# 主循环 — MCP stdio 传输
# ============================================================

# ============================================================
# 方法-处理器映射表（消除 if/elif 链，CC=4）
# ============================================================

_METHOD_HANDLERS = {
    "initialize": lambda req_id, params: create_response(req_id, {
        "protocolVersion": PROTOCOL_VERSION,
        "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        "capabilities": {"tools": {}, "resources": {}}
    }),
    "tools/list": lambda req_id, params: create_response(req_id, {"tools": TOOLS}),
    "resources/list": lambda req_id, params: create_response(req_id, {"resources": RESOURCES}),
}

_TOOL_HANDLERS = {
    "review_file": handle_review_file,
    "review_diff": handle_review_diff,
    "execute_rules": handle_execute_rules,
    "inject_constraints": handle_inject_constraints,
}


def handle_request(request):
    """分发 JSON-RPC 请求到对应处理器（v2.0.1: dispatch table 消除长 if/elif 链）"""
    method = request.get("method", "")
    req_id = request.get("id")
    params = request.get("params", {})

    # 初始化 / 工具列表 / 资源列表（dispatch table）
    if method in _METHOD_HANDLERS:
        return _METHOD_HANDLERS[method](req_id, params)

    # 工具调用
    if method == "tools/call":
        tool_name = params.get("name", "")
        handler = _TOOL_HANDLERS.get(tool_name)
        if handler:
            try:
                result = handler(params.get("arguments", {}))
                return create_response(req_id, {
                    "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2)}]
                })
            except Exception as e:
                sys.stderr.write(f"[CodeGuard MCP] Tool execution error: {e}\n{traceback.format_exc()}\n")
                sys.stderr.flush()
                return create_error(req_id, -32603, f"Tool execution error: {e}")
        return create_error(req_id, -32601, f"Unknown tool: {tool_name}")

    # 资源读取
    if method == "resources/read":
        uri = params.get("uri", "")
        result = handle_resource_read(uri)
        return create_response(req_id, result)

    # 通知处理
    if method == "notifications/initialized":
        return None

    # 未知方法
    return create_error(req_id, -32601, f"Method not found: {method}")


def main():
    parser = argparse.ArgumentParser(description=f"{SERVER_NAME} MCP Server")
    parser.add_argument("--project-root", default=".", help="项目根目录")
    args = parser.parse_args()
    
    # 切换到项目目录并设置路径沙箱根
    root_abs = os.path.abspath(args.project_root)
    os.chdir(root_abs)
    set_project_root(root_abs)
    
    # 写入 stderr 避免污染 stdio 通道
    sys.stderr.write(f"[CodeGuard MCP] Starting v{SERVER_VERSION} on {args.project_root}\n")
    sys.stderr.flush()
    
    # MCP 主循环：从 stdin 逐行读取 JSON-RPC 请求
    try:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            
            try:
                request = json.loads(line)
            except json.JSONDecodeError:
                sys.stderr.write(f"[CodeGuard MCP] Invalid JSON: {line[:100]}\n")
                sys.stderr.flush()
                continue
            
            response = handle_request(request)
            
            if response:
                sys.stdout.write(response + "\n")
                sys.stdout.flush()
    
    except KeyboardInterrupt:
        sys.stderr.write("[CodeGuard MCP] Shutting down...\n")
        sys.exit(0)
    except Exception as e:
        sys.stderr.write(f"[CodeGuard MCP] Fatal error: {e}\n")
        sys.stderr.write(traceback.format_exc())
        sys.exit(1)


if __name__ == "__main__":
    main()
