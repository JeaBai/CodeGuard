# 🛡️ CodeGuard — Kill Dead Code Before It Ships

<p align="center">
  <b>AI writes code. CodeGuard keeps it alive.</b><br>
  <sub>一个 CodeBuddy Skill + MCP Server，在 AI 生成代码的每一刻守护架构、阻断技术债务。</sub>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/version-3.1.0-blueviolet" alt="v3.1.0">
  <img src="https://img.shields.io/badge/Python-3.8%2B-blue" alt="Python">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="MIT">
  <img src="https://img.shields.io/badge/required%20dependencies-zero-brightgreen" alt="零必需依赖">
  <img src="https://img.shields.io/badge/MCP-compatible-purple" alt="MCP协议">
  <img src="https://img.shields.io/badge/confidence-0--100-orange" alt="置信度评分">
  <img src="https://img.shields.io/badge/tests-20%2F20-success" alt="测试">
</p>

---

## 💀 The Problem

AI 编程工具每天生成数十亿行代码。但数据不会说谎：

> **GitClear 2025** 分析了 2.11 亿行代码后发现：AI 辅助代码**返工率上升 39%**、复制粘贴代码**增长 48%**。
> **CodeRabbit** 审查 470 个 PR 后得出结论：AI 代码产生的 Bug **是人工的 1.7 倍**，安全漏洞高出 **274%**。
> **Veracode 2025**：45% 的 AI 生成代码未通过安全测试。

这不是工具的错，是**对话式交互的先天缺陷**：每次对话都是独立上下文，AI 天然缺乏对项目全局架构的持续感知。

## 🛡️ The Solution — 三层防线

```
 ┌──────────────────────────────────────────────────────────┐
 │  第一层  │  生成前  │  constraint_injector.py             │
 │         │         │  注入架构约束 + FileClassifier 差异化  │
 ├──────────────────────────────────────────────────────────┤
 │  第二层  │  生成中  │  quality_mid_check.py               │
 │         │         │  逐项自查，输出 {rule_id, passed,     │
 │         │         │  confidence, evidence}                │
 ├──────────────────────────────────────────────────────────┤
 │  第三层  │  生成后  │  quality_arch/security/modular      │
 │         │         │  循环依赖 + 三扫描安全 + 闭环审计      │
 └──────────────────────────────────────────────────────────┘
```

三层共享同一套规则元数据（`quality_rule_registry.py` 单一事实源），实现「注入约束 ↔ 检出违规」可追溯。

## ✨ 能力矩阵（v3.1.0）

| 维度 | 能力 |
|---|---|
| **行业分离** | web / embedded / safety 三行业规则集自动切换（`industry_detector.py` + `.code-guardian/profiles/`） |
| **C 方言分流** | 通用 C/C++ 与嵌入式 C（MISRA C:2012 子集 / ISR 安全 / volatile / 栈深度）在文件分类层自动分流 |
| **门禁分级** | 金 / 银 / 铜三级阈值（`_level` 字段一键切换），自定义阈值逐键覆盖 |
| **自定义规则** | `.code-guardian/rules.json` 声明式规则（正则 + 检测器双通道），存在即生效、优先于内置默认 |
| **模块化检测** | 跨模块硬编码 / 私有符号越界 / 同名脚本歧义 / 缺接口文档 / 无超时 / 无契约校验 / 无依赖锁定 等 9 条 |
| **MCP 协议** | JSON-RPC 2.0 over stdio，5 个 Tool，适配 Claude Code / Cursor / VS Code / CodeBuddy |
| **置信度评分** | 90-100 AST 精确 / 80-89 剥离注释后正则 / 70-79 原始正则 / 60-69 启发式 |
| **插件架构** | `@register_detector` 装饰器自注册，新增检测器不改编排逻辑 |
| **商业化分层** | free / pro / team / enterprise 四版功能矩阵（见 SKILL.md） |

## 📦 套件成员（本仓库同时是六个技能的统一安装包）

| 技能（DSH 名） | 定位 | 随包内容 |
|---|---|---|
| `codeguard` | AI 代码质量守护：三层防线、行业分离、金/银/铜门禁、模块化检测 | 63 个 Python 模块 + MCP Server |
| `iac-guardian` | 基础设施即代码（IaC）安全与成本守门 | scripts + MCP Server |
| `governance-hub` | 研发治理连接层：需求价值对齐、云成本基线、变更传播、快照门禁 | scripts + MCP Server |
| `project-manager` | 项目管理全流程：可行性研判、模板匹配、重构队列 | scripts + MCP Server |
| `fc-guardian` | 飞控硬件领域检测（引脚 / 串口 / 刷新率 / 状态机） | scripts + MCP Server |
| `embedded-flow-guardian` | 嵌入式研发流程审计与工作台 | scripts |

> 六个技能同装同用：CodeGuard 的链路脚本（`assets/codeguard-chain.*`）会调用 iac-guardian、governance-hub、project-manager，单独安装 CodeGuard 时该链路不可用。

## 📁 目录结构

```
.codebuddy/skills/
├── CodeGuard/                # 技能名 codeguard（DSH 要求小写）
│   ├── SKILL.md              #   Skill 定义（AI 调用入口，含金级门控使用规则）
│   ├── scripts/              #   63 个 Python 模块
│   │   ├── quality_*.py      #     质量检测引擎（门禁/行业/方言/模块化/覆盖率）
│   │   ├── blueprint_*.py    #     架构蓝图生成与 API 抽取
│   │   ├── context_*.py      #     L0-L3 分层上下文压缩
│   │   ├── impact_*.py       #     四维变更影响分析
│   │   ├── dashboard_*.py    #     可视化健康看板
│   │   ├── internal/         #     共享基础设施（rules_loader / detector_registry / exceptions）
│   │   ├── agents/           #     多 Agent 协作（architect / orchestrator / reviewer）
│   │   └── mcp_server.py     #     MCP JSON-RPC 2.0 stdio 服务
│   ├── rules/                #   声明式规则集（AI 专项规则包 / MISRA-C 子集）
│   ├── references/           #   架构规则完整定义（SOLID / 分层 / DRY / 安全红线）
│   ├── assets/               #   CI/CD、Dockerfile、全链路脚本
│   └── tests/                #   测试套件 + fixtures（违例/干净双样本，双向验证）
├── iac-guardian/             # IaC 安全与成本守门
├── governance-hub/           # 研发治理连接层
├── project-manager/          # 项目管理全流程
├── fc-guardian/              # 飞控硬件检测
└── embedded-flow-guardian/   # 嵌入式研发流程审计
.code-guardian/               # 本仓库自身门禁配置（金级 + embedded/silver profile）
```

## 🚀 快速开始

### 作为 CodeBuddy Skill

将 `.codebuddy/skills/` 下的技能目录复制到项目的 `.codebuddy/skills/` 即可（六个技能可全装，也可只装需要的）。当 AI 被要求生成 / 修改 / 重构代码，或提及代码质量、架构、技术债时自动触发。

### CLI

```bash
# 全量检测（退出码 0=PASS / 1=WARN / 2=BLOCK）
python .codebuddy/skills/CodeGuard/scripts/quality_check.py --path . --mode team

# 增量检测（只扫 git 变更）
python .codebuddy/skills/CodeGuard/scripts/quality_check.py --path . --mode diff

# 生成架构约束注入文本（生成前调用）
python .codebuddy/skills/CodeGuard/scripts/constraint_injector.py --path . --format checklist

# 其他工具
python .codebuddy/skills/CodeGuard/scripts/blueprint_generator.py --path . --output blueprint.json
python .codebuddy/skills/CodeGuard/scripts/module_health.py --blueprint blueprint.json
python .codebuddy/skills/CodeGuard/scripts/dashboard_generator.py --project .
```

### MCP Server

```json
{
  "mcpServers": {
    "codeguard": {
      "command": "python",
      "args": [".codebuddy/skills/CodeGuard/scripts/mcp_server.py", "--project-root", "."]
    }
  }
}
```

暴露 5 个 Tool：`review_file` / `review_diff` / `execute_rules` / `inject_constraints` / `get_industry`。

## 作为 DeepSeek Harness (dsh) 插件安装

本仓库是一个 dsh **配置型组合包**（`package.json` 声明 `dsh.bundle.patch`，补丁见 `cordis.patch.yml`）。安装即把 `.codebuddy/skills` 下的**六个技能**一起注册进 DSH 技能目录：

```bash
pnpm add https://github.com/JeaBai/CodeGuard
```

或在插件页用「Git 仓库」安装同一地址。安装后在插件管理中**启用** `codeguard`（或把 `"codeguard"` 加进 profile `package.json` 的 `dsh.profile.bundles`），按提示重启 profile 后生效。挂载两件事，互相独立：

1. **技能源**：`.codebuddy/skills` 作为 `customSkillDirs`（rank 300）注册，六个技能同时进入会话技能目录，由模型按任务渐进式加载（不依赖本机 Python）；
2. **MCP 服务**：CodeGuard 的 Python MCP Server 注册为 stdio 服务器，工具以 `mcp__codeguard__review_file` 等形式暴露（需要 `python` 在 PATH 中；缺失时该行自动降级，不影响技能行与 dsh 启动）。

如需固定 Python 解释器路径，在 profile 的 `cordis.patch.yml` 里按 id 覆盖 `mcp-codeguard` 行的 `command` 即可（profile 层最后应用，last write wins）。

> **技能名必须小写。** DSH 的技能名校验是 `/^[a-z0-9]+(?:-[a-z0-9]+)*$/`，大写名会被**静默跳过**（只在日志留一条 warning，界面上看不出区别）。因此本仓库内 CodeGuard 的 frontmatter `name` 是 `codeguard`；显示标题仍是 CodeGuard，目录名保持 `CodeGuard/` 以维持脚本与链路引用。**从上游同步时请保留这一行改动，否则该技能在 DSH 中会消失。**

> **不要与用户级技能根重复。** 若同名技能已放进 `~/.dsh/skills`（rank 400），组合包副本（rank 300）胜出，用户级那份只记 warning。二选一即可。

## 🔒 金级门禁与自定义规则

在项目根目录放置 `.code-guardian/rules.json` 即可启用金级门禁。**这是自定义规则文件：方案可直接设定，一旦存在即按设定执行、不采用内置默认。**

```json
{
  "_level": "gold",
  "thresholds": { "cyclomatic_complexity_block": 10, "max_nesting_block": 4 },
  "rules": [
    {
      "id": "GOLD_NO_BARE_EXCEPT",
      "severity": "block",
      "target": "python",
      "pattern": "except\\s*:",
      "message": "禁止裸 except",
      "suggestion": "捕获具体异常类型并记录日志"
    }
  ]
}
```

完整使用规则（定位顺序、字段表、三级阈值基准、叠加语义、边界）见 [`SKILL.md`](.codebuddy/skills/CodeGuard/SKILL.md) 的「`.code-guardian/rules.json` 金级门控使用规则」专节。

## 🧪 测试

零依赖内置 runner，无需 pytest：

```bash
python .codebuddy/skills/CodeGuard/tests/test_modularity.py    # 9 项
python .codebuddy/skills/CodeGuard/tests/test_empty_except.py  # 11 项
```

违例样本必须"全中"、干净样本必须"零误报"——双向验证，只测前者会漏掉误报。

## ⚠️ 已知缺口（如实披露）

v3.1.0 为在途版本：以**默认金级门禁**自检 `scripts/`，当前有 **169 个 BLOCK**（跨文件/文件内重复 102、圈复杂度 38、嵌套 20、文件规模 3、参数 2），集中在蓝图抽取与影响分析相关模块。功能完整、测试 20/20 通过、模块导入 29/29 通过；金级清理（拆函数 / 去重）列为后续工作，不在本版本范围内。

## 📊 规则设计依据

| 数据源 | 关键发现 | 对应规则 |
|--------|---------|---------|
| GitClear 2025（2.11 亿行） | 返工率 +39%，复制粘贴 +48% | 重复代码检测、重构提醒 |
| Sonar 2026 | >90% 问题为代码异味 | 圈复杂度、类大小限制 |
| DORA 2024 | AI 采纳 +25% → 交付稳定性 −7.2% | 增量检测模式、度量指标 |
| CodeRabbit 2025（470 PR） | AI 代码问题 1.7x，安全漏洞 +274% | 安全红线、复杂度门禁 |
| Veracode 2025 | 45% AI 代码未通过安全测试 | 硬编码密钥、SQL 注入检测 |

## 📄 License

[MIT](LICENSE) © 2026 Code Guardian
