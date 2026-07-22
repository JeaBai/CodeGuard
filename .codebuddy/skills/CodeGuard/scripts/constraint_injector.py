#!/usr/bin/env python3
"""
CodeGuard Constraint Injector
=================================
架构约束提取与注入脚本。从项目的 references 规则文件和 .code-guardian 配置中提取约束，
生成适合注入到 AI 对话上下文中的结构化约束摘要。

用法：
  python constraint_injector.py --path <project_root> [--format json|text|prompt]

用途：
  1. 检测项目是否有自定义架构规则配置
  2. 提取项目结构信息（目录布局、依赖关系）
  3. 生成精简的架构约束提示，注入到 AI 对话上下文

设计依据：
  - "Lost in the Middle" 效应（Liu et al., arXiv 2307.03172）：约束信息应放在 Prompt 最前和最后
  - 对抗自回归生成缺乏全局规划：在每次代码生成前注入架构全景信息
"""

import argparse
import json
import os
import sys
from pathlib import Path

# ============================================================
# 项目结构分析
# ============================================================

def detect_project_structure(root_path):
    """自动检测项目结构"""
    structure = {
        "type": "unknown",
        "languages": [],
        "top_dirs": [],
        "build_files": [],
        "has_tests": False,
        "has_docs": False,
        "layer_dirs": {},
    }
    
    root = Path(root_path)
    
    # 检测语言和构建工具
    indicators = {
        "Python": ["setup.py", "pyproject.toml", "requirements.txt", "Pipfile", "poetry.lock"],
        "JavaScript": ["package.json"],
        "TypeScript": ["tsconfig.json"],
        "Java": ["pom.xml", "build.gradle", "build.gradle.kts"],
        "Go": ["go.mod", "go.sum"],
        "Rust": ["Cargo.toml"],
        "C#": ["*.csproj", "*.sln"],
    }
    
    for lang, files in indicators.items():
        for f in files:
            matches = list(root.glob(f))
            if matches:
                structure["languages"].append(lang)
                for m in matches:
                    structure["build_files"].append(str(m.relative_to(root)))
                break
    
    # 兜底：通过源码文件存在性推断语言（无构建文件的项目）
    if not structure["languages"]:
        # 使用独立 if 以支持多语言项目
        if list(root.glob("**/*.py")):
            structure["languages"].append("Python")
        if list(root.glob("**/*.js")):
            structure["languages"].append("JavaScript")
        if list(root.glob("**/*.ts")):
            structure["languages"].append("TypeScript")
        if list(root.glob("**/*.java")):
            structure["languages"].append("Java")
        if list(root.glob("**/*.go")):
            structure["languages"].append("Go")
        if list(root.glob("**/*.rs")):
            structure["languages"].append("Rust")
    
    # 检测顶级目录
    skip_dirs = {".git", "__pycache__", "node_modules", "venv", ".venv", "dist", "build", 
                 "target", ".codebuddy", ".idea", ".vscode", ".cursor"}
    
    for item in sorted(root.iterdir()):
        if item.is_dir() and item.name not in skip_dirs:
            if not item.name.startswith("."):
                structure["top_dirs"].append(item.name)
    
    # 检测测试目录
    structure["has_tests"] = any(
        d in structure["top_dirs"] for d in ["test", "tests", "spec", "__tests__"]
    ) or any(root.glob("*test*")) or any(root.glob("*_test.*"))
    
    # 检测文档
    structure["has_docs"] = any(
        d in structure["top_dirs"] for d in ["docs", "doc", "documentation"]
    ) or any(root.glob("README*"))
    
    # 检测分层目录（根据常见模式）
    layer_indicators = {
        "domain": ["domain", "core", "entity", "model", "models"],
        "application": ["application", "service", "services", "usecase", "use_cases", "handler", "handlers"],
        "infrastructure": ["infrastructure", "infra", "repository", "repositories", "persistence", "database", "db"],
        "presentation": ["presentation", "controller", "controllers", "api", "web", "ui", "rest", "graphql", "routes", "router"],
    }
    
    for layer, layer_indicator_names in layer_indicators.items():
        found = []
        for d in structure["top_dirs"]:
            for indicator in layer_indicator_names:
                if indicator in d.lower():
                    found.append(d)
                    break
        if found:
            structure["layer_dirs"][layer] = found
    
    # 推断项目类型
    if structure["layer_dirs"]:
        structure["type"] = "layered"
    elif "src" in structure["top_dirs"] or "lib" in structure["top_dirs"]:
        structure["type"] = "src_based"
    else:
        structure["type"] = "flat"
    
    return structure


# ============================================================
# 约束规则提取
# ============================================================

def load_custom_rules(root_path):
    """加载项目自定义规则（v2.0.3: 移除 TOCTOU exists() 检查，仅支持 JSON）
    
    支持的配置文件路径:
      - .code-guardian/rules.json
      - .code-guardian/rules.yaml  (⚠️ 不支持，请使用 JSON)
      - .code-guardian.toml       (⚠️ 不支持，请使用 JSON)
    """
    rules = {"has_custom": False, "rules": []}
    
    config_paths = [
        (Path(root_path) / ".code-guardian" / "rules.json", "json"),
        (Path(root_path) / ".code-guardian" / "rules.yaml", "yaml"),
        (Path(root_path) / ".code-guardian.toml", "toml"),
    ]
    
    for config_path, fmt in config_paths:
        try:
            if fmt == "json":
                with open(config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if "rules" in data:
                    rules["has_custom"] = True
                    rules["rules"] = data["rules"]
            elif fmt in ("yaml", "toml"):
                # YAML/TOML 不支持解析，但检查文件是否存在以给出提示
                try:
                    with open(config_path, "r", encoding="utf-8") as f:
                        _ = f.read(1)  # 仅检查可读性，不实际解析
                    sys.stderr.write(
                        f"[CodeGuard] ⚠️ 发现 {config_path.name} 但仅支持 JSON。"
                        f"请转换为 {config_path.with_suffix('.json')} 格式。\n"
                    )
                except FileNotFoundError:
                    pass
        except FileNotFoundError:
            pass  # 文件不存在，正常跳过（消除 TOCTOU 预检查）
        except json.JSONDecodeError as e:
            sys.stderr.write(f"[CodeGuard] 自定义规则 JSON 解析失败: {config_path} - {e}\n")
        except Exception as e:
            sys.stderr.write(f"[CodeGuard] 加载自定义规则异常: {config_path} - {e}\n")
    
    return rules


def load_skill_rules():
    """加载 Skill 内置的通用架构规则"""
    # 通用规则摘要（精简版，用于注入到 AI 上下文）
    return [
        {
            "id": "SOLID_SRP",
            "name": "单一职责原则",
            "description": "类方法数 ≤15，类代码行数 ≤300（警告）/≤500（阻塞）",
            "severity": "warn"
        },
        {
            "id": "SOLID_DIP",
            "name": "依赖倒置原则",
            "description": "Domain 层不得直接 import Infrastructure 层",
            "severity": "block"
        },
        {
            "id": "LAYER_VIOLATION",
            "name": "分层架构约束",
            "description": "Domain → 不可依赖上层；Application → 只能依赖 Domain",
            "severity": "block"
        },
        {
            "id": "COMPLEXITY_CC",
            "name": "圈复杂度限制",
            "description": "CC >10 警告，CC >15 阻塞",
            "severity": "warn"
        },
        {
            "id": "DUPLICATE_CODE",
            "name": "重复代码检测",
            "description": "连续 6 行相同警告，10 行相同阻塞",
            "severity": "warn"
        },
        {
            "id": "SECURITY_HARDCODED",
            "name": "禁止硬编码密钥",
            "description": "禁止在代码中硬编码密码/API Key/Token",
            "severity": "block"
        },
        {
            "id": "SECURITY_SQL_INJECTION",
            "name": "SQL注入防护",
            "description": "必须使用参数化查询，禁止字符串拼接SQL",
            "severity": "block"
        },
        {
            "id": "SECURITY_COMMAND_INJECTION",
            "name": "命令注入防护",
            "description": "禁止 eval/exec/os.system 接受外部输入",
            "severity": "block"
        },
        {
            "id": "NAMING_CONSISTENCY",
            "name": "命名一致性",
            "description": "同一概念使用统一命名，避免 getUserById/fetchUserById 混用",
            "severity": "info"
        },
        {
            "id": "ERROR_HANDLING",
            "name": "错误处理完整性",
            "description": "禁止空 except 块或仅 print(e) 的异常处理",
            "severity": "warn"
        },
    ]


# ============================================================
# Prompt 生成
# ============================================================

def generate_constraint_prompt(structure, custom_rules, skill_rules):
    """生成可注入到 AI 对话的约束 Prompt"""
    
    lines = []
    
    # === 头部（首因效应：最重要信息放最前面） ===
    lines.append("## ⚠️ 架构约束（生成代码前必须遵守）\n")
    
    # 项目结构感知
    lines.append(f"### 项目结构（{structure['type']} 类型）")
    lines.append(f"- 语言: {', '.join(structure['languages']) if structure['languages'] else '自动检测'}")
    
    if structure["layer_dirs"]:
        lines.append("- 分层目录:")
        for layer, dirs in structure["layer_dirs"].items():
            lines.append(f"  - {layer}: {', '.join(dirs)}")
    else:
        lines.append(f"- 顶级目录: {', '.join(structure['top_dirs']) if structure['top_dirs'] else '无'}")
    
    lines.append("")
    
    # === 核心约束（精简，避免 "Lost in the Middle"） ===
    lines.append("### 必须遵守的约束\n")
    
    block_rules = [r for r in skill_rules if r["severity"] == "block"]
    warn_rules = [r for r in skill_rules if r["severity"] == "warn"]
    
    lines.append("**红线（违反将阻塞合并）：**")
    for r in block_rules:
        lines.append(f"- {r['description']}")
    
    lines.append("\n**警告（违反需解释原因）：**")
    for r in warn_rules:
        lines.append(f"- {r['description']}")
    
    # 自定义规则
    if custom_rules["has_custom"]:
        lines.append("\n**团队自定义规则：**")
        for r in custom_rules["rules"]:
            if isinstance(r, dict):
                lines.append(f"- [{r.get('id', '?')}] {r.get('description', '')}")
    
    lines.append("")
    
    # === 尾部（近因效应：关键提醒放最后） ===
    lines.append("### 生成代码检查清单\n")
    lines.append("在输出代码前，确认以下事项：")
    lines.append("1. [ ] 是否遵循了项目的分层架构？")
    lines.append("2. [ ] 是否有重复代码可以提取？")
    lines.append("3. [ ] 圈复杂度是否控制在 10 以内？")
    lines.append("4. [ ] 是否避免了硬编码密钥/密码？")
    lines.append("5. [ ] 命名是否与项目现有风格一致？")
    lines.append("6. [ ] 异常处理是否完善（非空 except/pass）？")
    
    if structure["has_tests"]:
        lines.append("7. [ ] 是否需要添加对应的测试？")
    
    return "\n".join(lines)


def generate_quick_checklist(structure):
    """生成轻量级检查清单（用于对话中快速提醒）"""
    items = [
        "🏗️ 分层架构：Domain 不依赖 Infrastructure",
        "📏 圈复杂度：CC ≤ 10",
        "🔄 避免重复：DRY 原则",
        "🔒 安全：无硬编码密钥",
        "📝 命名：与现有风格一致",
        "🛡️ 错误处理：非空 except",
    ]
    if structure["has_tests"]:
        items.append("🧪 测试：关键路径有覆盖")
    
    return " | ".join(items)


# ============================================================
# 主流程
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="CodeGuard 架构约束注入器")
    parser.add_argument("--path", default=".", help="项目根路径")
    parser.add_argument("--format", default="prompt", choices=["json", "text", "prompt", "checklist"],
                       help="输出格式: json=原始数据, text=可读摘要, prompt=AI注入格式, checklist=轻量提醒")
    args = parser.parse_args()
    
    root_path = os.path.abspath(args.path)
    if not os.path.isdir(root_path):
        print(f"错误: 路径不存在: {root_path}", file=sys.stderr)
        sys.exit(1)
    
    # 分析项目
    structure = detect_project_structure(root_path)
    custom_rules = load_custom_rules(root_path)
    skill_rules = load_skill_rules()
    
    if args.format == "json":
        output = {
            "structure": structure,
            "custom_rules": custom_rules,
            "skill_rules": skill_rules,
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))
    
    elif args.format == "text":
        print(f"项目类型: {structure['type']}")
        print(f"语言: {', '.join(structure['languages']) if structure['languages'] else '未检测到'}")
        print(f"测试: {'有' if structure['has_tests'] else '无'}")
        print(f"文档: {'有' if structure['has_docs'] else '无'}")
        if structure["layer_dirs"]:
            print("分层目录:")
            for layer, dirs in structure["layer_dirs"].items():
                print(f"  {layer}: {', '.join(dirs)}")
        print(f"\n活跃规则: {len(skill_rules)} 条通用规则", end="")
        if custom_rules["has_custom"]:
            print(f" + {len(custom_rules['rules'])} 条自定义规则")
        else:
            print("（无自定义规则）")
    
    elif args.format == "prompt":
        print(generate_constraint_prompt(structure, custom_rules, skill_rules))
    
    elif args.format == "checklist":
        print(generate_quick_checklist(structure))


if __name__ == "__main__":
    main()
