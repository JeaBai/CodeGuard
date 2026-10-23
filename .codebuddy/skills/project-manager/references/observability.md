# 可观测性工程方法论（Observability）

> 定位：project-manager 五阶段框架的 **D6 维度增补包**，将 Metrics/Logging/Tracing 三支柱、SLI/SLO/告警分级与 AI 生成代码的可观测性标准注入第三/四阶段。
> 体量标注：🟢 全体量适用 / 🟡 成长型及以上（≥50 人）/ 🔵 大型及跨国（≥500 人）。
> 实证依据：Google SRE Book (2016)、OpenTelemetry CNCF Graduated、Honeycomb O'Reilly Observability Engineering、CNCF Cloud Native Observability Survey 2024。
> 用法：在第三阶段「质量检查」和第二阶段「质量与验收标准」定义时加载对应词条。

## 一、可观测性三支柱

### 1.1 Metrics（指标）

| 信号类型 | 黄金指标（Google SRE Four Golden Signals） | 说明 |
|----------|-------------------------------------------|------|
| 延迟（Latency） | p50/p95/p99 响应时间 | 区分成功请求与错误请求的延迟 |
| 流量（Traffic） | QPS / RPS / 并发连接数 | 系统负载度量 |
| 错误（Errors） | 错误率（5xx/4xx/超时/业务错误码） | 显式失败 + 隐式失败（如返回正确但内容为空） |
| 饱和度（Saturation） | CPU/内存/磁盘 IO/连接池使用率 | 系统资源的"满度"，预测瓶颈 |

**RED 方法（适用于微服务）**：
- **R**ate：每秒请求数
- **E**rrors：失败请求数
- **D**uration：请求耗时分布

**USE 方法（适用于基础设施）**：
- **U**tilization：资源利用率
- **S**aturation：资源饱和程度
- **E**rrors：错误事件

### 1.2 Logging（日志）

| 级别 | 用途 | 示例 |
|:----:|------|------|
| DEBUG | 开发调试，默认关闭 | 变量值、中间计算步骤 |
| INFO | 关键业务流程节点 | 用户登录、订单创建、支付成功 |
| WARN | 非预期但可恢复的事件 | 重试成功、降级触发、接近配额上限 |
| ERROR | 需要人工介入的异常 | 支付失败、数据库连接超时、第三方 API 不可用 |
| FATAL | 系统级致命错误 | 数据库崩溃、OOM、不可恢复的配置错误 |

**结构化日志规范**：

```json
{
  "timestamp": "2026-07-26T10:30:00.000Z",
  "level": "ERROR",
  "service": "order-service",
  "trace_id": "a1b2c3d4e5f6",
  "span_id": "1234567890",
  "message": "Payment gateway timeout",
  "context": {
    "order_id": "ORD-2026-001",
    "gateway": "stripe",
    "timeout_ms": 5000,
    "retry_count": 3
  }
}
```

关键要求：每行日志必须包含 `trace_id` 以实现关联。

### 1.3 Tracing（追踪）

| 概念 | 说明 |
|------|------|
| Trace | 一个请求在分布式系统中的完整调用链 |
| Span | Trace 的一个片段，代表一个操作单元 |
| Span Context | 跨进程传递的上下文（trace_id + span_id + baggage） |
| Propagation | 通过 HTTP Header (W3C TraceContext) / gRPC metadata 传递上下文 |

**需要埋点的高价值节点**：
- 所有 HTTP/gRPC 入口与出口
- 数据库查询（含 ORM 层自动埋点）
- 消息队列生产/消费
- 缓存读写（命中/未命中计数）
- 外部 API 调用（特别是第三方支付/通知）
- AI 生成代码的推理 LLM 调用链（特有）

## 二、SLI / SLO / SLA 体系

### 2.1 概念金字塔

| 层级 | 全称 | 面向对象 | 示例 |
|:----:|------|----------|------|
| **SLI** | Service Level Indicator | 工程师 | p99 延迟 < 200ms |
| **SLO** | Service Level Objective | 产品/工程师 | 99.9% 的请求满足 SLI（月度窗口） |
| **SLA** | Service Level Agreement | 客户/法务 | 月度可用性 < 99.5% 时赔付 10% 月费 |

### 2.2 SLO 设定指南

| 服务等级 | 可用性 | 月度允许不可用时间 | 年度允许不可用时间 | 适用场景 |
|:------:|:------:|:------------------:|:------------------:|----------|
| 关键路径 | 99.99% | 4.38 min | 52.6 min | 支付/认证/核心交易 |
| 重要 | 99.9% | 43.8 min | 8.76 h | 用户主流程 |
| 一般 | 99.5% | 3.65 h | 1.83 d | 管理后台/报表 |
| 非关键 | 99% | 7.31 h | 3.65 d | 内部工具/实验功能 |

**错误预算（Error Budget）**：`1 - SLO` 即允许的不可用时长。当错误预算耗尽时，冻结新功能发布，全员转向稳定性修复。

### 2.3 常见 SLI 定义模板

```yaml
slis:
  availability:
    description: "HTTP 200/301/302 响应比例"
    metric: 'sum(rate(http_requests_total{status!~"5.."}[5m])) / sum(rate(http_requests_total[5m]))'
    target: 99.9%
    
  latency:
    description: "p99 延迟"
    metric: 'histogram_quantile(0.99, rate(http_request_duration_seconds_bucket[5m]))'
    target: "≤ 500ms"
    
  error_rate:
    description: "5xx + 超时请求比例（排除客户端错误4xx）"
    metric: 'sum(rate(http_requests_total{status=~"5.."}[5m])) / sum(rate(http_requests_total[5m]))'
    target: "≤ 0.1%"
```

## 三、告警分级与值班体系

### 3.1 告警分级

| 等级 | 响应时限 | 通知方式 | 示例 |
|:----:|:-------:|----------|------|
| P0 - 紧急 | 5 min | 电话 + IM + 声光告警 | 核心支付不可用、数据库全宕 |
| P1 - 严重 | 15 min | IM + 邮件 | 单服务不可用但影响主流程 |
| P2 - 警告 | 1 h | IM 群 | 错误预算消耗 > 50%、磁盘 > 85% |
| P3 - 提示 | 次日 | 邮件/Issue | 证书 30 天过期、非关键队列积压 |

### 3.2 告警反模式（需避免）

| 反模式 | 说明 | 改进方案 |
|--------|------|----------|
| 告警疲劳 | 大量低价值告警导致值班人员麻木 | 合并同类告警，设置告警静默窗口 |
| 无行动告警 | 收到告警后不知道做什么 | 每条告警必须附带 Runbook 链接 |
| 告警无 Owner | 告警发出后无人认领 | 按服务/团队明确值班表 |
| 阈值拍脑袋 | 凭直觉设阈值，频繁误报或漏报 | 基于历史数据 p95+3σ 或 SLO 反推 |

## 四、D6 可观测性检查词条

### 4.1 第二阶段：质量与验收标准定义

| # | 提问词条 | 调研目的 | 体量 |
|---|----------|----------|:---:|
| OB1 | 核心服务的 SLI/SLO 是否已定义并文档化？关键用户旅程的端到端 SLO 是否明确？ | 建立可度量、可沟通的质量目标 | 🟢 |
| OB2 | 所有服务是否已接入结构化日志（含 trace_id）？日志级别是否正确使用？ | 确保排查问题时有据可循 | 🟢 |

### 4.2 第三阶段：执行中 — 质量检查

| # | 提问词条 | 调研目的 | 体量 |
|---|----------|----------|:---:|
| OB3 | 本周错误预算消耗了多少？是否已触发冻结发布的阈值？ | 用数据驱动发布决策而非凭感觉 | 🟢 |
| OB4 | 可观测性三支柱的覆盖度如何？哪些服务缺少链路追踪/指标暴露？ | 识别观测盲区 | 🟡 |
| OB5 | AI 生成代码的推理/生成调用链是否具备端到端可观测性（token 消耗/延迟/错误分类）？ | 对 AI 辅助编程项目特有的观测需求 | 🟡 |
| OB6 | 告警信噪比如何？本周有效告警/总告警比例是否 > 50%？误报是否在收敛？ | 反告警疲劳治理 | 🟡 |
| OB7 | 是否有 AIOps 异常检测（动态阈值/基线）辅助人工研判？异常信号的平均发现时间（MTTD）是多少？ | 提升异常发现速度 | 🔵 |
| OB8 | 是否建立了服务依赖拓扑的自动发现与可视化（如 Service Map）？依赖关系是否实时更新？ | 理解系统全貌 | 🔵 |
| OB9 | 核心 Dashboard 是否覆盖了 RED（微服务）+ USE（基础设施）+ 业务指标（订单量/转化率）三层视角？ | 确保不同角色的观测需求 | 🔵 |

### 4.3 第四阶段：交付后复盘

| # | 提问词条 | 调研目的 | 体量 |
|---|----------|----------|:---:|
| OB10 | 本阶段线上故障的平均发现时间（MTTD）/ 平均恢复时间（MTTR）是否改善？ | 度量可观测性的实际价值 | 🟡 |
| OB11 | 是否有因缺少观测信号而错过的线上问题（未知未知）？如何补全？ | 识别观测体系盲区 | 🟡 |
| OB12 | 可观测性基础设施（Prometheus/OpenTelemetry/Grafana）的维护成本与产出是否匹配？ | 可观测性自身成本效益分析 | 🔵 |

## 五、工具链推荐

| 类别 | 工具 | 体量 |
|------|------|:---:|
| 指标采集 | Prometheus + Grafana | 🟢 |
| 链路追踪 | OpenTelemetry + Jaeger / Grafana Tempo | 🟡 |
| 日志聚合 | Loki + Grafana / ELK Stack | 🟢 |
| APM | Grafana Faro (RUM) / Sentry (错误追踪) | 🟡 |
| AIOps | Grafana ML (异常检测) / Datadog Watchdog | 🔵 |
| 告警管理 | Grafana Alerting / Alertmanager + PagerDuty | 🟡 |
| AI 可观测性 | LangSmith / LangFuse / OpenLLMetry | 🟡 |

## 六、使用建议

- **🟢 初创/个人项目**：OB1/OB2 两条词条 + Prometheus + Loki 基础搭建，满足排障需求即可。
- **🟡 成长型**：OB1-OB6 + OB10 纳入执行阶段；OpenTelemetry 自动埋点 + Grafana LGTM 全家桶。
- **🔵 大型/跨国**：全部词条纳入；Service Map 拓扑 + AIOps 异常检测 + 跨团队观测标准统一（OpenTelemetry Semantic Conventions）。

---
*v1.0 · 2026-07-26 · D6 可观测性工程方法论*
