# Token 成本与缓存经济学

> 本文件回答：**这套 Skill 体系的 token 花在哪里、缓存命中率怎么来的、如何在不为省 token 而牺牲质量的前提下降低成本。**
> 只在做 token 优化或改造 Skill 结构时加载。

## 1. 先看钱花在哪：三层加载模型

Skill 体系的 token 分三层，**只有前两层进上下文，第三层永不进**：

| 层 | 本仓库实测 | 何时进上下文 | 缓存特性 |
|---|---|---|---|
| **① description** | 7 个 Skill 合计 **2,782 字符** | **常驻**（system 层的技能清单） | 属 system 层，是整个缓存的**最前段**；命中时按 0.1x 计费 |
| **② SKILL.md** | 7 个合计 **53.0 KB** | 触发该 Skill 时 | 追加进 messages，成为后续轮次的缓存前缀 |
| **③ references** | 7 个合计 **565.8 KB** | 按需读取 | 同上，但**可选择性加载** |
| **④ scripts** | 7 个合计 **1,332.6 KB** | **永不**（被执行而非阅读） | 不占 token —— 这是最便宜的地方 |

各 Skill 体积分布（bytes）：

| Skill | SKILL.md | references | scripts | 脚本数 | ref 数 |
|---|---:|---:|---:|---:|---:|
| CodeGuard | 14,466 | 7,828 | 501,429 | 61 | 1 |
| easyeda-agent | 7,448 | **413,538** | 97,740 | 12 | **23** |
| embedded-flow-guardian | 6,722 | 100,035 | 177,949 | 13 | 9 |
| fc-guardian | 4,541 | 0 | 29,851 | 7 | 0 |
| governance-hub | 7,277 | 3,686 | 250,266 | 36 | 1 |
| iac-guardian | 4,926 | 4,294 | 107,892 | 11 | 1 |
| project-manager | 8,892 | 50,018 | 199,495 | 23 | 7 |
| **合计** | **54,272** | **579,399** | **1,364,622** | 163 | 42 |

粗算 token（中文重文本约 **tokens ≈ bytes / 3.5**，仅作量级参考）：
常驻 ≈ 0.8k · SKILL.md 合计 ≈ 15k · references 合计 ≈ 165k · scripts ≈ 390k（不进上下文）。

> **最重要的结论**：**常驻成本只有约 0.8k token**，非常健康。
> 真正的风险不在常驻，而在 **references 的滥用**——`easyeda-agent` 一家 413 KB（23 个文件），
> 若一次批量读取，单次就可能吃掉十几万 token。

## 2. 缓存机制：前缀匹配，改前面就废后面

（以下为 Anthropic/OpenAI/Gemini 官方文档与工程实践的一致结论）

| 事实 | 内容 |
|---|---|
| **匹配方式** | **前缀精确匹配（byte-for-byte）**，必须从头开始一致 |
| **层级** | `tools → system → messages`；改动某一层会使其**及其之后**全部失效 |
| **改动工具定义** | **使整个缓存失效**（tools + system + messages） |
| **最小可缓存长度** | **1,024 token**（Claude Haiku 3.5 为 2,048）；低于门槛缓存无效 |
| **TTL** | 默认 **5 分钟**，每次命中自动续期；可配 1 小时 |
| **计费** | 缓存**读 0.1x**；5 分钟**写 1.25x**；1 小时**写 2x** |
| **盈亏平衡** | 5 分钟缓存**被读 2 次即回本**；1 小时缓存需 **≥3 次** |
| **断点上限** | 最多 **4 个** cache breakpoint |
| **延迟加载工具** | **`defer_loading` 的工具不进 system 前缀**，发现时以 `tool_reference` 追加到对话历史 → **加工具不破缓存** |

**会打断缓存的常见操作**

| 操作 | 后果 |
|---|---|
| 改 description / system 指令（哪怕一个词） | 该层及其之后全部失效 → 下次请求全量重算 |
| 增删/修改工具定义 | **整个缓存失效** |
| 中途切换模型 | 全会话失效（模型特定指令在前缀里） |
| 在靠前位置写入时间戳 / 请求 ID | 每次请求都 miss —— **最常见的缓存杀手** |
| 工具列表枚举顺序不确定 | 前缀字节不一致 → 每次都 miss |
| 重排或重写历史 | 只能追加（append-only）；改写早期内容即失效 |
| TTL 过期 | 低流量场景常见：请求间隔 > 5 分钟即 miss |

**工程界的一致结论**：Manus 称「KV-cache 命中率是生产级 agent **最重要的单一指标**」，Claude Sonnet 上读/写价差 **10 倍**；有研究（*Don't Break the Cache*，2026）报告 agent 负载总成本可降 **41–80%**。这**不需要牺牲质量**——它是纯工程结构问题。

## 3. 本项目的缓存诊断

**有利因素（已经做对的）**

1. **渐进披露**：SKILL.md 只做路由，细节全放 references —— 与官方 `defer_loading` 的思路一致：**按需内容不进前缀，加内容不破缓存**。
2. **references 顶部标注「何时加载」** —— 抑制无脑全读。
3. **scripts 不进上下文**（163 个脚本、1.33 MB 零 token 成本）。
4. **常驻只有 0.8k token**，且 description 稳定（不随会话变化）。

**风险点（需约束）**

| # | 风险 | 影响 | 约束规则 |
|---|---|---|---|
| 1 | **改 description / SKILL.md** | system 层在最前，改了会废掉后续**全部**缓存 | **批量改，不要频繁小改**；结构性变更集中在会话开始前完成 |
| 2 | **references 批量读取** | 单次可能吃十几万 token（easyeda-agent 413 KB） | **一次只读一个文件**；禁止 `cat references/*` |
| 3 | **重复读取 / 重排 references** | 同一会话内重读旧文件会改写前缀 → miss | **只追加、不回头**；需要回顾时引用已有结论而非重读原文 |
| 4 | **SKILL.md 里写不稳定的细节** | 实现一变就要改 SKILL.md → 破缓存 | SKILL.md 只放稳定契约（命令、路由、原则）；易变细节进 references |
| 5 | **单个 description 低于 1,024 token** | 单独缓存门槛不够 | 靠**整体前缀**缓存，别指望单个描述被独立缓存 |

## 4. 可执行的省钱规则（不牺牲质量）

**规则 1 —— 批量改元数据，不做碎改**
Skill 的 description / SKILL.md 变更会触发全量缓存重建。
→ 攒一批一起改。本次升级（5 个折叠标量 + 6 个 agent_created + 4 个版本号）就是一次批量，**好过 15 次零散提交**。

**规则 2 —— references 严格单文件按需加载**
```bash
# 对
读 references/registry.md
# 错（可能十几万 token，且把缓存前缀拉得极长）
cat references/*.md
```

**规则 3 —— 只追加，不回读**
一旦某文件已进入本次会话前缀，**不要重复读取或重排顺序**。
需要复述时用已有结论，不要重新加载原文。

**规则 4 —— 易变内容不要写进常驻层**
判定规则、阈值、工具清单这类会演进的内容放 references 或配置（`.ef-guardian.json`），
SKILL.md 只写稳定契约。这样**改实现不必改 SKILL.md**，缓存前缀保持稳定。

**规则 5 —— 不要为本省 token 而牺牲正确性**
官方指引明确：*Never keep stale instructions merely because changing them would invalidate a cache.*
正确性优先。本次修掉「文档目录被误排除」的 bug 虽然改变了扫描结论，但它是必须修的。

**规则 6 —— 监控这个比值**
有 API 用量字段时看 `cache_read_input_tokens / total_input_tokens`。
本仓库没有 API 计量，用**可测代理指标**代替：

```bash
python audit_skills.py          # 输出各 Skill 的 SKILL.md / references / scripts 体积
python scripts/ef_dev.py registry verify   # 注册项完整性（间接反映是否有人乱塞工具）
```
**报警信号是量级变化**，不是绝对值：某次改动后常驻字符数或 SKILL.md 体积突然翻倍，才是问题。

**规则 7 —— 新增能力先问「该放哪一层」**

| 内容 | 该放 |
|---|---|
| 每次都要用的稳定契约（命令、边界、原则） | 常驻 description / SKILL.md |
| 特定场景才需要的知识 | references（按需单读） |
| 确定性逻辑 | scripts（零 token） |
| 项目特定值 | 项目根配置 `.ef-guardian.json`（不占 Skill 体积） |
| 一次性/机型专用工具 | 工程内 + 注册表登记（**不进 Skill**） |

## 5. 一句话总结

**常驻 0.8k、SKILL.md 15k、references 165k、scripts 0 —— 结构本身是健康的。**
真正的成本杠杆只有两个：**① 别频繁改常驻层（缓存前缀）；② 别批量读 references。**
两者都**不需要牺牲任何质量**。
