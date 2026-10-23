# Governance Hub — 研发治理连接层（v0.2.0）

打通"业务-研发-运维"闭环的治理断层：需求无源、变更无通告、成本无基线。

## 快速开始

```bash
# 发布前五问自动化检视
python .codebuddy/skills/governance-hub/scripts/governance_check.py --path . --format text

# Release Notes 自动草稿
python .codebuddy/skills/governance-hub/scripts/release_notes_draft.py --from HEAD~20

# 需求偏差率度量 (RVI)
python .codebuddy/skills/governance-hub/scripts/rvi_calc.py --path . --range 90d

# Jira 需求关联率统计
python .codebuddy/skills/governance-hub/scripts/jira_trace.py --project PROJ --range 30d

# MCP Server 模式
python .codebuddy/skills/governance-hub/scripts/mcp_server.py --project-root .
```

## 覆盖维度

| 维度 | 检查项 | 门禁级别 |
|------|--------|:------:|
| D9 需求对齐 | 需求关联率 / RVI 偏差率 | BLOCK |
| D11 成本基线 | 资源配额 / 成本趋势 | WARN |
| D12 变更传播 | 迁移回滚 / 契约破坏性 / 干系人通告 | BLOCK |

## MCP Tool 清单

| Tool | 描述 |
|------|------|
| `release_notes` | 基于 Conventional Commits 生成 Release Notes |
| `trace_requirements` | 需求追溯完整性检查 (D9) |
| `check_release_readiness` | 发布前五问自动化检视 |

## Roadmap

- [x] RVI 需求偏差率度量 (NASA SWE-200)
- [x] Jira API 联动 (PR↔需求关联率)
- [x] LLM 业务版 Release Notes 转换
- [x] 干系人 webhook (Slack/钉钉/飞书/企微)
- [x] MCP Server 模式 (3 Tools + 1 Resource)
- [x] 发布前五问自动化门禁 (CI/CD 可执行)
