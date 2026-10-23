"""文件类型分类器 FileClassifier — 规则 dispatch 表驱动。"""
import os

# ============================================================
# 文件类型分类器
# ============================================================

# ---- 文件分类子函数们（将 classify 的 if/elif 链拆为独立谓词） ----

def _classify_is_doc(path_lower, name, ext):
    if ext == ".md" or "documentation" in path_lower:
        return True
    return False

def _classify_is_test(path_lower, name, ext):
    _test_dirs = ["/test/", "/tests/", "/spec/", "/__tests__/",
                   "/testing/", "/fixtures/", "/mocks/", "/stubs/"]
    if any(p in path_lower for p in _test_dirs):
        return True
    _test_names = ("test_", "_test.py", ".test.js", ".spec.js",
                   ".test.ts", ".spec.ts", "Test.java", "Tests.java",
                   "_test.go", "_test.rs")
    if name.startswith("test_"):
        return True
    if any(name.endswith(suffix) for suffix in _test_names[1:]):
        return True
    return False

def _classify_is_generated(path_lower, name, ext):
    _gen_kw = ["generated", "_pb2", "_grpc", ".pb.", "auto_generated", "_generated"]
    if any(kw in name for kw in _gen_kw):
        return True
    _gen_dirs = ["/generated/", "/gen/", "/out/", "/dist/", "/build/",
                  "/node_modules/", "/vendor/", "/third_party/"]
    if any(kw in path_lower for kw in _gen_dirs):
        return True
    return False

def _classify_is_config(path_lower, name, ext):
    if ext in (".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".env", ".xml"):
        if "package.json" in name or "tsconfig" in name or "docker" in name:
            return True
    return False

def _classify_is_migration(path_lower, name, ext):
    _mig_dirs = ["/migration/", "/migrations/", "/migrate/", "/schema/"]
    if any(kw in path_lower for kw in _mig_dirs):
        return True
    if ext == ".sql":
        return True
    return False

# 规则 dispatch 表：(谓词函数, 返回值) 按优先级排列
_CLASSIFY_RULES = [
    (_classify_is_doc, "doc"),
    (_classify_is_test, "test"),
    (_classify_is_generated, "generated"),
    (_classify_is_config, "config"),
    (_classify_is_migration, "migration"),
]


class FileClassifier:
    """文件类型分类器（v2.0.10: CC=29→5，if/elif 链替换为规则 dispatch 表）"""
    
    def __init__(self):
        pass
    
    @staticmethod
    def classify(file_path):
        """根据文件路径和内容特征分类 — 规则 dispatch 表驱动"""
        path_lower = file_path.lower()
        name = os.path.basename(path_lower)
        ext = os.path.splitext(path_lower)[1].lower()
        
        for predicate, label in _CLASSIFY_RULES:
            if predicate(path_lower, name, ext):
                return label
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
