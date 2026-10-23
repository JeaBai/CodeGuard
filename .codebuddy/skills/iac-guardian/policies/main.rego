# iac-guardian OPA Rego 策略包 v0.1.0
#
# 使用方式:
#   conftest test terraform/ --policy policies/
#   opa eval --data policies/ --input terraform_plan.json "data.iac_guardian"
#
# 策略列表:
#   1. deny_public_s3.rego         — 禁止 S3 公开 ACL
#   2. deny_wide_open_sg.rego      — 禁止安全组 0.0.0.0/0
#   3. require_resource_limits.rego — 要求容器资源配额
#   4. require_encryption.rego     — 要求存储/KMS 加密
#   5. deny_privileged.rego        — 禁止特权容器
#
# 参考: Open Policy Agent (OPA) — https://www.openpolicyagent.org/
package iac_guardian

# 所有策略聚集入口
deny[msg] { msg := data.iac_guardian.deny_public_s3.violation }
deny[msg] { msg := data.iac_guardian.deny_wide_open_sg.violation }
deny[msg] { msg := data.iac_guardian.require_resource_limits.violation }
deny[msg] { msg := data.iac_guardian.require_encryption.violation }
deny[msg] { msg := data.iac_guardian.deny_privileged.violation }
