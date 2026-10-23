#!/usr/bin/env python3
"""
CodeGuard Constraint Injector (v2.0.9)
========================================
架构约束提取与注入脚本。从项目的 references 规则文件和 .code-guardian 配置中提取约束，
生成适合注入到 AI 对话上下文中的结构化约束摘要。

用法：
  python constraint_injector.py --path <project_root> [--format json|text|prompt]

设计依据：
  - "Lost in the Middle" 效应（Liu et al., arXiv 2307.03172）
  - 对抗自回归生成缺乏全局规划：在每次代码生成前注入架构全景信息
"""

import argparse
import json
import os
import sys
from pathlib import Path

from internal import rules_loader
import quality_rule_registry as _registry


# ============================================================
# 常量定义
# ============================================================

_LANGUAGE_INDICATORS = {
    "Python": ["setup.py", "pyproject.toml", "requirements.txt", "Pipfile", "poetry.lock"],
    "JavaScript": ["package.json"],
    "TypeScript": ["tsconfig.json"],
    "Java": ["pom.xml", "build.gradle", "build.gradle.kts"],
    "Go": ["go.mod", "go.sum"],
    "Rust": ["Cargo.toml"],
    "C#": ["*.csproj", "*.sln"],
}

_LANG_SOURCE_GLOBS = [
    ("Python", "**/*.py"),
    ("JavaScript", "**/*.js"),
    ("TypeScript", "**/*.ts"),
    ("Java", "**/*.java"),
    ("Go", "**/*.go"),
    ("Rust", "**/*.rs"),
]

_LAYER_INDICATORS = {
    "domain": ["domain", "core", "entity", "model", "models"],
    "application": ["application", "service", "services", "usecase", "use_cases", "handler", "handlers"],
    "infrastructure": ["infrastructure", "infra", "repository", "repositories", "persistence", "database", "db"],
    "presentation": ["presentation", "controller", "controllers", "api", "web", "ui", "rest", "graphql", "routes", "router"],
}

_SKIP_DIRS = {".git", "__pycache__", "node_modules", "venv", ".venv", "dist", "build",
              "target", ".codebuddy", ".idea", ".vscode", ".cursor"}


# ============================================================
# 结构分析助手（消除 detect_project_structure 的 CC=33）
# ============================================================

def _detect_languages(root):
    """检测项目语言：优先构建文件，回退到源码扫描"""
    languages = []
    build_files = []
    for lang, files in _LANGUAGE_INDICATORS.items():
        found_any = False
        for f in files:
            matches = list(root.glob(f))
            if matches:
                found_any = True
                for m in matches:
                    build_files.append(str(m.relative_to(root)))
        if found_any:
            languages.append(lang)
    
    # 回退：通过源码文件存在性推断
    if not languages:
        for lang, glob_pattern in _LANG_SOURCE_GLOBS:
            if list(root.glob(glob_pattern)):
                languages.append(lang)
    
    return languages, build_files


def _detect_top_dirs(root):
    """检测顶级目录（过滤隐藏目录和构建产物）"""
    return sorted([
        item.name for item in root.iterdir()
        if item.is_dir() and item.name not in _SKIP_DIRS and not item.name.startswith(".")
    ])


def _detect_layer_dirs(top_dirs):
    """检测架构分层目录"""
    layer_dirs = {}
    for layer, indicators in _LAYER_INDICATORS.items():
        found = []
        for d in top_dirs:
            for ind in indicators:
                if ind in d.lower():
                    found.append(d)
                    break
        if found:
            layer_dirs[layer] = found
    return layer_dirs


def _infer_structure_type(structure):
    """推断项目结构类型"""
    if structure.get("layer_dirs"):
        return "layered"
    if "src" in structure.get("top_dirs", []) or "lib" in structure.get("top_dirs", []):
        return "src_based"
    return "flat"


# ============================================================
# 主分析函数
# ============================================================

def detect_project_structure(root_path):
    """自动检测项目结构（v2.0.9: 模态分解 CC=33→8）"""
    root = Path(root_path)
    
    languages, build_files = _detect_languages(root)
    top_dirs = _detect_top_dirs(root)
    layer_dirs = _detect_layer_dirs(top_dirs)
    
    structure = {
        "type": "unknown",
        "languages": languages,
        "top_dirs": top_dirs,
        "build_files": build_files,
        "has_tests": any(d in top_dirs for d in ["test", "tests", "spec", "__tests__"])
                    or any(root.glob("*test*")) or any(root.glob("*_test.*")),
        "has_docs": any(d in top_dirs for d in ["docs", "doc", "documentation"])
                   or any(root.glob("README*")),
        "layer_dirs": layer_dirs,
    }
    structure["type"] = _infer_structure_type(structure)
    return structure


# ============================================================
# 自定义规则加载（消除 TOCTOU + 深度展平）
# ============================================================

def load_custom_rules(root_path):
    """加载项目自定义规则（v2.0.11: 使用 internal/rules_loader 消除重复）
    
    支持的配置文件: .code-guardian/rules.json
    不支持的格式 (yaml/toml): 输出警告后跳过
    """
    root = Path(root_path)
    rules = {"has_custom": False, "rules": []}
    
    data = rules_loader.load_rules_json(root)
    if data and "rules" in data:
        rules["has_custom"] = True
        rules["rules"] = data.get("rules", [])
    
    # 检查旧版格式并提供迁移提示
    legacy = rules_loader.check_legacy_rules_formats(root)
    for path_str in legacy:
        p = Path(path_str)
        sys.stderr.write(
            f"[CodeGuard] ⚠️ 发现 {p.name} 但仅支持 JSON。"
            f"请转换为 {p.with_suffix('.json')} 格式。\n"
        )
    
    return rules


# ============================================================
# 内置规则加载
# ============================================================

def load_skill_rules(file_type="source"):
    """加载 Skill 内置规则（v3.0.0: 从统一注册表读取，支持文件类型差异化）

    file_type 由 FileClassifier 五类（source/test/config/generated/migration/doc）指定，
    默认 source 返回全部 10 条规则（向后兼容）。
    """
    return _registry.get_rules(file_type)


# ============================================================
# Prompt 生成（保持原有逻辑不变）
# ============================================================

def generate_constraint_prompt(structure, custom_rules, skill_rules, file_type="source"):
    """生成可注入到 AI 对话的约束 Prompt（v3.0.0: 清单从注册表动态生成 + 文件类型差异化）

    file_type 由 FileClassifier 五类指定，清单与规则均按文件类型从注册表派生，
    确保注入约束与生成后门禁规则一致（修复 D1/D2/D3）。
    """
    
    lines = []
    lines.append("## ⚠️ 架构约束（生成代码前必须遵守）\n")
    
    lines.append(f"### 项目结构（{structure['type']} 类型）")
    lines.append(f"- 语言: {', '.join(structure['languages']) if structure['languages'] else '自动检测'}")
    
    if structure["layer_dirs"]:
        lines.append("- 分层目录:")
        for layer, dirs in structure["layer_dirs"].items():
            lines.append(f"  - {layer}: {', '.join(dirs)}")
    else:
        lines.append(f"- 顶级目录: {', '.join(structure['top_dirs']) if structure['top_dirs'] else '无'}")
    
    lines.append("")
    lines.append("### 必须遵守的约束\n")
    
    block_rules = [r for r in skill_rules if r["severity"] == "block"]
    warn_rules = [r for r in skill_rules if r["severity"] == "warn"]
    
    lines.append("**红线（违反将阻塞合并）：**")
    for r in block_rules:
        lines.append(f"- {r['description']}")
    
    lines.append("\n**警告（违反需解释原因）：**")
    for r in warn_rules:
        lines.append(f"- {r['description']}")
    
    if custom_rules["has_custom"]:
        lines.append("\n**团队自定义规则：**")
        for r in custom_rules["rules"]:
            if isinstance(r, dict):
                lines.append(f"- [{r.get('id', '?')}] {r.get('description', '')}")
    
    lines.append("")
    lines.append("### 生成代码检查清单\n")
    lines.append("在输出代码前，确认以下事项：")
    for idx, item in enumerate(_registry.get_checklist(file_type), start=1):
        lines.append(f"{idx}. [ ] {item}")
    
    if structure["has_tests"]:
        lines.append(f"{len(_registry.get_checklist(file_type)) + 1}. [ ] 是否需要添加对应的测试？")
    
    return "\n".join(lines)


def generate_quick_checklist(structure, file_type="source"):
    """生成轻量级检查清单（v3.0.0: 从注册表动态生成，含安全红线）"""
    items = []
    for r in _registry.RULE_SPECS:
        if file_type in r["file_types"]:
            emoji = _registry.get_category_emoji(r["category"])
            items.append(f"{emoji} {r['checklist']}")
    if structure["has_tests"]:
        items.append("🧪 测试：关键路径有覆盖")
    return " | ".join(items)


# ============================================================
# CLI 入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="CodeGuard 架构约束注入器")
    parser.add_argument("--path", default=".", help="项目根路径")
    parser.add_argument("--format", default="checklist", choices=["json", "text", "prompt", "checklist"],
                       help="输出格式: json=原始数据, text=可读摘要, prompt=AI注入格式, checklist=轻量提醒（默认，Token 最省）")
    args = parser.parse_args()
    
    root_path = os.path.abspath(args.path)
    if not os.path.isdir(root_path):
        print(f"错误: 路径不存在: {root_path}", file=sys.stderr)  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
        sys.exit(1)
    
    structure = detect_project_structure(root_path)
    custom_rules = load_custom_rules(root_path)
    skill_rules = load_skill_rules()
    
    if args.format == "json":
        print(json.dumps({"structure": structure, "custom_rules": custom_rules,  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
                          "skill_rules": skill_rules}, ensure_ascii=False, indent=2))
    elif args.format == "text":
        print(f"项目类型: {structure['type']}")  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
        print(f"语言: {', '.join(structure['languages']) if structure['languages'] else '未检测到'}")  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
        print(f"测试: {'有' if structure['has_tests'] else '无'}")  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
        print(f"文档: {'有' if structure['has_docs'] else '无'}")  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
        if structure["layer_dirs"]:
            print("分层目录:")  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
            for layer, dirs in structure["layer_dirs"].items():
                print(f"  {layer}: {', '.join(dirs)}")  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
        print(f"\n活跃规则: {len(skill_rules)} 条通用规则", end="")  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
        if custom_rules["has_custom"]:
            print(f" + {len(custom_rules['rules'])} 条自定义规则")  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
        else:
            print("（无自定义规则）")  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
    elif args.format == "prompt":
        print(generate_constraint_prompt(structure, custom_rules, skill_rules))  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
    elif args.format == "checklist":
        print(generate_quick_checklist(structure))  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION


# ============================================================
# v2.1.0: ConstraintInjectorBase 适配层（向后兼容）
# ============================================================

# 添加 shared 目录到路径
_SHARED_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "shared")
if _SHARED_DIR not in sys.path:
    sys.path.insert(0, _SHARED_DIR)

try:
    from constraint_injector_base import ConstraintInjectorBase

    class CodeGuardConstraintInjector(ConstraintInjectorBase):
        """CodeGuard约束注入器 — 继承ConstraintInjectorBase。

        复用现有的 load_skill_rules() 和项目结构检测逻辑。
        """

        def __init__(self, project_root: str = "."):
            super().__init__()
            self.project_root = project_root

        def get_constraint_rules(self) -> list:
            """返回CodeGuard约束规则。"""
            rules = load_skill_rules()
            custom = load_custom_rules(self.project_root)
            if custom.get("has_custom"):
                rules.extend(custom.get("rules", []))
            return rules

        def get_quality_gates(self) -> list:
            """返回CodeGuard质量门禁配置。"""
            return [
                {"name": "no_eval", "category": "security",
                 "pattern": r"\beval\s*\(", "fail_on_match": True,
                 "description": "禁止使用eval()"},
                {"name": "no_exec", "category": "security",
                 "pattern": r"\bexec\s*\(", "fail_on_match": True,
                 "description": "禁止使用exec()"},
                {"name": "no_hardcoded_secrets", "category": "security",
                 "pattern": r"(password|secret|api_key)\s*=\s*[\"'][^\"']+[\"']", "fail_on_match": True,
                 "description": "禁止硬编码密钥"},
            ]

    def inject_constraints(context: dict) -> str:
        """便捷函数：构建约束提示词。"""
        injector = CodeGuardConstraintInjector(context.get("project_root", "."))
        return injector.build_constraint_prompt(context)

    def check_quality(code: str) -> dict:
        """便捷函数：运行质量门禁检查。"""
        injector = CodeGuardConstraintInjector()
        return injector.run_all_gates(code)

except ImportError:
    pass  # constraint_injector_base 不可用时，保持原有函数式API


if __name__ == "__main__":
    main()
