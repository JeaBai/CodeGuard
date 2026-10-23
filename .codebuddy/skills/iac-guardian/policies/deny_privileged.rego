# deny_privileged.rego — 禁止特权容器
#
# 检测:
#   - kubernetes_pod 中 privileged: true
#   - kubernetes_pod 中 hostNetwork: true / hostPID: true / hostIPC: true
#   - kubernetes_pod 中未设置 runAsNonRoot
# 严重性: BLOCK (privileged/hostNetwork) / WARN (runAsNonRoot 缺失)
#
package iac_guardian.deny_privileged

import rego.v1

# 特权容器 (BLOCK)
violation contains msg if {
    container := input.resource_changes[_].change.after.spec.template.spec.containers[_]
    container.security_context.privileged == true
    msg := sprintf("Container '%s' runs in privileged mode [BLOCK]", [container.name])
}

# 宿主机网络 (BLOCK)
violation contains msg if {
    resource := input.resource_changes[_]
    resource.change.after.spec.template.spec.host_network == true
    msg := sprintf("Pod '%s' uses hostNetwork [BLOCK]", [resource.address])
}

# 宿主机 PID (WARN)
violation contains msg if {
    resource := input.resource_changes[_]
    resource.change.after.spec.template.spec.host_pid == true
    msg := sprintf("Pod '%s' uses hostPID [WARN]", [resource.address])
}

# 宿主机 IPC (WARN)
violation contains msg if {
    resource := input.resource_changes[_]
    resource.change.after.spec.template.spec.host_ipc == true
    msg := sprintf("Pod '%s' uses hostIPC [WARN]", [resource.address])
}

# 缺 runAsNonRoot (WARN)
violation contains msg if {
    container := input.resource_changes[_].change.after.spec.template.spec.containers[_]
    not container.security_context
    msg := sprintf("Container '%s' missing security_context [WARN]", [container.name])
}

violation contains msg if {
    container := input.resource_changes[_].change.after.spec.template.spec.containers[_]
    container.security_context
    not container.security_context.run_as_non_root
    msg := sprintf("Container '%s' not running as non-root [WARN]", [container.name])
}
