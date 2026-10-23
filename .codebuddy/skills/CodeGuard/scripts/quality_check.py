#!/usr/bin/env python3
"""
CodeGuard Quality Check — 薄编排器入口 (v2.0.10)
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
from pathlib import Path

# v2.0.14: Windows GBK 编码兼容层 — 所有 stdout/stderr 强制 UTF-8
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding='utf-8', errors='replace')
    except (AttributeError, OSError):
        pass

import quality_core as _core
import quality_checks as _checks
import quality_security as _security
import quality_dup as _dup
import quality_arch as _arch
import quality_modular as _modular
import quality_custom as _custom

# v2.1.0: 门禁级别动态切换
apply_gate_level = _core.apply_gate_level  # codeguard: ignore GOLD_NO_GLOBAL_STATE
get_gate_level_from_rules = _core.get_gate_level_from_rules  # codeguard: ignore GOLD_NO_GLOBAL_STATE

# ============================================================
# 向后兼容：重新导出所有公开符号
# ============================================================

# core
THRESHOLDS = _core.THRESHOLDS
LAYER_PATTERNS = _core.LAYER_PATTERNS
SECURITY_RED_FLAGS = _core.SECURITY_RED_FLAGS
_log = _core._log  # codeguard: ignore GOLD_NO_GLOBAL_STATE
find_source_files = _core.find_source_files  # codeguard: ignore GOLD_NO_GLOBAL_STATE
compute_cyclomatic_complexity = _core.compute_cyclomatic_complexity  # codeguard: ignore GOLD_NO_GLOBAL_STATE
count_lines_of_code = _core.count_lines_of_code  # codeguard: ignore GOLD_NO_GLOBAL_STATE
get_nesting_depth = _core.get_nesting_depth  # codeguard: ignore GOLD_NO_GLOBAL_STATE
strip_comments_and_strings = _core.strip_comments_and_strings  # codeguard: ignore GOLD_NO_GLOBAL_STATE
IssueCollector = _core.IssueCollector
FileClassifier = _core.FileClassifier
should_skip_category = _core.should_skip_category  # codeguard: ignore GOLD_NO_GLOBAL_STATE

# checks
check_python_file = _checks.check_python_file  # codeguard: ignore GOLD_NO_GLOBAL_STATE
check_javascript_file = _checks.check_javascript_file  # codeguard: ignore GOLD_NO_GLOBAL_STATE
check_java_file = _checks.check_java_file  # codeguard: ignore GOLD_NO_GLOBAL_STATE
check_go_file = _checks.check_go_file  # codeguard: ignore GOLD_NO_GLOBAL_STATE
check_csharp_file = _checks.check_csharp_file  # codeguard: ignore GOLD_NO_GLOBAL_STATE
check_generic_file = _checks.check_generic_file  # codeguard: ignore GOLD_NO_GLOBAL_STATE
check_c_file = _checks.check_c_file  # codeguard: ignore GOLD_NO_GLOBAL_STATE

# security
_check_security = _security._check_security  # codeguard: ignore GOLD_NO_GLOBAL_STATE
_check_empty_except = _security._check_empty_except  # codeguard: ignore GOLD_NO_GLOBAL_STATE
_check_empty_except_generic = _security._check_empty_except_generic  # codeguard: ignore GOLD_NO_GLOBAL_STATE

# dup
check_duplicates = _dup.check_duplicates  # codeguard: ignore GOLD_NO_GLOBAL_STATE

# arch
MULTILANG_IMPORT_PATTERNS = _arch.MULTILANG_IMPORT_PATTERNS
_detect_file_lang = _arch._detect_file_lang  # codeguard: ignore GOLD_NO_GLOBAL_STATE
DependencyGraph = _arch.DependencyGraph
build_dependency_graph = _arch.build_dependency_graph  # codeguard: ignore GOLD_NO_GLOBAL_STATE
check_architecture = _arch.check_architecture  # codeguard: ignore GOLD_NO_GLOBAL_STATE
check_modularity = _modular.check_modularity  # codeguard: ignore GOLD_NO_GLOBAL_STATE
_infer_layer = _arch._infer_layer  # codeguard: ignore GOLD_NO_GLOBAL_STATE

# custom
load_custom_quality_rules = _custom.load_custom_quality_rules  # codeguard: ignore GOLD_NO_GLOBAL_STATE
check_custom_rules = _custom.check_custom_rules  # codeguard: ignore GOLD_NO_GLOBAL_STATE
check_naming_consistency = _custom.check_naming_consistency  # codeguard: ignore GOLD_NO_GLOBAL_STATE
_match_target = _custom._match_target  # codeguard: ignore GOLD_NO_GLOBAL_STATE


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
    ".c":    check_c_file,
    ".cpp":  check_c_file,
    ".h":    check_c_file,
}


# ============================================================
# 主编排器
# ============================================================

def run_quality_check(root_path, mode="personal"):
    """执行完整质量检查（v2.0.10: 模块化编排 + 派发表消除 if/elif 链）"""
    collector = IssueCollector()
    
    is_diff = mode == "diff"
    check_mode = "team" if mode == "team" else "personal"
    
    _log(f"[CodeGuard] 开始代码质量检测...")
    _log(f"[CodeGuard] 模式: {mode}")
    _log(f"[CodeGuard] 路径: {root_path}")

    # v2.1.0: 从 rules.json 读取 _level 字段并动态切换门禁级别阈值
    try:
        gate_level, gate_thresholds = get_gate_level_from_rules(root_path)
        apply_gate_level(gate_level, gate_thresholds)
    except (OSError, ValueError, RuntimeError):
        # 无 rules.json 时使用默认金级阈值
        pass

    # v2.2.0: 从 rules.json 读取 _c_dialect 字段并设置 C 方言显式覆盖
    try:
        import json as _json  # codeguard: ignore GOLD_NO_GLOBAL_STATE
        rules_path = os.path.join(root_path, ".code-guardian", "rules.json")
        with open(rules_path, "r", encoding="utf-8") as _f:
            _rules_data = _json.load(_f)
        _explicit_dialect = _rules_data.get("_c_dialect", "auto")
        try:
            import quality_c_dialect as _c_dialect
            _c_dialect.set_explicit_dialect(_explicit_dialect)
        except ImportError:
            pass
        if _explicit_dialect != "auto":
            _log(f"[CodeGuard] C 方言显式覆盖: {_explicit_dialect}")
    except (OSError, ValueError, KeyError):
        pass

    # 加载自定义规则 + 阈值覆盖 + 忽略路径（必须在 find_source_files 之前）
    try:
        custom_rules, custom_thresholds, ignore_patterns = load_custom_quality_rules(root_path)
    except (OSError, ValueError, RuntimeError) as e:
        _log(f"[CodeGuard] 自定义规则加载失败: {e}")
        custom_rules, custom_thresholds, ignore_patterns = [], None, []
    if ignore_patterns:
        _log(f"[CodeGuard] 📂 忽略路径模式 {len(ignore_patterns)} 条: {', '.join(ignore_patterns[:5])}"
             f"{'...' if len(ignore_patterns) > 5 else ''}")

    if is_diff:
        source_files = get_changed_files(root_path)
        _log(f"[CodeGuard] 增量检测：{len(source_files)} 个变更文件")
    else:
        source_files = find_source_files(root_path, ignore_patterns=ignore_patterns)
        _log(f"[CodeGuard] 全量检测：{len(source_files)} 个源码文件")
    
    if not source_files:
        collector.add("info", "no_files", root_path, 0, "未发现源码文件")
        return collector
    
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
    # v3.1.0: 模块化与接口设计（《模块化与接口设计手册》可检测部分）
    check_modularity(source_files, collector, root_path)
    
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
    print(json.dumps(result, ensure_ascii=False, indent=2))  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION


def output_text(collector):
    """输出可读文本格式"""
    issues = sorted(collector.issues, key=lambda x: (
        {"block": 0, "warn": 1, "info": 2}[x["severity"]],
        x["category"], x["file"], x["line"]
    ))
    for issue in issues:
        prefix = {"block": "[BLOCK]", "warn": "[WARN]", "info": "[INFO]"}[issue["severity"]]
        print(f"\n{prefix} {issue['category']}  (置信度: {issue.get('confidence', '?')}%)")  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
        print(f"  文件: {issue['file']}:{issue['line']}")  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
        print(f"  问题: {issue['message']}")  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
        if issue["suggestion"]:
            print(f"  建议: {issue['suggestion']}")  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION


# ============================================================
# CLI 入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="CodeGuard 代码质量检测")
    parser.add_argument("--path", default=".", help="项目根路径")
    parser.add_argument("--mode", default="personal",
                       choices=["personal", "team", "diff", "test-coverage"],
                       help="检测模式: personal(个人全量) / team(团队全量) / "
                            "diff(增量仅变更文件) / test-coverage(覆盖率门禁)")
    parser.add_argument("--coverage-threshold", type=int, default=80,
                       help="test-coverage 模式的覆盖率阈值（默认 80）")
    parser.add_argument("--format", default="json", choices=["json", "text"],
                       help="输出格式")
    args = parser.parse_args()
    
    root_path = os.path.abspath(args.path)
    if not os.path.isdir(root_path):
        _log(f"错误: 路径不存在: {root_path}")
        sys.exit(1)

    if args.mode == "test-coverage":
        import quality_coverage as _cov
        result = _cov.run_test_coverage(Path(root_path), args.coverage_threshold)
        if args.format == "json":
            print(json.dumps(result, ensure_ascii=False, indent=2))  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
        else:
            for issue in result.get('issues', []):
                tag = f"[{issue['severity'].upper():5}]"
                print(f"{tag} {issue.get('rule', '')}")  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
                print(f"        {issue['message']}")  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
                if issue.get('suggestion'):
                    print(f"        修复: {issue['suggestion']}")  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
            pct = result['line_rate'] * 100
            print(f"\n覆盖率门禁: {pct:.0f}% (阈值 {args.coverage_threshold}%) "  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
                  f"→ 退出码 {result['exit_code']}")
        sys.exit(result['exit_code'])
    
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
