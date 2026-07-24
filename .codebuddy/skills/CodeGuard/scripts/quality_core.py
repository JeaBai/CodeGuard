#!/usr/bin/env python3
"""
CodeGuard Quality Core
=======================
共享基础设施：阈值定义、工具函数、问题收集器、文件分类器。
所有检测子模块的公共依赖，零外部依赖。
"""

import ast
import os
import re
import sys
from collections import defaultdict


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
    """统一日志输出到 stderr（v2.0.3: 替代散落的 print(..., file=sys.stderr)）"""
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
# 注释和字符串剥离（多语言）
# ============================================================

def strip_comments_and_strings(content, ext):
    """剥离注释和字符串字面量，保留行号结构。"""
    # Python
    if ext == ".py":
        content = re.sub(r'""".*?"""', lambda m: ' ' * len(m.group()), content, flags=re.DOTALL)
        content = re.sub(r"'''.*?'''", lambda m: ' ' * len(m.group()), content, flags=re.DOTALL)
        content = re.sub(r'#.*$', lambda m: ' ' * len(m.group()), content, flags=re.MULTILINE)
        content = re.sub(r'"(?:[^"\\]|\\.)*"', lambda m: ' ' * len(m.group()), content)
        content = re.sub(r"'(?:[^'\\]|\\.)*'", lambda m: ' ' * len(m.group()), content)
        return content
    
    # JS/TS
    elif ext in (".js", ".ts", ".mjs"):
        content = re.sub(r'/\*.*?\*/', lambda m: ' ' * len(m.group()), content, flags=re.DOTALL)
        content = re.sub(r'//.*$', lambda m: ' ' * len(m.group()), content, flags=re.MULTILINE)
        content = re.sub(r'`(?:[^`\\]|\\.)*`', lambda m: ' ' * len(m.group()), content)
        content = re.sub(r'"(?:[^"\\]|\\.)*"', lambda m: ' ' * len(m.group()), content)
        content = re.sub(r"'(?:[^'\\]|\\.)*'", lambda m: ' ' * len(m.group()), content)
        content = re.sub(
            r'(?:[=\(!:;,&\|\?]\s*)/(?![\s/])[^/\n]*?/[gimsuy]*',
            lambda m: ' ' * len(m.group()), content
        )
        return content
    
    # Java/C#
    elif ext in (".java", ".cs"):
        content = re.sub(r'/\*.*?\*/', lambda m: ' ' * len(m.group()), content, flags=re.DOTALL)
        content = re.sub(r'//.*$', lambda m: ' ' * len(m.group()), content, flags=re.MULTILINE)
        content = re.sub(r'@?"(?:[^"\\]|\\.)*"', lambda m: ' ' * len(m.group()), content)
        return content
    
    # Go
    elif ext == ".go":
        content = re.sub(r'/\*.*?\*/', lambda m: ' ' * len(m.group()), content, flags=re.DOTALL)
        content = re.sub(r'//.*$', lambda m: ' ' * len(m.group()), content, flags=re.MULTILINE)
        content = re.sub(r'`[^`]*`', lambda m: ' ' * len(m.group()), content)
        content = re.sub(r'"(?:[^"\\]|\\.)*"', lambda m: ' ' * len(m.group()), content)
        return content
    
    # Rust
    elif ext == ".rs":
        content = re.sub(r'/\*.*?\*/', lambda m: ' ' * len(m.group()), content, flags=re.DOTALL)
        content = re.sub(r'//.*$', lambda m: ' ' * len(m.group()), content, flags=re.MULTILINE)
        content = re.sub(r'"(?:[^"\\]|\\.)*"', lambda m: ' ' * len(m.group()), content)
        return content
    
    # C/C++
    elif ext in (".cpp", ".c", ".h"):
        content = re.sub(r'/\*.*?\*/', lambda m: ' ' * len(m.group()), content, flags=re.DOTALL)
        content = re.sub(r'//.*$', lambda m: ' ' * len(m.group()), content, flags=re.MULTILINE)
        content = re.sub(r'"(?:[^"\\]|\\.)*"', lambda m: ' ' * len(m.group()), content)
        return content
    
    return content


# ============================================================
# 问题收集器
# ============================================================

class IssueCollector:
    """问题收集器（v2.0: 支持置信度评分）"""
    def __init__(self):
        self.issues = []
        self.stats = defaultdict(int)
        self.confidence_base = {
            "complexity": 90, "complexity_regex": 80,
            "nesting": 90, "nesting_regex": 80,
            "params": 90, "params_regex": 80,
            "class_size": 85, "class_size_regex": 75,
            "file_size": 95,
            "security": 85, "security_raw": 70,
            "duplication": 85,
            "architecture": 90, "architecture_cycle": 95, "architecture_regex": 78,
            "error_handling": 82, "naming": 75,
            "custom_rule": 85, "parse_error": 95, "custom_rule_config": 95,
            "no_files": 95,
        }
    
    def add(self, severity, category, filepath, line, message, *args, **kwargs):
        """添加问题记录（v2.0.8: 签名压缩为6参 + *args/**kwargs 向后兼容）"""
        suggestion = args[0] if len(args) > 0 else kwargs.get("suggestion", "")
        confidence = args[1] if len(args) > 1 else kwargs.get("confidence", None)
        if confidence is None:
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
# 文件类型分类器
# ============================================================

class FileClassifier:
    """文件类型分类器"""
    
    def __init__(self):
        pass
    
    @staticmethod
    def classify(file_path):
        """根据文件路径和内容特征分类"""
        path_lower = file_path.lower()
        name = os.path.basename(path_lower)
        ext = os.path.splitext(path_lower)[1].lower()
        
        if ext == ".md" or "documentation" in path_lower:
            return "doc"
        
        if any(p in path_lower for p in ["/test/", "/tests/", "/spec/", "/__tests__/",
                                          "/testing/", "/fixtures/", "/mocks/", "/stubs/"]):
            return "test"
        if name.startswith("test_") or name.endswith("_test.py") or \
           name.endswith(".test.js") or name.endswith(".spec.js") or \
           name.endswith(".test.ts") or name.endswith(".spec.ts") or \
           name.endswith("Test.java") or name.endswith("Tests.java") or \
           name.endswith("_test.go") or name.endswith("_test.rs"):
            return "test"
        
        if any(kw in name for kw in ["generated", "_pb2", "_grpc", ".pb.", "auto_generated", "_generated"]):
            return "generated"
        if any(kw in path_lower for kw in ["/generated/", "/gen/", "/out/", "/dist/", "/build/",
                                            "/node_modules/", "/vendor/", "/third_party/"]):
            return "generated"
        
        if ext in (".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".env", ".xml"):
            if "package.json" in name or "tsconfig" in name or "docker" in name:
                return "config"
        
        if any(kw in path_lower for kw in ["/migration/", "/migrations/", "/migrate/", "/schema/"]):
            return "migration"
        if ext == ".sql":
            return "migration"
        
        return "source"
    
    @staticmethod
    def get_rule_adjustments(file_type):
        """返回规则调整建议"""
        _adjustments = {
            "test": {
                "skip_categories": ["security"],
                "lower_thresholds": {"complexity": -3, "params": -2},
                "file_label": "[TEST]"
            },
            "config": {
                "skip_categories": ["complexity", "nesting", "params", "class_size", "duplication"],
                "note": "配置文件仅执行安全检测",
                "file_label": "[CONFIG]"
            },
            "generated": {
                "skip_categories": ["complexity", "nesting", "params", "class_size", "duplication",
                                    "architecture", "naming", "error_handling", "security"],
                "note": "生成代码不执行检测，仅标记为不可维护",
                "file_label": "[GENERATED]"
            },
            "migration": {
                "skip_categories": ["complexity", "nesting", "params", "class_size", "naming"],
                "note": "迁移脚本仅执行 SQL 注入检测",
                "file_label": "[MIGRATION]"
            },
            "doc": {
                "skip_categories": ["*"],
                "note": "文档文件不执行检测",
                "file_label": "[DOC]"
            },
            "source": {
                "skip_categories": [],
                "file_label": "[SOURCE]"
            },
        }
        return _adjustments.get(file_type, _adjustments["source"])


def should_skip_category(file_type, category):
    """根据文件类型判断是否应跳过某类检测"""
    adjustments = FileClassifier.get_rule_adjustments(file_type)
    skipped = adjustments.get("skip_categories", [])
    return category in skipped or "*" in skipped
