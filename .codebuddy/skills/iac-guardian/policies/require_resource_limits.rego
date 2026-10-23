# require_resource_limits.rego — 要求容器资源配额声明
#
# 检测: kubernetes_deployment / kubernetes_pod 中未声明 resources.requests/limits
# 严重性: WARN
#
package iac_guardian.require_resource_limits

import rego.v1

violation contains msg if {
    container := input.resource_changes[_].change.after.spec.template.spec.containers[_]
    not container.resources
    msg := sprintf("Container '%s' missing resources declaration [WARN]", [container.name])
}

violation contains msg if {
    container := input.resource_changes[_].change.after.spec.template.spec.containers[_]
    container.resources
    not container.resources.requests
    msg := sprintf("Container '%s' missing resources.requests [WARN]", [container.name])
}

violation contains msg if {
    container := input.resource_changes[_].change.after.spec.template.spec.containers[_]
    container.resources
    not container.resources.limits
    msg := sprintf("Container '%s' missing resources.limits [WARN]", [container.name])
}
