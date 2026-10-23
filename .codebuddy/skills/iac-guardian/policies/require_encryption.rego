# require_encryption.rego — 要求存储和密钥加密
#
# 检测:
#   - RDS 未启用 storage_encrypted
#   - S3 未启用 server_side_encryption
#   - KMS 未启用 key_rotation
# 严重性: BLOCK（RDS/S3）/ WARN（KMS）
#
package iac_guardian.require_encryption

import rego.v1

# RDS 加密 (BLOCK)
violation contains msg if {
    resource := input.resource_changes[_]
    resource.type == "aws_db_instance"
    not resource.change.after.storage_encrypted
    msg := sprintf("RDS '%s' storage_encrypted not enabled [BLOCK]", [resource.address])
}

# S3 默认加密 (BLOCK)
violation contains msg if {
    resource := input.resource_changes[_]
    resource.type == "aws_s3_bucket_server_side_encryption_configuration"
    not resource.change.after.rule.apply_server_side_encryption_by_default
    msg := sprintf("S3 '%s' default server-side encryption not configured [BLOCK]", [resource.address])
}

# KMS 密钥轮换 (WARN)
violation contains msg if {
    resource := input.resource_changes[_]
    resource.type == "aws_kms_key"
    not resource.change.after.enable_key_rotation
    msg := sprintf("KMS key '%s' auto rotation not enabled [WARN]", [resource.address])
}
