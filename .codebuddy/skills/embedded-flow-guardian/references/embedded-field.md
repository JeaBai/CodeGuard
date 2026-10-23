# 嵌入式一线经验

> 调试、可观测性、软硬件调试差异、技术债、估算与「血泪教训」共识清单。
> 标注 `[A]`/`[B]`/`[C]`，完整来源见 `sources.md`。

## 1. 调试：业界唯一的共识

> **调试不是「让 bug 消失」，而是「知道 bug 为什么消失」；未经理解的修复会以更高代价回来。**

这是本次调研中**唯一被所有来源反复确认的共识**——从 Ganssle 到 Barr Group，从 Henrik Warne 到 NFF 航空维修统计，无一例外。

### 1.1 Jack Ganssle 的排障循环

```
while (bug(i)) {
  观察现象 → 观察附带行为 → 列出常见嫌疑 → 产生假设 → 设计实验 → 修复
}
```

- 原话：**"Assume it's broken. Never figure anything is working right until proven by repeated experiment"**
- 前置动作容易被跳过：*"Take a minute and make sure you have good access to the system"*——先焊好示波器地线引线、准备好延长卡，再开始查。

### 1.2 Henrik Warne 的「一次只改一处」

> *"**Change one thing at a time**… This applies down to the level of commits."*

他 2016 年复盘 13 年间 **194 个棘手 bug**，2025 年又复盘了随后 9 年的记录，**两轮结论高度一致**。

### 1.3 Ganssle 的统计数字

- **"5% of functions consume 80% of debugging time"**
- **"most projects wallow in the debug cycle, which often accounts for half of the entire schedule"**
- **"Eighty percent of embedded systems are delivered late"**
- **"Estimating dates instead of hours guarantees a late project"**

### 1.4 Heisenbug 与 Mandelbug

| 类型 | 定义 | 现场实例 |
|---|---|---|
| **Bohrbug** | 确定条件下稳定复现 | 空指针崩溃，给定输入必崩 |
| **Heisenbug** | **一探测就消失/性质改变** | Release 编译有、Debug 没有；竞态；未初始化变量（调试器把内存清零就「好了」） |
| **Mandelbug** | 成因极复杂、行为看似混沌但本质确定 | 依赖调度顺序的 OS bug；故障激活与最终失效之间长延迟 |

Barr Group：**"Introducing debugging code changes the execution timing so it is entirely possible that introducing debugging code makes a bug 'disappear' (Heisenbug)."**

> **判断准则**：凡是「加了 printf 就好、删了又坏」的现象，**先在脑海里判定为 Heisenbug**，而不是「修好了」。

### 1.5 git bisect 的真实收益

- 47 个候选 commit → **6 次测试**、约 20 分钟（对比手工逐个 checkout 2 天+）
- **前提**：bisect 要求「单调性」——bug 引入后一直存在。**间歇性 bug 不满足，不能用。**

### 1.6 被证伪：shotgun debugging

> *"making relatively undirected changes to software in the hope that a bug will be perturbed out of existence. This has a relatively low success rate… and **it usually introduces more bugs**."*

真实案例：老代码库 UI bug，两人电话里乱调样式，改了个 if 条件上线后「好了」，**几周后复发**。真实根因是内部 UI 库 stylesheet 编译产物陈旧，与那个 if 条件无关。

### 1.7 「怀疑硬件还是软件」

| 场景 | 第一嫌疑 | 动作 |
|---|---|---|
| 同设计、别人 work、我 fail，且我软件与 vendor 一致 | **硬件损坏** | 换同型号硬件（5 分钟）优先于猜固件/接线/驱动（1–2 天） |
| 全新设计、谁都没跑通 | **软件/配置/接线** | 因为没有 work 的 baseline |

口诀：**「别人 work 我 fail」= 先怀疑自己，不是怀疑硬件。**

## 2. 日志与可观测性

### 2.1 printf 在实时系统里的代价

| 方案 | 实时性影响 | 侵入性 | 硬件依赖 |
|---|---|---|---|
| UART 重定向 printf | 高（阻塞 CPU） | 极高 | 外设+波特率限制 |
| **SWO/ITM** | 极低（异步） | 低 | 需 SWD 调试器 |
| **RTT** | 微小（RAM 缓冲） | 中 | 占用部分 RAM |

**真实案例**：某工业控制项目，高速电机控制循环出现莫名抖动，**排查三天三夜**，根因是**中断服务函数里一条深埋的 printf**——串口波特率太低，CPU 等发送缓冲空闲时阻塞，破坏了 PWM 相位精度。

**STM32F407 相关数据**：STLinkv3 通过 SWO 引脚可读到 **~2MB/s**；ITM 有 **32 个通道**，硬件负责序列化与时间戳。SWV/ITM 走 `PB3`(TRACESWO)，SWO 时钟需 ≤ HCLK/2。

> 原文提醒：**"Don't call heavy printf inside ISRs."**

### 2.2 看门狗复位原因是关键证据

复位原因寄存器本身就能区分故障类型（以 ESP32 为例：`ESP_RST_INT_WDT → SoftwareWatchdog`、`ESP_RST_TASK_WDT → TaskWatchdog`、`ESP_RST_WDT → HardwareWatchdog`）——**区分「哪个看门狗」本身就是定位线索**。

STM32F4 侧对应 `RCC_CSR` 的 `IWDGRSTF`（独立看门狗）/`WWDGRSTF`（窗口看门狗）/`SFTRSTF`（软件复位）/`PORRSTF`（上电）等标志位。

### 2.3 现场可观测性的核心论据

> *"By sampling data from all the devices in your fleet, we can surface the ultra rare bugs that occur in production, **which are nearly impossible to find and reproduce otherwise**."*

业界用「**1 in 10,000 hour bugs**（万小时一遇的 bug）」形容这类问题。客户实证：接入后 **debugging 快 5 倍、续航翻倍、客户问题解决效率 10 倍**，并在生产中实锤捕获到 bit flip。

### 2.4 NFF（无法复现故障）比例——航空业最硬的数字

| 场景 | NFF 比例 |
|---|---|
| 航空/防务电子 LRU 返回 | **20–30%** |
| AIAA NFF 指导委员会：机械 LRU / 航电 LRU | **~40% / ~60%** |
| 航电工程师普遍估计 | **30%–50%** |
| Honeywell（公务航空） | 最好 **15%**，最差 **>60%** |
| 单个部件样本（GCU，12 个月 14 次拆换） | **71%** 返回标注 NFF |

**DoD 数据**：美国国防部估计 WRA 内部的间歇性航电故障**每年耗费 >20 亿美元**。

> **落地建议**：NFF 的成因清单里，「**无法复现故障发生时的环境**」和「**缺乏故障日志**」排在最前。
> **这就是为什么「黑匣子」（环形缓冲 + 复位原因 + 静默计数）要在点亮 LED 之后立刻做，而不是等炸机后。**

## 3. 硬件调试 vs 软件调试

**硬件问题无法「重跑」**：*"**You can't always 'single step' through code!**"*——发动机控制、印刷机、飞行管理等场景，停机即意味着灾难或高成本，**必须在「带电、在跑」的状态下调试**。

### 3.1 虚焊 / 批次 / 冷焊的间歇性故障实例

| 案例 | 根因 | 数字/细节 |
|---|---|---|
| 100 片量产批次 | 手焊原型 vs 产线焊接，虚焊 | **8/100 首周现场失效**，原理图与固件均未改 |
| 消费电子 PCBA | 回流失温 + 焊锡超期 | 峰值温度比 SAC305 推荐低 **5°C**；焊膏储存 **18 个月**超 12 个月保质期；不良率 **15% → 0.5%** |
| ECU 失效分析 | BGA 焊点纳米级氧化（「冷焊」）+ 导热硅脂老化 | +5V 纹波 **62mV**（限值 ≤50mV）；结温 **125°C**（规范 105°C） |
| 接地脚焊接不良 | 电源状态切换时噪声耦合到地址线 | 偶发内存损坏、自动重启，软件层完全查不出 |
| 看门狗上拉电阻不当 | 极端温度下 GPIO 信号异常 | 系统每 72 小时死机 |

> **冷焊的物理本质（值得记住）**：冷焊点的**复阻抗**会随温度、振动、湿度动态变化，**万用表静态测阻值往往完全正常**——**这就是 NFF 的来源**。诊断需**动态测试**：温度循环、振动、高频信号注入。

**EMC 导致的间歇性故障**：系统在**高 EMI 事件**中偶发失效，虚假中断微妙改变执行时序。**实验室完全正常，只有在噪声环境下暴露**。此类场景断点/单步**完全无用**，改用：不干扰实时性的日志、硬件看门狗强制定复位、冗余错误检测、**测试阶段统计式故障注入**。

## 4. 技术债与遗留代码

### 4.1 Joel Spolsky 原文要点（《Things You Should Never Do, Part I》，2000-04-06）

> *"**There never was a version 5.0.**"* / *"They did it by making the **single worst strategic mistake** that any software company can make: They decided to rewrite the code from scratch."*
>
> *"**It's harder to read code than to write it.**"*
>
> *"The idea that new code is better than old is patently absurd. **Old code has been used. It has been tested. Lots of bugs have been found, and they've been fixed.**"*
>
> *"There is **absolutely no reason** to believe that you are going to do a better job than you did the first time."*

### 4.2 反方观点（有些系统确实该重写）

| 反方来源 | 核心论点 |
|---|---|
| DZone | *"You cannot refactor a **GWT app to Angular or React. It must be a rewrite.**"*（押错技术栈） |
| Securosis（作者成功重写 2/3 次） | *"I have inherited code so bad that **bug fixes cost 4x in time and usually created new bugs**"*；「一个简单的 true/false 比较 **做了 12 次比较、8 次数据库插入和 7 次删除——造成 180 倍性能损失**」 |
| HN 讨论 | *"**Netscape's problem isn't that they did a rewrite**… **it's that they essentially abandoned their old code too early, and announced the rewrite too soon.**"* |
| HN 讨论 | 重写失败的真正原因：*「在重写达到功能对等之前，**它已经被当初促使重写的那些问题所腐蚀**」*——组织问题没解决 |

### 4.3 决策表

| 判据 | 偏重构 | 偏重写 |
|---|---|---|
| 是否理解代码「做什么」 | 理解 | **完全无法理解「为什么」** |
| 技术栈 | 仍是主流 | **押错技术栈** |
| 组织能力 | 团队掌握领域 | 原班人马不在、无人能接手 |
| 团队是否同一批人 | 是 | **否——「别让把船开搁浅的同一批人掌舵」** |
| 补救手段 | 自动化测试 + 文档 | 均已失效 |

> **嵌入式特有补充**：**"When the developers are afraid to change a function, it's time to rewrite that code from scratch."** 这些「烂函数」的成本是其他函数的 **4 倍**（Boehm 数据）。
>
> **代码复用收益递减**：移植旧代码若修改量超过约 **25%**，基本没有进度收益。

### 4.4 渐进式改造套路

1. **先建特征化测试**（characterization tests）——把现有行为（含 bug）锁死，作为重构安全网
2. **引入 facade**——把模块 API 包裹为函数指针结构体，形成可替换接缝
3. **抽取纯逻辑**——把计算/状态机搬到零硬件依赖的 `.c/.h`，在宿主上测
4. **HAL 解耦**——用驱动结构体替换寄存器直写
5. **灰度切换**——至少一个发布周期后再删旧码

> **第一性约束不是技术，而是「重新认证成本」**。有认证负担的领域（车规/航电），改造必须与再验证/再认证预算绑定决策。**没有自动化测试网的重构，等同于赌博。**

## 5. 嵌入式估算为什么特别难

### 5.1 供应链的硬约束

| 关键数据 | 数值 |
|---|---|
| 行业平均芯片交期峰值（2022 年中） | **约 27 周**；最紧缺的 FPGA 报价 **一年以上** |
| JEDEC 停产通知（PDN）缓冲窗口 | 下最后订单 **约 6 个月**，最后收货 **12 个月** |
| 2019 年「正常」交期 → 2021 年 12 月 | **6–9 周 → ≈25.8 周** |
| 芯片荒累计经济损失 | **超过 5000 亿美元**；汽车行业 2021 年收入损失 **2100 亿美元**、净产量减少 **770 万辆** |

**一线工程师原话**（IIT Bombay, 2021-12）：

> "Around **1500 were available with the vendor**. However, **from the moment I thought of putting it into the cart and checking out, the entire 1500 was bought by someone**… so I can't use that controller in my board and **have to redesign and redo my firmware**."

以及总结硬件本质的那句：**"your entire hardware production cycle is dependent on the slowest component in the chain. Even if one capacitor is missing in the product chain, you can't ship that product."**

### 5.2 硬件迭代一轮的时间成本

| 环节 | 典型周期 |
|---|---|
| 打样（2 层板） | 标准 **5–10 工作日**；快板 **24–48 小时** |
| 打样（4–6 层） | 标准 **10–15 工作日**；快板 **2–3 工作日** |
| 打样（8–12 层） | 标准 **15–20 工作日**；快板 **3–5 工作日** |
| 贴片（原型） | 再加 **1–3 天** |
| 总周期（Gerber→测试完成） | **约 1–4 周** |

> **直接影响**：一轮「改原理图→重打板→重贴片→重调试」的**现实最短反馈周期是 3–7 天，长则 3–4 周**。
> 这意味**硬件迭代次数必须靠软件仿真和面包板验证来压缩**——也是「把可观测性做足」的经济理由。

### 5.3 估算本身的结构性难题

| 规律 | 内容 |
|---|---|
| **Cargill 定律** | "The first 90 percent of the code accounts for the first 90 percent of the development time. **The remaining 10 percent… accounts for the other 90 percent.**" |
| CPU 占用与工期 | 加载到 90% 性能需 **2×** 开发时间；95% 需 **3×** |
| 复用收益拐点 | 旧代码修改量 >25% 则无进度收益 |
| 开发者实际投入 | 平均仅约 **55%** 时间用于新产品工作 |
| 交付延误 | **80% 嵌入式系统延期**；平均消耗 **2×** 预算工时 |

## 6. 「血泪教训」共识清单

以下几条在多个独立来源中重复出现，**共识度最高**：

| # | 教训 | 印证来源 |
|---|---|---|
| 1 | **一次只改一处**，改完立刻验证 | Warne；CSDN 调试方法论；Barr Group |
| 2 | **先装「眼睛」再调功能**——可观测性优先于功能开发 | Warne；Memfault；CSDN |
| 3 | **先找 baseline，再下结论**；没有对照前别断言「硬件问题」 | CSDN 调试方法论（「两次栽在同一个坑」） |
| 4 | **别用随机修改代替理解**（shotgun debugging 有害） | Jargon File；真实复发案例 |
| 5 | **与同事讨论是攻克难题最高效的手段** | Warne 两轮复盘均列第一位 |
| 6 | **「最后一次改动」是最高概率嫌疑**（哪怕只加了一行日志） | Warne；Interrupt；git bisect 案例 |
| 7 | **相信用户**：别默认「不可能，肯定是用户操作错了」 | Warne |
| 8 | **修完必须验证**：先复现、再修、再看是否消失 | Warne |
| 9 | **验证每个新分支至少被执行一次** | Warne |
| 10 | **别在 ISR 里放阻塞/耗时操作**（printf、动态内存、锁） | Ganssle；STM32 实践；三天排查案例 |
| 11 | **间歇性问题的根因常在「环境」而非代码**（电源、温度、EMC、焊接） | embedded.com；冷焊分析；批次案例 |
| 12 | **「设备群体的历史数据」比「一台设备的现场」更值钱** | Memfault（1 in 10,000 hour bugs 只有靠 fleet 抽样才抓得到） |

**「锅黏在工牌上」**（一线共鸣最高的一条吐槽）：

> 「嵌入式的锅特别黏。它不干脆。**软件怀疑电源。硬件怀疑时序。测试怀疑环境。客户怀疑你们上周是不是偷偷改过版本。**」

**可操作性最强的两条应对（原文）**：

> - 「**关键节点尽量留痕。版本号、烧录记录、配置差异、复现条件、已经排除的项，写成别人能看懂的句子**，而不是只活在脑子里。」
> - 「**该拒绝的承诺要拒绝**——很多锅的种子，埋在你点头太快的那一刻。」
