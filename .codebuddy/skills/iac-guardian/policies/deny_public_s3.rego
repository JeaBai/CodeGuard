# deny_public_s3.rego — 禁止 S3/OSS 对象存储公开 ACL
#
# 检测: aws_s3_bucket 资源 acl = "public-read" / "public-read-write"
# 严重性: BLOCK
#
package iac_guardian.deny_public_s3

import rego.v1

violation contains msg if {
    resource := input.resource_changes[_]
    resource.type == "aws_s3_bucket"
    resource.change.after.acl == "public-read"
    msg := sprintf("S3 bucket '%s' uses public-read ACL [BLOCK]", [resource.address])
}

violation contains msg if {
    resource := input.resource_changes[_]
    resource.type == "aws_s3_bucket"
    resource.change.after.acl == "public-read-write"
    msg := sprintf("S3 bucket '%s' uses public-read-write ACL [BLOCK]", [resource.address])
}

violation contains msg if {
    resource := input.resource_changes[_]
    resource.type == "aws_s3_bucket"
    resource.change.after.acl == "authenticated-read"
    msg := sprintf("S3 bucket '%s' uses authenticated-read ACL [WARN]", [resource.address])
}
