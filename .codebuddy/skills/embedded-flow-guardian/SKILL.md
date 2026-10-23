---
name: embedded-flow-guardian
description: 嵌入式研发流程守护与工作台 Skill（v1.3.1）。双角色：(1) 流程审计——检测交付物完整性（需求规格、ICD、RTM、硬固件兼容矩阵、变更记录、准出清单）、需求双向追溯、硬件-固件版本绑定、变更管理、发布准出与可复现构建、工程自动化基线；(2) 日常工作台——Keil 自动编译与烧录（工程自动发现、版本头注入、日志解析）、串口枚举与探测、只读监听、CSV 采集（旁车元数据、断线重连）、采集数据分析（统计、分箱、FFT 频谱、异常段、PNG 出图），并通过工具注册表统一调用通用能力与项目专项工具。内置嵌入式开发与管理经验知识库与交付物模板。当用户请求检查嵌入式项目研发流程与交付物、需求追溯、版本绑定、变更留痕、发布准出，或请求编译/烧录 Keil 工程、查找并读取串口、采集与分析飞控遥测，或提及 ICD、RTM、需求追溯矩阵、兼容矩阵、准出清单、可复现构建、串口采集、遥测分析、振动频谱时应触发。纯 Python 标准库实现（自实现 FFT 与 PNG 编码器，串口走 ctypes），零第三方依赖。
agent_created: true
---

# embedded-flow-guardian — 嵌入式研发流程守护与工作台（v1.3.1）

## 定位：双角色

```
① 流程审计   交付物齐不齐 / 追溯成不成立 / 发布有没有依据   →  ef_scan.py
② 工作台     编译烧录 → 串口采集 → 数据分析               →  ef_dev.py
```

> 模块化与接口设计检测由 **CodeGuard**（`quality_modular.py`）负责 —— 那是它的核心使命
> 「防止 AI 生成代码沦为死山代码」。本 Skill 不重复实现。

**与既有 SKILL 的边界**（不修改任何既有 SKILL 文件，仅只读复用 CodeGuard 的 IssueCollector）：

```
CodeGuard        → 代码层（复杂度/重复/安全/嵌入式规范 9 项）
fc-guardian      → 飞控硬件层（引脚/串口/刷新率/状态机/飞控安全）
iac-guardian     → 基础设施层（Terraform / K8s）
governance-hub   → 发布治理层（需求关联率/迁移回滚/成本基线）
project-manager  → 队列与看板
本 SKILL          → 流程交付物层 + 日常工具链层
```

## 工具管理原则（重要）

**通用能力进 Skill；项目专项工具留在工程内，经注册表统一调用。**

- 通用代码中**不得出现任何项目特定值**（目录名、串口号、字段数、参考树路径）
- 项目值一律声明在项目根的 `.ef-guardian.json`
- 项目专项工具（机型专用验证、电机映射等）由注册表自动扫描登记，并标注
  **可移植性原因**与**安全分级**（`R` 只读 / `W` 会写文件 / `!!` 驱动执行机构）
- 详细规范见 `references/registry.md`

## 快速开始

```bash
# 工具一览与统一调用（先跑这个，避免重复造轮子）
python scripts/ef_dev.py registry list
python scripts/ef_dev.py registry list --nonportable
python scripts/ef_dev.py registry run <tool-id> -- <args>
python scripts/ef_dev.py registry scan          # 重建登记
python scripts/ef_dev.py registry verify        # 校验路径

# 工作台
python scripts/ef_dev.py discover                         # 工程与 Target/UV4
python scripts/ef_dev.py build --inject-version version.h # 编译 + 版本注入
python scripts/ef_dev.py flash                            # 编译 + 烧录
python scripts/ef_dev.py ports                            # 枚举串口
python scripts/ef_dev.py watch                            # 只读监听
python scripts/ef_dev.py capture --out data/run1.csv      # 采集（带元数据）
python scripts/ef_dev.py analyze data/run1.csv --bin <油门列>   # 统计/FFT/异常段

# 流程审计
python scripts/ef_scan.py --path .              # 退出码 0=PASS / 1=WARN / 2=BLOCK
python scripts/ef_scan.py --path . --level gold
```

## 路由表

**references/**（按需加载，**不要一次全读**）

| 文件 | 何时加载 |
|------|---------|
| `registry.md` | **工具该放哪、怎么统一调用、token 成本纪律** —— 新增工具前必读 |
| `token-economy.md` | **token 花在哪、缓存如何命中、7 条省钱规则** —— 改造 Skill 结构或优化成本时读 |
| `usage.md` | 要跑构建/串口/分析时；含模块约束、零依赖说明、8 条已知陷阱 |
| `lifecycle.md` | 设计或评审研发流程；五种范式、十阶段产物、验证阶梯 MIL→SIL→SITL→HIL |
| `management.md` | 排期/估算/需求/团队问题；含 CHAOS 报告的否证与度量失效 |
| `engineering-practice.md` | 分支策略（git-flow 作者反思原文）、评审基准、CI/flaky、文档 |
| `embedded-field.md` | 调试、Heisenbug、可观测性、NFF 统计、技术债、嵌入式估算 |
| `anti-patterns.md` | **评审/复盘/方案对比首选**：做/不做对照清单 |
| `compliance.md` | 面向车规/工业/医疗/航空客户；ISO 26262 / DO-178C / ASPICE 强制产物 |
| `sources.md` | **引用任何数据前必查**：可信度分级与存疑条目黑名单 |

**assets/templates/**：`ICD_template.md` · `RTM.csv` · `compat_matrix.csv` · `change_log.csv` ·
`release_checklist.md` · `ADR_template.md` · `gitattributes_template.txt` · `ef-guardian.json`

**scripts/**：`ef_scan` + 6 个流程检测器 · `ef_build` · `ef_serial` · `ef_analyze` ·
`ef_dev`（工作台入口）· `ef_registry`（注册表）· `ef_common`（共享层，含配置访问器）

## 配置（项目根 `.ef-guardian.json`）

项目特定值集中于此；缺省时工具退化为最保守的通用行为（**不猜测**）：

```json
{
  "defaultLevel": "silver",
  "corePaths": ["<核心固件目录>"],
  "moduleLevels": { "<核心目录>/**": "gold", "<测试目录>/**": "silver" },
  "excludePaths": ["<第三方参考代码树>/**"],
  "preferredPorts": ["<COMx>"],
  "telemetryFields": 27
}
```

`corePaths` 会自动展开为 gold 门禁规则；显式 `moduleLevels` 优先。
未配置 `preferredPorts` 时不会猜端口——仅当存在唯一可用端口才自动选用，
使"选错端口"成为显式错误而非静默行为。模板见 `assets/templates/ef-guardian.json`。

## 版本历史

| 版本 | 变更 |
|------|------|
| v1.0.0 | 首版：6 个流程检测器 + per-module 门禁分级 + 知识库 + 交付物模板 |
| v1.1.0 | 新增工作台：`ef_dev` / `ef_build`（Keil 编译烧录与版本注入）/ `ef_serial`（零依赖串口）/ `ef_analyze`（自实现 FFT 与 PNG） |
| v1.2.0 | **工具管理规范化**：新增 `ef_registry` 工具注册表（通用/项目专项分层、可移植性证据判定、安全分级、统一调用）；项目特定值全部移出通用代码改为配置驱动；详细内容移入 `references/usage.md`、新增 `references/registry.md`，SKILL.md 瘦身为路由 |
| v1.3.0 | **性能与正确性修复**：遍历改为 `os.walk` 阶段剪枝（`ef_scan` 18s→0.88s、`registry scan` 480ms→140ms）；修复 `文档/` 被误当 vendor 排除导致 ICD 等交付物漏检的 bug；`_detect` 加文件列表缓存 + 子串预筛（正则调用 78k→大幅下降）；新增 `references/token-economy.md`（缓存机制与 7 条省钱规则） |
| v1.3.1 | **通用化清理**：把示例/提示文本中的本项目真实值（项目路径、串口号、工程名）统一替换为占位符；`PROJECT_DIR_WORDS` 标注为通用启发式清单。功能零变更 |
