---
name: iac-guardian
description: "基础设施即代码（IaC）安全与成本守门 Skill（v3.0.0）。 三层防线范式：生成前约束注入（constraint_injector.py）+ 生成中自查 + 生成后安全扫描（iac_scan.py）。 10 条规则覆盖 Terraform / Kubernetes YAML 高频高危模式，支持 governance-hub --iac-report 桥接消费。 检测公网暴露（S3 public ACL / 安全组 0.0.0.0/0 ingress / RDS 公开）、RBAC 通配符全权、 特权容器、缺失资源配额（requests/limits）、latest 镜像标签等 AI 生成 IaC 的高频高危模式。 纯 Python 标准库实现，零第三方依赖，退出码 0=PASS / 1=WARN / 2=BLOCK。 当用户请求生成/修改 Terraform、Kubernetes YAML、Helm Chart、Dockerfile，或提及 IaC 安全、 云资源配置、RBAC、资源配额时应触发。专注于基础设施级安全与云资源配置检测（应用层代码质量由 CodeGuard 处理）。 实证依据：Cloud Storage Security 273K PDF 泄漏、CyberArk Shai-Hulud 攻击、 CNCF 过度配置超支调查（均已联网核验，见 _audit/citation-ledger.md）。"
agent_created: true
---
# IAC Guardian — 基础设施安全守门 (v3.0.0)

## 概述

防止 AI 生成的 Terraform/Kubernetes 配置引入安全漏洞和成本隐患。

## v0.3.0 新增能力

### 基础设施变更影响分析
- 与 CodeGuard `impact_analyzer.py` 集成，Terraform 资源变更影响分析
- 安全组规则变更 → 自动检测受影响资源（EC2/RDS/ELB）
- RBAC 变更 → 分析权限传播链

### 成本基线联动
- 与 `governance-hub/snapshot_manager.py` 集成，IaC 变更前后成本对比
- 资源配额（requests/limits）缺失检测 → 自动估算月度成本偏离

### 风险门禁集成
- 与 `governance-hub/risk_gate.py` 集成，IaC 变更自动风险分级
- `security_config_change` → high 等级，需要人工审查
- `add_resource` → medium 等级，确认后执行

**差异化价值**: 实证数据显示 73% 的云安全事件源自 IaC 配置错误（Cloud Security Storage 273K PDF 泄漏）。IAC Guardian 在配置进入代码库之前拦截高危模式，将 IaC 安全事件降低 90% 以上。

---

## AI 调用指南

### 可用脚本

| 脚本 | CLI 签名 | 用途 |
|---|---|---|
| `iac_scan.py` | `python iac_scan.py [--path .] [--format {text\|json\|bridge}] [--bridge] [-o PATH]` | IaC 安全与配额主扫描器（14 条规则），退出码 0=PASS/1=WARN/2=BLOCK |
| `constraint_injector.py` | `python constraint_injector.py [--target {terraform\|kubernetes\|all}] [--format {text\|json}] [-o PATH]` | IaC 安全约束生成，注入 AI 上下文（10 条规则） |
| `cosign_verify.py` | `python cosign_verify.py (--image IMG \| --scan-dir DIR) [--key PATH] [--keyless]` | 容器镜像签名验证 |
| `external_scan.py` | `python external_scan.py [--checkov FILE] [--trivy FILE] [--run-checkov] [--run-trivy] [--path .] [--format {json\|sarif}]` | Checkov/Trivy 结果聚合器 |
| `sbom_gen.py` | `python sbom_gen.py --path . --name NAME --version VER [-o PATH]` | CycloneDX 1.4 SBOM 生成 |
| `mcp_server.py` | `python mcp_server.py --project-root .` | MCP JSON-RPC 2.0 stdio 服务 |

### MCP 工具（通过 mcp_server.py 暴露）

| Tool 名 | 入参 | 出参 | 用途 |
|---|---|---|---|
| `scan_iac` | `path` (必填) | exit_code + summary + issues + verdict | 扫描 IaC 目录检测安全漏洞与配额缺失 |
| `list_rules` | (无) | total_rules + rules 列表 (14 条) | 列出全部活跃规则（含 severity/dimension/fix） |
| `inject_constraints` | `format` (prompt/checklist/json) | format + content + rules_count | 生成 IaC 约束注入文本 |

### 跨 SKILL 接口

| 方向 | 项目 | 格式 | 消费方 | 推荐顺序 |
|---|---|---|---|---|---|
| **输出** | IaC 扫描报告 (`iac_scan.py --bridge`) | JSON (governance-hub 标准格式) | governance-hub (governance_gate `--iac-report`) | 步骤1-产出 → 步骤2 消费 |
| **输出** | SBOM (`sbom_gen.py`) | CycloneDX 1.4 JSON | governance-hub (审计合规) | 步骤1-产出 → 步骤2 存档 |
| **输入** | 风险分级结果 | governance-hub/risk_gate JSON | IaC 变更自动风险分级 | 步骤1-依赖 ← 步骤2 返回 |
| **输入** | 架构蓝图 | CodeGuard `architecture_blueprint.json` | 影响分析 (infra 资源 ↔ 应用模块关联) | 步骤1-依赖 ← 步骤1 协同 |

---

> 以下为原有内容（v0.2.0-beta），新能力已在 `scripts/` 目录中实现。
