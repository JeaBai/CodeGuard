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

def _log(msg):
    """统一日志输出到 stderr（v2.0.3: 替代散落的 print(..., file=sys.stderr)）
    
    所有诊断/进度日志经由本函数写入 stderr，确保：
    - MCP 模式下不污染 JSON-RPC stdio 通道
    - CLI 终端下进度消息仍可见
    - 统一前缀便于日志过滤
    """
    sys.stderr.write(f"{msg}\n")
    sys.stderr.flush()


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
    """问题收集器（v2.0: 支持置信度评分）

    置信度评分标准（参考 mrzadexinho/codeguard 设计）：
      - 90-100: 确定 — AST 精确分析
      - 80-89:  高   — 剥离注释和字符串后的正则匹配
      - 70-79:  中   — 原始正则匹配
      - 60-69:  低   — 启发式/统计推断
      - <60:    不确定 — 仅供参考
    """
    def __init__(self):
        self.issues = []
        self.stats = defaultdict(int)
        # 默认置信度矩阵（按检测类别）
        self.confidence_base = {
            "complexity": 90,      # AST 精确
            "complexity_regex": 80, # 剥离后正则近似
            "nesting": 90,
            "nesting_regex": 80,
            "params": 90,
            "params_regex": 80,
            "class_size": 85,
            "class_size_regex": 75,
            "file_size": 95,
            "security": 85,        # 剥离后正则
            "security_raw": 70,    # 原始正则（含注释噪音）
            "duplication": 85,
            "architecture": 90,    # 依赖图分析
            "architecture_cycle": 95,  # 循环依赖高度确定
            "architecture_regex": 78,
            "error_handling": 82,
            "naming": 75,
            "custom_rule": 85,
            "parse_error": 95,
            "custom_rule_config": 95,
            "no_files": 95,
        }
    
    def add(self, severity, category, filepath, line, message, suggestion="", confidence=None):
        if confidence is None:
            # 从矩阵获取默认置信度
            confidence = self.confidence_base.get(category, 80)
        
        self.issues.append({
            "severity": severity,
            "category": category,
            "file": filepath,
            "line": line,
            "message": message,
            "suggestion": suggestion,
            "confidence": confidence
        })
        self.stats[severity] += 1
    
    def has_blocks(self):
        return self.stats.get("block", 0) > 0
    
    def has_warns(self):
        return self.stats.get("warn", 0) > 0
    
    def summary(self):
        # 计算平均置信度
        avg_conf = 0
        if self.issues:
            avg_conf = sum(i.get("confidence", 80) for i in self.issues) // len(self.issues)
        return {
            "total_issues": len(self.issues),
            "blocks": self.stats.get("block", 0),
            "warnings": self.stats.get("warn", 0),
            "info": self.stats.get("info", 0),
            "avg_confidence": avg_conf
        }


# ============================================================
# 文件类型分类器（v2.0: 按文件类型调整规则行为）
# 参考 mrzadexinho/codeguard 的文件类型感知设计
# ============================================================

class FileClassifier:
    """文件类型分类器
    - source:    业务源代码 → 全量检测
    - test:      测试文件 → 跳过安全规则，降低复杂度阈值
    - config:    配置文件 → 跳过圈复杂度，保留安全检测
    - generated: 自动生成的代码 → 跳过所有检测，仅标记
    - migration: 数据库迁移 → 跳过复杂度，保留 SQL 注入检测
    - doc:       文档/标记文件 → 全部跳过
    """
    
    def __init__(self):
        pass
    
    @staticmethod
    def classify(file_path):
        """根据文件路径和内容特征分类"""
        path_lower = file_path.lower()
        name = os.path.basename(path_lower)
        ext = os.path.splitext(path_lower)[1].lower()
        
        # 文档
        if ext == ".md" or "documentation" in path_lower:
            return "doc"
        
        # 测试文件（路径或命名）
        if any(p in path_lower for p in ["/test/", "/tests/", "/spec/", "/__tests__/",
                                          "/testing/", "/fixtures/", "/mocks/", "/stubs/"]):
            return "test"
        if name.startswith("test_") or name.endswith("_test.py") or \
           name.endswith(".test.js") or name.endswith(".spec.js") or \
           name.endswith(".test.ts") or name.endswith(".spec.ts") or \
           name.endswith("Test.java") or name.endswith("Tests.java") or \
           name.endswith("_test.go") or name.endswith("_test.rs"):
            return "test"
        
        # 生成代码
        if any(kw in name for kw in ["generated", "_pb2", "_grpc", ".pb.", "auto_generated", "_generated"]):
            return "generated"
        if any(kw in path_lower for kw in ["/generated/", "/gen/", "/out/", "/dist/", "/build/",
                                            "/node_modules/", "/vendor/", "/third_party/"]):
            return "generated"
        
        # 配置文件
        if ext in (".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".env", ".xml"):
            if "package.json" in name or "tsconfig" in name or "docker" in name:
                return "config"
        
        # 数据库迁移
        if any(kw in path_lower for kw in ["/migration/", "/migrations/", "/migrate/", "/schema/"]):
            return "migration"
        if ext == ".sql":
            return "migration"
        
        return "source"
    
    @staticmethod
    def get_rule_adjustments(file_type):
        """返回规则调整建议
        返回 dict: {"skip_categories": [...], "lower_thresholds": {...}, "note": "..."}
        """
        if file_type == "test":
            return {
                "skip_categories": ["security"],  # 测试文件跳过安全检测
                "lower_thresholds": {"complexity": -3, "params": -2},  # 测试函数允许更高复杂度
                "file_label": "[TEST]"
            }
        elif file_type == "config":
            return {
                "skip_categories": ["complexity", "nesting", "params", "class_size", "duplication"],
                "note": "配置文件仅执行安全检测",
                "file_label": "[CONFIG]"
            }
        elif file_type == "generated":
            return {
                "skip_categories": ["complexity", "nesting", "params", "class_size", "duplication",
                                    "architecture", "naming", "error_handling", "security"],
                "note": "生成代码不执行检测，仅标记为不可维护",
                "file_label": "[GENERATED]"
            }
        elif file_type == "migration":
            return {
                "skip_categories": ["complexity", "nesting", "params", "class_size", "naming"],
                "note": "迁移脚本仅执行 SQL 注入检测",
                "file_label": "[MIGRATION]"
            }
        elif file_type == "doc":
            return {
                "skip_categories": ["*"],
                "note": "文档文件不执行检测",
                "file_label": "[DOC]"
            }
        else:  # source
            return {
                "skip_categories": [],
                "file_label": "[SOURCE]"
            }


def _should_skip_category(file_type, category):
    """根据文件类型判断是否应跳过某类检测"""
    adjustments = FileClassifier.get_rule_adjustments(file_type)
    skipped = adjustments.get("skip_categories", [])
    return category in skipped or "*" in skipped


def check_python_file(filepath, collector):
    """对单个 Python 文件执行质量检测（v2.0: 文件类型感知 + 置信度评分）"""
    file_type = FileClassifier.classify(filepath)
    
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
    except Exception as e:
        collector.add("info", "parse_error", filepath, 0, f"无法读取文件: {e}")
        return
    
    # 生成代码/文档：仅标记，跳过检测
    if file_type in ("generated", "doc"):
        if file_type == "generated":
            collector.add("info", "file_type", filepath, 0,
                         "[GENERATED] 自动生成文件，跳过质量检测",
                         "如需检测生成代码，请在 FileClassifier 中移除该路径")
        return
    
    loc = count_lines_of_code(content)
    _check_file_size(loc, filepath, collector)
    
    try:
        tree = ast.parse(content)
    except SyntaxError as e:
        collector.add("warn", "parse_error", filepath, e.lineno or 0, f"语法错误: {e}")
        return
    
    # 遍历所有函数
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            _check_function(node, filepath, collector, file_type)
        elif isinstance(node, ast.ClassDef):
            _check_class(node, filepath, collector, file_type)
    
    # 安全检查（v2.0.6: 传入 file_type 避免冗余 classify）
    _check_security(content, filepath, collector, file_type=file_type)
    
    # 空异常处理检测
    _check_empty_except(content, filepath, collector, file_type)


def _check_function(node, filepath, collector, file_type="source"):
    """检测函数质量（v2.0: 置信度评分）"""
    func_name = node.name
    
    # 圈复杂度（AST 精确，置信度 90）
    cc = compute_cyclomatic_complexity(node)
    if cc > THRESHOLDS["cyclomatic_complexity_block"]:
        collector.add("block", "complexity", filepath, node.lineno,
                      f"函数 '{func_name}' 圈复杂度 {cc} > {THRESHOLDS['cyclomatic_complexity_block']}（阻塞）",
                      "拆分为多个小函数，或使用策略模式",
                      confidence=90)
    elif cc > THRESHOLDS["cyclomatic_complexity_warn"]:
        collector.add("warn", "complexity", filepath, node.lineno,
                      f"函数 '{func_name}' 圈复杂度 {cc} > {THRESHOLDS['cyclomatic_complexity_warn']}（警告）",
                      "考虑拆分为更小的函数",
                      confidence=90)
    
    # 参数数量（AST 精确，置信度 92）
    num_params = len(node.args.args)
    if num_params > THRESHOLDS["max_function_params_block"]:
        collector.add("block", "params", filepath, node.lineno,
                      f"函数 '{func_name}' 参数数量 {num_params} > {THRESHOLDS['max_function_params_block']}（阻塞）",
                      "封装为参数对象或数据类",
                      confidence=92)
    elif num_params > THRESHOLDS["max_function_params_warn"]:
        collector.add("warn", "params", filepath, node.lineno,
                      f"函数 '{func_name}' 参数数量 {num_params} > {THRESHOLDS['max_function_params_warn']}（警告）",
                      "考虑使用参数对象",
                      confidence=92)
    
    # 嵌套深度（AST 精确，置信度 90）
    depth = get_nesting_depth(node)
    if depth > THRESHOLDS["max_nesting_block"]:
        collector.add("block", "nesting", filepath, node.lineno,
                      f"函数 '{func_name}' 嵌套深度 {depth} > {THRESHOLDS['max_nesting_block']}（阻塞）",
                      "使用 early return 或提取嵌套逻辑为独立函数",
                      confidence=90)
    elif depth > THRESHOLDS["max_nesting_warn"]:
        collector.add("warn", "nesting", filepath, node.lineno,
                      f"函数 '{func_name}' 嵌套深度 {depth} > {THRESHOLDS['max_nesting_warn']}（警告）",
                      "考虑使用 early return 减少嵌套",
                      confidence=90)


def _check_class(node, filepath, collector, file_type="source"):
    """检测类质量（v2.0: 置信度评分）"""
    class_name = node.name
    
    # 方法数量（AST 精确，置信度 85）
    methods = [n for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
               and not n.name.startswith("__")]
    num_methods = len(methods)
    
    if num_methods > THRESHOLDS["max_class_methods_warn"]:
        collector.add("warn", "class_size", filepath, node.lineno,
                      f"类 '{class_name}' 方法数 {num_methods} > {THRESHOLDS['max_class_methods_warn']}（警告）",
                      "检查是否违反单一职责原则，考虑拆分",
                      confidence=85)
    
    # 类代码行数（AST 精确，置信度 85）
    class_lines = node.end_lineno - node.lineno + 1 if node.end_lineno else 0
    if class_lines > THRESHOLDS["max_class_lines_block"]:
        collector.add("block", "class_size", filepath, node.lineno,
                      f"类 '{class_name}' 代码行数 {class_lines} > {THRESHOLDS['max_class_lines_block']}（阻塞）",
                      "拆分为多个职责单一的类",
                      confidence=85)
    elif class_lines > THRESHOLDS["max_class_lines_warn"]:
        collector.add("warn", "class_size", filepath, node.lineno,
                      f"类 '{class_name}' 代码行数 {class_lines} > {THRESHOLDS['max_class_lines_warn']}（警告）",
                      "检查是否违反单一职责原则",
                      confidence=85)


def _check_security(content, filepath, collector, file_type=None):
    """安全检查 — 三扫描模式（v2.0.3: 新增多行 DOTALL 扫描阶段）
    
    第一遍：原始内容逐行扫描 → 置信度 70 (security_raw) 
    第二遍：剥离注释和字符串后逐行扫描 → 置信度 85 (security)
    第三遍：剥离后全文 DOTALL 多行扫描 → 置信度 75 (security_multiline)
    三遍结果合并去重，只有剥离后仍匹配的才报 block。
    
    v2.0.4: file_type 可选参数，由调用方传入时跳过冗余 classify。
    """
    ext = os.path.splitext(filepath)[1].lower()
    if file_type is None:
        file_type = FileClassifier.classify(filepath)
    
    # 测试文件跳过安全检测
    if file_type == "test":
        return
    
    # 第一遍：原始扫描（快速筛查，置信度低）
    lines = content.split("\n")
    raw_matches = []  # (line_no, pattern_index, matched_text)
    
    for i, line in enumerate(lines, 1):
        for idx, (pattern, description) in enumerate(SECURITY_RED_FLAGS):
            match = re.search(pattern, line, re.IGNORECASE)
            if match:
                raw_matches.append((i, idx, match.group(), description))
    
    # 第二遍：剥离后扫描（高精度，去注释/字符串噪音）
    stripped = _strip_comments_and_strings(content, ext) if ext in (
        ".py", ".js", ".ts", ".mjs", ".java", ".cs", ".go", ".rs", ".cpp", ".c", ".h"
    ) else content
    stripped_lines = stripped.split("\n")
    
    confirmed = set()  # 已确认问题去重
    
    for i, line in enumerate(stripped_lines, 1):
        if i > len(lines):
            break
        for idx, (pattern, description) in enumerate(SECURITY_RED_FLAGS):
            match = re.search(pattern, line, re.IGNORECASE)
            if match:
                key = (i, idx)
                if key not in confirmed:
                    confirmed.add(key)
                    collector.add("block", "security", filepath, i,
                                  f"安全问题: {description}",
                                  "使用环境变量/密钥管理服务存储凭证，使用参数化查询",
                                  confidence=85)
    
    # 第三遍：多行 DOTALL 双通道扫描（v2.0.5: 密码通道+函数调用通道分离）
    # - 密码通道 (索引0): 归一化 \n、(、)、\ → 捕获 password = (\n "secret"\n) 等
    # - 函数调用通道 (索引1-8): 仅归一化 \n → 保留 ( 使 eval\(/exec\(等正则正常匹配
    # 两通道独立匹配、合并去重，严重级别统一为 block(85)
    PASSWORD_CHANNEL_INDICES = {0}  # 硬编码密钥/密码模式
    normalized_pwd = stripped.replace('\n', ' ').replace('(', ' ').replace(')', ' ').replace('\\', ' ')
    normalized_func = stripped.replace('\n', ' ').replace('\\', ' ')  # v2.0.5: 续行符归一化（修复#3）
            
    for idx, (pattern, description) in enumerate(SECURITY_RED_FLAGS):
        normalized = normalized_pwd if idx in PASSWORD_CHANNEL_INDICES else normalized_func
        for match in re.finditer(pattern, normalized, re.IGNORECASE):
            # 位置映射：normalized 由 stripped 经 1:1 单字符替换得来
            # 注意：此 1:1 映射依赖于所有替换都是单字符→单空格替换的前提
            line_no = stripped[:match.start()].count('\n') + 1
            key = (line_no, idx)
            if key not in confirmed:
                confirmed.add(key)
                collector.add("block", "security", filepath, line_no,
                              f"安全问题(多行检测): {description}",
                              "使用环境变量/密钥管理服务存储凭证，使用参数化查询",
                              confidence=85)
    
    # 对仅在原始扫描中发现但剥离后未发现的问题，作为低置信度警告
    for line_no, idx, matched, desc in raw_matches:
        key = (line_no, idx)
        if key not in confirmed:
            # 仅在剥离前匹配 → 可能在注释或字符串中，低置信度
            collector.add("warn", "security_raw", filepath, line_no,
                          f"安全问题(低置信度，可能在注释/字符串中): {desc}",
                          "确认该匹配不在注释或字符串中",
                          confidence=70)


def _check_empty_except(content, filepath, collector, file_type="source"):
    """检测空的或过于简单的异常处理（v2.0.2: 同行检测 + 多行支持）"""
    lines = content.split("\n")
    
    in_except = False
    except_line = 0
    except_indent = 0
    in_docstring = False  # v2.0.6: 跟踪多行 docstring 状态，修复#1 中间行中断检测
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        
        # 同行检测：except SomeError: pass 或 except: pass
        if re.match(r'except\b', stripped):
            # v2.0.6: 先移除内联注释再检查，修复#9 内联注释绕过
            code_only = re.sub(r'#.*$', '', stripped).rstrip()
            rest = re.sub(r'^.*:\s*', '', code_only)
            if rest in ("pass", "") or code_only.endswith(": pass"):
                collector.add("warn", "error_handling", filepath, i,
                              "异常处理过于简单（except 行直接 pass）",
                              "添加适当的日志记录和错误处理逻辑",
                              confidence=82)
                continue
            in_except = True
            except_line = i
            except_indent = len(line) - len(line.lstrip())
            in_docstring = False
            continue
        
        if in_except:
            current_indent = len(line) - len(line.lstrip())
            # 缩进退回（跳出 except 块）—— 先于 docstring 检查，确保正常退出
            if current_indent <= except_indent:
                in_except = False
                in_docstring = False
                continue
            # v2.0.6: docstring 状态机 — 多行 docstring 中间行和结束行不中断检测
            if in_docstring:
                if stripped.startswith('"""') or stripped.startswith("'''"):
                    in_docstring = False  # docstring 结束行
                continue  # docstring 内部行跳过
            if stripped == "" or stripped.startswith('#'):
                continue
            # docstring 开始行
            if (stripped.startswith('"""') or stripped.startswith("'''")):
                if stripped.endswith('"""') or stripped.endswith("'''"):
                    if len(stripped) <= 6:  # 单行空 docstring
                        continue
                # 检查是否单行闭合 ('"""..."""' 或 "''''...'''")
                quote3 = stripped[:3]
                if len(stripped) > 3 and stripped.endswith(quote3) and len(stripped) > 6:
                    continue  # 单行完整 docstring，跳过
                else:
                    in_docstring = True  # 多行 docstring 开始
                    continue
            if stripped in ("pass", "") or re.match(r'print\s*\(', stripped):
                collector.add("warn", "error_handling", filepath, except_line,
                              "异常处理过于简单（pass 或仅 print）",
                              "添加适当的日志记录和错误处理逻辑",
                              confidence=82)
            in_except = False


def check_duplicates(source_files, collector):
    """检测重复代码块（支持跨文件检测）
    v2.0.6: 比较前剥离注释行，修复#8 注释差异导致重复代码漏检
    """
    block_map = defaultdict(list)
    
    for filepath in source_files:
        try:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                # 剥离注释行后比较：替换 # 行和 // 行为空行保持行号对齐
                raw_lines = f.readlines()
                lines = []
                for l in raw_lines:
                    stripped_line = l.strip()
                    # 跳过纯注释行（替换为空行保持行号对齐，不改变行数）
                    if stripped_line.startswith('#') or stripped_line.startswith('//'):
                        lines.append('')
                    else:
                        lines.append(stripped_line)
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


# ============================================================
# 依赖图（v2.0: import 依赖追踪 + 循环依赖检测）
# 参考 mrzadexinho/codeguard 的 import 追踪设计
# ============================================================

class DependencyGraph:
    """模块间依赖关系图
    构建全局依赖图，支持：
    - 分层违规检测
    - 循环依赖检测
    - 依赖方向分析
    """
    
    def __init__(self):
        self.edges = defaultdict(set)     # file → set of imported files
        self.reverse = defaultdict(set)    # file → set of files that import it
        self.layer_map = {}               # file → layer
        self.lang_map = {}                # file → language
    
    def add_edge(self, from_file, to_module):
        """添加一条依赖边"""
        self.edges[from_file].add(to_module)
        self.reverse[to_module].add(from_file)
    
    def set_layer(self, filepath, layer):
        self.layer_map[filepath] = layer
    
    def set_lang(self, filepath, lang):
        self.lang_map[filepath] = lang
    
    def find_cycles(self, max_depth=50):
        """DFS 检测循环依赖
        
        返回: [(cycle_files, cycle_path)] 循环依赖列表
        confidence: 95 (高度确定)
        """
        cycles = []
        all_nodes = list(self.edges.keys())
        
        for start in all_nodes:
            visited = set()
            path = [start]
            
            def dfs(node, depth):
                if depth > max_depth:
                    return
                for neighbor in self.edges.get(node, set()):
                    # 找到实际文件（模糊匹配）
                    matching = self._find_matching_files(neighbor)
                    for actual_file in matching:
                        if actual_file == start and len(path) > 1:
                            cycles.append((list(path), path + [actual_file]))
                            return
                        if actual_file not in visited and actual_file not in path:
                            visited.add(actual_file)
                            path.append(actual_file)
                            dfs(actual_file, depth + 1)
                            path.pop()
            
            dfs(start, 0)
        
        return cycles
    
    def _find_matching_files(self, module_or_path):
        """根据模块名精确匹配文件路径（v2.0.3: 路径段边界匹配，消除子串误报）
        
        例如 module="os" → 匹配 .../os.py 或 .../os/... 
        但不匹配 .../composer.py、.../close_handler.py
        """
        results = []
        module_lower = module_or_path.lower().replace(".", "/")
        module_parts = [p for p in module_lower.split("/") if p]
        
        if not module_parts:
            return results
        
        for filepath in self.edges:
            filepath_lower = filepath.lower().replace("\\", "/")
            filepath_parts = [p for p in filepath_lower.split("/") if p]
            
            # 尾部文件名匹配（不含扩展名，如 os.py → os == os）
            basename = os.path.basename(filepath_lower)
            basename_no_ext = os.path.splitext(basename)[0].lower()
            if basename_no_ext == module_parts[-1]:
                results.append(filepath)
                continue
            
            # 完整路径段后缀匹配（如 domain/user → .../domain/user/...）
            if len(module_parts) <= len(filepath_parts):
                if filepath_parts[-len(module_parts):] == module_parts:
                    results.append(filepath)
        
        return results[:5]  # 限制返回数
    
    def check_layer_violations(self, collector):
        """检查分层违规 + 检测循环依赖"""
        # 1. 分层违规检测
        for filepath, imps in self.edges.items():
            file_layer = self.layer_map.get(filepath, _infer_layer(filepath.lower()))
            file_type = FileClassifier.classify(filepath)
            
            # 跳过非源码文件
            if file_type in ("generated", "doc", "config"):
                continue
            
            for imp in imps:
                imp_layer = _infer_layer(imp.lower())
                
                # Domain 层不应依赖 Infrastructure 或 Presentation
                if file_layer == "domain" and imp_layer in ("infrastructure", "presentation"):
                    # 置信度：如果有精确的 filepath 映射，用90；否则用78
                    conf = 90 if self._find_matching_files(imp) else 78
                    collector.add("block", "architecture", filepath, 0,
                                  f"架构违规：Domain 层引用了 {imp_layer} 层 ({imp})",
                                  "Domain 层应定义接口，由 Infrastructure 层实现",
                                  confidence=conf)
                
                # Application 层不应直接依赖 Infrastructure 具体实现
                if file_layer == "application" and imp_layer == "infrastructure":
                    conf = 88
                    collector.add("warn", "architecture", filepath, 0,
                                  f"架构警告：Application 层直接引用 Infrastructure 层 ({imp})",
                                  "应通过接口/抽象类进行依赖倒置",
                                  confidence=conf)
        
        # 2. 循环依赖检测
        cycles = self.find_cycles()
        reported_cycles = set()
        for cycle_files, cycle_path in cycles:
            cycle_key = tuple(sorted(cycle_files[:3]))  # 用前3个节点去重
            if cycle_key not in reported_cycles:
                reported_cycles.add(cycle_key)
                first_file = cycle_files[0] if cycle_files else "unknown"
                cycle_desc = " → ".join([os.path.basename(f) for f in cycle_path[:6]])
                collector.add("block", "architecture_cycle", first_file, 0,
                              f"循环依赖检测: {cycle_desc}",
                              "重构模块结构，使用依赖倒置或接口隔离消除循环",
                              confidence=95)


def build_dependency_graph(source_files):
    """从源文件列表构建完整依赖图"""
    graph = DependencyGraph()
    
    for filepath in source_files:
        filepath_lower = filepath.lower()
        
        # 跳过非源码文件
        file_type = FileClassifier.classify(filepath)
        if file_type in ("generated", "doc", "config"):
            continue
        
        file_layer = _infer_layer(filepath_lower)
        file_lang = _detect_file_lang(filepath)
        
        graph.set_layer(filepath, file_layer)
        graph.set_lang(filepath, file_lang)
        
        try:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except Exception:
            continue
        
        # 多语言 import 提取
        for pattern, lang in MULTILANG_IMPORT_PATTERNS:
            if lang == file_lang:
                for match in pattern.finditer(content):
                    module = match.group(1) or (match.group(2) if match.lastindex and match.lastindex >= 2 else None)
                    if module:
                        graph.add_edge(filepath, module)
                break
    
    return graph


def check_architecture(source_files, collector):
    """检测架构分层违规 + 循环依赖（v2.0: 基于 DependencyGraph）"""
    graph = build_dependency_graph(source_files)
    graph.check_layer_violations(collector)


def _infer_layer(path_or_module):
    """根据路径或模块名推断架构层级"""
    for layer, patterns in LAYER_PATTERNS.items():
        for p in patterns:
            if p in path_or_module:
                return layer
    return "unknown"


# ============================================================
# 多语言正则近似检测（保持零外部依赖）
# 关键改进：先剥离注释和字符串再匹配，消除正则"盲目"匹配问题
# ============================================================

def _strip_comments_and_strings(content, ext):
    """剥离注释和字符串字面量，保留行号结构。
    
    返回 (stripped_content, original_content)
    在 stripped 上做 CC/嵌套/参数正则匹配，避免注释和字符串中的误报。
    """
    # Python: # 注释 + 多行三引号 + 单引号/双引号字符串
    if ext == ".py":
        # 移除多行字符串（三引号）
        content = re.sub(r'""".*?"""', lambda m: ' ' * len(m.group()), content, flags=re.DOTALL)
        content = re.sub(r"'''.*?'''", lambda m: ' ' * len(m.group()), content, flags=re.DOTALL)
        # 移除单行注释
        content = re.sub(r'#.*$', lambda m: ' ' * len(m.group()), content, flags=re.MULTILINE)
        # 移除单行字符串
        content = re.sub(r'"(?:[^"\\]|\\.)*"', lambda m: ' ' * len(m.group()), content)
        content = re.sub(r"'(?:[^'\\]|\\.)*'", lambda m: ' ' * len(m.group()), content)
        return content
    
    # JS/TS: // 注释 + /* */ 块注释 + 模板字符串 + 单双引号 + 正则字面量
    elif ext in (".js", ".ts", ".mjs"):
        content = re.sub(r'/\*.*?\*/', lambda m: ' ' * len(m.group()), content, flags=re.DOTALL)
        content = re.sub(r'//.*$', lambda m: ' ' * len(m.group()), content, flags=re.MULTILINE)
        content = re.sub(r'`(?:[^`\\]|\\.)*`', lambda m: ' ' * len(m.group()), content)
        content = re.sub(r'"(?:[^"\\]|\\.)*"', lambda m: ' ' * len(m.group()), content)
        content = re.sub(r"'(?:[^'\\]|\\.)*'", lambda m: ' ' * len(m.group()), content)
        # 正则字面量（启发式：跟在特定语法上下文之后）
        content = re.sub(
            r'(?:[=\(!:;,&\|\?]\s*)/(?![\s/])[^/\n]*?/[gimsuy]*',
            lambda m: ' ' * len(m.group()), content
        )
        return content
    
    # Java/C#: // 注释 + /* */ 块注释 + 双引号字符串
    elif ext in (".java", ".cs"):
        content = re.sub(r'/\*.*?\*/', lambda m: ' ' * len(m.group()), content, flags=re.DOTALL)
        content = re.sub(r'//.*$', lambda m: ' ' * len(m.group()), content, flags=re.MULTILINE)
        content = re.sub(r'@?"(?:[^"\\]|\\.)*"', lambda m: ' ' * len(m.group()), content)
        return content
    
    # Go: // 注释 + /* */ 块注释 + 双引号字符串 + 反引号原始字符串
    elif ext == ".go":
        content = re.sub(r'/\*.*?\*/', lambda m: ' ' * len(m.group()), content, flags=re.DOTALL)
        content = re.sub(r'//.*$', lambda m: ' ' * len(m.group()), content, flags=re.MULTILINE)
        content = re.sub(r'`[^`]*`', lambda m: ' ' * len(m.group()), content)
        content = re.sub(r'"(?:[^"\\]|\\.)*"', lambda m: ' ' * len(m.group()), content)
        return content
    
    # Rust: // 注释 + /* */ 块注释 + 双引号字符串
    elif ext == ".rs":
        content = re.sub(r'/\*.*?\*/', lambda m: ' ' * len(m.group()), content, flags=re.DOTALL)
        content = re.sub(r'//.*$', lambda m: ' ' * len(m.group()), content, flags=re.MULTILINE)
        content = re.sub(r'"(?:[^"\\]|\\.)*"', lambda m: ' ' * len(m.group()), content)
        return content
    
    # C/C++: // 注释 + /* */ 块注释 + 双引号字符串
    elif ext in (".cpp", ".c", ".h"):
        content = re.sub(r'/\*.*?\*/', lambda m: ' ' * len(m.group()), content, flags=re.DOTALL)
        content = re.sub(r'//.*$', lambda m: ' ' * len(m.group()), content, flags=re.MULTILINE)
        content = re.sub(r'"(?:[^"\\]|\\.)*"', lambda m: ' ' * len(m.group()), content)
        return content
    
    return content


# 各语言分支关键词（用于圈复杂度近似）
LANG_CC_PATTERNS = {
    ".js": [r'\bif\s*\(', r'\belse\s+if\s*\(', r'\bfor\s*\(', r'\bwhile\s*\(',
            r'\bswitch\s*\(', r'\bcase\s+', r'&&', r'\|\|', r'\?\?', r'\bcatch\s*\('],
    ".ts": [r'\bif\s*\(', r'\belse\s+if\s*\(', r'\bfor\s*\(', r'\bwhile\s*\(',
            r'\bswitch\s*\(', r'\bcase\s+', r'&&', r'\|\|', r'\?\?', r'\bcatch\s*\('],
    ".mjs": [r'\bif\s*\(', r'\belse\s+if\s*\(', r'\bfor\s*\(', r'\bwhile\s*\(',
             r'\bswitch\s*\(', r'\bcase\s+', r'&&', r'\|\|', r'\?\?', r'\bcatch\s*\('],
    ".java": [r'\bif\s*\(', r'\belse\s+if\s*\(', r'\bfor\s*\(', r'\bwhile\s*\(',
              r'\bswitch\s*\(', r'\bcase\s+', r'&&', r'\|\|', r'\bcatch\s*\('],
    ".go": [r'\bif\s+', r'\bfor\s+', r'\bswitch\s+', r'&&', r'\|\|',
            r'\bcase\s+', r'if\s+err\s*!=\s*nil'],
    ".cs": [r'\bif\s*\(', r'\belse\s+if\s*\(', r'\bfor\s*\(', r'\bforeach\s*\(',
            r'\bwhile\s*\(', r'\bswitch\s*\(', r'\bcase\s+', r'&&', r'\|\|', r'\bcatch\b'],
    ".rs": [r'\bif\s+', r'\bfor\s+', r'\bwhile\s+', r'\bmatch\s+', r'&&', r'\|\|'],
    ".cpp": [r'\bif\s*\(', r'\belse\s+if\s*\(', r'\bfor\s*\(', r'\bwhile\s*\(',
             r'\bswitch\s*\(', r'\bcase\s+', r'&&', r'\|\|', r'\bcatch\s*\('],
    ".c": [r'\bif\s*\(', r'\belse\s+if\s*\(', r'\bfor\s*\(', r'\bwhile\s*\(',
           r'\bswitch\s*\(', r'\bcase\s+', r'&&', r'\|\|'],
    ".h": [r'\bif\s*\(', r'\belse\s+if\s*\(', r'\bfor\s*\(', r'\bwhile\s*\(',
           r'\bswitch\s*\(', r'\bcase\s+', r'&&', r'\|\|'],
}

# 各语言函数签名参数提取
LANG_PARAM_PATTERNS = {
    ".js": re.compile(r'(?:function\s+\w+\s*|=>\s*|\(\s*)\(([^)]*)\)'),
    ".ts": re.compile(r'(?:function\s+\w+\s*|=>\s*|\(\s*)\(([^)]*)\)'),
    ".mjs": re.compile(r'(?:function\s+\w+\s*|=>\s*|\(\s*)\(([^)]*)\)'),
    ".java": re.compile(r'(?:public|private|protected|static|\s)+\w+\s+(\w+)\s*\(([^)]*)\)'),
    ".go": re.compile(r'func\s+(?:\(\w+\s+\*?\w+\)\s+)?(\w+)\s*\(([^)]*)\)'),
    ".cs": re.compile(r'(?:public|private|protected|internal|static|\s)+\w+\s+(\w+)\s*\(([^)]*)\)'),
    ".rs": re.compile(r'fn\s+(\w+)\s*\(([^)]*)\)'),
    ".cpp": re.compile(r'\w+\s+(\w+)\s*\(([^)]*)\)'),
}

# 大括号语言嵌套深度关键词（触发深度+1）
LANG_NESTING_KEYWORDS = {
    ".js": r'\b(?:if|for|while|switch|catch|function|class)\b',
    ".ts": r'\b(?:if|for|while|switch|catch|function|class)\b',
    ".mjs": r'\b(?:if|for|while|switch|catch|function|class)\b',
    ".java": r'\b(?:if|for|while|switch|catch|class|try)\b',
    ".cs": r'\b(?:if|for|foreach|while|switch|catch|class|try)\b',
    ".cpp": r'\b(?:if|for|while|switch|catch|class|try)\b',
}


def _compute_cc_regex(content, ext, *, stripped=None):
    """用正则近似计算圈复杂度（基础值=1），先在剥离注释和字符串的内容上运行
    v2.0.4: stripped 可选参数，由调用方预剥离时传入避免重复 strip。"""
    if stripped is None:
        stripped = _strip_comments_and_strings(content, ext)
    patterns = LANG_CC_PATTERNS.get(ext, [])
    cc = 1
    for pattern in patterns:
        cc += len(re.findall(pattern, stripped, re.IGNORECASE))
    return cc


def _compute_nesting_regex(content, ext, *, stripped=None):
    """用大括号计数近似计算最大嵌套深度，先在剥离注释后的内容上运行
    v2.0.5: stripped 可选参数，由调用方预剥离时传入避免重复 strip。"""
    if ext not in LANG_NESTING_KEYWORDS:
        return 0
    
    if stripped is None:
        stripped = _strip_comments_and_strings(content, ext)
    nesting_kw = LANG_NESTING_KEYWORDS[ext]
    lines = stripped.split('\n')
    max_depth = 0
    current_depth = 0
    pending_depth = 0      # v2.0.2: 单语句控制流深度暂存
    pending_releases = []  # v2.0.4: 栈追踪待释放的单语句体深度（修复嵌套永不递减）
    
    for line in lines:
        line_content = line.strip()
        # 忽略注释和空行
        if not line_content or line_content.startswith('//') or line_content.startswith('#'):
            continue
        
        # 计算当前行的净深度变化
        opens = len(re.findall(r'\{', line_content))
        closes = len(re.findall(r'\}', line_content))
        
        # v2.0.4: 先结算上轮的待定深度（单语句体不会增加 { 但会增加嵌套）
        current_depth += pending_depth
        pending_depth = 0
        
        # v2.0.5: 若本行无大括号变化（opens==0 and closes==0）且非关键词→释放一个待定层级
        # 修复#4: 体行含{}时由大括号逻辑处理，不跳过释放导致双计
        if pending_releases and not re.search(nesting_kw, line_content, re.IGNORECASE) and opens == 0 and closes == 0:
            current_depth -= pending_releases.pop()
        
        # v2.0.6: findall统计同行关键词数量，修复#5多关键词深度被低估
        # 同时先释放pending_releases旧条目再append新条目，修复#3连续单语句体累积
        kw_matches = re.findall(nesting_kw, line_content, re.IGNORECASE)
        kw_count = len(kw_matches)
        
        if kw_count > 0:
            # 先释放所有旧待定条目（本行是一个新的控制流，旧体已结束）
            if pending_releases:
                current_depth -= sum(pending_releases)
                pending_releases.clear()
            if '{' in line_content:
                # 关键词行有 { → 正常处理大括号
                current_depth += opens
                current_depth -= closes
            else:
                # 单语句控制流 → 暂定深度+N，入栈待体行消费后释放
                pending_depth = kw_count
                pending_releases.extend([1] * kw_count)
        else:
            current_depth += opens - closes
            # v2.0.5: 先结算所有未释放的待定深度再清空，修复#6 clear导致深度丢失
            if current_depth <= 0:
                if pending_releases:
                    current_depth -= sum(pending_releases)
                current_depth = 0
                pending_depth = 0
                pending_releases.clear()
        
        current_depth = max(0, current_depth)
        max_depth = max(max_depth, current_depth)
    
    return max_depth


def _count_params_regex(content, ext, *, stripped=None):
    """用正则提取函数参数数量，先在剥离注释和字符串的内容上运行
    v2.0.4: stripped 可选参数，由调用方预剥离时传入避免重复 strip。"""
    if stripped is None:
        stripped = _strip_comments_and_strings(content, ext)
    pattern = LANG_PARAM_PATTERNS.get(ext)
    if not pattern:
        return {}
    
    results = {}
    lines = stripped.split('\n')
    for i, line in enumerate(lines, 1):
        for match in pattern.finditer(line):
            groups = match.groups()
            # 找到参数组（最后一个捕获组通常是参数列表）
            params_str = groups[-1] if groups else ""
            if not params_str or params_str.isspace():
                count = 0
            else:
                # 简单逗号计数（不完美但近似）
                count = params_str.count(',') + 1
            func_name = groups[0] if len(groups) >= 2 and groups[0] else "unknown"
            results[(func_name, i)] = count
    
    return results


def _count_java_methods(content, *, stripped=None):
    """统计 Java/C# 类的方法数，先在剥离注释和字符串的内容上运行
    v2.0.5: stripped 可选参数，由调用方预剥离时传入避免重复 strip。"""
    if stripped is None:
        stripped = _strip_comments_and_strings(content, ".java")
    method_pattern = re.compile(
        r'(?:public|private|protected|static|final|abstract|synchronized)\s+\S+\s+(\w+)\s*\([^)]*\)\s*(\{|throws)',
        re.IGNORECASE
    )
    return len(method_pattern.findall(stripped))


# ============================================================
# 语言专用检测器（v2.0.3: 抽取 _check_regex_based_file 消除 80% 重复）
# ============================================================

def _check_regex_based_file(filepath, collector, ext, *, check_nesting=True, check_methods=False):
    """通用正则检测驱动器 — 服务于 JS/TS/Java/Go/C# 的共享检测逻辑
    
    Args:
        check_nesting: 是否执行嵌套深度检测（Go 跳过）
        check_methods: 是否执行类方法数检测（Java/C# 适用）
    """
    file_type = FileClassifier.classify(filepath)
    if file_type in ("generated", "doc"):
        return
    
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
    except Exception:
        return
    
    # 基础检查
    loc = count_lines_of_code(content)
    _check_file_size(loc, filepath, collector)
    _check_security(content, filepath, collector, file_type=file_type)  # v2.0.4: 传入 file_type 避免冗余 classify
    
    # v2.0.5: 预剥离注释/字符串共享给 CC/嵌套/参数检测，避免重复 strip
    # 注意: 即使文件为 test 类型（security 已跳过），CC/嵌套/参数仍需剥离后检测
    stripped = _strip_comments_and_strings(content, ext)
    
    # 圈复杂度（剥离后正则，置信度 80）
    cc = _compute_cc_regex(content, ext, stripped=stripped)
    if cc > THRESHOLDS["cyclomatic_complexity_block"]:
        collector.add("block", "complexity_regex", filepath, 0,
                      f"圈复杂度(近似) {cc} > {THRESHOLDS['cyclomatic_complexity_block']}(阻塞)",
                      "拆分为多个小函数", confidence=80)
    elif cc > THRESHOLDS["cyclomatic_complexity_warn"]:
        collector.add("warn", "complexity_regex", filepath, 0,
                      f"圈复杂度(近似) {cc} > {THRESHOLDS['cyclomatic_complexity_warn']}(警告)",
                      "考虑拆分", confidence=80)
    
    # 嵌套深度（大括号计数，置信度 80）
    if check_nesting:
        depth = _compute_nesting_regex(content, ext, stripped=stripped)  # v2.0.5: 传入预剥离结果
        if depth > THRESHOLDS["max_nesting_block"]:
            collector.add("block", "nesting_regex", filepath, 0,
                          f"嵌套深度(近似) {depth} > {THRESHOLDS['max_nesting_block']}(阻塞)",
                          "使用 early return 减少嵌套", confidence=80)
        elif depth > THRESHOLDS["max_nesting_warn"]:
            collector.add("warn", "nesting_regex", filepath, 0,
                          f"嵌套深度(近似) {depth} > {THRESHOLDS['max_nesting_warn']}(警告)",
                          "考虑使用 early return", confidence=80)
    
    # 参数数量（剥离后正则，置信度 80）
    params = _count_params_regex(content, ext, stripped=stripped)
    for (func_name, line), count in params.items():
        if count > THRESHOLDS["max_function_params_block"]:
            collector.add("block", "params_regex", filepath, line,
                          f"函数 '{func_name}' 参数 {count} > {THRESHOLDS['max_function_params_block']}(阻塞)",
                          "封装为参数对象", confidence=80)
        elif count > THRESHOLDS["max_function_params_warn"]:
            collector.add("warn", "params_regex", filepath, line,
                          f"函数 '{func_name}' 参数 {count} > {THRESHOLDS['max_function_params_warn']}(警告)",
                          "考虑使用参数对象", confidence=80)
    
    # 类方法数（Java/C# 适用）
    if check_methods:
        method_count = _count_java_methods(content, stripped=stripped)  # v2.0.5: 传入预剥离结果
        if method_count > THRESHOLDS["max_class_methods_warn"]:
            collector.add("warn", "class_size_regex", filepath, 0,
                          f"类方法数(近似) {method_count} > {THRESHOLDS['max_class_methods_warn']}(警告)",
                          "检查是否违反单一职责原则", confidence=75)
    
    _check_empty_except_generic(content, filepath, collector, ext)


def check_javascript_file(filepath, collector, ext):
    """JS/TS 专用检测（v2.0.3: 委托 _check_regex_based_file）"""
    _check_regex_based_file(filepath, collector, ext, check_nesting=True, check_methods=False)


def check_java_file(filepath, collector):
    """Java 专用检测（v2.0.3: 委托 _check_regex_based_file）"""
    _check_regex_based_file(filepath, collector, ".java", check_nesting=True, check_methods=True)


def check_go_file(filepath, collector):
    """Go 专用检测（v2.0.3: 委托 _check_regex_based_file，跳过嵌套深度）"""
    _check_regex_based_file(filepath, collector, ".go", check_nesting=False, check_methods=False)


def check_csharp_file(filepath, collector):
    """C# 专用检测（v2.0.3: 委托 _check_regex_based_file）"""
    _check_regex_based_file(filepath, collector, ".cs", check_nesting=True, check_methods=True)


def _check_file_size(loc, filepath, collector):
    """通用文件大小检查（置信度 95）"""
    if loc > THRESHOLDS["max_file_lines_block"]:
        collector.add("block", "file_size", filepath, 0,
                      f"文件代码行数 {loc} > {THRESHOLDS['max_file_lines_block']}（阻塞阈值）",
                      "将文件拆分为多个模块", confidence=95)
    elif loc > THRESHOLDS["max_file_lines_warn"]:
        collector.add("warn", "file_size", filepath, 0,
                      f"文件代码行数 {loc} > {THRESHOLDS['max_file_lines_warn']}（警告阈值）",
                      "考虑拆分大文件", confidence=95)


def check_generic_file(filepath, collector, ext):
    """对非主流语言执行通用质量检测（v2.0.2: 增加 CC/params 正则检测）"""
    file_type = FileClassifier.classify(filepath)  # v2.0.6: 提前分类传入 _check_security
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
    except Exception as e:
        collector.add("info", "parse_error", filepath, 0, f"无法读取文件: {e}")
        return
    
    loc = count_lines_of_code(content)
    _check_file_size(loc, filepath, collector)
    _check_security(content, filepath, collector, file_type=file_type)  # v2.0.6: 传入 file_type
    
    # v2.0.5: 预剥离注释/字符串共享给 CC 和参数检测，避免重复 strip
    if ext in LANG_CC_PATTERNS or ext in LANG_PARAM_PATTERNS:
        stripped = _strip_comments_and_strings(content, ext)
    
    # CC 和参数数量正则检测（对支持的语言）
    if ext in LANG_CC_PATTERNS:
        cc = _compute_cc_regex(content, ext, stripped=stripped)
        if cc > THRESHOLDS["cyclomatic_complexity_block"]:
            collector.add("block", "complexity_regex", filepath, 0,
                          f"圈复杂度(近似) {cc} > {THRESHOLDS['cyclomatic_complexity_block']}(阻塞)",
                          "拆分为多个小函数", confidence=80)
        elif cc > THRESHOLDS["cyclomatic_complexity_warn"]:
            collector.add("warn", "complexity_regex", filepath, 0,
                          f"圈复杂度(近似) {cc} > {THRESHOLDS['cyclomatic_complexity_warn']}(警告)",
                          "考虑拆分", confidence=80)
    
    if ext in LANG_PARAM_PATTERNS:
        params = _count_params_regex(content, ext, stripped=stripped)
        for (func_name, line), count in params.items():
            if count > THRESHOLDS["max_function_params_block"]:
                collector.add("block", "params_regex", filepath, line,
                              f"函数 '{func_name}' 参数 {count} > {THRESHOLDS['max_function_params_block']}(阻塞)",
                              "封装为参数对象", confidence=80)
            elif count > THRESHOLDS["max_function_params_warn"]:
                collector.add("warn", "params_regex", filepath, line,
                              f"函数 '{func_name}' 参数 {count} > {THRESHOLDS['max_function_params_warn']}(警告)",
                              "考虑使用参数对象", confidence=80)
    
    # 通用异常处理检测（多语言支持）
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
        # Go 惯用错误处理: return err / return nil, err / return ... , err / log.Fatal
        _go_err_return = ("return", "return err", "return nil", "return nil, err",
                          "return 0, err", "return false, err", "return \"\", err")
        empty_body = _go_err_return
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
            handler_line = i
            # 同行的空体检测：} catch (Exception e) {} 或 catch (e) {}
            after_catch = stripped
            if ')' in after_catch:
                body_after = after_catch[after_catch.rfind(')') + 1:].strip()
                if body_after in empty_body or body_after == "{}" or body_after == "{ }":
                    collector.add("warn", "error_handling", filepath, handler_line,
                                  "异常处理过于简单（同行空体）",
                                  "添加适当的日志记录和错误处理逻辑",
                                  confidence=82)
                    continue
            in_handler = True
            continue
        if in_handler:
            # v2.0.5: 空行和注释行跳过，修复#11 注释中断多行异常检测
            if stripped == "" or stripped.startswith('//') or stripped.startswith('#'):
                continue
            if stripped in empty_body or re.match(r'print\s*\(', stripped) or \
               (ext == ".go" and any(stripped.startswith(p) for p in _go_err_return)):
                collector.add("warn", "error_handling", filepath, handler_line,
                              "异常处理过于简单",
                              "添加适当的日志记录和错误处理逻辑",
                              confidence=82)
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
    """加载 .code-guardian/rules.json 中的自定义质量规则（v2.0.3: 与 constraint_injector 逻辑统一）"""
    custom_rules = []
    config_path = Path(root_path) / ".code-guardian" / "rules.json"
    
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if "rules" in data:
            custom_rules = data["rules"]
    except FileNotFoundError:
        pass
    except json.JSONDecodeError as e:
        _log(f"[CodeGuard] 自定义规则 JSON 解析失败: {config_path} - {e}")
    except Exception as e:
        _log(f"[CodeGuard] 加载自定义规则异常: {config_path} - {e}")
    
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
    
    # 加载自定义规则
    custom_rules = load_custom_quality_rules(root_path)
    if custom_rules:
        _log(f"[CodeGuard] 加载 {len(custom_rules)} 条自定义规则")
    
    # 1. 逐文件检测（多语言派发）
    for filepath in source_files:
        ext = os.path.splitext(filepath)[1].lower()
        if ext == ".py":
            check_python_file(filepath, collector)
        elif ext in (".js", ".ts", ".mjs"):
            check_javascript_file(filepath, collector, ext)
        elif ext == ".java":
            check_java_file(filepath, collector)
        elif ext == ".go":
            check_go_file(filepath, collector)
        elif ext == ".cs":
            check_csharp_file(filepath, collector)
        else:
            check_generic_file(filepath, collector, ext)
    
    # 2. 跨文件检测
    check_duplicates(source_files, collector)
    check_architecture(source_files, collector)
    
    if check_mode == "team":
        check_naming_consistency(source_files, collector)
    
    # 3. 自定义规则检测（所有模式均执行）
    check_custom_rules(source_files, custom_rules, collector)
    
    _log(f"\n[CodeGuard] 检测完成: {collector.summary()}")
    return collector


def output_json(collector):
    """输出 JSON 格式（v2.0: 包含置信度）"""
    result = {
        "summary": collector.summary(),
        "issues": sorted(collector.issues, key=lambda x: (
            {"block": 0, "warn": 1, "info": 2}[x["severity"]],
            x["category"],
            x["file"],
            x["line"]
        ))
    }
    # 置信度分布统计
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
    """输出可读文本格式（v2.0: 显示置信度）"""
    issues = sorted(collector.issues, key=lambda x: (
        {"block": 0, "warn": 1, "info": 2}[x["severity"]],
        x["category"],
        x["file"],
        x["line"]
    ))
    
    for issue in issues:
        prefix = {"block": "[BLOCK]", "warn": "[WARN]", "info": "[INFO]"}[issue["severity"]]
        print(f"\n{prefix} {issue['category']}  (置信度: {issue.get('confidence', '?')}%)")
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
        _log(f"错误: 路径不存在: {root_path}")
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
