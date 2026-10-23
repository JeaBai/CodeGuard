# IaC Guardian 规则定义与实证依据（v0.3.0）

> 每条规则附：检测逻辑 / 修复指引 / 误报豁免 / 实证来源（均已经联网核验或官方来源确认，详见 `_audit/citation-ledger.md`）。

## BLOCK 级规则

### tf-public-s3-acl — S3 公开 ACL
- **检测**：`acl = "public-*"`（Terraform）
- **修复**：删除 `acl` 属性（默认 private）；附加 `aws_s3_bucket_public_access_block` 并四项全开
- **豁免**：公开静态站点托管桶——改用 CloudFront + OAC 后豁免
- **实证**：Cloud Storage Security 2025-10 披露印度金融系统 273K 银行转账 PDF 因 S3 公开泄漏；Qualys 2025-11 汽车巨头约 70TB 数据湖暴露（S3 公开 + 弱认证）

### tf-open-cidr（ingress 上下文）— 安全组全网开放
- **检测**：`"0.0.0.0/0"` 且前 8 行上下文含 `ingress|from_port|security_group_rule|firewall`
- **修复**：ingress 限定办公网/堡垒机 CIDR 或源安全组；80/443 走 LB/WAF 层而非主机层
- **豁免**：egress 规则、公开 LB 的 80/443 ingress——将规则级别降为 WARN 人工确认
- **实证**：基座报告 D8 指出"AI 生成的 Terraform 默认暴露公网 S3 桶、RBAC 权限过宽已成为多起数据泄漏主因"

### tf-iam-wildcard — IAM 全权策略
- **检测**：`"*:*"` 或 `"Action": "*"`
- **修复**：按应用调用清单显式列举 Action 与 Resource ARN；托管策略优先于内联通配
- **豁免**：不可豁免（`Action:"*"` 配 `Resource:"*"` 无任何合法场景）

### k8s-rbac-wildcard — RBAC 通配全权
- **检测**：文件含 `kind: Role/ClusterRole` 且存在列表项 `"*"`
- **修复**：`resources: ["pods"]`、`verbs: ["get","list"]` 显式列举；聚合 ClusterRole 复用
- **豁免**：`system:` 前缀系统组件部署清单（跳过 `kube-system` 命名空间文件）
- **实证**：CyberArk 披露 Shai-Hulud npm 供应链攻击 24h 感染 180+ 包，过宽身份权限是横向扩散主因

### k8s-privileged — 特权容器
- **检测**：`privileged: true`
- **修复**：移除；需内核能力时用 `securityContext.capabilities.add: ["NET_ADMIN"]` 细粒度授权
- **豁免**：不可豁免（特权容器逃逸即宿主机沦陷）

## WARN 级规则

### tf-db-no-prevent-destroy — 数据库缺销毁保护
- **检测**：`resource "aws_db_instance"` 块内无 `prevent_destroy`
- **修复**：`lifecycle { prevent_destroy = true }`；销毁前先移除保护再走变更流程
- **实证**：2025-12 AWS 内部 Kiro AI 代理删除并重建生产环境致 13 小时中断（FT 首报，已核验）；cordum.io 披露 Claude Code `terraform destroy` 删除数据库+快照+2.5 年记录（单一来源，标注待核实）

### k8s-no-resource-limits — 缺失资源配额
- **检测**：`kind: Deployment` 且全文无 `limits` 关键字（文件级启发式）
- **修复**：每容器声明 `requests`（调度依据）与 `limits`（防爆围栏）；上限由 finops-quota CI（CPU≤2C/内存≤4Gi）兜底
- **实证**：CNCF 微调查——K8s 超支主因过度配置（InfoQ 2024-03，已核验）；Datadog《State of Cloud Costs 2024》——83% 容器成本与空闲资源相关（已核验）

### k8s-latest-image — latest 镜像标签
- **检测**：`image:` 值无标签或为 `:latest`
- **修复**：固定语义化版本或 digest（`image@sha256:...`）
- **实证**：latest 标签使灰度回滚无法定位版本，Knight Capital 类"部分节点版本漂移"事故的温床（SEC 2013-222，已核验）

### k8s-host-network / k8s-run-as-root
- **修复**：非必要不启用 `hostNetwork`；`securityContext` 声明 `runAsNonRoot: true` 与非 root UID
- **豁免**：CNI/监控 DaemonSet 等系统组件——注释原因后豁免

## 已知边界（骨架版）

1. 采用行扫描 + 花括号配对启发式，不做 HCL/YAML 完整语义解析；`k8s-no-resource-limits` 为文件级近似，多容器部分声明场景可能漏报——生产级检测请接入 Checkov/conftest（见 Roadmap）。
2. 多文件资源关联（如 Role 与 RoleBinding 分离文件）不做跨文件图分析。
3. 豁免机制当前依赖人工确认；v2 将引入 `.iac-guardian/ignore.json` 声明式豁免。
