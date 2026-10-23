# MCP 协议兼容性说明

## 概述

本 Skill 完全兼容 MCP (Model Context Protocol) 协议，可作为标准 MCP Server 被以下客户端调用：

- **Claude Code** (Anthropic)
- **Cursor** (Anthropic/OpenAI)
- **VS Code** (通过 MCP 扩展)
- **CodeBuddy** (腾讯)
- 任何支持 MCP 协议的 AI 编程助手

## 快速启动

### 1. 安装依赖

```bash
pip install mcp httpx beautifulsoup4
```

### 2. 启动 MCP Server

**stdio 模式**（最常用）：

```bash
python .codebuddy/skills/project-manager/scripts/mcp_server.py
```

**SSE 模式**（远程调用）：

```bash
python .codebuddy/skills/project-manager/scripts/mcp_server.py --transport sse --port 8765
```

### 3. 测试工具列表

```bash
python .codebuddy/skills/project-manager/scripts/mcp_server.py --list-tools
```

### 4. 直接调用单个工具

```bash
python .codebuddy/skills/project-manager/scripts/mcp_server.py \
  --tool start_feasibility_check \
  --args '{"project_name":"我的项目"}'
```

## 客户端配置

### Claude Code MCP 配置

在 `~/.claude/claude_desktop_config.json` 或项目根目录 `.mcp.json` 中添加：

```json
{
  "mcpServers": {
    "project-manager": {
      "command": "python",
      "args": [
        "path/to/.codebuddy/skills/project-manager/scripts/mcp_server.py"
      ]
    }
  }
}
```

### Cursor MCP 配置

在 Cursor 设置 → MCP → 添加新 Server：

```json
{
  "mcpServers": {
    "project-manager": {
      "command": "python",
      "args": [
        "path/to/.codebuddy/skills/project-manager/scripts/mcp_server.py"
      ]
    }
  }
}
```

### VS Code MCP 配置

通过 MCP 扩展设置或 `.vscode/mcp.json`：

```json
{
  "servers": {
    "project-manager": {
      "command": "python",
      "args": [
        "path/to/.codebuddy/skills/project-manager/scripts/mcp_server.py"
      ]
    }
  }
}
```

## 可用 MCP 工具

### 1. start_feasibility_check — 项目可行性研判

**对应阶段**：第一阶段

**参数**：
- `project_name` (string): 项目名称
- `answers` (string): JSON 格式的用户回答

**示例调用**：
```json
{
  "project_name": "AI写作助手",
  "answers": "{\"1\": \"研究生需要高效论文写作工具\", \"2\": \"Grammarly/DeepL/文心一言\"}"
}
```

**返回**：Markdown 格式的可行性评估报告

### 2. create_project_plan — 生成项目启动规划书

**对应阶段**：第二阶段

**参数**：
- `project_name` (string): 项目名称
- `deadline` (string): 目标交付日期
- `answers` (string): JSON 格式的回答

### 3. daily_progress_check — 每日进度自检

**对应阶段**：第三阶段

**参数**：
- `answers` (string): JSON `{today_done, status, blocker, blocker_plan}`

### 4. quality_gate_check — 质量门禁检查

**对应阶段**：第三阶段

**参数**：
- `answers` (string): JSON `{edge_cases, coverage, tech_debt, feedback_pattern, quality_breach}`

### 5. vision_tracker_scan — 技术趋势扫描

**对应阶段**：第三/五阶段

**参数**：
- `domain` (string): 关注领域
- `keywords` (string): 逗号分隔的关键词

### 6. generate_retrospective — 生成项目复盘报告

**对应阶段**：第四阶段

**参数**：
- `project_name` (string)
- `answers` (string): JSON 格式的复盘数据

### 7. knowledge_asset_export — 导出知识沉淀文档

**对应阶段**：第四阶段

**参数**：
- `project_name` (string)
- `assets` (string): JSON 数组 `[{name, type, desc, scenario, location}]`

### 8. weekly_vision_report — 每周视野跟踪报告

**对应阶段**：第五阶段

**参数**：
- `domain` (string): 关注领域
- `findings` (string): JSON 格式的发现数据

## 架构说明

```
mcp_server.py (MCP Server 主程序)
├── MCP Protocol Layer (mcp 库)
│   ├── list_tools() → 工具发现
│   └── call_tool() → 工具调用
├── Tool Implementations
│   ├── start_feasibility_check()
│   ├── create_project_plan()
│   ├── daily_progress_check()
│   ├── quality_gate_check()
│   ├── vision_tracker_scan()
│   ├── generate_retrospective()
│   ├── knowledge_asset_export()
│   └── weekly_vision_report()
└── Data Layer
    └── PHASE_QUESTIONS (55个标准化问题)
```

## 对 CodeBuddy Skill 的 MCP 扩展

本 Skill 同时提供 CodeBuddy Skill 模式 + MCP 模式：

| 模式 | 使用方式 | 优势 |
|------|----------|------|
| CodeBuddy Skill | 对话式交互 | 自然语言引导、上下文丰富 |
| MCP Server | 标准化工具调用 | 跨平台兼容、可编程调用 |

两种模式共享相同的框架数据和检查清单，确保一致性。
