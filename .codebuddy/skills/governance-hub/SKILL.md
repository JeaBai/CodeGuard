---
name: governance-hub
description: "研发治理连接层 Skill（v3.0.0），覆盖 D9 需求与业务价值对齐、 D11 云成本基线检视、D12 变更传播与发布通知三大治理维度， 新增架构决策记录（ADR）、设计意图保护、风险门禁、快照回滚能力。 提供发布前治理检视流程（需求关联率/迁移回滚/成本基线/契约破坏性/干系人通告）、 Conventional Commits Release Notes 草稿自动生成（release_notes_draft.py，纯标准库）、 以及变更通告模板（技术版/业务版双轨）。 当用户准备发布、需要生成 Release Notes、做需求追溯检查、成本检视、 破坏性变更评估或干系人通告时应触发。"
agent_created: true
---
# Governance Hub — 研发治理连接层 (v3.0.0)

## 概述

打通"业务-研发-运维"闭环的治理断层。v0.3.0 新增 **ADR 管理**、**设计意图保护**、**三级风险门禁**、**架构快照回滚**四大能力。

## v0.3.0 新增能力

### 架构决策记录 (ADR)
- **adr_manager.py**: 完整 ADR 生命周期管理（创建→评审→实施→替代→回滚）
- `get_active_context()`: AI 会话恢复时自动加载活跃架构决策
- 状态机 DAG（6 状态 + 8 合法转换路径）
- Markdown 时间线导出 + 回滚信息查询

### 设计意图保护
- **intent_protection.py**: 记录用户确认为有意设计的代码模式
- 保护项自动过期（expires 字段）+ 过期提醒
- 与 CodeGuard IssueCollector 集成：保护项自动 skip/downgrade/report_with_note

### 三级风险门禁
- **risk_gate.py**: 根据操作类型自动分级（🟢auto/🟡confirm/🔴manual）
- 四级升级规则（影响分析/intent_protection/file_lock/标签禁止）
- 人话确认消息生成 + diff 预览 + 执行包装器

### 架构快照与回滚
- **snapshot_manager.py**: 重构前后快照对比 + 自动门禁判断
- 11 项指标对比（复杂度/重复/循环依赖/全局变量/覆盖率等）
- auto_gate 四条件裁决（恶化>20%→reject / 覆盖率下降→reject）
- Git 集成回滚建议

### 模块标签管理
- **tag_manager.py**: 8 种模块标签 + 3 种参数标签
- 冲突检测（如 frozen + allow_split 互斥）
- 与 CodeGuard 标签白名单对齐

### 对话式约束编辑
- **constraint_editor.py**: 自然语言修改模块约束
- 模块名三级匹配（精确/语义/路径）+ 意图关键词识别

## 商业化模式

| 层级 | 功能 | 定价模型 |
|------|------|---------|
| **免费版** | ADR 记录、标签管理、基础门禁规则 | 开源免费 |
| **专业版** | 风险门禁、设计意图保护、快照对比、Release Notes 生成 | 按团队/月 |
| **企业版** | 合规审计、干系人自动通告、多项目治理大盘、SLA 保障 | 年度合同 |

**差异化价值**: 实证数据显示 60% 的线上事故源于"变更后缺乏系统性验证"（GitLab 2017 删库事故）。Governance Hub 通过"ADR记录→风险门禁→快照对比→自动回滚"四层防线，将变更风险降低 80% 以上。

---

## AI 调用指南

### 可用脚本

| 脚本 | CLI 签名 | 用途 |
|---|---|---|
| `adr_manager.py` | `python adr_manager.py --action {list\|get\|active-context\|create\|update\|supersede\|rollback-info\|timeline} [--id ADR-XXX] [--project-root .] [--format {text\|json}]` | ADR 全生命周期管理 |
| `risk_gate.py` | `python risk_gate.py --action {check\|classify\|confirm\|diff\|config} [--type T] [--file F] [--function F] [--blueprint P]` | 三级风险门禁（auto/confirm/manual） |
| `snapshot_manager.py` | `python snapshot_manager.py --action {create\|compare\|gate\|list\|get\|rollback} [--project .] [--before ID] [--after ID]` | 架构快照创建/对比/回滚 |
| `tag_manager.py` | `python tag_manager.py --blueprint BLUEPRINT --action {list\|apply\|remove\|validate\|check\|export-doc} [--module M] [--tag T]` | 模块标签管理系统 |
| `intent_protection.py` | `python intent_protection.py --action {add\|remove\|check\|list-active\|list-expired\|report} [--file F] [--function F] [--rule R]` | 设计意图保护记录 |
| `governance_check.py` | `python governance_check.py --path . [--format {text\|json}] [--ci]` | 发布前五问自动化检视 |
| `governance_gate.py` | `python governance_gate.py --mode {release\|cost-only\|contract-only\|trace-only\|deploy-only\|auto-trace} [--path .]` | 发布前三合一门禁 |
| `release_notes_draft.py` | `python release_notes_draft.py [--from HEAD~20] [--to HEAD] [-o PATH]` | Conventional Commits → Release Notes 草稿 |
| `rvi_calc.py` | `python rvi_calc.py --path . [--range 90d] [--format {text\|json}]` | 需求偏差率 (RVI) 度量 |
| `jira_trace.py` | `python jira_trace.py --project PROJ [--path .] [--range 30d]` | Jira 需求关联率统计 |
| `llm_business.py` | `python llm_business.py --tech TECH_MD [--from HEAD~20] [--to HEAD] [--model gpt-4o-mini]` | LLM 业务版 Release Notes 转换 |
| `stakeholder_webhook.py` | `python stakeholder_webhook.py --platform {slack\|dingtalk\|feishu\|wecom\|custom\|all} [--title T] [--dry-run]` | 干系人通告 webhook 推送 |
| `mcp_server.py` | `python mcp_server.py --project-root .` | MCP JSON-RPC 2.0 stdio 服务 |

### MCP 工具（通过 mcp_server.py 暴露）

| Tool 名 | 入参 | 出参 | 用途 |
|---|---|---|---|
| `release_notes` | `from_ref` (必填), `to_ref` (必填), `output_file` (可选) | exit_code + notes Markdown | 基于 Conventional Commits 生成 Release Notes |
| `trace_requirements` | `sample_size` (可选, 默认 20) | exit_code + summary (关联率) | 需求追溯完整性检查 |
| `check_release_readiness` | `path` (必填) | Q1-Q5 各维度结果 + 门禁结论 | 发布前五问自动化检视 |

### 跨 SKILL 接口

| 方向 | 项目 | 格式 | 消费方 | 推荐顺序 |
|---|---|---|---|---|---|
| **输出** | 风险分级结果 (`risk_gate.py check`) | `{level: auto\|confirm\|manual, reason, ...}` | CodeGuard (分级修复), project-manager (refactor_queue 门禁) | 步骤2-产出 → 步骤1/3 反馈 |
| **输出** | 快照对比结果 (`snapshot_manager.py gate`) | `{verdict: approve\|reject\|manual_review, metrics, ...}` | CodeGuard (重构前/后门禁) | 步骤2-产出 → 步骤1 门禁 |
| **输出** | 设计意图保护记录 (`intent_protection.py`) | `.codebuddy/intent_protection.json` | CodeGuard (扫描时自动 skip/downgrade) | 步骤2-产出 → 步骤1 过滤 |
| **输出** | 标签约束 (`tag_manager.py export-doc`) | ai_constraint 文本 | CodeGuard (生成约束注入 AI 上下文) | 步骤2-产出 → 步骤1 注入 |
| **输入** | 架构蓝图 | CodeGuard `architecture_blueprint.json` | tag_manager (模块索引), risk_gate (影响分析联动) | 步骤2-依赖 ← 步骤1 产出 |
| **输入** | CodeGuard 扫描结果 | CodeGuard `scan_results` JSON | risk_gate (风险升级依据) | 步骤2-依赖 ← 步骤1 产出 |
| **输入** | IaC 成本报告 | iac-guardian `--bridge` JSON | governance_gate `--iac-report` (成本基线联动) | 步骤2-依赖 ← 步骤1 扫描 |

---

> 以下为原有内容（v0.1.0），新能力已在 `scripts/` 目录中实现。
