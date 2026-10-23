"""从 CodeGuard 结果导入重构任务。"""
from __future__ import annotations

import json
import os
from collections import defaultdict

from refactor_queue_store import _load_queue, _save_queue, _log
from refactor_queue_core import enqueue

# ============================================================
# 公共 API：import_refactor_tasks()
# ============================================================

def import_refactor_tasks(codeguard_output: str, blueprint_path: str = "",
                          project_root: str = ".") -> dict:
    """从 CodeGuard 检测结果自动生成重构队列项。

    规则:
      - 同一文件的多个问题合并为一个任务
      - block 级问题 → P0
      - warn 级问题 → P1
      - info 级问题 → P2
      - 按复杂度/重复代码/架构违规分类
    """
    try:
        with open(codeguard_output, "r", encoding="utf-8") as f:
            cg_data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        return {"status": "error", "message": f"CodeGuard 输出加载失败: {e}"}

    issues = cg_data.get("issues", cg_data.get("data", []))
    if not isinstance(issues, list):
        issues = []

    if not issues:
        return {"status": "ok", "imported": 0, "message": "CodeGuard 未检出任何问题"}

    # 按文件分组
    file_groups: dict[str, list[dict]] = defaultdict(list)
    for issue in issues:
        fpath = issue.get("file", "unknown")
        file_groups[fpath].append(issue)

    # 加载蓝图（用于分析依赖）
    bp = None
    if blueprint_path and os.path.isfile(blueprint_path):
        try:
            bp = json.loads(open(blueprint_path, "r", encoding="utf-8").read())
        except (json.JSONDecodeError, OSError):
            pass

    imported = 0
    deps = bp.get("dependency_graph", {}) if bp else {}

    for fpath, file_issues in file_groups.items():
        # 合并问题描述
        blocks = [i for i in file_issues if i.get("severity") == "block"]
        warns = [i for i in file_issues if i.get("severity") == "warn"]
        infos = [i for i in file_issues if i.get("severity") == "info"]

        # 优先级：有 block → P0，有 warn → P1，否则 P2
        if blocks:
            priority = "P0"
        elif warns:
            priority = "P1"
        else:
            priority = "P2"

        # 标题
        categories = set(i.get("category", "") for i in file_issues)
        cat_labels = {
            "complexity": "圈复杂度",
            "nesting": "嵌套深度",
            "duplication": "重复代码",
            "architecture": "架构违规",
            "security": "安全问题",
            "params": "参数过多",
            "file_size": "文件过大",
        }
        cat_names = [cat_labels.get(c, c) for c in categories if c]
        title = f"{os.path.basename(fpath)}: {', '.join(cat_names[:3])}"

        # 描述
        desc_lines = []
        for i in file_issues[:5]:
            sev = i.get("severity", "").upper()
            msg = i.get("message", "")
            line = i.get("line", 0)
            desc_lines.append(f"[{sev}:L{line}] {msg}")
        description = "; ".join(desc_lines[:3])

        # 寻找依赖：如果涉及的文件在某个模块中，依赖该模块被依赖
        depends_on = []
        module_name = _find_module_for_file(fpath, bp)
        if module_name and deps:
            for dep in deps.get(module_name, []):
                # 查找依赖模块是否有已生成的任务
                pass  # 简单模式：不自动建立跨模块依赖

        # tags_required
        tags_required = _infer_tags_required(categories, file_issues)

        # max_nesting_target
        max_nesting_target = None
        for i in file_issues:
            if i.get("category") == "nesting":
                current = i.get("line", 8)
                max_nesting_target = max(3, current - 3)

        result = enqueue(
            title=title,
            files=[fpath],
            priority=priority,
            description=description,
            depends_on=depends_on,
            tags_required=tags_required,
            project_root=project_root,
        )
        if result["status"] == "enqueued":
            # 设置额外字段
            data = _load_queue(project_root)
            for t in data.get("queue", []):
                if t["id"] == result["id"]:
                    t["max_nesting_target"] = max_nesting_target
                    break
            _save_queue(data, project_root)
            imported += 1

    _log(f"导入完成: {imported} 个任务")
    return {"status": "ok", "imported": imported, "total_issues": len(issues)}


def _find_module_for_file(filepath: str, bp: dict | None) -> str | None:
    if bp is None:
        return None
    for m in bp.get("modules", []):
        if filepath.startswith(m.get("path", "")):
            return m.get("name", "")
    return None


def _infer_tags_required(categories: set[str], issues: list[dict]) -> dict[str, str]:
    """根据问题类型推断需要的标签。"""
    tags: dict[str, str] = {}
    cat_tag_map = {
        "complexity": "allow_split",
        "nesting": "allow_split",
        "file_size": "allow_split",
        "duplication": "shared_util",
    }
    for cat in categories:
        tag = cat_tag_map.get(cat)
        if tag:
            for i in issues:
                fpath = i.get("file", "")
                # 提取模块名作为 key
                module = os.path.dirname(fpath) or os.path.basename(fpath)
                tags[module] = tag
                break
    return tags
