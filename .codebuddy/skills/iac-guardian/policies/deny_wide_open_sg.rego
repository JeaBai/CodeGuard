# deny_wide_open_sg.rego — 禁止安全组 0.0.0.0/0 ingress
#
# 检测: aws_security_group / openstack_networking_secgroup 中 cidr_blocks = ["0.0.0.0/0"]
# 严重性: BLOCK（非 80/443 端口）/ WARN（80/443 端口）
#
package iac_guardian.deny_wide_open_sg

import rego.v1

violation contains msg if {
    rule := input.resource_changes[_]
    rule.type in {"aws_security_group_rule", "openstack_networking_secgroup_rule_v2"}
    rule.change.after.cidr_blocks[_] == "0.0.0.0/0"
    not is_http_port(rule.change.after)
    msg := sprintf("Security group '%s' opens to 0.0.0.0/0 on non-HTTP port [BLOCK]", [rule.address])
}

violation contains msg if {
    rule := input.resource_changes[_]
    rule.type in {"aws_security_group_rule", "openstack_networking_secgroup_rule_v2"}
    rule.change.after.cidr_blocks[_] == "0.0.0.0/0"
    is_http_port(rule.change.after)
    msg := sprintf("Security group '%s' opens to 0.0.0.0/0 on HTTP port (80/443) [WARN]", [rule.address])
}

is_http_port(rule) if {
    rule.from_port == 80
}

is_http_port(rule) if {
    rule.from_port == 443
}

is_http_port(rule) if {
    rule.to_port == 80
}

is_http_port(rule) if {
    rule.to_port == 443
}
