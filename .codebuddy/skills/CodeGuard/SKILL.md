---
name: codeguard
description: "防止 AI 生成代码沦为\"死山代码\"的质量守护 Skill / MCP Server (v3.1.0)。 三层防线：生成前自动注入架构约束、生成中自查、生成后质量门禁检查；支持 CodeBuddy Skill 模式 + MCP 协议跨平台模式 (Claude Code/Cursor/VS Code)。 检测圈复杂度、重复代码、架构分层违规、循环依赖、安全漏洞、错误处理完整性。 行业规则集自动切换（Web/云、嵌入式、安全关键）；C 方言自动分流（通用 C/C++ 与嵌入式 C：MISRA/ISR/volatile/栈深度）。 输出置信度评分。 当用户请求生成/修改/重构代码，或提及代码质量、架构、技术债，或需要规范模块化与接口设计、降低模块耦合、检查跨模块调用是否可稳定、维护模块索引、接口契约与版本管理、依赖锁定与可复现构建、避免死山代码时应触发。 专注于应用层代码质量与安全（基础设施级 IaC 安全由 iac-guardian 处理）。 基于实证研究设计 (GitClear 2025, Sonar 2026, DORA 2024, CodeRabbit 2025, Veracode 2025)。"
agent_created: true
---
# CodeGuard — AI 代码质量守护者 (v3.1.0)

## 概述

防止 AI 生成代码沦为"死山代码"。v2.0 新增 **MCP 协议支持**、**置信度评分**、**文件类型感知**和**循环依赖检测**，覆盖所有主流 MCP 客户端。

## `.code-guardian/rules.json` 金级门控使用规则（自定义规则）

**定位**：`.code-guardian/rules.json` 是 CodeGuard 的**项目级自定义规则文件**——门禁方案（级别、阈值、规则、忽略路径、C 方言）**可直接在文件里设定，无需改任何代码**，金级门控即由它驱动。

**铁律 —— 自定义优先，存在即遵守**：

1. 该文件存在且设定了某一项 ⇒ **必须按设定值执行，该项不采用内置默认值**；
2. 文件缺失、JSON 解析失败或顶层不是对象 ⇒ 整体回退内置默认金级（gold）；
3. 某一项未设定 ⇒ 仅该项回落默认，已设定项仍按设定执行。

**文件定位顺序**（`internal/rules_loader.py`，首个命中生效）：

| 顺序 | 路径 |
|---|---|
| 1 | `<项目根>/.code-guardian/rules.json`（推荐，`_level`/`_c_dialect` 只认这一处） |
| 2 | `<项目根>/rules.json` |
| 3 | `<项目根>/.code-guardian.json` |

**预设从哪来**：技能目录内的 `templates/code-guardian-preset/` 是与内置金级 36 条规则同步的配置快照（`rules.json` + `rules-silver.json` + `config.json` + `profiles/`）。项目根没有 `.code-guardian/` 时，把它复制成 `<项目根>/.code-guardian/` 即可启用完整金级门控；**不复制则只有内置金级阈值生效，那 36 条金级自定义规则不参与检测**（实测同一份代码：无配置 4 项 / 有配置 10 项）。

### 可设定字段（存在即生效）

| 字段 | 取值 | 生效行为 |
|---|---|---|
| `_level` | `gold`/`silver`/`bronze` | 整组阈值基准切换为该级别；缺省 `gold`；未知值告警并回退 `gold` |
| `thresholds` | 键值对 | **逐键覆盖**同级别默认阈值；仅已知键生效，未知键告警后忽略 |
| `rules` | 规则数组 | 自定义规则**追加**在内置检测之后执行（叠加，不替换内置规则） |
| `ignorePaths.patterns` | glob 数组 | 扫描前跳过匹配的目录/文件 |
| `_c_dialect` | `auto`/`generic`/`embedded` | C 方言显式覆盖，压过自动分流 |

> `_comment`/`_version`/`_description`/`_usage` 等 `_` 前缀字段是元数据，不参与门禁判定。

### 三级阈值基准（`_level`）

| 指标 | gold | silver | bronze |
|---|---|---|---|
| 圈复杂度 warn/block | 8/10 | 10/12 | 15/20 |
| 函数参数 warn/block | 4/6 | 5/7 | 8/10 |
| 嵌套深度 warn/block | 3/4 | 4/5 | 6/8 |
| 类行数 warn/block | 200/350 | 300/450 | 500/800 |
| 类方法数 warn | 12 | 15 | 20 |
| 接口方法数 warn | 8 | 10 | 15 |
| 重复行 warn/block | 5/8 | 6/10 | 10/15 |
| 跨文件重复 block | 15 | 20 | 30 |
| 文件行数 warn/block | 200/350 | 300/450 | 500/800 |
| 测试覆盖率下限 % | 80 | 60 | 0 |

未写 `thresholds` 时按 `_level` 对应基准整组执行；写了就**只覆盖写出的键**，其余仍走该级别基准。

### 自定义规则条目格式（`rules` 数组）

| 字段 | 必填 | 说明 |
|---|---|---|
| `pattern` | ✅ | 正则（Python `re`；默认忽略大小写 + MULTILINE，`case_sensitive: true` 可关） |
| `id` | 推荐 | 规则唯一标识，报告以 `[id]` 前缀回显；缺省显示为 `?` |
| `severity` | ❌ | `block`/`warn`/`info`，默认 `warn` |
| `target` | ❌ | 作用域：`all`(默认) / 语言（`python`/`javascript`/`java`/`go`/`csharp`/`rust`）/ 管道多语言 / 架构层（`domain`/`application`/`infrastructure`/`presentation`）/ glob |
| `message`/`suggestion` | ❌ | 违规消息 / 修复建议 |
| `expected_precision` | ❌ | 0–1，校准置信度（未指定时正则规则默认 80） |

**叠加语义**：内置检测（函数级圈复杂度/参数/嵌套、重复、架构分层、安全红线、模块化）**始终执行**；`rules` 里的自定义规则在其后叠加。想排除某类误报用 `ignorePaths` 或行内豁免，不存在"自定义规则替换内置规则"。

**行内豁免**：目标行或其上方 3 行内的 `# codeguard: ignore <RULE_ID>` / `# noqa`。

### 边界（如实说明）

- `.code-guardian/config.json` 的 `gate_level` 被**显式设为非 gold** 时，优先于 rules.json 的 `_level`（config.json 是显式选择，rules.json 是默认值）；行业维度（web/embedded/safety）及其阈值覆盖由 MCP 侧 `init_industry_aware` 在门禁阈值之上再叠加。
- 旧版 `.code-guardian/rules.yaml|yml|toml` 不受支持，仅输出迁移警告后跳过。
- 未知 `_level`、未知阈值键、无效正则都会**告警并跳过对应项**，不会静默生效。

## v3.0.0 新增能力

### 行业分离（Web/云 vs 嵌入式 vs 安全关键）

**核心问题**：Web/云金级规则（34条）包含 API版本管理、DB迁移安全、健康检查端点等 6 条 Web 专用规则，在嵌入式固件场景全是噪音。同时，嵌入式核心 MISRA-C 规则（9条）在 Web 项目中无适用对象。统一规则集导致双向误报。

**解决方案**：三维正交设计 — 行业维度 × 门禁级别 × 商业版本，互不耦合。

| 行业 | 规则集文件 | 金级规则数 | 适用场景 |
|------|-----------|:---------:|---------|
| `web` | `rules.json` (现有) | 34 条 | API服务/前端/后端/云原生 |
| `embedded` | `profiles/embedded-gold.json` | 26 条 | RTOS/裸机/单片机/固件/驱动 |
| `safety` | `profiles/safety-gold-asil-dc.json` (Phase 2) | 待定 | 车规ASIL D-C/医疗IEC 62304/工业IEC 61508 |

**行业自动检测**：`industry_detector.py` 根据项目特征（ISR/volatile/链接脚本/Cargo.toml no_std/ISO 26262关键词）自动判定行业维度，也可通过 `.code-guardian/config.json` 显式指定。

**配置入口**：`.code-guardian/config.json`
```json
{
  "industry": "auto",      // auto/web/embedded/safety
  "gate_level": "gold",     // gold/silver/bronze
  "asil_level": null        // 仅 safety 行业有效: A/B/C/D
}
```

**集成初始化**：`quality_core_config.py` 新增 `init_industry_aware(root_path)` — 一次性完成门禁级别读取 + 行业检测 + 阈值叠加 + 规则集加载。

**阈值差异**：嵌入式金级放宽 CC 至 15（状态机天然偏高）、收紧嵌套至 3（中断嵌套应更严格）、放宽文件行数至 500（驱动文件常超 350 行）。

**MCP 新增工具**：
- `get_industry` — 查询当前项目行业维度配置（行业/门禁级别/规则集路径/阈值数）

**`execute_rules` 增强**：返回值新增 `industry`、`gate_level`、`profile_path`、`industry_rules` 字段，并自动追加行业规则集规则。

### 三层防线（生成前 / 生成中 / 生成后）

统一规则单一事实源 `quality_rule_registry.py`，三层防线共享同一套规则元数据（rule_id/name/severity/category/confidence/file_types/checklist），消除三处硬编码不一致。

| 层 | 阶段 | 组件 | 能力 |
|----|------|------|------|
| 第一层 | 生成前 | `constraint_injector.py` + `FileClassifier` | 注入架构约束 + 文件类型差异化过滤（`load_skill_rules(file_type)`），清单从注册表动态生成 |
| 第二层 | 生成中 | `quality_mid_check.py` | 对代码片段逐项自查，输出 `{rule_id, passed, confidence, evidence}` 置信度评分 |
| 第三层 | 生成后 | `quality_arch.py` + `quality_security.py` | DependencyGraph 循环依赖 + 三扫描安全 + `rule_id↔category` 闭环审计 |

**闭环映射**：`IssueCollector` 记录 `rule_id`（category 唯一映射时自动补），报告可反查注入规则名，实现"注入约束 ↔ 检出违规"可追溯。

## v2.2.1 新增能力

### 函数级检测精度修复（消除文件级累加误报）

**核心问题**：文件级 CC/nesting 累加导致多函数 clean 文件被误报（10 项 FP）。

**解决方案**：改为函数级检测（`_compute_function_cc` / `_compute_function_nesting`），按函数定义正则分割函数体、屏蔽嵌套函数体，独立计算每个函数的 CC/嵌套深度；修正正则重复计数（Go `if err != nil`、各语言 `else if`），嵌套关键字移除 class/function 结构项。

### 语言专属规则（补齐 10 语言漏检）

`LANG_SPECIFIC_RULES` 补齐各语言 easy 级违规模式：C `goto`、C++ 裸 `new`/多继承、Go `panic`/匿名 `goroutine`、Java `System.exit`/`while(true)`、TS `@ts-ignore`/`@ts-nocheck`、Rust `unsafe`/`transmute`/FFI、C# 空 `catch`/`.Result` 阻塞；嵌入式 `_ISR_BLOCKING_CALLS` 扩展 `delay\w*`。

### 约束注入自动分档（Token 经济化）

`inject_constraints` 按项目复杂度自动分档：常规任务 → `checklist`（轻量，Token 净节省 ~50%），复杂任务（源码文件 >50 / 存在架构蓝图 / 分层目录 ≥3）→ `prompt`（完整架构全景）。CLI `--format` 默认值统一为 `checklist`。

## v2.2.0 新增能力

### C 方言分流（通用 C/C++ vs 嵌入式 C）

**核心问题**：通用 C/C++ 与嵌入式 C 虽同用 C 语言，但规则集本质冲突（通用允许 new/递归/goto，嵌入式 MISRA 硬禁 malloc/递归/goto），混用同一套规则会双向误报。

**解决方案**：在文件分类层自动分流，各走各的规则集与阈值：

| 方言 | 判定信号 | 规则集 | 阈值 |
|------|---------|--------|------|
| `generic` | 默认（无嵌入式信号） | 函数级圈复杂度 + 参数 + 嵌套 + 安全 | 全局金级 |
| `embedded` | RTOS 头/ISR 定义/寄存器宏/链接脚本/裸机操作 | MISRA C:2012 子集 + ISR 安全 + volatile + 栈深度 + 递归/goto/动态内存禁用 | 独立模块常量 |

**显式覆盖**：`.code-guardian/rules.json` 的 `_c_dialect` 字段（`auto`/`generic`/`embedded`）。

**新模块**：
- `quality_c_dialect.py` — 方言分类器（O(n) 单次扫描）
- `quality_embedded.py` — 嵌入式专用检测（7 类规则）
- `rules/misra-c-rules.json` — MISRA C:2012 子集声明式清单

**架构检测修复**：补 C/C++ `#include` 提取 + 嵌入式分层映射（HAL/BSP/Driver→infrastructure，App/Task→application），消灭此前 C 文件静默跳过依赖图的伪覆盖。

## v2.0.14 新增能力

### 蓝图生成与上下文压缩
- **blueprint_generator.py**: 从代码库自动生成 `architecture_blueprint.json`，提取模块结构、依赖图、公共 API、嵌套深度
- **blueprint_schema.py**: 定义蓝图的完整 JSON Schema + Pydantic 运行时校验
- **context_compressor.py**: L0-L3 四层上下文压缩，对抗"Lost in the Middle"效应
- **impact_analyzer.py**: 变更影响分析，支持函数签名变更/文件移动/全局变量/模块依赖四维分析
- **dashboard_generator.py**: 可视化健康看板生成，多维度评分含安全/代码/架构

### 可视化
- 暗色主题健康看板，Canvas 雷达图，三维度评分卡片
- 交互式问题列表（一键修复/查看详情/人工确认）
- 响应式设计，移动端/平板/桌面自适应

## 嵌入式与工具链检测项（全量开放，无版本门控）

以下检测器全部随技能发布，`register_detector(dialect, category)` 注册即生效，**代码层面没有任何版本/授权门控**：

| 检测项 | 实现 |
|---|---|
| MISRA-C 子集：动态内存禁用 / 递归 / goto / ISR 安全 / volatile / 栈深度 | `quality_embedded.py`（6 个 detector） |
| ISR 优先级分组 / 看门狗喂狗 / 电源管理（WFI/WFE） | `quality_embedded.py`（Phase 3 扩展） |
| 启动文件（`startup_*.s`）向量表 / 栈堆配置 | `quality_startup.py` |
| 链接脚本（`.ld`）RAM/Flash 与段布局 | `quality_linker.py` |
| Makefile/CMake 交叉编译 / LTO / 警告配置 | `quality_toolchain.py` |
| Hex/Bin 产物校验（校验和 / 向量表偏移） | `quality_artifact.py` |
| Rust embedded 方言（`no_std` / `cortex_m` / `embedded_hal`） | `quality_c_dialect.py` |
| 飞控硬件（引脚 / 串口 / 刷新率 / 状态机） | `fc-guardian` 技能 |

### 检测器插件架构

所有检测器通过 `@register_detector` 装饰器自注册到 `detector_registry.py`：

```python
from detector_registry import register_detector

@register_detector("embedded", "isr")
def _check_isr_priority(file_path, content, findings):
    # 检测逻辑
    return findings
```

新增检测器只需编写函数 + 加装饰器，无需修改编排逻辑。

**差异化价值**: 实证数据显示 AI 辅助编程导致代码返工率上升 39%（GitClear 2025），CodeGuard 通过"生成前约束注入 → 生成后门禁验证"闭环将返工率降低 60% 以上。

---

## AI 调用指南

### 可用脚本

| 脚本 | CLI 签名 | 用途 |
|---|---|---|
| `quality_check.py` | `python quality_check.py [--path .] [--mode {personal\|team\|diff\|test-coverage}] [--coverage-threshold 80] [--format {json\|text}]` | 全量/增量质量检测入口，退出码 0=PASS/1=WARN/2=BLOCK |
| `blueprint_generator.py` | `python blueprint_generator.py --path . --output blueprint.json [--incremental] [--no-validate] [--summary-only]` | 从代码库生成架构蓝图 JSON |
| `blueprint_schema.py` | `python blueprint_schema.py <blueprint.json>` | Pydantic 运行时蓝图校验 |
| `constraint_injector.py` | `python constraint_injector.py [--path .] [--format {json\|text\|prompt\|checklist}]` | 提取架构约束生成 AI prompt 注入文本 |
| `context_compressor.py` | `python context_compressor.py --action {generate-all\|generate-l0\|get-context\|refresh} [--project .] [--module M] [--task T]` | L0-L3 分层上下文压缩 |
| `impact_analyzer.py` | `python impact_analyzer.py --action {analyze\|file-move\|global-var\|module-dep} [--file F] [--function F] [--change C]` | 四维变更影响分析 |
| `dashboard_generator.py` | `python dashboard_generator.py [--project .] [--blueprint PATH] [--codeguard-output PATH] [--output dashboard.html] [--watch]` | 生成可视化健康看板 |
| `quality_coverage.py` | `python quality_coverage.py [--path .] [--threshold 80] [--format {json\|text}]` | 测试覆盖率门禁 |
| `module_health.py` | `python module_health.py --blueprint blueprint.json [--focus all\|orphans\|utilization\|bloat\|hotspot\|dead-code\|clones\|shared] [--format text\|json] [--max-files 10] [--max-lines 2000] [--since-days 90] [--project-root .] [--codeowners PATH]` | 模块健康分析 v1.3.0：孤儿/利用率/膨胀/热点/dead-code 死代码/CODEOWNERS 集成/AST 语义克隆+复用建议 |
| `api_compatibility.py` | `python api_compatibility.py --old v1.json --new v2.json [--format markdown\|text\|json] [--output report.md]` | API 破坏性变更检测：前后蓝图 public_api diff → 兼容性报告 |
| `mcp_server.py` | `python mcp_server.py --project-root .` | MCP JSON-RPC 2.0 stdio 服务 |

### MCP 工具（通过 mcp_server.py 暴露）

| Tool 名 | 入参 | 出参 | 用途 |
|---|---|---|---|
| `review_file` | `file_path` (必填), `mode` (personal/team) | issues 列表 + summary + exit_code | 单文件质量检测 |
| `review_diff` | `project_root` (必填), `mode` (personal/team) | issues + summary + exit_code | Git 变更增量检测 |
| `execute_rules` | `project_root` (必填) | total_rules + industry + gate_level + profile_path + rules 列表含 severity/confidence | 列出所有活跃规则 (含行业规则集 v3.0.0) |
| `inject_constraints` | `project_root` (必填), `format` (prompt/checklist/json，省略时自动分档), `file_type` (source/test/config/generated/migration/doc) | format + content + project_type + file_type + auto_tiered | 生成架构约束注入文本（v3.0.0 自动分档 + 文件类型差异化） |
| `get_industry` | `project_root` (必填) | industry + gate_level + profile_path + industry_rules_count + thresholds_applied | 查询项目行业维度配置 (v3.0.0) |

### 跨 SKILL 接口

| 方向 | 项目 | 格式 | 消费方 | 推荐顺序 |
|---|---|---|---|---|---|
| **输出** | `architecture_blueprint.json` | Blueprint Schema | governance-hub (tag_manager/risk_gate), project-manager (template_engine/refactor_queue) | 步骤1-产出 → 步骤2/3 入口 |
| **输出** | `scan_results` (collector.summary + issues) | IssueCollector 格式 | governance-hub (risk_gate 分级), project-manager (refactor_queue 入队) | 步骤1-产出 → 步骤2 分级 |
| **输出** | 模块健康报告 (`module_health.py --format json`) | JSON（利用率/孤儿/膨胀/热点/死代码/克隆） | project-manager (refactor_queue 入队), dashboard_generator (看板集成) |\n| **输出** | API 兼容性报告 (`api_compatibility.py --format markdown`) | Markdown breaking changes 报告 | governance-hub (发布门禁), project-manager (规划输入) | 步骤1-产出 → 步骤3 评估 |
| **输入** | 风险分级结果 | governance-hub/risk_gate JSON | 分级修复决策 (auto/confirm/manual) | 步骤2-依赖 ← 步骤2 返回 |
| **输入** | 快照对比结果 | governance-hub/snapshot_manager JSON | 门禁判断 (approve/reject) | 步骤2-依赖 ← 步骤2 返回 |
| **输入** | 设计意图保护记录 | governance-hub/intent_protection.json | 扫描时自动 skip/downgrade 保护项 | 步骤2-依赖 ← 步骤2 过滤 |

---

> 以下为原有内容（v2.0.12），新能力已在 `scripts/` 目录中实现。

## 版本历史

> 变更史**只放这里**，不写进 description（description 只承载「是什么 + 触发条件」，
> 写了变更史会白占常驻 token 且对触发毫无帮助）。

| 版本 | 变更 |
|---|---|
| v3.1.0 | **新增模块化与接口设计维度**：`quality_modular.py` 9 条规则（跨模块硬编码、私有符号越界、同名脚本歧义、缺接口文档、无超时、测试未分层、无契约校验、无依赖锁定、版本浮动），规则统一登记在 `quality_rule_registry.RULE_SPECS` 供三层防线共用；新增 `tests/test_modularity.py` |
| v3.0.0 | 新增行业分离：Web/云、嵌入式、安全关键三行业规则集自动切换 |
| v2.2.1 | 新增函数级圈复杂度/嵌套检测 + 语言专属规则（消除文件级累加误报）+ 约束注入自动分档 |
| v2.2.0 | 新增 C 方言分流：通用 C/C++ 与嵌入式 C（MISRA/ISR/volatile/栈深度）在文件分类层自动分流 |

### 置信度评分口径

| 区间 | 依据 |
|---|---|
| 90-100 | AST 精确分析 |
| 80-89 | 剥离注释/字符串后的正则 |
| 70-79 | 原始正则 |
| 60-69 | 启发式 |
