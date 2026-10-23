# 工具注册表梳理与精简评估

> 对象：`project-manager` 的 MCP 工具注册表（`scripts/mcp_tools_registry.py` / `TOOL_REGISTRY`）
> 评估依据：**实测**入参 schema 质量、实现同构度、是否有逻辑分支、`tools/list` 载荷量
> 日期：2026-10-03

---

## 一、先看成本：`tools/list` 是常驻开销

MCP 客户端连接时会调用 `tools/list` 并把**全部工具定义**放进上下文 —— 这是**每次会话常驻**的 token 成本。

| 指标 | 实测值 |
|---|---|
| 工具数 | 16 |
| `tools/list` 载荷 | **5,765 字符 ≈ 2,882 token** |
| 性质 | **常驻**（相当于把 16 段接口文档塞进每次对话） |

**所以"精简工具条目"不是审美问题，是直接的 token 成本问题。**

## 二、逐工具清单：职责 / 调用场景 / 入参质量

| # | 工具 | schema | 职责 | 调用场景 | 入参质量 |
|---|---|---:|------|------|---|
| 1 | `configure_agent_roster` | 861 | 配置多 Agent 角色矩阵（define/list/assign） | 需要多角色协作编排时 | ✅ 显式字段 |
| 2 | `manage_experience_library` | 808 | 经验资产库增删查（register/search/…） | 沉淀/检索可复用经验 | ✅ 显式字段 |
| 3 | `import_from_tencentdb` | 430 | 从本地 TencentDB 目录批量导入记忆 | **冷启动一次性迁移** | ✅ 显式字段 |
| 4 | `sync_adr_decisions` | 320 | 关键决策同步到 governance-hub ADR | 决策需要归档时 | ⚠️ 裸 JSON |
| 5 | `create_project_plan` | 317 | 生成启动规划书（质量标准/里程碑/技术选型） | 项目启动时 | ⚠️ 裸 JSON |
| 6 | `start_feasibility_check` | 304 | 可行性研判（市场/资源/风险） | 立项前 | ⚠️ 裸 JSON |
| 7 | `extract_knowledge_assets` | 300 | 从 CodeGuard 蓝图自动提取经验资产 | 复盘后资产化 | ✅ 显式字段 |
| 8 | `knowledge_asset_export` | 297 | 导出知识沉淀文档 | 需要交付文档时 | ⚠️ 裸 JSON |
| 9 | `vision_tracker_scan` | 271 | 扫描 GitHub Trending / AI 工具 / 框架更新 | 开阔视野 | ✅ 显式字段 |
| 10 | `communications_plan` | 271 | PMBOK 沟通绩效域评估 | 沟通机制设计 | ⚠️ 裸 JSON |
| 11 | `stakeholder_analysis` | 267 | PMBOK 干系人绩效域评估 | 干系人管理 | ⚠️ 裸 JSON |
| 12 | `quality_gate_check` | 265 | 质量门禁（覆盖率/技术债/红线） | 阶段准出前 | ⚠️ 裸 JSON |
| 13 | `generate_retrospective` | 263 | 项目复盘报告 | 阶段/项目结束 | ⚠️ 裸 JSON |
| 14 | `team_health_check` | 262 | PMBOK 团队绩效域评估 | 团队协作体检 | ⚠️ 裸 JSON |
| 15 | `weekly_vision_report` | 252 | 每周视野跟踪报告 | 周期性防闭门造车 | ⚠️ 裸 JSON |
| 16 | `daily_progress_check` | 234 | 每日进度自检（完成/阻塞） | 日常节奏 | ⚠️ 裸 JSON |

## 三、已修复的缺陷（最严重的一条）

### PMBOK 三域工具**客观上无法调用**

**症状**：`team_health_check` / `stakeholder_analysis` / `communications_plan` 的实现读取的是**问卷题号**：

```python
result += f"**关键缺口**: {data.get('58', '未检测')}\n"   # ← '58' 是题号
result += f"- 团队士气 (1-5): {data.get('59', 'N/A')}\n"
```

**证据链**（已按实测更正）：
1. 共 **16 处**数字键（题号 58–74）—— 题号来自 `mcp_data.PHASE_QUESTIONS`，
   **题库实际有 86 题（1–86，连续无缺口）**，58–74 **全部在库内**，**并非"越界"或"无定义"**
2. schema 只写"JSON格式的团队评估数据"，**不透露任何键名** ← 这才是真成因
3. `SKILL.md` / `references/mcp_usage.md` **均未记录这三个工具的键名**
   （`mcp_usage.md` 只文档化了前 8 个工具）
4. **实测传空 `{}` 不报错**，输出全是"未检测/未评估/N/A"占位 → **静默失效**
5. **另查出漏题**：`team_health_check` 漏题 56/57、`stakeholder_analysis` 漏题 65（不报错，报告静默缺维度）

**结论**：调用方（无论 AI 还是人）**不可能知道要传 `{"58": ...}`**，这三个工具形同虚设。

**处置**：已把 16 处数字键替换为**语义键**，并在 schema 里显式列出字段名：

| 工具 | 现在的 `answers` 字段 |
|---|---|
| `team_health_check` | `{skill_gaps, morale, conflicts, deep_work_hours, onboarding, last_retro}` |
| `stakeholder_analysis` | `{power_map, attitude, comm_frequency, info_asymmetry, pending_feedback}` |
| `communications_plan` | `{meeting_duration, escalation_path, external_contact, primary_tool, decision_traceability}` |

> 保形不破坏：仍用 `answers: string`（与其他工具一致），只把键名写进 description —— 与
> `daily_progress_check` 的 `{today_done, status, blocker, blocker_plan}` 写法保持同一约定。

## 四、剩余冗余判定

| 组 | 工具 | 证据 | 判定 |
|---|---|---|---|
| **PMBOK 三域** | `team_health_check` / `stakeholder_analysis` / `communications_plan` | **签名完全同构**（`project_name` + `answers`）；实现均为**纯拼接**（无 if/for/try 分支）；仅输出模板不同 | ⚠️ **可合并为 `pmbok_assess(project_name, domain)`** —— 省 2 个条目约 **530 字符 ≈ 265 token** |
| **一次性桥接** | `import_from_tencentdb` | 从**外部产品的本地目录**批量导入，属冷启动迁移；**无 docstring**；依赖外部产品目录结构 | ⚠️ **候选剔除** —— 省 **430 字符 ≈ 215 token**（代价：失去该导入能力，属产品决策） |
| 知识资产 | `knowledge_asset_export`(导出文档) / `extract_knowledge_assets`(从蓝图提取入库) / `manage_experience_library`(库操作) | 三者边界**清晰**（导出 / 采集 / 库管理），非重复 | ✅ 保留 |
| 视野跟踪 | `vision_tracker_scan`(扫描) / `weekly_vision_report`(汇总报告) | 一个采集、一个成文，边界清晰 | ✅ 保留 |
| 阶段工具 | `start_feasibility_check` / `create_project_plan` / `daily_progress_check` / `quality_gate_check` / `generate_retrospective` | 各自对应**不同阶段的交付物**，同构但语义不同 | ✅ 保留（**同构 ≠ 冗余**） |

### 数据结论

| 项 | 字符 | token | 占比 |
|---|---:|---:|---:|
| 当前 `tools/list` 载荷 | 5,765 | 2,882 | 100% |
| 合并 PMBOK 三域 | −530 | −265 | −9% |
| 剔除 `import_from_tencentdb` | −430 | −215 | −7% |
| **两者合计** | **−960** | **−480** | **−17%** |

## 五、为何"同构"不等于"冗余"

`start_feasibility_check`、`create_project_plan`、`daily_progress_check`、`quality_gate_check`、
`generate_retrospective` 五个工具签名也高度同构（`project_name` + `answers`），但**不应合并**：
它们的区别是**阶段语义与产出的交付物**（可行性研判 / 规划书 / 日进度 / 质量门禁 / 复盘报告），
合并会迫使调用方用 `phase` 参数猜测该填什么，**反而提高调用成本**。

**判据**：合并的前提是"**同一类事物的不同维度**"（PMBOK 三绩效域），
而不是"**同一套流程的不同阶段**"（阶段工具）。前者合并降本，后者合并增本。

## 六、待决策

1. **合并 PMBOK 三域为 `pmbok_assess`？** —— 修 bug 已完成（三域现在可用），合并是**额外的 token 优化**（−9%）
2. `import_from_tencentdb` —— **职责理解已更正**（见下），不再是"候选剔除"
3. 其余 12 个工具的 `answers` 裸 JSON **是否要逐一补字段名？** —— 建议按需补（现有 `mcp_usage.md` 已记录多数工具的字段，可对齐）

---

## 七、更正：`import_from_tencentdb` 的定位（勿按"一次性桥接"处理）

我在本篇 §四 曾把 `import_from_tencentdb` 判为「**冷启动一次性迁移**」并列为候选剔除 —— **该理解有误**。

**正确认识**：**TencentDB 是跨团队记忆复用工具，其作用是降低历史记忆的 token 输出，而非移除这些记忆。**
因此它与"一次性冷启动"无关，而属于**常态化的记忆供给链路**。

**由此引出的结论**：在 TencentDB 之上**再叠加一层本地注册表（`experience_store` 的"统一登记"）**
**不产生实际价值** —— 它不降 token（降 token 靠检索后少量注入），却引入
**双写不一致、技能目录内落盘导致升级丢失、元数据双重维护** 三重风险。

**详细论证与替代方案**：见 `references/tool-contract-analysis.md` §三、§四。

> 本篇 §四 的"精简候选 −430 字符"**作废**：不该按 token 面积决定它的去留，
> 而应按**职责边界**决定（它是否在扮演"第二记忆源"）。

---

## 七、更正：`import_from_tencentdb` 的定位（勿按"一次性桥接"处理）

我在本篇 §四 曾把 `import_from_tencentdb` 判为「**冷启动一次性迁移**」并列为候选剔除 —— **该理解有误**。

**正确认识**：**TencentDB 是跨团队记忆复用工具，其作用是降低历史记忆的 token 输出，而非移除这些记忆。**
因此它与"一次性冷启动"无关，而属于**常态化的记忆供给链路**。

**由此引出的结论**：在 TencentDB 之上**再叠加一层本地注册表（`experience_store` 的"统一登记"）**
**不产生实际价值** —— 它不降 token（降 token 靠检索后少量注入），却引入
**双写不一致、技能目录内落盘导致升级丢失、元数据双重维护** 三重风险。

**详细论证与替代方案**：见 `references/tool-contract-analysis.md` §三、§四。

> 本篇 §四 的"精简候选 −430 字符"**作废**：不该按 token 面积决定它的去留，
> 而应按**职责边界**决定（它是否在扮演"第二记忆源"）。
