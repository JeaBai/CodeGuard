"""共享工具函数 — 文件查找 / AST 指标 / 注释剥离。"""
import ast
import os
import re
import sys
from collections import defaultdict

# ============================================================
# 工具函数
# ============================================================

def _log(msg):  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
    """统一日志输出到 stderr（v2.0.3: 替代散落的 print(..., file=sys.stderr)）"""  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
    sys.stderr.write(f"{msg}\n")
    sys.stderr.flush()


def find_source_files(root_path, extensions=None, ignore_patterns=None):
    """递归查找源码文件，支持 glob 排除模式"""
    if extensions is None:
        extensions = {".py", ".js", ".ts", ".java", ".go", ".rs", ".cpp", ".c", ".h", ".cs"}
    if ignore_patterns is None:
        ignore_patterns = []

    source_files = []
    skip_dirs = {"node_modules", ".git", "__pycache__", "venv", ".venv", "dist", "build", "target"}

    import fnmatch as _fnmatch

    def _should_skip(fpath):
        """检查文件路径是否匹配任何 ignore 模式"""
        for pattern in ignore_patterns:
            if _fnmatch.fnmatch(fpath, pattern):
                return True
        return False

    for dirpath, dirnames, filenames in os.walk(root_path):
        dirnames[:] = [d for d in dirnames if d not in skip_dirs]
        for f in filenames:
            ext = os.path.splitext(f)[1].lower()
            if ext in extensions:
                full_path = os.path.join(dirpath, f)
                if not _should_skip(full_path):
                    source_files.append(full_path)
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
