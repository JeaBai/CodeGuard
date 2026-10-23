# 管理经验（管理者视角）

> 本文件是「管理者会遇到什么、哪些流行说法已被证伪」的经验汇编。
> 每条结论后标注可信度：`[A]` 同行评议/官方 · `[B]` 专业机构/从业者一手 · `[C]` 社区/厂商（需交叉验证）。
> 完整来源见 `sources.md`。

## 1. 估算：三个流行说法与它们的反证

### 1.1 不要引用「70% 项目失败」

| 流行说法 | 反证 | 等级 |
|---|---|---|
| CHAOS 报告「70% 项目失败」 | Eveleens & Verhoef 用 **5,457 份预测、1,211 个真实项目**复现后结论：*"the Standish figures didn't reflect the reality of the case studies at all"*。归纳其定义四大问题：**误导性、单边性、扭曲估算实践、数字无意义** | `[A]` |
| 「189% 成本超支」 | 同类调查普遍约 **33%**；且该报告称 1998 年超支降到 69%——「4 年内从 189% 降到 69%，这几乎不可能发生」 | `[A]` |
| Cone of Uncertainty「误差随阶段收敛」 | 用 **106 个真实商业项目、3 年每周数据**发现：**不确定性区间在整个项目周期内几乎不变**。且锥体是对称的，但现实是「**几乎总是延期，很少提前**」 | `[A]` |

### 1.2 可用的替代：Reference Class Forecasting（RCF）

- **有效证据**：Edinburgh Tram 2 号线（2004 首次落地）。项目方自报基础成本 £255M + 25% 应急；用 **46 个可比轨道项目**做参照类，结论是总资本成本「更可能是 £357M」，降至 20% 超支风险需 £400M。苏格兰财政大臣因此**公开叫停推进**。英国财政部 2003 年写入 Green Book，丹麦 2006 年强制。
- **被证伪**：丹麦 Signalling Programme **用了 RCF 但仍超支、延期、砍范围**。原因是估算专家本身仍带偏差；且「大家都相信 RCF 优于其他方法」，**外部干系人不再质疑估算**。
- **结论**：RCF 的价值在于「走外部视角」，**不是「用了就准」的免检招牌**。

### 1.3 可引用的分布数据与汇报语言

| 数据集 | 规模 | 结论 |
|---|---|---|
| Flyvbjerg & Budzier, HBR 2011 | 1,471 个 IT 项目 | 平均超支 **27%**；**1/6 是「黑天鹅」**（超支 >200%、延期 70%） |
| Budzier & Flyvbjerg 2013 | 1,355 个公共部门项目 | 典型项目**没有超支**，但工期平均长 **24%**；**18%** 超支 >25%（正态分布下应仅 1%） |
| Flyvbjerg & Gardner 2023 | 16,000+ 项目 | **仅 0.5%** 同时做到按时、按预算、按承诺收益。IT 类平均超支 **+73%**；进入肥尾的 18% 平均超支 **+447%** |

> **Flyvbjerg 的核心判断（建议直接背）**：
> *"We need to dispel the illusion of adequate predictions. IT projects are impossible to predict. Instead, IT project managers should focus their efforts on **prevention**."*

**汇报语言建议**：用**分布语言**（「这类项目 18% 会超支 400%+」）比用**点估计**更诚实。

### 1.4 可引用的替代统计

- NIST Planning Report 02-3（2002）：测试基础设施不足使美国经济年损失约 **595 亿美元**，其中约 **222 亿美元**可通过更早的测试改进避免。
- **不要引用**「IBM 缺陷成本 1-10-100 曲线（100 倍）」——原始研究**不可检索**；Boehm 本人 2001 年表示小规模非关键系统更接近 **5:1**。

## 2. 需求与变更

**失控路径**（航天硬件从业者复盘）与**可执行清单**见 `lifecycle.md` 第 7 节。

**核心结论**：
- 需求「冻结」不是不能改，而是**改的成本被看见**（CR/ECO + CCB + 影响分析）。
- 让 scrum story 事实上承担硬件需求基线是**被证伪**的做法——硬件变更的代价是**不可逆的物理代价**（开模、流片、认证）。

## 3. 跨职能协作的真实摩擦

| 冲突对 | 具体表现 | 等级 |
|---|---|---|
| **固件 vs 硬件（最普遍）** | *"这可能就是项目超支最常见的根因：一群有才华的人并行努力工作，但没有同步。固件等硬件，硬件等固件。所有人都以为别人会兜住。"* | `[B]` |
| **固件作者 vs 芯片厂商** | 向硬件厂商报 bug「可能令人沮丧」，最坏情况是「**问题被否认、被混淆、得不到解决**」；厂商倾向「先给大客户修」 | `[B]` |
| **软件 vs 硬件节奏** | iOS 8 事故：前苹果工程师直言「苹果的软件团队和硬件团队的步调并不一致」；新机发布首月 iOS 8 故障率比 iOS 7 **高 60%** | `[B]` |
| **远程硬件访问** | 调查显示**超过一半**从业者认为远程硬件访问「必不可少」，但**不到 10% 对现有方案满意** | `[B]` |

> **正反对照**
> - ✅ **有效**：设一个专职「胶水」工程师 + 把追溯链做成工程对象（需求↔设计↔测试↔缺陷），让影响分析从「开会问人」变成「在关系图上看范围」。
> - ❌ **被证伪**：靠加会议解决跨职能摩擦。**渠道制度化缺失**时，会议只会放大信息漂移。

## 4. 技术领导者的真实建议（含被证伪的观点）

### Camille Fournier（《The Manager's Path》）

| 观点 | 原文引述 |
|---|---|
| 技术负责人 ≠ 最资深工程师 | *"The idea that the tech lead role should automatically be given to the most experienced engineer... is a common misconception that even experienced managers fall for."* |
| 别把「alpha geek」直接提拔成管理者 | 他们试图建卓越文化，结果建成了恐惧文化 |
| 微观管理的判据 | *"The worst micromanagers are those who constantly ask for the information they could easily get themselves."* |
| 估算口诀 / 排期纪律 | *"take your guess and double it"* / *"As you approach deadlines, it is your job to say no."* |
| 产能基线 | 每位工程师每季度约 **10 个有效工程周**；**不低于 20%** 时间留给通用维护性工程 |
| 失败的真正信号 | **「管理者的真正失败，是团队开始隐藏信息」**——比任何交付延期都更能预测团队崩坏 |

### Charity Majors（honeycomb CTO）

> *"**Management is not a promotion, management is a change of profession.** And you will be bad at it for a long time after you start doing it. **If you don't think you're bad at it, you aren't doing your job.**"*

- 传统假设被逐条否定：「管理是单向旅程、是晋升、钱更多、是唯一影响力来源、最好的工程师会是最好的管理者——**these are all crap**」。
- 关于管理膨胀：**责任不在这些管理者**，而在「没有做出艰难决定、没有进行尴尬谈话、没有让人失望」的总监/VP。

### Will Larson（《An Elegant Puzzle》）——最能落地成数字

| 规则 | 数字 |
|---|---|
| 管理者直接下属 / 管理者的管理者 | **6–8 人** / **4–6 个管理者** |
| 7×24 两级 on-call | **8 名工程师** |
| **快速扩张的产能陷阱** | 新工程师前 6 个月只有 **30% 效能**；每位老工程师每周花 **10 小时**带新人 → 若每人带 2 个，**3 个人的产出只有约 1.16 人份** |
| 组织调整原则 | **"Move scope, not people"** |
| 反模式 | 反对「peanut buttering」（把有限资源平均撒给所有团队） |

### Lara Hogan（《Resilient Management》）

- **BICEPS 六项核心需求**：Belonging / Improvement / Choice / Equality / Predictability / Significance。**一个需求未满足时，人的反应会显得「不合理」。**
- **四种帽子**：mentor（给经验）/ coach（提开放式问题）/ **sponsor（主动争取机会）**/ feedback。
- **反馈三段式**：Observation（不加评判陈述行为）→ Impact（说明影响）→ Question/Request。
- **被证伪**：*"asking 'is there anything I can improve' won't get you the most effective response"*（问得太泛）。

## 5. 度量为什么失效

**Goodhart 定律**：*"When a measure becomes a target, it ceases to be a good measure."*

**被证伪的度量与实际博弈行为**

| 度量 | 团队的实际反应 | 后果 |
|---|---|---|
| 代码行数（LOC） | 冗长代码、不必要的抽象 | 技术债爆炸 |
| 提交次数 | 把每个 PR 拆成 12 个提交 | 历史不可读、评审变慢 |
| Story points | 抬高估算 | 速度数字上升，产出持平 |
| 缺陷关闭数 | 把自己的 bug 标成 "won't fix" | 客户可见缺陷上升 |
| 测试覆盖率 | 写「执行了但不验证」的测试 | 覆盖率 100%，实际质量 0 |
| 部署频率（单用） | 拆成大量无价值小部署 | 故障率静默上升 |

**DORA 指标被误用的三条（对嵌入式尤其相关）**

1. **把指标变成目标**："every team must deploy multiple times per day by Q4" 只会激励作弊。
2. **跨团队横比**：*"A web frontend team will naturally deploy more frequently than ... **a team working on embedded systems**. Comparing them is misleading."*
3. **用在个人绩效考核上**：一旦把部署频率挂到奖金上，开发者会把变更拆成微小 PR 冲合并数。

**度量应该怎么做**
- **成组使用、互为约束**：*"If improving one metric degrades another, you're not actually improving."*
- **用比率而非绝对值**；**加入同伴信号**——"humans are harder to game than numbers"。
- **只用团队/组织级**：DORA 官方指引明确 "Never use SPACE (or DORA) to evaluate individual developers."
- **SPACE 框架**补充 DORA 盲区：Satisfaction / Performance / Activity / Communication / Efficiency & Flow。

## 6. 团队能力建设

**嵌入式招聘难是结构性的**

| 数据 | 等级 |
|---|---|
| **27%** 组织认为软件类岗位最难招；欧洲芯片设计/制造缺约 **10,800** 名专业人员 | `[B]` |
| 英国每年工程师缺口超 **59,000**；专业嵌入式岗位平均招聘周期 **8–12 周**（远长于其他技术岗），技能导向招聘可缩短到 **4–6 周** | `[B]` |
| 英国 LinkedIn 嵌入式/固件岗位空缺 **3,000+**；但 **200+** 软件开发本科课程中**固件方向为 0** | `[B]` |

**结构性原因**：CS 课程偏 web/cloud；**资深 web 工程师的 Python/JS 经验并不能让他们胜任 bare-metal、内存受限的固件**；JD 要求过宽而预算偏低；HR 缺硬件背景，用僵化清单筛掉好候选人。

**Bus Factor（丰田 ETCS 案例，Michael Barr 专家证词）**

- 主 CPU 之外有监控 CPU，**但监测加速踏板位置的 ADC 只有一颗**——"the single ADC that feeds both CPUs"。
- **看门狗只由一个 timer-tick ISR 喂**，CPU 过载时可继续异常运行最长达 **1.5 秒**才被复位；且「大多数表示任务异常的 RTOS 错误码被直接忽略——这是明确的 MISRA-C 违规」。
- 安全关键逻辑集中在一个巨型任务 "Task X" 里——**又一个人为的单点**。

> **SPOF 判据**：如果一个元件失效时 ①没有备份、②失效不可检测、③不能保证进入安全状态 —— 它就是一个 SPOF。
>
> **正反对照**：✅ 把「bus factor = 1」当作**架构缺陷**去消除（双 bank flash / 独立监督看门狗 / 冗余通信）。❌ 认为「有第二个 CPU 就是冗余」——丰田案例里第二个 CPU 仍依赖同一个 ADC 和同一个 Task X。

## 7. 管理者自身的常见错误

**Peter Principle 在工程团队的表现**

- **Benson, Li & Shue (2018)**：**最好的销售最可能被提拔，也最可能在新岗位上表现不佳**；企业「可测量地牺牲了管理质量，以维持『晋升作为激励』这一机制」。
- **为什么工程比销售更严重**：*"Promotion across that boundary is not advancement along a skill curve. **It is a career change administered without consent, training, or, frequently, awareness.**"*
- **三个结构性推力**：**薪酬拓扑**（没有真实技术晋升通道时，管理是拿到 staff 级薪水的唯一路径——*"People do not choose management. They choose rent."*）、**地位信号**（headcount 被读作重要性）、**评估缺口**。
- **修复是结构性的**：建立与 director 线**薪酬对等**的 staff/principal 通道；管理转型以**可逆的 6 个月试用**开始。

**微观管理的机制解释**（Majors）：技术出身的管理者「**会微观管理技术决策，因为那是这份工作里他唯一懂的部分**」，而这恰恰摧毁团队自主性。
