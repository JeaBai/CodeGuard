---
name: project-manager
description: "项目管理全流程智能助手 (MCP Compatible v3.1.0)。 覆盖项目全生命周期：启动前(可行性研判+模板匹配)、启动时(规划书+蓝图)、执行中(每日进度+质量门禁+重构队列)、交付后(复盘+经验资产化+快照对比)、持续视野(趋势扫描+周报)、团队经验资产库、多 Agent 角色矩阵编排、PMBOK 三绩效域评估(团队健康/干系人/沟通)。 当用户请求项目立项与可行性研判、制定项目规划与里程碑、跟踪进度与阻塞、项目复盘与经验沉淀、技术选型与竞品/技术趋势调研、风险评估与干系人及沟通管理、搭建或查询团队经验资产库、配置多 Agent 角色分工时，或提及项目管理、WBS、里程碑、干系人、复盘、经验资产、Agent 编排时应触发。 不适用于：单文件代码质量与架构违规检测(归 CodeGuard)、发布治理与 ADR(归 governance-hub)、IaC 安全(归 iac-guardian)。 MCP 协议兼容，可作为 MCP Server 被 Claude Code、Cursor、VS Code 等客户端调用。"
triggers:
  - 项目管理 / 项目立项 / 可行性研判 / 值不值得做
  - 项目规划 / 规划书 / 里程碑 / 排期 / WBS
  - 进度跟踪 / 每日自检 / 阻塞点 / 延期
  - 项目复盘 / 回顾 / 经验沉淀 / 目标达成率
  - 技术选型 / 竞品分析 / 技术趋势扫描 / 周报
  - 风险评估 / 干系人分析 / 沟通计划
  - 经验资产库 / 知识沉淀 / 可复用资产
  - 多 Agent 编排 / 角色矩阵 / Agent 分工
avoid:
  - 单文件代码质量、复杂度、安全漏洞、架构分层 → CodeGuard
  - 发布治理、ADR、风险门禁、快照回滚 → governance-hub
  - Terraform/K8s 等 IaC 安全与成本 → iac-guardian
  - 引脚/串口/看门狗等飞控硬件层 → fc-guardian
  - 交付物完整性、需求追溯、串口采集 → embedded-flow-guardian
agent_created: true
---
# 项目管理全流程助手 — Project Manager Skill (v3.0.0)

## 概述

覆盖项目全生命周期的 AI 助手。v2.3 工程补全：**SQLite FTS5 全文检索**、**内容指纹去重**、**Tool 调用计时**、**自动经验提取管道**、**Agent 结构化记忆**、**TencentDB 桥接导入**，补齐存储/去重/可观测性/自动化/记忆/冷启动六大工程差距。

## v2.3 工程补全（零外部依赖）

### 团队经验资产库
- **experience_library.py**: 对标 TencentDB Chat Memory/Skill/Wiki/CodeGraph 四种记忆资产统一登记
- 支持 register(登记)/search(搜索)/load(加载到 AI 上下文)/tag(版本标签)/expire(过期)/stats(统计)
- 四级可见性分级：private(仅Owner)/team(团队)/restricted(ACL)/agent(Agent 装配)
- 零外部依赖，纯 JSON 文件存储于 `.codebuddy/experience/`

### 多 Agent 角色矩阵与编排
- **agent_roster.py**: 对标 TencentDB Team→Agent→Loadout 三层模型
- 7 个预设角色：Scout(侦察兵)/Builder(构建者)/Reviewer(审查官)/Test Pilot(测试)/DevOps/Architect(架构师)/PM Lead(负责人)
- 支持 define-role(定义角色)/assign-memory(装配经验)/create-squad(组建小队)/export-manifest(导出编排清单)
- 零外部依赖，配置文件存储于 `.codebuddy/roster/`

### 会话记忆持久化
- MCP Server 启动时从 `.codebuddy/session_state.json` 恢复上次上下文
- 每次 Tool 调用后自动保存当前阶段/活跃任务/关键决策
- 无状态文件时静默降级（无状态模式）

### ADR 决策同步
- `sync_adr_decisions`: 项目关键决策自动同步到 governance-hub ADR 管理器
- 同时登记到经验资产库，形成决策时间线

### 知识自动提取管道
- `extract_knowledge_assets`: 从 CodeGuard 蓝图自动提取可复用模块
- 高价值克隆组自动登记为经验资产（skill 类型）
- 与 experience_library.py 闭环联动

## v2.1 能力（保留）

### 渐进式重构队列
- **refactor_queue.py**: 将 CodeGuard 检测结果转化为有序重构任务队列
- 文件锁机制（`.codebuddy/file_locks.json`）防止多会话冲突
- 自动导入 CodeGuard 输出 → block→P0 / warn→P1 / info→P2
- 依赖管理 + 过期锁自动清理（>2h）

### 场景模板引擎
- **template_engine.py**: 6 个预制场景模板（电商/官网/后台/API/数据/IoT）
- 关键词匹配：自然语言描述 → 最佳模板
- 一键应用：模板 → `architecture_blueprint.json`
- 定制化：±模块、改约束、加共享工具

### 可视化健康看板
- **dashboard_generator.py**: 生成自包含 HTML 看板
- 三维度评分（安全/代码/架构）+ 趋势箭头
- 问题清单 + 交互式操作（一键修复/查看详情/人工确认）
- 暗色主题 + 响应式设计
- `--watch` 监听模式自动刷新

## 商业化模式

| 层级 | 功能 | 定价模型 |
|------|------|---------|
| **免费版** | 基础模板、个人重构队列、健康看板生成 | 开源免费 |
| **专业版** | 高级模板（10+）、团队队列协作、多项目看板 | 按团队/月 |
| **企业版** | 自定义模板引擎、自动化流水线集成、OKR 追踪、SLA 保障 | 年度合同 |

**差异化价值**: 项目管理最大的痛点是"计划与执行脱节"。Project Manager 通过"模板→蓝图→重构队列→看板"闭环，将规划到可执行步骤的转化时间从数天缩短到分钟级别。

---

## AI 调用指南

### 可用脚本

| 脚本 | CLI 签名 | 用途 |
|---|---|---|
| `template_engine.py` | `python template_engine.py --action {list\|get\|apply\|match\|customize\|summary} [--id ID] [--project .] [--description DESC]` | 场景模板管理（6 模板 + 关键词匹配） |
| `refactor_queue.py` | `python refactor_queue.py --action {enqueue\|dequeue\|status\|complete\|fail\|lock\|unlock} [--title T] [--files F] [--project .]` | 渐进式重构队列（文件锁 + 自动入队） |
| `report_generator.py` | `python report_generator.py --type {feasibility\|planning\|retrospective} [--project NAME] [--deadline DATE] [--output DIR]` | Markdown/JSON/HTML 项目报告生成 |
| `vision_tracker.py` | `python vision_tracker.py [--domain D] [--keywords CSV] [--format {text\|json}]` | 技术趋势/竞品动态自动扫描 |
| `mcp_server.py` | `python mcp_server.py [--transport {stdio\|sse}] [--port 8765] [--list-tools] [--tool T] [--args JSON]` | MCP 入口（stdio/SSE 双模式 + 非 MCP CLI） |

### MCP 工具（通过 mcp_server.py 暴露，异步 TOOL_REGISTRY 架构）

| Tool 名 | 入参 | 出参 | 用途 |
|---|---|---|---|
| `start_feasibility_check` | `project_name`, `answers` (JSON) | Markdown 可行性报告 | PMBOK 启动：市场需求/资源/风险评估 |
| `create_project_plan` | `project_name`, `deadline`, `answers` (JSON) | Markdown 规划书 | PMBOK 规划：质量标准/里程碑/技术选型 |
| `daily_progress_check` | `answers` (JSON) | Markdown 日报 | PMBOK 执行：今日完成/阻塞/明日计划 |
| `quality_gate_check` | `answers` (JSON) | Markdown 门禁报告 | PMBOK 监控：覆盖率/技术债务/质量红线 |
| `vision_tracker_scan` | `domain`, `keywords` | Markdown 趋势报告 | 技术趋势/竞品动态自动扫描 |
| `generate_retrospective` | `project_name`, `answers` (JSON) | Markdown 复盘报告 | PMBOK 收尾：目标达成/经验资产/续投决策 |
| `knowledge_asset_export` | `project_name`, `assets` (JSON) | Markdown 资产清单 | 知识沉淀：可复用代码/模板/流程/踩坑 |
| `weekly_vision_report` | `domain`, `findings` (JSON) | Markdown 周报 | 每周视野跟踪：技术趋势/市场信号 |
| `team_health_check` | `project_name`, `answers` (JSON) | Markdown 团队评估 | PMBOK Team 绩效域：技能/士气/深度工作 |
| `stakeholder_analysis` | `project_name`, `answers` (JSON) | Markdown 干系人报告 | PMBOK Stakeholder 绩效域：权力图谱/参与策略 |
| `communications_plan` | `project_name`, `answers` (JSON) | Markdown 沟通计划 | PMBOK Communications 绩效域：节奏/协议/渠道 |
| `manage_experience_library` | `project_name`, `action`, `...` | Markdown/JSON | 经验资产库：register/search/load/stats（v2.2） |
| `configure_agent_roster` | `project_name`, `action`, `...` | Markdown/JSON | Agent 角色编排：define-role/assign-memory/create-squad（v2.2） |
| `sync_adr_decisions` | `project_name`, `answers` (JSON) | Markdown | ADR 决策同步 → governance-hub（v2.2） |
| `extract_knowledge_assets` | `project_name`, `blueprint_path` | Markdown | 知识自动提取：CodeGuard → 经验资产库（v2.2） |

### 跨 SKILL 接口

| 方向 | 项目 | 格式 | 消费方 | 推荐顺序 |
|---|---|---|---|---|---|
| **输出** | 重构队列状态 (`refactor_queue.py status`) | `{queue items, locks, ...}` | AI 会话（并发协调） | 步骤3-产出 → 持续反馈 |
| **输出** | 项目报告 (`report_generator.py`) | Markdown/JSON/HTML | 干系人通告 | 步骤3-产出 → 干系人交付 |
| **输入** | 架构蓝图 | CodeGuard `architecture_blueprint.json` | template_engine (模板应用/定制) | 步骤3-依赖 ← 步骤1 产出 |
| **输入** | CodeGuard 扫描结果 | CodeGuard `scan_results` JSON | refactor_queue (自动入队 block→P0/warn→P1) | 步骤3-依赖 ← 步骤1 产出 |
| **输入** | 风险分级结果 | governance-hub/risk_gate JSON | refactor_queue (门禁阻断判定) | 步骤3-依赖 ← 步骤2 返回 |
| **输入** | 快照对比结果 | governance-hub/snapshot_manager JSON | refactor_queue (重构后验证输入) | 步骤3-依赖 ← 步骤2 返回 |
| **输入** | ADR 决策记录 | governance-hub/adr_manager JSON | sync_adr_decisions (决策同步) | 步骤4-依赖 ← 步骤2 返回（v2.2） |

---

> 以下为原有内容（v2.0），新能力已在 `scripts/` 目录中实现。

## 工具注册表

- `references/tool-contract-analysis.md` —— **工具契约缺陷成因 + 记忆层机制判断**：PMBOK 三域为何不可调用、漏题缺陷、以及"不该在 TencentDB 上叠注册表"的论证
- `references/tool-inventory.md` —— 16 个工具的职责/调用场景/入参质量、冗余判定与 token 成本量化。**改工具前必读。**
