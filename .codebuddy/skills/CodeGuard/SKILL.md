---
name: CodeGuard
description: >
  防止 AI 生成代码沦为"死山代码"的质量守护 Skill / MCP Server (v2.0.10)。
  在 AI 生成代码前自动注入架构约束，生成后执行质量门禁检查。
  支持 CodeBuddy Skill 模式 + MCP 协议跨平台模式 (Claude Code/Cursor/VS Code)。
  检测圈复杂度、重复代码、架构分层违规、循环依赖、安全漏洞等问题。
  输出置信度评分 (90-100=AST精确/80-89=高/70-79=中/60-69=低)。
  当用户请求生成/修改代码、重构、或提及代码质量、架构、技术债务时应触发。
  基于验证过的实证研究设计 (GitClear 2025, Sonar 2026, DORA 2024, CodeRabbit 2025, Veracode 2025)。
---

# CodeGuard — AI 代码质量守护者 (v2.0.10)

## 概述

防止 AI 生成代码沦为"死山代码"。v2.0 新增 **MCP 协议支持**、**置信度评分**、**文件类型感知**和**循环依赖检测**，覆盖所有主流 MCP 客户端。

**两大运行模式：**

| 模式 | 入口 | 适用场景 |
|------|------|---------|
| **CodeBuddy Skill** | 自动激活 (SKILL.md) | CodeBuddy 内 AI 辅助编程 |
| **MCP Server** | `python scripts/mcp_server.py` | Claude Code / Cursor / VS Code / 任意 MCP 客户端 |

**核心命题**：当前 AI 编程工具的对话式交互每次都是独立上下文，天然缺乏对项目全局架构的持续感知。实证数据（GitClear 2025，2.11 亿行代码）显示 AI 辅助编程已导致代码返工率上升 39%、重构占比下降 60%、复制粘贴代码增长 48%。

**解决路径**：建立"生成前约束注入 → 生成中检查提醒 → 生成后脚本验证"三层防线 + 修复指引，从根源遏制死山代码。

## MCP 协议跨平台支持 (v2.0.10)

CodeGuard v2.0 实现了完整的 MCP (Model Context Protocol) 服务器，遵循 JSON-RPC 2.0 over stdio 规范。

### 配置方式

**Claude Code:**
```json
{ "mcpServers": { "codeguard": { "command": "python", "args": ["scripts/mcp_server.py"] } } }
```

**Cursor / VS Code:**
在 `.cursor/mcp.json` 或 VS Code MCP 设置中添加：
```json
{ "mcpServers": { "codeguard": { "command": "python", "args": ["path/to/mcp_server.py"] } } }
```

### MCP Tool 清单

| Tool | 描述 | 输入 |
|------|------|------|
| `review_file` | 单文件完整检测 (含置信度) | `file_path`, `mode` |
| `review_diff` | Git diff 增量检测 | `project_root`, `mode` |
| `execute_rules` | 列出所有活跃规则 | `project_root` |
| `inject_constraints` | 生成架构约束提示 | `project_root`, `format` |

### MCP Resource 清单

| URI | 描述 |
|-----|------|
| `codeguard://rules/default` | 默认规则集 (JSON) |
| `codeguard://config/project` | 项目自定义配置 |

## v2.0.10 新增能力

### 0. 模块化架构重构

将原 1303 行单体 `quality_check.py` 拆分为 6 个模块化子文件 + 薄编排器入口：

| 模块 | 职责 | 行数 |
|------|------|------|
| `quality_core.py` | THRESHOLDS/_log/IssueCollector/FileClassifier/strip | ~200 |
| `quality_checks.py` | 多语言复杂度/嵌套/参数/Python AST 检测 | ~270 |
| `quality_security.py` | 安全检查(三扫描管线) + 异常处理检测 | ~170 |
| `quality_dup.py` | 文件内/跨文件重复代码检测 | ~50 |
| `quality_arch.py` | 依赖图/架构分层违规/循环依赖 | ~150 |
| `quality_custom.py` | 自定义规则引擎/阈值覆盖/命名一致性 | ~110 |
| `quality_check.py` | 薄编排器入口 (派发表消除 if/elif 链) | ~200 |

`mcp_server.py` 新增 `_make_mcp_tool()` 工厂函数，消除 4 个 MCP tool 定义的重复结构。
`constraint_injector.py` 模态分解 `detect_project_structure` (CC=33→8) 和 `load_custom_rules` (depth=7→3)。

### 1. 置信度评分

每项检测输出 0-100 置信度分数，按 mrzadexinho/codeguard 的设计标准：

| 置信度 | 等级 | 来源 |
|--------|------|------|
| 90-100 | 确定 | AST 精确分析、循环依赖 |
| 80-89 | 高 | 剥离注释/字符串后的正则、架构分析 |
| 70-79 | 中 | 原始正则 (含注释噪音)、类方法数近似 |
| 60-69 | 低 | 启发式推断、统计模式 |

### 2. 文件类型感知 (FileClassifier)

自动识别 6 种文件类型并调整规则行为：

| 类型 | 触发条件 | 规则调整 |
|------|---------|---------|
| `source` | 默认 | 全量检测 |
| `test` | `test_*/_test.*/tests/` | 跳过安全规则 |
| `config` | `.json/.yaml/.toml` 非 src | 跳过复杂度，保留安全 |
| `generated` | `generated/_pb2/_grpc/` | 跳过所有，仅标记 |
| `migration` | `migration/` `.sql` | 跳过复杂度，保留 SQL 注入 |
| `doc` | `.md` `docs/` | 全部跳过 |

### 3. 依赖图 (DependencyGraph)

构建全局模块依赖图，检测：
- **分层违规**：Domain→Infrastructure (block)、Application→Infrastructure (warn)
- **循环依赖**：DFS 检测 A→B→C→A 模式 (block, 置信度 95)

### 4. 三扫描安全检测

安全检测分三遍执行：
- 第一遍：原始内容快速筛 (置信度 70)
- 第二遍：剥离注释/字符串后精确匹 (置信度 85)
- 第三遍：剥离后全文 DOTALL 双通道多行扫描 — 密码通道(括号+续行符归一化, block/85) + 函数调用通道(仅换行归一化) (v2.0.9)
- 三遍结果合并去重，消除注释/字符串中的误报

## 触发条件

在以下任一场景中激活本 Skill：

- 用户请求生成或修改代码文件
- 用户要求重构、优化、扩展功能
- 用户讨论架构设计、代码质量、技术债务
- 用户输入 `/review`、`/quality` 等命令
- 检测到项目根目录存在 `.code-guardian/` 自定义配置目录

## 多 Agent 协作架构

> **⚠️ 设计规范：** 此章节为多 Agent 协作的架构设计规范。当前版本无独立代码实现——Agent 间协作由 CodeBuddy Team Mode 平台层提供（参见 `send_message` / `team_create` 工具）。消息协议格式用于指导 Agent 间通信，非独立可执行功能。

本 Skill 支持在 Team Mode 下拆分职责到多个 Agent 并行执行，解决单 Agent 模式下"生成与审查角色冲突"的问题。

### Agent 角色定义

| 角色 | 名称 | 职责 | 何时创建 |
|------|------|------|---------|
| **Architect** | `CodeGuard-architect` | 执行约束注入，在生成前将架构规则注入上下文 | 用户提出代码生成/修改请求时立即创建 |
| **Generator** | `CodeGuard-generator` | 在注入的架构约束下生成/修改代码 | Architect 完成约束注入后创建 |
| **Reviewer** | `CodeGuard-reviewer` | 执行质量门禁，审查生成的代码并产出报告 | Generator 完成代码生成后创建 |

### 协作工作流（Team Mode）

```
用户请求 "实现用户注册功能"
    │
    ▼
┌─────────────────────────────────┐
│ 1. Architect Agent 启动         │
│    - 运行 constraint_injector   │
│    - 注入架构约束到上下文        │
│    - 向 Generator 发送约束消息   │
└─────────────┬───────────────────┘
              │ 消息: {"type":"constraints", "rules":[...]}
              ▼
┌─────────────────────────────────┐
│ 2. Generator Agent 启动         │
│    - 基于约束生成代码            │
│    - 逐项自查（防线二）          │
│    - 输出代码 + 自查报告         │
│    - 向 Reviewer 发送代码        │
└─────────────┬───────────────────┘
              │ 消息: {"type":"code", "files":[...], "self_check":{...}}
              ▼
┌─────────────────────────────────┐
│ 3. Reviewer Agent 启动          │
│    - 运行 quality_check.py      │
│    - 对照约束验证代码            │
│    - 产出质量报告                │
│    - 向 main 汇报结果            │
└─────────────┬───────────────────┘
              │ 消息: {"type":"report", "summary":{...}, "issues":[...]}
              ▼
          用户收到质量报告
```

### Agent 间消息协议

**Architect → Generator（约束消息）：**
```json
{
  "type": "constraints",
  "version": "1.0",
  "project_structure": {"type": "layered", "layers": {}},
  "block_rules": ["Domain层不得import Infrastructure层", "..."],
  "warn_rules": ["圈复杂度≤10", "..."],
  "custom_rules": ["TEAM_NO_PRINT_IN_PRODUCTION", "..."],
  "checklist": ["分层架构: Domain不依赖Infrastructure", "..."]
}
```

**Generator → Reviewer（代码提交消息）：**
```json
{
  "type": "code_submission",
  "version": "1.0",
  "files": [
    {"path": "domain/user.py", "lines": 45, "language": "python"},
    {"path": "application/user_service.py", "lines": 30, "language": "python"}
  ],
  "self_check": {
    "architecture_ok": true,
    "complexity_ok": true,
    "security_ok": false,
    "security_notes": "使用环境变量存储API密钥，未硬编码"
  },
  "notes": "实现用户注册功能，遵循分层架构"
}
```

**Reviewer → Main（质量报告消息）：**
```json
{
  "type": "quality_report",
  "version": "1.0",
  "exit_code": 1,
  "summary": {"total_issues": 3, "blocks": 0, "warnings": 2, "info": 1},
  "issues": [
    {"severity": "warn", "category": "complexity", "file": "domain/user.py", "line": 23, "message": "..."}
  ],
  "verdict": "PASS_WITH_WARNINGS",
  "suggestions": ["建议拆分 calculate_score 函数降低复杂度"]
}
```

### 单 Agent 模式（默认）

如果不使用 Team Mode，主 Agent 按顺序执行三层防线：

1. 运行 `constraint_injector.py --format checklist` 注入约束
2. 生成代码并逐项自查
3. 运行 `quality_check.py --mode personal --format json` 执行门禁
4. 对 block 级别问题引导用户修复

## 三层防线工作流

### 防线一：生成前 — 注入架构约束

**目标**：在生成任何代码之前，将项目架构规则注入到对话上下文中，利用首因效应对抗 "Lost in the Middle" 现象。

**执行步骤（严格按顺序）：**

1. 运行约束注入脚本获取项目结构：

```bash
python scripts/constraint_injector.py --path <project_root> --format checklist
```

2. 将脚本输出的检查清单放置于本次对话**第一条消息的开头**，确保约束在上下文最前端。

3. 如果任务是跨文件修改或架构级变更，执行完整约束注入：

```bash
python scripts/constraint_injector.py --path <project_root> --format prompt
```

4. 将完整约束注入内容作为代码生成前的**系统级前置说明**。

5. 从 `references/architecture_rules.md` 中读取规则定义，确保检测逻辑与注入约束一致。

6. **多 Agent 模式**：Architect Agent 执行此步骤，通过 `{"type":"constraints", ...}` 消息将结果传递给 Generator Agent。

### 防线二：生成中 — 逐项自查

**目标**：代码生成后、输出给用户前，逐项对照检查清单确认。

**执行步骤（对每次代码生成输出执行）：**

1. 检查分层架构：
   - Domain 层是否引用了 Infrastructure 或 Presentation 层？如有 → 标记为架构违规并说明正确做法
   - Application 层是否直接依赖 Infrastructure 具体实现？如有 → 警告并建议通过接口倒置

2. 检查重复代码：
   - 新增代码是否与已有功能存在重叠？如有 → 警告并建议重构而非叠加

3. 检查复杂度：
   - 单函数圈复杂度是否超过 10？如有 → 建议拆分
   - 函数参数是否超过 5 个？如有 → 建议封装为参数对象

4. 检查安全性：
   - 代码中是否包含硬编码密码/API Key/Token？如有 → 阻塞，使用环境变量替代
   - 是否使用字符串拼接构造 SQL？如有 → 阻塞，改用参数化查询

5. 检查命名一致性：
   - 同一概念是否与项目中已有命名风格一致？不一致 → 统一为已有风格

6. 检查异常处理：
   - except/catch 块是否为空或仅 print？如有 → 警告并添加适当的错误处理

7. **多 Agent 模式**：Generator Agent 生成代码并完成自查后，通过 `{"type":"code_submission", ...}` 消息将代码和自查结果传递给 Reviewer Agent。

### 防线三：生成后 — 质量门禁

**目标**：代码落地后执行自动化检测，产出结构化质量报告。

**执行步骤：**

1. 个人模式（默认，快速检查）：

```bash
python scripts/quality_check.py --path <project_root> --mode personal --format json
```

2. 团队模式（额外启用命名一致性检查 + 自定义规则执行）：

```bash
python scripts/quality_check.py --path <project_root> --mode team --format json
```

3. 增量模式（仅检测 git 变更文件，适合大项目）：

```bash
python scripts/quality_check.py --path <project_root> --mode diff --format json
```

4. 解读 JSON 输出：
   - 退出码 0 → 通过，无问题
   - 退出码 1 → 有警告，需人工确认
   - 退出码 2 → 有阻塞项，必须修复

5. 对每个阻塞（block）级别的问题，提供具体修复方案并引导用户修改。

6. **多 Agent 模式**：Reviewer Agent 执行此步骤，通过 `{"type":"quality_report", ...}` 消息向 main 汇报结果。

### 修复指引

当检测到问题时，按以下映射提供修复建议：

| 问题类别 | 修复建议 |
|---------|---------|
| 圈复杂度超标 (complexity) | 拆分为多个小函数；使用策略模式消除条件分支 |
| 重复代码 (duplication) | 提取为共享函数或模块；考虑模板方法模式 |
| 架构分层违规 (architecture) | Domain 层定义接口，Infrastructure 层实现；使用依赖注入 |
| 安全红线 (security) | 使用环境变量/密钥管理服务；参数化查询；禁用 eval/exec |
| 命名不一致 (naming) | 统一为项目中已有命名约定；建立团队术语表 |
| 文件过大 (file_size) | 按职责拆分为多个模块，单文件 ≤ 300 行 |
| 错误处理不足 (error_handling) | 添加日志记录和错误恢复/降级逻辑 |
| 自定义规则 (custom_rule) | 参见 `.code-guardian/rules.json` 中对应规则的 suggestion 字段 |

## 可执行脚本

### scripts/constraint_injector.py

架构约束提取与 Prompt 注入。

| 场景 | 命令 | Agent 角色 |
|------|------|-----------|
| 生成前快速检查清单 | `python scripts/constraint_injector.py --path . --format checklist` | Architect |
| 复杂任务的完整约束 | `python scripts/constraint_injector.py --path . --format prompt` | Architect |
| 程序集成（JSON） | `python scripts/constraint_injector.py --path . --format json` | Architect |
| 人工查看 | `python scripts/constraint_injector.py --path . --format text` | — |

### scripts/quality_check.py

代码质量门禁检测。

| 场景 | 命令 | Agent 角色 |
|------|------|-----------|
| 个人全量检测 | `python scripts/quality_check.py --path . --mode personal` | Reviewer |
| 团队全量检测 | `python scripts/quality_check.py --path . --mode team` | Reviewer |
| 增量检测（仅变更文件） | `python scripts/quality_check.py --path . --mode diff` | Reviewer |
| 文本格式输出 | `python scripts/quality_check.py --path . --format text` | — |

### scripts/mcp_server.py (v2.0.10)

MCP 协议服务端，JSON-RPC 2.0 over stdio。

| 场景 | 命令 |
|------|------|
| 启动 MCP Server | `python scripts/mcp_server.py --project-root .` |
| MCP 客户端配置 | 参见上方 "MCP 协议跨平台支持" 节 |

### 检测范围对照

| 文件类型 | 复杂度 | 嵌套深度 | 参数数量 | 类方法数 | 文件大小 | 安全红线 | 重复代码 | 架构违规 | 异常处理 |
|---------|--------|---------|---------|---------|---------|---------|---------|---------|---------|
| `.py` | ✅ AST | ✅ AST | ✅ AST | ✅ AST | ✅ | ✅ | ✅ | ✅ | ✅ |
| `.js/.ts` | ✅ 正则 | ✅ 大括号 | ✅ 正则 | — | ✅ | ✅ | ✅ | ✅ | ✅ |
| `.java` | ✅ 正则 | ✅ 大括号 | ✅ 正则 | ✅ 正则 | ✅ | ✅ | ✅ | ✅ | ✅ |
| `.go` | ✅ 正则 | — | ✅ 正则 | — | ✅ | ✅ | ✅ | ✅ | ✅ |
| `.cs` | ✅ 正则 | ✅ 大括号 | ✅ 正则 | ✅ 正则 | ✅ | ✅ | ✅ | ✅ | ✅ |
| `.cpp/.c/.h` | ✅ 正则 | ✅ 大括号 | ✅ 正则 | — | ✅ | ✅ | ✅ | ✅ | ✅ |
| `.rs` | ✅ 正则 | — | ✅ 正则 | — | ✅ | ✅ | ✅ | ✅ | ✅ |

> 正则近似精度比 AST 低 ~15%，但保持零外部依赖。Go 的嵌套深度检测未实现（Go 用缩进而非大括号控制作用域，需 gofmt 辅助解析）。

> 架构违规检测现已支持 Python/JS/TS/Java/Go/C#/Rust 的 import 语法提取。

## 团队自定义

在项目根目录创建 `.code-guardian/rules.json`。自定义规则采用声明式格式，`quality_check.py` 的声明式引擎自动解析执行。

```json
{
  "rules": [
    {
      "id": "TEAM_NO_DIRECT_DB",
      "description": "Controller 层不得直接调用数据库操作",
      "severity": "block",
      "target": "presentation",
      "pattern": "(?:DatabaseConnection|db\\.execute|Session\\(\\)|create_engine)",
      "message": "Controller 层直接访问数据库",
      "suggestion": "必须通过 Service 层封装所有数据库操作"
    },
    {
      "id": "TEAM_LOGGING_STANDARD",
      "description": "所有异常必须使用 structured logging 记录",
      "severity": "warn",
      "target": "all",
      "pattern": "except\\s+\\w+.*:\\s*\\n\\s*(?:pass|print|return\\s+None)",
      "message": "异常处理缺少日志记录",
      "suggestion": "使用 logging.exception() 记录异常上下文"
    }
  ]
}
```

### 自定义规则字段说明

| 字段 | 必填 | 说明 |
|------|------|------|
| `id` | ✅ | 规则唯一标识 |
| `description` | ✅ | 规则说明 |
| `severity` | ✅ | `block` / `warn` / `info` |
| `target` | ❌ | 作用域：`all`(默认) / `domain` / `application` / `infrastructure` / `presentation` / `python` / `javascript` / `java` / `go` / `csharp` / `rust` / 文件名模式 |
| `pattern` | ✅ | 正则表达式（Python re 语法） |
| `message` | ❌ | 违规时的消息（默认使用 description） |
| `suggestion` | ❌ | 修复建议 |

### 金级质量门禁（v2.0.10）

CodeGuard 内置腾讯金级（核心系统）质量门禁预设。只需在项目根目录放置 `.code-guardian/rules.json`，即可一键升级到金级标准。

**金级 vs 默认：**

| 指标 | 默认(warn/block) | 金级(warn/block) |
|------|-----------------|------------------|
| 圈复杂度 | 10/15 | 8/10 |
| 嵌套深度 | 4/6 | 3/4 |
| 函数参数 | 5/8 | 4/6 |
| 文件行数 | 300/500 | 200/400 |
| 类行数 | 300/500 | 200/400 |
| 类方法数 | 15 | 10 |
| 重复行 | 6/10 | 4/6 |
| 跨文件重复 | 20 | 15 |

**金级额外规则**（17 条强制规则）：禁止裸 except / 可变默认参数 / 通配符导入 / print 生产代码 / console.log / any 类型 / 同步 I/O / 魔法数字 / 硬编码 URL / SQL 拼接 / os.system / 空异常块 / eval 动态执行等。

**使用方法**：复制 CodeGuard 仓库中的 `.code-guardian/rules.json` 到你的项目根目录，或参阅该文件自行定制。

**自定义阈值**：在 `rules.json` 的 `"thresholds"` 字段覆盖任意 THRESHOLDS 键值。未知键将被静默忽略。支持分级（金/银/铜）快速切换。

```json
{
  "thresholds": {
    "cyclomatic_complexity_block": 10,
    "max_nesting_block": 4
  },
  "rules": [...]
}
```

## 参考文档

- `references/architecture_rules.md` — 完整架构规则定义，包含 SOLID 原则、分层约束、DRY 检测、安全红线、AI 代码反模式、度量指标

### 规则设计依据（已独立验证的实证研究）

| 数据源 | 关键发现 | 对应规则 |
|--------|---------|---------|
| GitClear 2025 (2.11亿行) | 返工率 +39%，重构占比 −60%，复制粘贴 +48% | 重复代码检测、重构提醒 |
| Sonar 2026 | 信任度 29% vs 采纳率 84%；>90% 问题为代码异味 | 圈复杂度、类大小限制 |
| DORA 2024 | AI 采纳 +25% → 交付稳定性 −7.2% | 增量检测模式、度量指标 |
| CodeRabbit 2025 (470 PR) | AI 代码问题 1.7x，安全漏洞 +274% | 安全红线、复杂度门禁 |
| Veracode 2025 | 45% AI 代码未通过安全测试 | 硬编码密钥、SQL 注入检测 |
| arXiv 2603.28592 (6299仓库) | AI 技术债务 89.3% 为代码异味 | 架构分层违规检测 |
| METR RCT (16 资深开发者) | 使用 AI 实际慢 19%，自认快 20% | 约束注入（防止"效率幻觉"导致的审查放松） |

## 技术债务度量建议

使用本 Skill 时追踪以下指标（基于 GitClear 2025 和 DORA 2024 研究）：

| 指标 | 健康值 | 警示值 | 测量方式 |
|------|--------|--------|----------|
| 代码耐久性 | > 80% | < 60% | 14 天后未修改的代码占比 (`git log`) |
| AI 代码变动率 | < 20% | > 30% | 14 天内被修改的 AI 代码占比 (`git diff`) |
| 重复代码率 | < 5% | > 10% | `quality_check.py --mode diff` |
| CRAP 指数 | < 15 | > 30 | CC² × (1−coverage)³ + CC |
