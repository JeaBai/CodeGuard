#!/usr/bin/env python3
"""
CodeGuard Quality Check — 薄编排器入口 (v2.0.9)
=================================================
模块化重构：编排 6 个子模块 → 全量/增量/金级门禁检测。

用法：
  python quality_check.py [--path <dir>] [--mode personal|team] [--format json|text]

子模块：
  quality_core     — 阈值/日志/IssueCollector/FileClassifier/strip_comments
  quality_checks   — 多语言复杂度/嵌套/参数/Python AST 检测
  quality_security — 安全检查(三扫描) + 异常处理空块检测
  quality_dup      — 文件内/跨文件重复代码检测
  quality_arch     — 依赖图/架构分层违规/循环依赖
  quality_custom   — 自定义规则加载/模式匹配/命名一致性
"""

import argparse
import json
import os
import subprocess
import sys

import quality_core as _core
import quality_checks as _checks
import quality_security as _security
import quality_dup as _dup
import quality_arch as _arch
import quality_custom as _custom

# ============================================================
# 向后兼容：重新导出所有公开符号
# ============================================================

# core
THRESHOLDS = _core.THRESHOLDS
LAYER_PATTERNS = _core.LAYER_PATTERNS
SECURITY_RED_FLAGS = _core.SECURITY_RED_FLAGS
_log = _core._log
find_source_files = _core.find_source_files
compute_cyclomatic_complexity = _core.compute_cyclomatic_complexity
count_lines_of_code = _core.count_lines_of_code
get_nesting_depth = _core.get_nesting_depth
strip_comments_and_strings = _core.strip_comments_and_strings
IssueCollector = _core.IssueCollector
FileClassifier = _core.FileClassifier
should_skip_category = _core.should_skip_category

# checks
check_python_file = _checks.check_python_file
check_javascript_file = _checks.check_javascript_file
check_java_file = _checks.check_java_file
check_go_file = _checks.check_go_file
check_csharp_file = _checks.check_csharp_file
check_generic_file = _checks.check_generic_file

# security
_check_security = _security._check_security
_check_empty_except = _security._check_empty_except
_check_empty_except_generic = _security._check_empty_except_generic

# dup
check_duplicates = _dup.check_duplicates

# arch
MULTILANG_IMPORT_PATTERNS = _arch.MULTILANG_IMPORT_PATTERNS
_detect_file_lang = _arch._detect_file_lang
DependencyGraph = _arch.DependencyGraph
build_dependency_graph = _arch.build_dependency_graph
check_architecture = _arch.check_architecture
_infer_layer = _arch._infer_layer

# custom
load_custom_quality_rules = _custom.load_custom_quality_rules
check_custom_rules = _custom.check_custom_rules
check_naming_consistency = _custom.check_naming_consistency
_match_target = _custom._match_target


# ============================================================
# 变更文件获取（增量模式）
# ============================================================

def get_changed_files(root_path):
    """通过 git diff 获取变更文件列表（增量模式，覆盖 4 种变更源）"""
    extensions = {".py", ".js", ".ts", ".java", ".go", ".rs", ".cpp", ".c", ".h", ".cs"}
    all_changed = set()
    
    def _run_git(args):
        try:
            result = subprocess.run(args, capture_output=True, text=True,
                                    cwd=root_path, timeout=10)
            if result.returncode == 0:
                for f in result.stdout.strip().split("\n"):
                    f = f.strip()
                    if f:
                        full_path = os.path.join(root_path, f)
                        if os.path.splitext(f)[1].lower() in extensions and os.path.isfile(full_path):
                            all_changed.add(full_path)
        except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
            _log(f"[CodeGuard] git 命令失败 (args={args[0]!r}): 跳过该变更源")
    
    _run_git(["git", "diff", "--name-only", "--diff-filter=ACMR", "HEAD"])
    _run_git(["git", "diff", "--name-only"])
    _run_git(["git", "diff", "--name-only", "--cached"])
    _run_git(["git", "ls-files", "--others", "--exclude-standard"])
    
    return sorted(all_changed)


# ============================================================
# 多语言文件派发表（消除长 if/elif 链）
# ============================================================

_FILE_CHECKERS = {
    ".py":  check_python_file,
    ".js":  lambda fp, c: check_javascript_file(fp, c, ".js"),
    ".ts":  lambda fp, c: check_javascript_file(fp, c, ".ts"),
    ".mjs": lambda fp, c: check_javascript_file(fp, c, ".mjs"),
    ".java": check_java_file,
    ".go":   check_go_file,
    ".cs":   check_csharp_file,
}


# ============================================================
# 主编排器
# ============================================================

def run_quality_check(root_path, mode="personal"):
    """执行完整质量检查（v2.0.9: 模块化编排 + 派发表消除 if/elif 链）"""
    collector = IssueCollector()
    
    is_diff = mode == "diff"
    check_mode = "team" if mode == "team" else "personal"
    
    _log(f"[CodeGuard] 开始代码质量检测...")
    _log(f"[CodeGuard] 模式: {mode}")
    _log(f"[CodeGuard] 路径: {root_path}")
    
    if is_diff:
        source_files = get_changed_files(root_path)
        _log(f"[CodeGuard] 增量检测：{len(source_files)} 个变更文件")
    else:
        source_files = find_source_files(root_path)
        _log(f"[CodeGuard] 全量检测：{len(source_files)} 个源码文件")
    
    if not source_files:
        collector.add("info", "no_files", root_path, 0, "未发现源码文件")
        return collector
    
    # 加载自定义规则 + 阈值覆盖
    custom_rules, custom_thresholds = load_custom_quality_rules(root_path)
    if custom_thresholds:
        overridden = {k: v for k, v in custom_thresholds.items() if THRESHOLDS.get(k) != v}
        THRESHOLDS.update(custom_thresholds)
        if overridden:
            _log(f"[CodeGuard] 🔧 阈值覆盖 {len(overridden)} 项: "
                 f"{', '.join(f'{k}={v}' for k, v in sorted(overridden.items()))}")
    if custom_rules:
        _log(f"[CodeGuard] 加载 {len(custom_rules)} 条自定义规则")
    
    # 1. 逐文件检测（派发表消除 if/elif 链）
    for filepath in source_files:
        ext = os.path.splitext(filepath)[1].lower()
        checker = _FILE_CHECKERS.get(ext, 
            lambda fp, c, e=ext: check_generic_file(fp, c, e))
        checker(filepath, collector)
    
    # 2. 跨文件检测
    check_duplicates(source_files, collector)
    check_architecture(source_files, collector)
    
    if check_mode == "team":
        check_naming_consistency(source_files, collector)
    
    # 3. 自定义规则
    check_custom_rules(source_files, custom_rules, collector)
    
    _log(f"\n[CodeGuard] 检测完成: {collector.summary()}")
    return collector


# ============================================================
# 输出格式化
# ============================================================

def output_json(collector):
    """输出 JSON 格式（v2.0: 包含置信度）"""
    result = {
        "summary": collector.summary(),
        "issues": sorted(collector.issues, key=lambda x: (
            {"block": 0, "warn": 1, "info": 2}[x["severity"]],
            x["category"], x["file"], x["line"]
        ))
    }
    confidences = [i.get("confidence", 80) for i in collector.issues]
    result["confidence_stats"] = {
        "avg": round(sum(confidences) / len(confidences), 1) if confidences else 0,
        "min": min(confidences) if confidences else 0,
        "max": max(confidences) if confidences else 0,
        "distribution": {
            "90-100": len([c for c in confidences if c >= 90]),
            "80-89": len([c for c in confidences if 80 <= c < 90]),
            "70-79": len([c for c in confidences if 70 <= c < 80]),
            "60-69": len([c for c in confidences if c < 70]),
        }
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


def output_text(collector):
    """输出可读文本格式"""
    issues = sorted(collector.issues, key=lambda x: (
        {"block": 0, "warn": 1, "info": 2}[x["severity"]],
        x["category"], x["file"], x["line"]
    ))
    for issue in issues:
        prefix = {"block": "[BLOCK]", "warn": "[WARN]", "info": "[INFO]"}[issue["severity"]]
        print(f"\n{prefix} {issue['category']}  (置信度: {issue.get('confidence', '?')}%)")
        print(f"  文件: {issue['file']}:{issue['line']}")
        print(f"  问题: {issue['message']}")
        if issue["suggestion"]:
            print(f"  建议: {issue['suggestion']}")


# ============================================================
# CLI 入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="CodeGuard 代码质量检测")
    parser.add_argument("--path", default=".", help="项目根路径")
    parser.add_argument("--mode", default="personal", choices=["personal", "team", "diff"],
                       help="检测模式: personal(个人全量) / team(团队全量) / diff(增量仅变更文件)")
    parser.add_argument("--format", default="json", choices=["json", "text"],
                       help="输出格式")
    args = parser.parse_args()
    
    root_path = os.path.abspath(args.path)
    if not os.path.isdir(root_path):
        _log(f"错误: 路径不存在: {root_path}")
        sys.exit(1)
    
    collector = run_quality_check(root_path, args.mode)
    
    if args.format == "json":
        output_json(collector)
    else:
        output_text(collector)
    
    if collector.has_blocks():
        sys.exit(2)
    elif collector.has_warns():
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
