#!/usr/bin/env python3
"""architect.py — CodeGuard 约束注入 Agent（生成前阶段）

执行 constraint_injector 并产出 {type: constraints} 消息。
在 Team Mode 下作为独立 Agent 运行，将架构约束注入 Generator。

用法:
  python architect.py --path . --format json     # 输出约束 JSON 到 stdout
  python architect.py --path . --format prompt   # 输出完整约束提示
"""
import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import constraint_injector
import quality_rule_registry as _registry


def generate_constraints(project_root: str, fmt: str = "json") -> dict:
    """分析项目结构并生成约束消息，用于 Team Mode Agent 间通信。

    Returns:
        架构约束消息 dict，符合 SKILL.md 定义的消息协议格式
    """
    structure = constraint_injector.detect_project_structure(project_root)
    custom_rules = constraint_injector.load_custom_rules(project_root)
    skill_rules = constraint_injector.load_skill_rules()

    block_rules = [r["name"] for r in skill_rules if r["severity"] == "block"]
    warn_rules = [r["name"] for r in skill_rules if r["severity"] == "warn"]

    custom_rule_ids = [r.get("id", "?") for r in custom_rules.get("rules", [])]

    if fmt == "prompt":
        content = constraint_injector.generate_constraint_prompt(structure, custom_rules, skill_rules)
    elif fmt == "checklist":
        content = constraint_injector.generate_quick_checklist(structure)
    else:
        content = json.dumps({
            "structure": structure,
            "block_rules": block_rules,
            "warn_rules": warn_rules,
            "custom_rules": custom_rule_ids,
        }, ensure_ascii=False, indent=2)

    return {
        "type": "constraints",
        "version": "1.0",
        "project_type": structure["type"],
        "languages": structure["languages"],
        "block_rules": block_rules,
        "warn_rules": warn_rules,
        "custom_rules": custom_rule_ids,
        "has_custom": custom_rules.get("has_custom", False),
        "checklist": wizard_checklist(structure),
        "content": content if fmt == "prompt" else None,
    }


_WIZARD_LIST = [
    f"{r['name']}: {r['checklist']} ({r['severity']})"
    for r in _registry.RULE_SPECS
]


def wizard_checklist(structure: dict) -> list[str]:
    """生成任务化约束清单（v3.0.0: 从统一注册表派生，消除硬编码不一致）。"""
    layers = structure.get("layers", {})
    checklist = list(_WIZARD_LIST)

    if layers:
        checklist.append(f"项目分层: {', '.join(layers.keys())}")
    if structure.get("languages"):
        checklist.append(f"检测语言: {', '.join(structure['languages'])}")

    return checklist


def main():
    parser = argparse.ArgumentParser(description="CodeGuard Architect Agent — 约束注入")
    parser.add_argument("--path", default=".", help="项目根目录")
    parser.add_argument("--format", choices=["json", "prompt", "checklist"], default="json")
    args = parser.parse_args()

    constraints = generate_constraints(args.path, args.format)
    print(json.dumps(constraints, ensure_ascii=False, indent=2))  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
    return 0


if __name__ == "__main__":
    sys.exit(main())
