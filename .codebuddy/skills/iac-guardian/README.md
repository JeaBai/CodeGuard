# IaC Guardian — IaC 安全与成本守门（骨架版 v0.2.0-beta）

在 AI 生成 Terraform / Kubernetes YAML 的每一刻拦截公网暴露、全权授予与配额缺失。

## 快速开始

```bash
# 扫描当前目录（文本输出）
python .codebuddy/skills/iac-guardian/scripts/iac_scan.py --path .

# CI 集成（JSON 输出，退出码 0=PASS / 1=WARN / 2=BLOCK）
python .codebuddy/skills/iac-guardian/scripts/iac_scan.py --path . --format json

# MCP Server 模式
python .codebuddy/skills/iac-guardian/scripts/mcp_server.py --project-root .
```

零第三方依赖（Python 3.8+ 标准库）。

## 检测能力（25 条）

| 级别 | 规则 |
|------|------|
| BLOCK | S3 公开 ACL / 安全组 0.0.0.0/0 ingress / IAM 全权 / RBAC 通配 / 特权容器 / RDS 加密 / CloudTrail / 环境变量泄露 |
| WARN | DB 缺 prevent_destroy / 缺 resources 配额 / latest 镜像 / hostNetwork / root 运行 / KMS 轮换 / S3 版本控制 / IMDSv2 / NetworkPolicy / seccomp |
| INFO | Docker COPY vs ADD / 安全组自引用 |

完整规则定义与实证依据：`references/iac_rules.md`。
OPA Rego 策略包：`policies/`（5 条，conftest/opa 可加载）。

## MCP Tool 清单

| Tool | 描述 |
|------|------|
| `scan_iac` | 扫描 IaC 目录，返回安全与配额发现 |
| `list_rules` | 列出全部 14 条活跃规则 |
| `inject_constraints` | 生成 IaC 约束提示注入到 AI 上下文 |

## 在 CodeBuddy 中使用

本 SKILL 已放置于项目 `.codebuddy/skills/iac-guardian/`，当对话涉及 Terraform/K8s YAML 生成或修改时自动激活三层防线（约束注入 → 自查 → 门禁扫描）。

## 与体系的关系

- 上游：`CodeGuard`（代码内建质量）——本 SKILL 复用其三层防线范式与退出码语义
- 同级：`governance-hub`（发布前治理检视）——通过 `--bridge` 模式消费 iac-guardian 扫描结果
- 下游 CI：`finops-quota.gitlab-ci.yml`（配额兜底）、Checkov/Trivy（生产级深度扫描）
- 设计依据：`docs/skill-gap-design.md`（SKILL 综合评估与定制设计方案）

## Roadmap

- [x] SBOM 生成与归档（`scripts/sbom_gen.py` — CycloneDX 1.4）
- [x] cosign 镜像签名验证（`scripts/cosign_verify.py` — Keyless + Key-based）
- [x] Checkov/Trivy 聚合（`scripts/external_scan.py` — SARIF 导入）
- [x] MCP Server 模式（`scripts/mcp_server.py` — 3 Tools + 1 Resource）
- [x] OPA Rego 策略包（`policies/` — 5 条 Rego 模板）
- [x] 规则扩展至 25 条（`scripts/iac_scan_extended.py`）
