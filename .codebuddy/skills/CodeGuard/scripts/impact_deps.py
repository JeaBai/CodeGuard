from __future__ import annotations

# ============================================================
# 模块依赖分析
# ============================================================

def _analyze_module_deps(module_name: str, change_type: str,
                         blueprint: dict) -> dict:
    """基于蓝图依赖图分析模块级变更影响。"""
    deps = blueprint.get("dependency_graph", {})
    modules = blueprint.get("modules", [])

    forward = deps.get(module_name, [])
    reverse = [m.get("name", "") for m in modules
               if module_name in deps.get(m.get("name", ""), [])]

    impacted_upstream = sorted(set(forward + _recursive_deps(forward, deps)))
    impacted_downstream = sorted(set(reverse + _recursive_reverse_deps(reverse, deps)))

    breaking = False
    recommendation = "review_and_proceed"

    if change_type == "remove_dep":
        # 移除依赖：上游受影响
        impacted = impacted_downstream
        action = f"移除 {module_name} 的依赖将影响 {len(impacted)} 个下游模块"
        breaking = len(reverse) > 0
        recommendation = "ensure_interface_stability" if breaking else "review_and_proceed"
    elif change_type == "add_dep":
        impacted = impacted_upstream
        action = f"新增 {module_name} 的依赖将影响 {len(impacted)} 个上游模块"
        recommendation = "possible_cycle_risk"
    else:
        impacted = list(set(impacted_upstream + impacted_downstream))
        action = f"模块依赖变更影响 {len(impacted)} 个模块"

    return {
        "module": module_name,
        "change": change_type,
        "forward_deps": forward,
        "reverse_deps": reverse,
        "impacted_modules": impacted,
        "impacted_count": len(impacted),
        "breaking": breaking,
        "recommendation": recommendation,
        "description": action,
    }


def _recursive_deps(start_nodes: list[str], deps: dict[str, list[str]],
                    max_depth: int = 5) -> list[str]:
    """递归查找上游依赖链。"""
    result = []
    queue = list(start_nodes)
    visited = set(start_nodes)
    depth = 0
    while queue and depth < max_depth:
        depth += 1
        current = queue.pop(0)
        for dep in deps.get(current, []):
            if dep not in visited:
                visited.add(dep)
                result.append(dep)
                queue.append(dep)
    return result


def _recursive_reverse_deps(start_nodes: list[str], deps: dict[str, list[str]],
                            max_depth: int = 5) -> list[str]:
    """递归查找下游反向依赖链。"""
    result = []
    queue = list(start_nodes)
    visited = set(start_nodes)
    depth = 0
    while queue and depth < max_depth:
        depth += 1
        current = queue.pop(0)
        for m, dep_list in deps.items():
            if current in dep_list and m not in visited:
                visited.add(m)
                result.append(m)
                queue.append(m)
    return result
