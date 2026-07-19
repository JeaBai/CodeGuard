#!/usr/bin/env python3
"""
CodeGuard Quality Check Script
===================================
AI 代码质量门禁脚本：检测圈复杂度、重复代码、架构分层违规、安全问题。

用法：
  python quality_check.py [--path <dir>] [--mode personal|team] [--format json|text]

输出 JSON 格式的质量报告。退出码 0 = 通过，1 = 警告，2 = 阻塞。

基于验证过的实证数据设计（GitClear 2025, Sonar 2026, DORA 2024, CodeRabbit 2025, Veracode 2025）。
"""

import argparse
import ast
import fnmatch
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

# ============================================================
# 配置：阈值定义（基于实证研究验证）
# ============================================================

THRESHOLDS = {
    "cyclomatic_complexity_warn": 10,
    "cyclomatic_complexity_block": 15,
    "max_function_params_warn": 5,
    "max_function_params_block": 8,
    "max_nesting_warn": 4,
    "max_nesting_block": 6,
    "max_class_lines_warn": 300,
    "max_class_lines_block": 500,
    "max_class_methods_warn": 15,
    "max_interface_methods_warn": 10,
    "duplicate_lines_warn": 6,
    "duplicate_lines_block": 10,
    "cross_file_duplicate_block": 20,
    "max_file_lines_warn": 300,
    "max_file_lines_block": 500,
}

# 架构分层关键词映射
LAYER_PATTERNS = {
    "domain": ["domain", "core", "entity", "model", "repository_interface"],
    "application": ["application", "service", "usecase", "use_case", "handler"],
    "infrastructure": ["infrastructure", "infra", "persistence", "database", "db", "http_client", "external"],
    "presentation": ["presentation", "controller", "api", "web", "ui", "rest", "graphql"],
}

# 安全红线模式
SECURITY_RED_FLAGS = [
    (r'(password|passwd|pwd|secret|api_key|apikey|token)\s*=\s*["\'][^"\']+["\']', "硬编码密钥/密码"),
    (r'execute\s*\(\s*["\'].*%\s*.*["\']', "SQL拼接风险"),
    (r'\.execute\s*\(\s*f["\']', "SQL注入风险(f-string)"),
    (r'eval\s*\(', "eval() 调用风险"),
    (r'exec\s*\(', "exec() 调用风险"),
    (r'os\.system\s*\(', "os.system() 命令注入风险"),
    (r'subprocess\.call\s*\(\s*["\'].*\$', "subprocess 命令注入风险"),
    (r'\.debug\(.*password', "日志泄露密码"),
    (r'\.info\(.*token', "日志泄露token"),
]

# ============================================================
# 工具函数
# ============================================================

def find_source_files(root_path, extensions=None):
    """递归查找源码文件"""
    if extensions is None:
        extensions = {".py", ".js", ".ts", ".java", ".go", ".rs", ".cpp", ".c", ".h", ".cs"}
    
    source_files = []
    skip_dirs = {"node_modules", ".git", "__pycache__", "venv", ".venv", "dist", "build", "target", ".codebuddy"}
    
    for dirpath, dirnames, filenames in os.walk(root_path):
        dirnames[:] = [d for d in dirnames if d not in skip_dirs]
        for f in filenames:
            ext = os.path.splitext(f)[1].lower()
            if ext in extensions:
                source_files.append(os.path.join(dirpath, f))
    return source_files


def compute_cyclomatic_complexity(node):
    """计算 AST 节点的圈复杂度"""
    complexity = 1
    for child in ast.walk(node):
        if isinstance(child, (ast.If, ast.While, ast.For, ast.ExceptHandler,
                              ast.And, ast.Or, ast.comprehension)):
            complexity += 1
        elif isinstance(child, ast.BoolOp):
            complexity += len(child.values) - 1
        elif isinstance(child, ast.Match):
            complexity += 1
    return complexity


def count_lines_of_code(content):
    """统计代码行数（排除空行和纯注释行）"""
    lines = content.split("\n")
    count = 0
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and not stripped.startswith("//"):
            count += 1
    return count


def get_nesting_depth(node):
    """计算 AST 节点的最大嵌套深度"""
    max_depth = 0
    
    class DepthVisitor(ast.NodeVisitor):
        def __init__(self):
            self.current_depth = 0
            self.max_depth = 0
            self.nesting_nodes = {ast.If, ast.For, ast.While, ast.Try, ast.With, ast.Match}
        
        def generic_visit(self, node):
            if type(node) in self.nesting_nodes:
                self.current_depth += 1
                self.max_depth = max(self.max_depth, self.current_depth)
                super().generic_visit(node)
                self.current_depth -= 1
            else:
                super().generic_visit(node)
    
    visitor = DepthVisitor()
    visitor.visit(node)
    return visitor.max_depth


# ============================================================
# 检测模块
# ============================================================

class IssueCollector:
    """问题收集器"""
    def __init__(self):
        self.issues = []
        self.stats = defaultdict(int)
    
    def add(self, severity, category, filepath, line, message, suggestion=""):
        self.issues.append({
            "severity": severity,  # "info", "warn", "block"
            "category": category,
            "file": filepath,
            "line": line,
            "message": message,
            "suggestion": suggestion
        })
        self.stats[severity] += 1
    
    def has_blocks(self):
        return self.stats.get("block", 0) > 0
    
    def has_warns(self):
        return self.stats.get("warn", 0) > 0
    
    def summary(self):
        return {
            "total_issues": len(self.issues),
            "blocks": self.stats.get("block", 0),
            "warnings": self.stats.get("warn", 0),
            "info": self.stats.get("info", 0)
        }


def check_python_file(filepath, collector):
    """对单个 Python 文件执行质量检测"""
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
    except Exception as e:
        collector.add("info", "parse_error", filepath, 0, f"无法读取文件: {e}")
        return
    
    loc = count_lines_of_code(content)
    if loc > THRESHOLDS["max_file_lines_block"]:
        collector.add("block", "file_size", filepath, 0,
                      f"文件代码行数 {loc} > {THRESHOLDS['max_file_lines_block']}（阻塞阈值）",
                      "将文件拆分为多个模块")
    elif loc > THRESHOLDS["max_file_lines_warn"]:
        collector.add("warn", "file_size", filepath, 0,
                      f"文件代码行数 {loc} > {THRESHOLDS['max_file_lines_warn']}（警告阈值）",
                      "考虑拆分大文件")
    
    try:
        tree = ast.parse(content)
    except SyntaxError as e:
        collector.add("warn", "parse_error", filepath, e.lineno or 0, f"语法错误: {e}")
        return
    
    # 遍历所有函数
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            _check_function(node, filepath, collector)
        elif isinstance(node, ast.ClassDef):
            _check_class(node, filepath, collector)
    
    # 安全检查
    _check_security(content, filepath, collector)
    
    # 空异常处理检测
    _check_empty_except(content, filepath, collector)


def _check_function(node, filepath, collector):
    """检测函数质量"""
    func_name = node.name
    
    # 圈复杂度
    cc = compute_cyclomatic_complexity(node)
    if cc > THRESHOLDS["cyclomatic_complexity_block"]:
        collector.add("block", "complexity", filepath, node.lineno,
                      f"函数 '{func_name}' 圈复杂度 {cc} > {THRESHOLDS['cyclomatic_complexity_block']}（阻塞）",
                      "拆分为多个小函数，或使用策略模式")
    elif cc > THRESHOLDS["cyclomatic_complexity_warn"]:
        collector.add("warn", "complexity", filepath, node.lineno,
                      f"函数 '{func_name}' 圈复杂度 {cc} > {THRESHOLDS['cyclomatic_complexity_warn']}（警告）",
                      "考虑拆分为更小的函数")
    
    # 参数数量
    num_params = len(node.args.args)
    if num_params > THRESHOLDS["max_function_params_block"]:
        collector.add("block", "params", filepath, node.lineno,
                      f"函数 '{func_name}' 参数数量 {num_params} > {THRESHOLDS['max_function_params_block']}（阻塞）",
                      "封装为参数对象或数据类")
    elif num_params > THRESHOLDS["max_function_params_warn"]:
        collector.add("warn", "params", filepath, node.lineno,
                      f"函数 '{func_name}' 参数数量 {num_params} > {THRESHOLDS['max_function_params_warn']}（警告）",
                      "考虑使用参数对象")
    
    # 嵌套深度
    depth = get_nesting_depth(node)
    if depth > THRESHOLDS["max_nesting_block"]:
        collector.add("block", "nesting", filepath, node.lineno,
                      f"函数 '{func_name}' 嵌套深度 {depth} > {THRESHOLDS['max_nesting_block']}（阻塞）",
                      "使用 early return 或提取嵌套逻辑为独立函数")
    elif depth > THRESHOLDS["max_nesting_warn"]:
        collector.add("warn", "nesting", filepath, node.lineno,
                      f"函数 '{func_name}' 嵌套深度 {depth} > {THRESHOLDS['max_nesting_warn']}（警告）",
                      "考虑使用 early return 减少嵌套")


def _check_class(node, filepath, collector):
    """检测类质量"""
    class_name = node.name
    
    # 方法数量
    methods = [n for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
               and not n.name.startswith("__")]
    num_methods = len(methods)
    
    if num_methods > THRESHOLDS["max_class_methods_warn"]:
        collector.add("warn", "class_size", filepath, node.lineno,
                      f"类 '{class_name}' 方法数 {num_methods} > {THRESHOLDS['max_class_methods_warn']}（警告）",
                      "检查是否违反单一职责原则，考虑拆分")
    
    # 类代码行数
    class_lines = node.end_lineno - node.lineno + 1 if node.end_lineno else 0
    if class_lines > THRESHOLDS["max_class_lines_block"]:
        collector.add("block", "class_size", filepath, node.lineno,
                      f"类 '{class_name}' 代码行数 {class_lines} > {THRESHOLDS['max_class_lines_block']}（阻塞）",
                      "拆分为多个职责单一的类")
    elif class_lines > THRESHOLDS["max_class_lines_warn"]:
        collector.add("warn", "class_size", filepath, node.lineno,
                      f"类 '{class_name}' 代码行数 {class_lines} > {THRESHOLDS['max_class_lines_warn']}（警告）",
                      "检查是否违反单一职责原则")


def _check_security(content, filepath, collector):
    """安全检查（基于 Veracode 2025: 45% AI代码未通过安全测试）"""
    lines = content.split("\n")
    for i, line in enumerate(lines, 1):
        for pattern, description in SECURITY_RED_FLAGS:
            if re.search(pattern, line, re.IGNORECASE):
                collector.add("block", "security", filepath, i,
                              f"安全问题: {description}",
                              "使用环境变量/密钥管理服务存储凭证，使用参数化查询")


def _check_empty_except(content, filepath, collector):
    """检测空的或过于简单的异常处理"""
    lines = content.split("\n")
    
    # 匹配 except 块后紧跟 pass 或只有 print
    in_except = False
    except_line = 0
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if re.match(r'except\b', stripped):
            in_except = True
            except_line = i
            continue
        if in_except:
            if stripped in ("pass", "") or re.match(r'print\s*\(', stripped):
                collector.add("warn", "error_handling", filepath, except_line,
                              "异常处理过于简单（pass 或仅 print）",
                              "添加适当的日志记录和错误处理逻辑")
            in_except = False


def check_duplicates(source_files, collector):
    """检测重复代码块（支持跨文件检测）"""
    block_map = defaultdict(list)
    
    for filepath in source_files:
        try:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                lines = [l.strip() for l in f.readlines()]
        except Exception:
            continue
        
        for i in range(len(lines)):
            for length in [THRESHOLDS["duplicate_lines_block"], THRESHOLDS["duplicate_lines_warn"]]:
                if i + length <= len(lines):
                    block = "\n".join(lines[i:i+length])
                    if len(block) > 20:  # 忽略过短的块
                        block_map[block].append((filepath, i+1, length))
    
    reported = set()
    for block, occurrences in block_map.items():
        if len(occurrences) > 1:
            # 判断是否跨文件
            unique_files = set(occ[0] for occ in occurrences)
            is_cross_file = len(unique_files) > 1
            
            for filepath, line, length in occurrences:
                key = (filepath, line)
                if key in reported:
                    continue
                reported.add(key)
                
                if is_cross_file and length >= THRESHOLDS["cross_file_duplicate_block"]:
                    severity = "block"
                elif length >= THRESHOLDS["duplicate_lines_block"]:
                    severity = "block"
                else:
                    severity = "warn"
                
                cross_tag = "跨文件" if is_cross_file else "文件内"
                collector.add(severity, "duplication", filepath, line,
                              f"{cross_tag}重复代码块（{length}行），共出现 {len(occurrences)} 次（{len(unique_files)} 个文件）",
                              "提取为共享函数或模块")


# 多语言 import 提取模式
MULTILANG_IMPORT_PATTERNS = [
    # Python: from x import y / import x
    (re.compile(r'(?:from\s+(\S+)\s+import|import\s+(\S+))'), "python"),
    # JS/TS: import ... from 'x' / require('x')
    (re.compile(r'(?:import\s+.*?\s+from\s+["\']([^"\']+)["\']|require\s*\(\s*["\']([^"\']+)["\']\s*\))'), "javascript"),
    # Java: import com.xxx.yyy;
    (re.compile(r'import\s+([\w.]+);'), "java"),
    # Go: import "xxx/yyy" (仅匹配 import 块内的字符串)
    (re.compile(r'import\s+(?:\(\s*)?(?:"([^"]+)"\s*)+\)?|"[^"]+"'), "go"),
    # C#: using xxx.yyy;
    (re.compile(r'using\s+([\w.]+);'), "csharp"),
    # Rust: use xxx::yyy;
    (re.compile(r'use\s+([\w:]+);'), "rust"),
]


def _detect_file_lang(filepath):
    """根据扩展名推断文件语言"""
    ext = os.path.splitext(filepath)[1].lower()
    lang_map = {
        ".py": "python", ".pyx": "python",
        ".js": "javascript", ".mjs": "javascript",
        ".ts": "javascript", ".tsx": "javascript",
        ".java": "java",
        ".go": "go",
        ".cs": "csharp",
        ".rs": "rust",
    }
    return lang_map.get(ext, "unknown")


def check_architecture(source_files, collector):
    """检测架构分层违规（多语言支持）"""
    imports = defaultdict(set)
    
    for filepath in source_files:
        filepath_lower = filepath.lower()
        
        # 推断文件所属层级
        file_layer = _infer_layer(filepath_lower)
        file_lang = _detect_file_lang(filepath)
        
        try:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except Exception:
            continue
        
        # 多语言 import 提取（仅匹配文件对应语言的模式）
        for pattern, lang in MULTILANG_IMPORT_PATTERNS:
            if lang == file_lang:
                for match in pattern.finditer(content):
                    module = match.group(1) or (match.group(2) if match.lastindex and match.lastindex >= 2 else None)
                    if module:
                        imports[filepath].add(module)
                break  # 匹配到语言对应的模式后停止
        
        # 检查分层违规
        for imp in imports[filepath]:
            imp_layer = _infer_layer(imp.lower())
            
            # Domain 层不应依赖 Infrastructure 或 Presentation
            if file_layer == "domain" and imp_layer in ("infrastructure", "presentation"):
                collector.add("block", "architecture", filepath, 0,
                              f"架构违规：Domain 层引用了 {imp_layer} 层 ({imp})",
                              "Domain 层应定义接口，由 Infrastructure 层实现")
            
            # Application 层不应直接依赖 Infrastructure 具体实现
            if file_layer == "application" and imp_layer == "infrastructure":
                collector.add("warn", "architecture", filepath, 0,
                              f"架构警告：Application 层直接引用 Infrastructure 层 ({imp})",
                              "应通过接口/抽象类进行依赖倒置")


def _infer_layer(path_or_module):
    """根据路径或模块名推断架构层级"""
    for layer, patterns in LAYER_PATTERNS.items():
        for p in patterns:
            if p in path_or_module:
                return layer
    return "unknown"


def check_generic_file(filepath, collector, ext):
    """对非 Python 文件执行通用质量检测（文件大小、安全、异常处理）"""
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
    except Exception as e:
        collector.add("info", "parse_error", filepath, 0, f"无法读取文件: {e}")
        return
    
    loc = count_lines_of_code(content)
    if loc > THRESHOLDS["max_file_lines_block"]:
        collector.add("block", "file_size", filepath, 0,
                      f"文件代码行数 {loc} > {THRESHOLDS['max_file_lines_block']}（阻塞阈值）",
                      "将文件拆分为多个模块")
    elif loc > THRESHOLDS["max_file_lines_warn"]:
        collector.add("warn", "file_size", filepath, 0,
                      f"文件代码行数 {loc} > {THRESHOLDS['max_file_lines_warn']}（警告阈值）",
                      "考虑拆分大文件")
    
    # 通用安全检查（适用于所有文本源码文件）
    _check_security(content, filepath, collector)
    
    # 空异常处理检测（多语言支持）
    if ext in (".py", ".js", ".ts", ".java", ".cs", ".go", ".rs", ".cpp", ".c", ".h"):
        _check_empty_except_generic(content, filepath, collector, ext)


def _check_empty_except_generic(content, filepath, collector, ext):
    """多语言空异常处理检测"""
    lines = content.split("\n")
    
    if ext == ".py":
        except_pattern = re.compile(r'except\b')
        empty_body = ("pass", "")
    elif ext in (".js", ".ts"):
        except_pattern = re.compile(r'catch\s*\(')
        empty_body = ("{}", "")
    elif ext == ".java":
        except_pattern = re.compile(r'catch\s*\(')
        empty_body = ("{}", "", "// TODO", "// ignore")
    elif ext in (".cs"):
        except_pattern = re.compile(r'catch\b')
        empty_body = ("{}", "", "// TODO")
    elif ext == ".go":
        except_pattern = re.compile(r'if\s+err\s*!=\s*nil')
        empty_body = ("return",)
    elif ext in (".rs", ".cpp", ".c", ".h"):
        except_pattern = re.compile(r'catch\b')
        empty_body = ("{}", "")
    else:
        return
    
    in_handler = False
    handler_line = 0
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if except_pattern.search(stripped):
            in_handler = True
            handler_line = i
            continue
        if in_handler:
            if stripped in empty_body or re.match(r'print\s*\(', stripped) or \
               (ext == ".go" and stripped in ("return", "return nil", "return err")):
                collector.add("warn", "error_handling", filepath, handler_line,
                              "异常处理过于简单",
                              "添加适当的日志记录和错误处理逻辑")
            in_handler = False


def check_naming_consistency(source_files, collector):
    """检测命名一致性（支持多语言函数声明）"""
    # 收集所有函数名和方法名
    name_map = defaultdict(set)
    
    # 多语言函数声明模式
    func_patterns = [
        (re.compile(r'def\s+(\w+)'), "python"),
        (re.compile(r'(?:async\s+)?function\s+(\w+)'), "javascript"),
        (re.compile(r'(?:public|private|protected|static)?\s*(?:async\s+)?(?:[\w<>\[\]]+\s+)?(\w+)\s*\([^)]*\)\s*\{'), "java/csharp"),
        (re.compile(r'func\s+(?:\(\w+\s+\*?\w+\)\s+)?(\w+)\s*\('), "go"),
        (re.compile(r'fn\s+(\w+)\s*\('), "rust"),
    ]
    
    for filepath in source_files:
        try:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except Exception:
            continue
        
        ext = os.path.splitext(filepath)[1].lower()
        
        # 选择匹配模式
        for pattern, lang in func_patterns:
            for match in pattern.finditer(content):
                func_name = match.group(1)
                if func_name.startswith("__") or func_name.startswith("_"):
                    continue
                # 提取动词前缀
                for prefix in ["get_", "fetch_", "retrieve_", "find_", "query_",
                              "set_", "update_", "modify_", "save_", "create_",
                              "delete_", "remove_", "destroy_",
                              "get", "fetch", "retrieve", "find", "query",
                              "set", "update", "modify", "save", "create",
                              "delete", "remove", "destroy"]:
                    if func_name.lower().startswith(prefix.lower()):
                        suffix = func_name[len(prefix):]
                        name_map[("verb", prefix)].add((suffix, filepath))
                        break
    
    # 检查同一实体使用不同动词前缀
    for (_, prefix), entries in name_map.items():
        suffixes = defaultdict(list)
        for suffix, fpath in entries:
            suffixes[suffix].append(fpath)
        
        for suffix, paths in suffixes.items():
            if len(paths) > 1:
                collector.add("info", "naming", paths[0], 0,
                              f"命名不一致：实体 '{suffix}' 在多处使用前缀 '{prefix}'，"
                              f"请确认是否有更合适的统一命名")


# ============================================================
# 主流程
# ============================================================

def get_changed_files(root_path):
    """通过 git diff 获取变更文件列表（增量模式）
    
    覆盖四种变更场景：
    1. 已提交变更（git diff HEAD）
    2. 未暂存变更（git diff）
    3. 已暂存变更（git diff --cached）
    4. 未跟踪文件（git ls-files --others --exclude-standard）
    """
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
            pass
    
    # 1. 已提交变更（相对于 HEAD）
    _run_git(["git", "diff", "--name-only", "--diff-filter=ACMR", "HEAD"])
    
    # 2. 未暂存变更
    _run_git(["git", "diff", "--name-only"])
    
    # 3. 已暂存但未提交
    _run_git(["git", "diff", "--name-only", "--cached"])
    
    # 4. 未跟踪的新文件
    _run_git(["git", "ls-files", "--others", "--exclude-standard"])
    
    return sorted(all_changed)


def load_custom_quality_rules(root_path):
    """加载 .code-guardian/rules.json 中的自定义质量规则"""
    custom_rules = []
    config_path = Path(root_path) / ".code-guardian" / "rules.json"
    
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if "rules" in data:
                custom_rules = data["rules"]
        except Exception:
            pass
    
    return custom_rules


def check_custom_rules(source_files, custom_rules, collector):
    """根据自定义规则执行检测（声明式模式匹配引擎）
    
    支持的自定义规则格式 (rules.json):
    {
      "rules": [
        {
          "id": "RULE_ID",
          "description": "规则描述",
          "severity": "block|warn|info",
          "target": "file_pattern|layer|language",  // 可选：限定作用域
          "pattern": "regex_pattern",                // 正则表达式
          "message": "违规时输出的消息",
          "suggestion": "修复建议"
        }
      ]
    }
    
    target 支持:
      - file_pattern: 文件名 glob 匹配 (如 "domain/**" 或 "*_controller.py")
      - layer: 架构层级 (domain/application/infrastructure/presentation)
      - language: 编程语言 (python/javascript/java/go/csharp/rust)
      - all: 全部文件
    """
    if not custom_rules:
        return
    
    for rule in custom_rules:
        rule_id = rule.get("id", "?")
        severity = rule.get("severity", "warn")
        description = rule.get("description", "")
        target = rule.get("target", "all")
        pattern_str = rule.get("pattern", "")
        message = rule.get("message", f"自定义规则 [{rule_id}]: {description}")
        suggestion = rule.get("suggestion", "")
        
        if not pattern_str:
            collector.add("info", "custom_rule_config", "", 0,
                          f"自定义规则 [{rule_id}] 缺少 pattern 字段，跳过",
                          "在 rules.json 中为该规则添加 pattern 正则表达式")
            continue
        
        try:
            pattern = re.compile(pattern_str, re.MULTILINE | re.IGNORECASE)
        except re.error as e:
            collector.add("info", "custom_rule_config", "", 0,
                          f"自定义规则 [{rule_id}] 正则表达式无效: {e}",
                          "修正 rules.json 中的 pattern 字段")
            continue
        
        for filepath in source_files:
            # 作用域过滤
            if not _match_target(filepath, target):
                continue
            
            try:
                with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
            except Exception:
                continue
            
            # 执行模式匹配
            for match in pattern.finditer(content):
                line_no = content[:match.start()].count("\n") + 1
                matched_text = match.group(0)[:80]
                collector.add(severity, "custom_rule", filepath, line_no,
                              f"{message} (匹配: {matched_text})",
                              suggestion)


def _match_target(filepath, target):
    """检查文件是否匹配自定义规则的作用域"""
    if target == "all":
        return True
    
    filepath_lower = filepath.lower()
    file_lang = _detect_file_lang(filepath)
    
    # 按语言过滤
    lang_targets = {"python", "javascript", "java", "go", "csharp", "rust"}
    if target in lang_targets:
        return file_lang == target
    
    # 按架构层级过滤
    layer_targets = {"domain", "application", "infrastructure", "presentation"}
    if target in layer_targets:
        return _infer_layer(filepath_lower) == target
    
    # 按文件模式过滤 (glob-like)
    # 支持: "**/domain/**", "*.py", "*_controller.py", "domain/user_*.py"
    pattern_lower = target.lower()
    
    # 简单的 glob 匹配
    if "**" in pattern_lower:
        # **/domain/** → 路径中是否包含 domain/
        parts = pattern_lower.split("**")
        for part in parts:
            part = part.strip("/\\")
            if part and part not in filepath_lower.replace("\\", "/"):
                return False
        return True
    
    if "*" in pattern_lower:
        return fnmatch.fnmatch(os.path.basename(filepath_lower), pattern_lower)
    
    # 直接字符串包含匹配
    return pattern_lower in filepath_lower


def run_quality_check(root_path, mode="personal"):
    """执行完整质量检查
    
    mode 支持: personal, team, diff
    - personal/team: 全量扫描
    - diff: 仅检测 git 变更文件（增量模式）
    """
    collector = IssueCollector()
    
    is_diff = mode == "diff"
    check_mode = "team" if mode == "team" else "personal"
    
    print(f"[CodeGuard] 开始代码质量检测...")
    print(f"[CodeGuard] 模式: {mode}")
    print(f"[CodeGuard] 路径: {root_path}")
    
    if is_diff:
        source_files = get_changed_files(root_path)
        print(f"[CodeGuard] 增量检测：{len(source_files)} 个变更文件")
    else:
        source_files = find_source_files(root_path)
        print(f"[CodeGuard] 全量检测：{len(source_files)} 个源码文件")
    
    if not source_files:
        collector.add("info", "no_files", root_path, 0, "未发现源码文件")
        return collector
    
    # 加载自定义规则
    custom_rules = load_custom_quality_rules(root_path)
    if custom_rules:
        print(f"[code-guardian] 加载 {len(custom_rules)} 条自定义规则")
    
    # 1. 逐文件检测
    for filepath in source_files:
        ext = os.path.splitext(filepath)[1].lower()
        if ext == ".py":
            check_python_file(filepath, collector)
        else:
            check_generic_file(filepath, collector, ext)
    
    # 2. 跨文件检测
    check_duplicates(source_files, collector)
    check_architecture(source_files, collector)
    
    if check_mode == "team":
        check_naming_consistency(source_files, collector)
    
    # 3. 自定义规则检测（所有模式均执行）
    check_custom_rules(source_files, custom_rules, collector)
    
    print(f"\n[CodeGuard] 检测完成: {collector.summary()}")
    return collector


def output_json(collector):
    """输出 JSON 格式"""
    result = {
        "summary": collector.summary(),
        "issues": sorted(collector.issues, key=lambda x: (
            {"block": 0, "warn": 1, "info": 2}[x["severity"]],
            x["category"],
            x["file"],
            x["line"]
        ))
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


def output_text(collector):
    """输出可读文本格式"""
    issues = sorted(collector.issues, key=lambda x: (
        {"block": 0, "warn": 1, "info": 2}[x["severity"]],
        x["category"],
        x["file"],
        x["line"]
    ))
    
    for issue in issues:
        prefix = {"block": "[BLOCK]", "warn": "[WARN]", "info": "[INFO]"}[issue["severity"]]
        print(f"\n{prefix} {issue['category']}")
        print(f"  文件: {issue['file']}:{issue['line']}")
        print(f"  问题: {issue['message']}")
        if issue["suggestion"]:
            print(f"  建议: {issue['suggestion']}")


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
        print(f"错误: 路径不存在: {root_path}", file=sys.stderr)
        sys.exit(1)
    
    collector = run_quality_check(root_path, args.mode)
    
    if args.format == "json":
        output_json(collector)
    else:
        output_text(collector)
    
    # 退出码
    if collector.has_blocks():
        sys.exit(2)  # 阻塞
    elif collector.has_warns():
        sys.exit(1)  # 警告
    else:
        sys.exit(0)  # 通过


if __name__ == "__main__":
    main()
