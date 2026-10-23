# 来源可信度与存疑清单

> **引用纪律**：本 SKILL 的所有结论都标注可信度等级。**引用前先查本文件的存疑清单。**
> 访问日期统一为 **2026-09-11**。

## 0. 可信度分级

| 标记 | 含义 | 使用建议 |
|---|---|---|
| `[A]` | 同行评议论文 / 标准组织 / 官方文档 / 官方博客 | 可直接引用 |
| `[B]` | 专业工程机构 / 从业者一手复盘 / 厂商官方文档 | 可引用，注明机构 |
| `[C]` | 社区个人观点 / 媒体评论 / **厂商内容营销**（利益相关） | 仅作旁证，须交叉验证或标注「社区观点」 |

## 1. 已逐字核实的承重结论（可放心引用）

| 结论 | 核实方式 |
|---|---|
| **git-flow 作者 2020-03-05 补记 Note of reflection** | 找到原文全文。含 "If your team is doing continuous delivery... adopt a much simpler workflow (like GitHub flow) instead of trying to shoehorn git-flow"，且**明确保留**「显式版本化/多版本在野」场景；结尾 "panaceas don't exist. Consider your own context. Don't be hating. Decide for yourself." |
| **Atlassian 自 2021-08 起将 git-flow 标为 legacy** | 多源一致（含 Web Archive 时间戳佐证） |
| **Google flaky test：1.5% 运行 / ≈16% 测试 / ≈84% pass→fail** | Google Testing Blog 原文（John Micco，**2016-05-27**）逐字核对；补充：约 420 万条测试；Microsoft 五项目约 4.6% |
| **MISRA C:2025 于 2025-03 发布，225 条有效准则，新增 5 条，Rule 15.5 被 disapplied** | Perforce 官方博客等多源一致；MISRA C:2023 = 221 条；C++:2023 吸纳 AUTOSAR C++14、面向 C++17 |
| **Perforce P4 免费额度 = 5 用户 + 20 工作区 + 自托管存储无限制；超限则限 1000 文件** | Perforce 官方定价页与管理员手册一致 |
| **Automotive SPICE 4.0 于 2023-11-29 发布；新增 HWE/MLE/VAL；删除 ACQ.3/11–15、SPL.1、SUP.2/4/7** | VDA / EuroSPI / Process Fellows 三源一致 |
| **DO-178C 目标数 DAL A=71、B=69、C=62、D=26、E=0；MC/DC 仅 DAL A 强制** | 多源一致（**独立性目标数各源口径不一，勿套用单一数字**） |
| **Mender 定价 Basic $34/月、Professional $291/月、Enterprise 定制** | Mender 官方定价页一致 |

## 2. ⚠️ 存疑清单（引用前必须确认，或直接不要引用）

| 条目 | 问题 | 建议 |
|---|---|---|
| **「71% 嵌入式项目失败源于需求管理不当」** | 源自 CIO Magazine，经 PTC 转引，**原始统计口径无法核实** | **不要引用**；改用可核实的项目级案例 |
| **「IBM 缺陷成本 1-10-100 曲线（100 倍）」** | **原始研究不可检索**；Boehm 本人 2001 年表示小规模非关键系统更接近 **5:1** | 改用 **NIST Planning Report 02-3（2002）** 作为方向性依据 |
| **「EVT 后修复成本是 POC 的 10–50 倍」** | 单一供应商博客，无独立来源 | 标注为经验性判断 |
| **「某知名车企引入 ASPICE 后缺陷率降 37%、修复时间缩短 52%」** | ASPICE **咨询商口径，无出处** | **不要引用** |
| **「严格采用 ASPICE 是常规项目的 3–5 倍工作量」** | 从业者经验值，无方法论披露 | 标注「从业者经验值」 |
| **「需求变更超 5 次 → 交付延迟 2.3 倍、成本超支 1.8 倍」** | 咨询机构内容，无独立验证 | 仅作感性参考 |
| **「某企业加人后延期率从 60% 涨到 72%」** | 咨询机构内容，利益相关 | 需交叉验证 |
| **「某金融企业 Jira 迁移附件丢 3.2%（4800 文件）」** | 社区文章，**单一来源** | 谨慎采信 |
| **国产工具横向对比表（禅道/PingCode/TAPD/Worktile/CodeArts/Gitee）** | 多数为**厂商内容营销** | 选型时要求现场演示与审计模拟 |
| **各商业 ALM 许可单价**（DOORS Next/Polarion/Jama/Visure/Codebeamer） | **均为「需询价」，无公开 list price** | 采购前必须官方询价 |
| **SonarQube 定价** | 多个第三方来源相互冲突（$720/年 vs $2,500/年/100K LOC 等） | 向 SonarSource 直接询价 |
| **ASPICE 评估费用与周期** | 来自 `[C]` 级市场报告与咨询机构自述 | 仅作量级参考 |
| **「DORA 四指标比单指标预测交付表现高 22%」** | 未核实到一手 DORA 报告 | **不要引用具体数值** |
| **「某团队 commit volume 加权 → 提交体积降 67%」** | 二手博客，非权威一手研究 | 标注「二手来源」 |
| **Gallup「1/10 天生具备管理才能、82% 选错人」** | 二手转述，未核实原始报告 | 标注「二手转述」 |
| **「一人公司每月创业成本一万元」/「某玩具厂半年卖 50 万台」** | 平台访谈 / 自媒体转述，均无独立来源 | 仅作参考，**不要引用数字** |
| **「某大厂硬件专家 50 万年薪 vs 软件架构师百万」** | 媒体评论，无统计口径 | 仅作观感参考 |
| **代码复杂度（圈复杂度）企业级通用阈值** | **无权威来源** | 不要给具体数字 |
| **「良好 HAL 可减少 30–40% 移植时间」** | 单行业博客，无方法论披露 | **不要引用** |
| **「MISRA 违规率 600 处/KLOC（Hatton 2003）」** | 2003 年数据，工具与规则已变 | 作历史参照，不作现状判断 |

## 3. 主要来源清单

### 3.1 估算与实证研究 `[A]`

| 来源 | URL |
|---|---|
| Eveleens & Verhoef, *The Rise and Fall of the Chaos Report Figures*, IEEE Software 2010 | https://www.cs.vu.nl/~x/the_rise_and_fall_of_the_chaos_report_figures.pdf |
| Jørgensen & Moløkken-Østvold 2006, *How large are software cost overruns?* | https://doi.org/10.1016/j.infsof.2005.07.002 |
| Todd Little, *Schedule Estimation and Uncertainty Surrounding the Cone of Uncertainty*, IEEE Software 2006 | （IEEE Software, 2006） |
| Flyvbjerg, *Delusion and Deception in Large Infrastructure Projects*, CMR 2009 | https://www.lasg.org/documents/Flyvbjerg_Deception_lg_infrastructure_proj_winter2009.pdf |
| Budzier & Flyvbjerg 2013 | https://econpapers.repec.org/RePEc:arx:papers:1304.4525 |
| Flyvbjerg & Gardner 2023 基础概率表 | https://budgetoverrun.com/studies/flyvbjerg-megaproject-database |
| NIST Planning Report 02-3 (2002) | https://www.nist.gov/document/report02-3.pdf |
| Bossavit, *The Leprechauns of Software Engineering* 第 2 章 | https://leanpub.com/read/leprechauns/leanpub-auto-chapter-2-the-cone-of-uncertainty |
| Doing Projects Wiki, *Biases in Project Management*（RCF 反例） | http://wiki.doing-projects.org/index.php/Biases_in_Project_Management |

### 3.2 工程实践与评审 `[A]`

| 来源 | URL |
|---|---|
| **Vincent Driessen, git-flow 原文 + 2020-03-05 Note of reflection** | https://nvie.com/posts/a-successful-git-branching-model/ |
| **John Micco, *Flaky Tests at Google and How We Mitigate Them*, 2016-05-27** | https://testing.googleblog.com/2016/05/flaky-tests-at-google-and-how-we.html |
| **Sadowski et al., *Modern Code Review: A Case Study at Google*, ICSE-SEIP 2018** | https://storage.googleapis.com/gweb-research2023-stg-media/pubtools/4476.pdf |
| Bacchelli & Bird, *Expectations, Outcomes, and Challenges of Modern Code Review*, ICSE 2013 | DOI: 10.1109/ICSE.2013.6606617 |
| SmartBear / Cisco 代码评审案例 | http://support.smartbear.com/resources/cc/book/code-review-cisco-case-study.pdf |
| **Michael Nygard, *Documenting Architecture Decisions*, 2011-11-15** | https://www.cognitect.com/blog/2011/11/15/documenting-architecture-decisions |
| **Paul Graham, *Maker's Schedule, Manager's Schedule*, 2009-07** | https://www.paulgraham.com/makersschedule.html |
| **Joel Spolsky, *Things You Should Never Do, Part I*, 2000-04-06** | https://www.joelonsoftware.com/2000/04/06/things-you-should-never-do-part-i/ |
| Lam et al., *A Study on the Lifecycle of Flaky Tests*, ISSTA 2020 | https://mir.cs.illinois.edu/winglam/publications/2020/LamETAL20FaTB.pdf |
| Yocto Project Docs, Reproducible Builds | https://docs.yoctoproject.org/5.0.1/test-manual/reproducible-builds.html |
| SonarSource 官方文档, Quality Gates | https://docs.sonarsource.com/sonarqube/10.6/user-guide/quality-gates/ |

### 3.3 嵌入式一线 `[B]`

| 来源 | URL |
|---|---|
| Jack Ganssle, *Troubleshooting* | http://www.ganssle.com/articles/atblsho.htm |
| Jack Ganssle, *Jack's Rules of Thumb* | https://www.embedded.com/?p=4023959 |
| Henrik Warne, *Lessons Learned in Software Development* | http://henrikwarne.com/2015/04/16/lessons-learned-in-software-development |
| Memfault, *Automated Failure Analysis of Remote Edge*（1 in 10,000 hour bugs） | https://go.memfault.com/hubfs/ArmDevSummit%202022_AutomatedFailureAnalysisOfRemoteEdge.pdf |
| Aviation Maintenance, *Getting Serious About No Fault Found*（NFF 40%/60%，DoD $2B） | https://www.avm-mag.com/wp-content/uploads/2021/04/2014-02.pdf |
| Silicon Labs, *Debugging Live Cortex-M Based Embedded Systems* | https://www.silabs.com/documents/public/presentations/ew-2018-debugging-live-cortex-m-based-embedded-systems.pdf |
| Salkinium, *Debugging Microcontrollers*（SWO/ITM/RTT 带宽与成本） | https://salkinium.com/talks/cccamp23_debugging_microcontrollers.pdf |
| Trailblazing Astronautics, *Project Chaos: Uncontrolled Hardware Agile* | https://www.trailblazeastro.com/post/project-chaos-uncontrolled-hardware-agile |
| Arrow Jungle, *The Peter Principle*（含 Benson, Li & Shue 2018） | https://arrowjungle.com/part-5-of-the-laws-we-ignore-an-eleven-part-series-on-the-eponymous-laws-that-quietly-govern-engineering-organizations |
| EDN, *Toyota's killer firmware*（Michael Barr 证词） | https://www.edn.com/?p=4423428 |
| Promwad, 容器化固件构建可复现性失败案例 | https://promwad.com/news/containerized-embedded-development-docker-cicd-firmware-teams |
| Visure Solutions, *Integration of Hardware and Firmware in Embedded Systems*（ICD/兼容矩阵） | https://visuresolutions.com/integration-of-hardware-and-firmware-in-embedded-systems/ |
| NASA, *Mars Climate Orbiter Mishap Investigation Board Phase I Report* | https://go.nasa.gov/3m0jshc |

### 3.4 合规与标准 `[A]/[B]`

| 来源 | URL |
|---|---|
| MISRA, *MISRA Compliance:2020*（PDF） | https://misra.org.uk/app/uploads/2021/06/MISRA-Compliance-2020.pdf |
| Perforce, *What Developers Need to Know About MISRA C:2025* | https://www.perforce.com/blog/sca/misra-c-2025 |
| EuroSPI, *Automotive SPICE 4.0 Analysis* | https://conference.eurospi.net/images/eurospi/2024/Ekert-Soqrates-WorkingGroup_ASPICE_40_Analysis_TechDay_v2.pdf |
| Process Fellows, *ASPICE 4.0 Evolution or Revolution* | https://www.processfellows.de/uploads/1/1/8/8/118812826/pf_webinar_aspice4.0_-_evolution_or_revolution_holger_hoehn_2.pdf |
| Sanei, 3.1→4.0 过程对照 | https://www.sanei-hy.co.jp/en/blog/2025/01/00316/ |
| UL Solutions, Automotive SPICE Process Model | http://aws-dewi.ul.com/sis/services/automotive-spice-process-model-spice-extensions |
| ISO 26262 DIA 详解 | https://iso26262.academy/features/concepts/development-interface-agreement |
| ISO 26262 工具资质 TI/TD/TCL | https://iso26262.academy/blog/confidence-in-software-tools-a-guide-to-iso-26262-qualification |
| Jama Software, DO-178C 解读 | https://www.jamasoftware.com/requirements-management-guide/aerospace-and-defense/do-178c/ |
| IEEE, *RTOS Compliance with MISRA-C: A Comprehensive Study* | https://ieeexplore.ieee.org/abstract/document/10716387 |
| SEI/CMU, SEI CERT C and C++ Coding Standards | https://sei.cmu.edu/library/sei-cert-c-and-c-coding-standards/ |

### 3.5 工程管理作者 `[B]`

| 来源 | URL |
|---|---|
| Charity Majors 语录汇编 | https://antoinebuteau.com/lessons-from-charity-majors/ |
| Will Larson, *An Elegant Puzzle* 高亮 | https://highlights.sawyerh.com/volumes/vq63YdP8UcM4Egg9CscM |
| Camille Fournier, *The Manager's Path* 摘录 | https://nikola-breznjak.com/blog?p=4226 |
| Lara Hogan, *Resilient Management* AMA | https://www.mindtheproduct.com/resilient-management-ama-with-lara-hogan/ |

### 3.6 中国本土实践 `[C]`（需交叉验证）

| 来源 | URL |
|---|---|
| EEWorld 转载《汽车研发过程管理之怪现状》 | https://www.eeworld.com.cn/emp/aes/a397019.jspx |
| 电子工程专辑《敏捷与 ASPICE》 | https://www.eet-china.com/mp/a86063.html |
| InfoQ 汪阳《帮助某百年车企实施 ASPICE 的一点点感悟》 | https://xie.infoq.cn/article/241026c95cd6c309d0b17c5d6 |
| 掘金《嵌入式最难受的不是加班，是锅来了你跑不掉》 | https://juejin.cn/post/7669455291915288611 |
| CSDN《嵌入式调试方法论》 | https://blog.csdn.net/qq_61101621/article/details/162061019 |
| 手搓 STM32H743 开源飞控系列 | https://damodev.csdn.net/68a6b9a34e4959284dabc1c2.html |
| V2EX《硬件工程师和软件工程师哪个重要》 | https://global.v2ex.co/t/1104983 |
| 经济参考报（新华社）/ 嘉立创官方数据 | http://jjckb.xinhuanet.com/20260507/0395ead554634fa1b05369b94e7d837c/c.html |

### 3.7 工具与平台官方 `[A]/[B]`

| 来源 | URL |
|---|---|
| Perforce P4 Pricing and Plans | https://www.perforce.com/resources/vcs/helix-core-pricing |
| Perforce P4 Server Licensing（免费额度规则） | https://help.perforce.com/helix-core/server-apps/p4sag/2024.2/Content/P4SAG/install.tips.release.html |
| Mender Pricing | https://www.mender.io/plans/pricing |
| Atlassian Data Center EOL 官方页 | https://wac-cdn.atlassian.com/zh/licensing/data-center-end-of-life |
| ArduPilot SITL Simulator | https://ardupilot.org/dev/docs/sitl-simulator-software-in-the-loop.html |
| PX4 HITL | https://docs.px4.io/main/en/simulation/hitl |

## 4. 引用时的三条纪律

1. **能核实的才引**：标注「已验证」的条目已逐字核对；其余标注等级与出处。
2. **区分「已验证」与「经验性判断」**：跨来源比对得出的结论必须写明「经验性判断」。
3. **厂商内容不等于独立统计**：咨询机构、工具厂商的自述数据一律降级为 `[C]`，不作为唯一依据。
