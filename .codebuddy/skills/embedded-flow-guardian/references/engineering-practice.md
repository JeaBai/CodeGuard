# 工程实践（工程师视角）

> 本文件是「分支/评审/CI/文档/时间」的一线实操经验与踩坑记录。
> 标注 `[A]` 同行评议/官方 · `[B]` 专业机构/从业者一手 · `[C]` 社区/厂商。完整来源见 `sources.md`。

## 1. 分支策略：按软件类型选，而不是选「标准」

### 1.1 git-flow 作者本人的反思（已逐字核实）

Vincent Driessen 于 **2020-03-05** 在原文顶部补记 Note of reflection：

> *"This model was conceived in 2010... In those 10 years, git-flow... has become hugely popular... but unfortunately also as a **dogma or panacea**."*
>
> *"**If your team is doing continuous delivery of software, I would suggest to adopt a much simpler workflow (like GitHub flow) instead of trying to shoehorn git-flow into your team.**"*
>
> *"**If, however, you are building software that is explicitly versioned, or if you need to support multiple versions of your software in the wild, then git-flow may still be as good of a fit to your team as it has been to people in the last 10 years.**"*
>
> *"To conclude, always remember that **panaceas don't exist**. Consider your own context. Don't be hating. Decide for yourself."*

**关键边界**：他**没有**否定 git-flow。明确保留「显式版本化 / 需支持多个在野版本」的场景——**这恰恰是固件的典型场景**。因此「git-flow 已死」是过度解读，正确结论是**按软件类型选**。

同时：Atlassian 官方 Git 教程自 **2021 年 8 月**起把 git-flow 描述为 **"a legacy workflow"**。

### 1.2 DORA 的可检验阈值（比「应该用 TBD」有用）

- 仓库里**活跃分支 ≤ 3 个**
- **每天至少合并到 trunk 一次**
- **没有 code freeze 和集成阶段**
- 分支/fork 生命周期 **< 1 天**

DORA 明确指出常见障碍是「过重的代码评审流程要求多次批准」——**如果评审延迟以天计，「每日合并」在算术上就不可能实现**。且 DORA 结论：**速度与稳定性不是 trade-off**，顶级团队在吞吐和稳定性上同时表现好。

### 1.3 嵌入式特有的三个真问题

| 问题 | 实践做法 |
|---|---|
| **多硬件版本** | 五分支隔离模型：`main`（量产基线，禁止直接改）、`develop`、`feature/*`、`hotfix/*`（从 main 拉出，修完**双向合并**回 develop），以及嵌入式独有的 **`hardware/vx.x`**（隔离不同硬件版本的引脚/时钟/外设适配）。命名如 `hw/rev-3.0` |
| **二进制产物** | 用 **Git LFS**，不要裸塞。真实案例：某传感器固件团队从共享网盘（文件名形如 `Firmware_v2.3_final_FINAL_johns_fix.zip`）迁到 Git + LFS + submodule 后，**克隆体积从 1.8GB 降到 45MB**。坑点：CI runner 必须先 `git lfs install`，否则 LFS 文件被检出为指针文本 |
| **Tag 与版本绑定** | 每个出厂 BIN/HEX 唯一对应一组源码版本。提交信息建议含硬件影响：`fix: 修复UART驱动在STM32F407 RevB上的DMA异常 影响:硬件RevB 内存变化:+128 Bytes` |

**提交粒度**：一个 commit = 一个逻辑变更；**如果描述里需要用「and」连接，就该拆**。写 "why" 而非 "what"。

## 2. 代码评审

### 2.1 规模基准（SmartBear / Cisco，2,500 次评审、320 万行代码）

| 指标 | 建议值 |
|---|---|
| 单次评审代码量 | **< 200–400 LOC**（超过 400 行后缺陷密度接近 0） |
| 检视速率 | **< 300–500 LOC/小时** |
| 单次时长 | **60–90 分钟以内** |
| 收益 | 轻量评审平均每次评审省 **6.5 工时** |

Cisco 研究：**轻量评审的缺陷检出速度是重量级正式审查的约 7 倍**。

### 2.2 Google 基准（Sadowski et al., ICSE-SEIP 2018；900 万次已评审变更）

| 指标 | Google 数值 |
|---|---|
| 变更规模（中位） | **24 行**；>35% 只改 1 个文件 |
| 评审者数量 | **约 75% 的变更只需 1 名评审者** |
| 首次反馈速度 | 小变更 **< 1 小时** |
| 全流程时长（中位） | **< 4 小时**（对比 Microsoft 中位批准 14.7–24 小时） |
| 评论密度 | 约 **1 条评论 / 100 行** |

**关键洞见**：Google 认为评审首要目标**不是找 Bug**，而是「**确保每段代码至少两个人理解它**」。

### 2.3 被高估的缺陷检出（Bacchelli & Bird, ICSE 2013）

> 约 **44%** 的人把「发现缺陷」列为首要动机，但实际评论中**只有 14% 与缺陷相关**；29% 是「代码改进」，18% 是澄清性问题，15% 是替代方案讨论。且缺陷类评论主要覆盖「微小低级逻辑问题」——**宏观设计问题很少在评审中被发现**。

### 2.4 正反对照

- ✅ **有效**：小 PR（≤200–400 行）、快反馈（小时内）、多数变更单人评审、评审聚焦「为什么」、**把风格交给自动化（linter/formatter）以释放人力看逻辑**。
- ❌ **被证伪**：以缺陷数考核评审者；要求所有变更两人批准；用 LGTM 数量当「评审已发生」的证据；在 PR 已「木已成舟」后才评审。

**橡皮章检测启发式**：`(批准时间 − 被指派时间) < (改动行数 / 200) 分钟` → 疑似橡皮章。400 行 2 分钟批准不是评审。

## 3. CI 与自动化

### 3.1 Flaky test 的真实代价（已逐字核实，Google Testing Blog，2016）

> *"We define a 'flaky' test result as a test that exhibits **both a passing and a failing result with the same code**."*

| 数字 | 原文 |
|---|---|
| **1.5%** | "a continual rate of about **1.5% of all test runs** reporting a 'flaky' result" |
| **≈16%** | "**Almost 16% of our tests have some level of flakiness**... **more than 1 in 7** of the tests written by our world-class engineers occasionally fail" |
| **≈84%** | "about **84% of the transitions** we observe from pass to fail involve a flaky test" |
| **≈15 条** | "the average project contains 1000 or so individual tests. If 1.5% of test results are flaky, **15 tests will likely fail**" |

**最具启发性的一点——显而易见的缓解手段有反效果**：

> 「把测试标记为 flaky、只在连续失败 3 次时才报警」这个做法 *"**encourages developers to ignore flakiness in their own tests**"*；一个 15 分钟的集成测试若被真的改坏，要等 3 次执行（**45 分钟**）才发现。

**横向参照**：Microsoft 研究显示五个项目约 **4.6%** 的测试是 flaky。

### 3.2 Jenkins 的维护成本

- 「Maintenance Nightmare」：插件更新**经常把流水线弄坏**。
- **迁移判据（可直接用）**：「当维护占用某位 DevOps 工程师**超过 20% 的时间**、开发者每周抱怨 CI 可靠性超过一次、或要启动不需遗留流水线的新项目时，就该从 Jenkins 迁走。」
- 最扎心的总结：*「成功用 Jenkins 的团队把它当作**需要真实预算供养的自有基础设施**；失败的团队把它当成**应该自己一直跑下去的东西**。」*

### 3.3 构建时间的隐性影响

- **10 分钟阈值**：超过约 10 分钟开发者就会去做别的；中断后**平均需 23 分钟**才能完全回到任务。**超过 20 分钟，就「还有流水线，但不再有真正意义的持续集成」。**
- Google 内部目标：**90% 的构建在 5 分钟内完成**。
- 开发者**平均每天花 57 分钟等构建**（Incredibuild 自有调研）。

### 3.4 嵌入式 CI 与 Web CI 的差异

| 差异点 | Web CI | 嵌入式 CI |
|---|---|---|
| 工具链 | `npm install` | 需交叉工具链，**必须容器化并固定版本** |
| 运行环境 | 云 VM 干净启动 | 云 VM **无法插 USB**，必须自建 runner |
| 测试终点 | 逻辑正确即通过 | 定时器精度、GPIO/SPI/I2C、BLE 射频、DMA、中断时序**只能在真实板卡验证** |
| 失败性质 | 多为逻辑/异步 bug，改代码可解 | 常由物理环境造成（供电波动、温度、EMI），**改代码不可解** |
| 制品 | KB 级 JS | ELF/镜像 MB 级 + 签名 + SBOM |

### 3.5 可复现构建

> **原则**：**「没被重建两次并 diff 过的一致性，只是一个声明，不是属性。」**

**真实失败案例**：某工业控制器项目已容器化并接入 CI，但**同一 release tag 三次干净重建产出三个不同二进制**。原因：①Dockerfile 用包管理器装工具链且未固定版本；②固件内嵌 `__DATE__` 与绝对构建路径；③部分 `SRCREV` 未固定。更隐蔽的问题：**HIL 阶段写在托管 runner 上、根本没有连接目标板，几个月来一直是空跑，流水线还在「报告覆盖率」**。

**四个必做项**
1. **固定所有输入**：工具链按镜像 digest 固定、依赖走带哈希的 lockfile、`SRCREV` 固定到 commit。工具链变更必须是「一次被评审的提交」。
2. **设置确定性变量**：`SOURCE_DATE_EPOCH`、`-ffile-prefix-map` / `-fdebug-prefix-map`、`PYTHONHASHSEED=0`、`TZ=UTC`。
3. **验证而非假设**：同一 commit 在两台机器各构建两次并 diff 哈希；用 `diffoscope` 定位残余差异。
4. **产出 SBOM** 并绑定到确切二进制。

### 3.6 正反对照

- ✅ **有效**：门禁只拦**快且确定**的信号（单测、lint/format、类型检查、依赖与密钥扫描）；慢/天然 flaky 的全部**移到 merge 之后**跑。flaky 用**自动隔离（quarantine）**——非确定失败的测试自动移出阻塞路径 + 开单 + 限时修复/删除。
- ❌ **被证伪**：「门禁一切」→ 流水线又慢又 flaky → 工程师学会「红≠坏」→ 失败默认重跑不排查 → **门禁沦为剧场**：拖慢一切却什么都抓不到。
- ❌ **被证伪**：让团队「更认真对待失败」（对已被证明不可靠的信号投入注意力，在激励上必输）。
- ✅ **门禁必须基于增量指标**：新代码覆盖率 ≥80%、新代码重复率 ≤3%、新增 Blocker/Critical = 0。**只看全仓库绝对覆盖率 = 在历史代码上永久卡住流水线。**

## 4. 文档

### 4.1 自文档化代码的边界

Coding Horror 的结论即标题：**"Code Tells You How, Comments Tell You Why"**

> *"it's impossible for code to be **completely** self-documenting... **Code can't explain why** the program is being written, and the rationale for choosing this or that method."*

Kevlin Henney 的判据：*"a comment is of **zero (or negative) value if it is wrong**"*——错误/噪声注释会训练程序员**整体忽略注释**。

### 4.2 ADR（架构决策记录）

Michael Nygard 原文定义（2011-11-15）：

- 是「**a short text file**」，五段式：**Title / Context / Decision / Status / Consequences**
- 编号单调递增、不复用；被推翻的标 `superseded` 而不删除
- 原文要求：*"**The whole document should be one or two pages long.** We will write each ADR as if it is a conversation with a future developer."* 且 *"**All consequences should be listed here, not just the 'positive' ones.**"*
- **动机（值得引用）**：不记录理由时新人只有两条路——「**Blindly accept the decision**」或「**Blindly change it**」；「如果项目积累了太多未经理解就被接受的决策，团队会害怕改动任何东西，项目就会被自身重量压垮。」

**现实摩擦（诚实版）**：ADR 在多数团队没落地的原因是**经济性**——写好一份 ADR（尤其记录备选方案）耗时明显，而复利收益被折现掉了。

### 4.3 工程师实际会读什么（一项 600+ 参与者研究）

- 多数开发者**在头文件里找答案**，简单 API 直接读代码
- 部分开发者有「**不信任文档准确性/时效性**」的哲学，宁读代码这个「一手资料」
- 研究建议：**代码简单时不写文档；开发剧烈变化中不写文档；没有资源持续维护时不写文档**
- 数字补充：一项 89 名从业者研究显示 **96% 认可文档价值，但 70% 承认讨厌写**

**文档为什么会烂（正反馈恶性循环）**：文档与现实漂移 → 开发者不再信任 → 更少读 → 团队更少投入。且测试通常是必需的（失败会阻断构建），文档更新却是可选的、常被跳过。

- ✅ **真正被读的**：README（入口）、运行手册（runbook）、架构总览、变更所在处的 why 注释、ADR 的 Context。
- ❌ **没人读的**：比源码字节数还大的规格书、与代码分居不同系统且无 owner 的文档、以及**陈旧的文档（比没有更糟，会误导人和 AI agent）**。

## 5. 时间管理（工程师视角）

**Paul Graham《Maker's Schedule, Manager's Schedule》（2009-07）原文**

> *"**You can't write or program well in units of an hour.** That's barely enough time to get started."*
>
> *"**When you're operating on the maker's schedule, meetings are a disaster. A single meeting can blow a whole afternoon, by breaking it into two pieces each too small to do anything hard in.**"*
>
> *"**For someone on the maker's schedule, having a meeting is like throwing an exception.** It doesn't merely cause you to switch from one task to another; **it changes the mode in which you work.**"*

**级联效应**（原文）：*「如果我预知下午会被打断，我上午就略不愿意开始一件有野心的事。」*

**解法**：把会议聚成 **office hours**，集中在工作日末尾——"these meetings are never an interruption"。

**为什么工程师「看起来很闲但产出很高」**：盯着屏幕不动的那 40 分钟，可能正在做**调试/推理**这类无法被旁观者量化的工作；而一次 15 分钟会议的成本不是 15 分钟，而是「整个下午被劈成两段 + 23 分钟级联恢复」。Graham 的观察：**被中断的创作性工作不只是被慢化，而是错误率更高**。
