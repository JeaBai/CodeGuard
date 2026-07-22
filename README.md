# 🛡️ CodeGuard — Kill Dead Code Before It Ships

<p align="center">
  <b>AI writes code. CodeGuard keeps it alive.</b><br>
  <sub>一个 CodeBuddy Skill，在 AI 生成代码的每一刻守护架构、阻断技术债务。</sub>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.8%2B-blue" alt="Python">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="MIT">
  <img src="https://img.shields.io/badge/dependencies-zero-brightgreen" alt="零依赖">
  <img src="https://img.shields.io/badge/coverage-16%2F16%20categories-9cf" alt="检测覆盖">
  <img src="https://img.shields.io/badge/MCP-compatible-purple" alt="MCP协议">
  <img src="https://img.shields.io/badge/confidence-0--100-orange" alt="置信度评分">
  <img src="https://img.shields.io/badge/status-production%20ready-success" alt="状态">
  <img src="https://img.shields.io/badge/version-2.0.5-blueviolet" alt="v2.0.5">
</p>

---

## 💀 The Problem

AI 编程工具每天生成数十亿行代码。但数据不会说谎：

> **GitClear 2025** 分析了 2.11 亿行代码后发现：
> - 📈 AI 辅助代码**返工率上升 39%**
> - 📉 重构占比从 24% **骤降至不足 10%**  
> - 📋 复制粘贴代码**增长 48%**
>
> **CodeRabbit** 审查 470 个 PR 后得出结论：AI 代码产生的 Bug **是人工的 1.7 倍**，安全漏洞高出 **274%**。

这不是工具的错，是**对话式交互的先天缺陷**：每次对话都是独立上下文，AI 天然缺乏对项目全局架构的持续感知。

## 🛡️ The Solution

CodeGuard 建立**三层防线**，在 AI 生成代码的每一刻自动介入：

```
 ┌──────────────────────────────────────────────────────────┐
 │  第一层  │  生成前  │  注入架构约束 + FileClassifier     │
 │  第二层  │  生成中  │  逐项自查 + 置信度评分              │
 │  第三层  │  生成后  │  DependencyGraph + 双扫描安全       │
 └──────────────────────────────────────────────────────────┘
          ↓ 退出码: 0=PASS / 1=WARN / 2=BLOCK
```

**v2.0 新增能力：**

| 能力 | 描述 | 模块 |
|------|------|------|
| 🖥️ MCP 协议 | JSON-RPC 2.0 over stdio，Claude Code/Cursor/VS Code 即插即用 | `mcp_server.py` |
| 📊 置信度评分 | 每条问题 0-100 分 (90+=AST/80+=剥离正则/70+=原始正则) | `IssueCollector` |
| 📁 文件类型感知 | test/config/generated/migration/doc 6 种类型规则自适应 | `FileClassifier` |
| 🔄 循环依赖 | DFS 依赖图 A→B→C→A 检测 (置信度 95) | `DependencyGraph` |
| 🔍 双扫描安全 | 剥离前+后双重匹配去重，消除注释误报 | `_check_security` |

**实测对比（同一功能，AI 风格 vs 人类风格）：**

| | AI 风格代码 | 人类风格代码 |
|---|---|---|
| 安全违规 | **7 BLOCK** | 0 |
| 圈复杂度 | 10 (临界) | 5 (健康) |
| 嵌套深度 | 6 层 | 1 层 |
| 参数数量 | 10 个 | 2 个 |
| 异常处理 | `except: pass` | `logger.exception()` |
| 架构分层 | 无 | 清晰 3 层 |
| **CodeGuard 退出码** | **2 (BLOCK)** | **0 (PASS)** |

> ✅ AI 代码被精准拦截，人类代码零误报。

## ⚡ Quick Start

### CodeBuddy Skill 模式
```bash
# 一行安装（个人）
cp -r CodeGuard/ ~/.codebuddy/skills/

# 或团队共享
cp -r CodeGuard/ .codebuddy/skills/
```

### MCP 跨平台模式 (Claude Code / Cursor / VS Code)
```bash
# 启动 MCP Server (stdio 模式)
python scripts/mcp_server.py --project-root .

# 或配置到 MCP 客户端:
# Claude Code: 在 claude_desktop_config.json 添加
{
  "mcpServers": {
    "codeguard": {
      "command": "python",
      "args": ["path/to/mcp_server.py", "--project-root", "."]
    }
  }
}
```

之后 AI 生成代码时**自动激活**。也可以手动运行：

```bash
# 增量检测（仅变更文件，秒级）
python scripts/quality_check.py --path . --mode diff

# 全量检测
python scripts/quality_check.py --path . --mode personal

# 团队模式（含命名一致性检查）
python scripts/quality_check.py --path . --mode team
```

## 🔍 What It Detects

| 类别 | Python | JS/TS | Java | Go | C# | C/C++ | Rust |
|------|:------:|:-----:|:----:|:--:|:--:|:-----:|:----:|
| 圈复杂度 | ✅ AST | ✅ 正则 | ✅ 正则 | ✅ 正则 | ✅ 正则 | ✅ 正则 | ✅ 正则 |
| 嵌套深度 | ✅ AST | ✅ 大括号 | ✅ 大括号 | — | ✅ 大括号 | ✅ 大括号 | — |
| 参数数量 | ✅ AST | ✅ 正则 | ✅ 正则 | ✅ 正则 | ✅ 正则 | ✅ 正则 | ✅ 正则 |
| 类方法数 | ✅ AST | — | ✅ 正则 | — | ✅ 正则 | — | — |
| 文件大小 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 🔒 安全红线 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 重复代码 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 🏗️ 架构分层 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 异常处理 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 命名一致性 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |

**安全红线（不可绕过）：**
- ❌ 硬编码密码/API Key/Token
- ❌ SQL 字符串拼接（SQL 注入）
- ❌ `eval()` / `exec()` / `os.system()` 接受外部输入
- ❌ 日志泄露敏感数据
- ❌ 空异常处理块

## 🎛️ Custom Rules — 声明式引擎

不需要改代码。在 `.code-guardian/rules.json` 中声明：

```json
{
  "rules": [
    {
      "id": "TEAM_NO_DIRECT_DB",
      "description": "Controller 层禁止直接访问数据库",
      "severity": "block",
      "target": "presentation",
      "pattern": "(?:DatabaseConnection|db\\.execute|Session\\(\\))",
      "message": "Controller 直接访问数据库",
      "suggestion": "通过 Service 层封装所有数据操作"
    }
  ]
}
```

支持的作用域过滤：`domain` | `application` | `infrastructure` | `presentation` | `python` | `javascript` | `java` | `go` | 文件名 glob 模式 | `all`

## 🤖 Multi-Agent Mode

在 CodeBuddy Team Mode 下拆分为三个并行 Agent：

| Agent | 角色 | 职责 |
|-------|------|------|
| **CodeGuard-architect** | 架构师 | 注入项目架构约束 |
| **CodeGuard-generator** | 生成者 | 在约束下生成代码 |
| **CodeGuard-reviewer** | 审查者 | 执行质量门禁 |

完整消息协议参见 [SKILL.md](CodeGuard/SKILL.md)。

## 📊 Evidence-Based Design

CodeGuard 的每一条规则都有独立的实证研究支撑：

| 数据源 | 规模 | 关键发现 |
|--------|------|---------|
| GitClear | 2.11 亿行 | AI 代码返工率 +39% |
| Sonar | 4,400 任务 | 89.3% AI 问题为代码异味 |
| DORA 2024 | 3.6 万团队 | AI 采纳增加 25% → 交付稳定性下降 7.2% |
| CodeRabbit | 470 PR | AI 代码安全漏洞 +274% |
| Veracode | 企业级 | 45% AI 代码未通过安全测试 |
| METR RCT | 16 资深开发者 | 使用 AI 实际慢 19%，自认快 20% |

## 🧪 We Eat Our Own Dog Food

CodeGuard 用自己审查自己。自检测试中发现了 `constraint_injector.py` 的一处空异常处理并已修复。**v1.2.0 自身代码通过全部检测。**

## 📦 Tech Stack

- **纯 Python 3.8+ 标准库** — 零 `pip install`
- **跨平台** — Windows / macOS / Linux
- **内存友好** — 500 文件项目 < 1MB，10,000 文件项目 < 15MB
- **秒级响应** — 500 文件 < 1s，增量模式毫秒级

## 🗺️ Roadmap

- [x] 三层防线（注入 → 自查 → 门禁）
- [x] 声明式自定义规则引擎
- [x] 多 Agent 协作支持
- [x] 多语言架构检测（7 种语言）
- [x] 增量模式（git diff）
- [ ] IDE 实时提示集成
- [ ] 趋势面板（技术债务变化追踪）
- [ ] SonarQube / ESLint 互操作

## 📄 License

MIT — 自由使用、修改、分发。

---

<p align="center">
  <sub>Built with data, verified by research, tested on itself.</sub>
</p>
