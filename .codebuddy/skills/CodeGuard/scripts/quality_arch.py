#!/usr/bin/env python3
"""
CodeGuard Quality Architecture
===============================
依赖图构建、架构分层违规检测、循环依赖检测。
支持多语言 import 提取 (Python/JS/TS/Java/Go/C#/Rust)。
"""

import os
import re
from collections import defaultdict

import quality_core as _core


# ============================================================
# 多语言 import 提取 + 语言检测
# ============================================================

MULTILANG_IMPORT_PATTERNS = [
    (re.compile(r'(?:from\s+(\S+)\s+import|import\s+(\S+))'), "python"),
    (re.compile(r'(?:import\s+.*?\s+from\s+["\']([^"\']+)["\']|require\s*\(\s*["\']([^"\']+)["\']\s*\))'), "javascript"),
    (re.compile(r'import\s+([\w.]+);'), "java"),
    (re.compile(r'import\s+(?:\(\s*)?(?:"([^"]+)"\s*)+\)?|"[^"]+"'), "go"),
    (re.compile(r'using\s+([\w.]+);'), "csharp"),
    (re.compile(r'use\s+([\w:]+);'), "rust"),
    # C/C++ 族：#include "xxx.h" / #include <xxx.h>（v2.2.0 修复伪覆盖）
    (re.compile(r'#\s*include\s*[<"]([^>"]+)[>"]'), "c"),
]

_LANG_EXT_MAP = {
    ".py": "python", ".pyx": "python",
    ".js": "javascript", ".mjs": "javascript",
    ".ts": "javascript", ".tsx": "javascript",
    ".java": "java",
    ".go": "go",
    ".cs": "csharp",
    ".rs": "rust",
    # C/C++ 族（v2.2.0 修复伪覆盖：此前 C 文件 _detect_file_lang 返回 unknown 被静默跳过）
    ".c": "c", ".h": "c",
    ".cpp": "c", ".hpp": "c", ".cc": "c", ".cxx": "c",
}

# 嵌入式专用分层映射（v2.2.0）：嵌入式无 DDD 概念，映射到等价抽象层级
# HAL/BSP/Driver/寄存器 → infrastructure（底层）；app/task/main → application（上层）
_EMBEDDED_LAYER_MAP = {
    "hal": "infrastructure", "bsp": "infrastructure", "board": "infrastructure",
    "driver": "infrastructure", "drivers": "infrastructure", "mcu": "infrastructure",
    "register": "infrastructure", "peripheral": "infrastructure",
    "app": "application", "application": "application", "task": "application",
    "tasks": "application", "middleware": "application",
}


def _detect_file_lang(filepath):
    """根据扩展名推断文件语言"""
    ext = os.path.splitext(filepath)[1].lower()
    return _LANG_EXT_MAP.get(ext, "unknown")


def _infer_layer(path_or_module):
    """根据路径或模块名推断架构层级。

    优先匹配嵌入式专用分层（HAL/BSP/Driver/App），回退到通用 DDD 分层。
    """
    lowered = path_or_module.lower()
    # 1) 嵌入式分层（v2.2.0）
    for kw, layer in _EMBEDDED_LAYER_MAP.items():
        if kw in lowered:
            return layer
    # 2) 通用 DDD 分层 — 单词边界匹配（下划线视为段边界），避免子串误报
    #    例：stdbool 含子串 "db" 不应判定为 infrastructure 层
    for layer, patterns in _core.LAYER_PATTERNS.items():
        for p in patterns:
            if re.search(r'(?<![a-z0-9])' + re.escape(p) + r'(?![a-z0-9])', lowered):
                return layer
    return "unknown"


# ============================================================
# 依赖图
# ============================================================

class DependencyGraph:
    """模块间依赖关系图"""
    
    def __init__(self):
        self.edges = defaultdict(set)
        self.reverse = defaultdict(set)
        self.layer_map = {}
        self.lang_map = {}
    
    def add_edge(self, from_file, to_module):
        self.edges[from_file].add(to_module)
        self.reverse[to_module].add(from_file)
    
    def set_layer(self, filepath, layer):
        self.layer_map[filepath] = layer
    
    def set_lang(self, filepath, lang):
        self.lang_map[filepath] = lang
    
    def _find_matching_files(self, module_or_path):
        """根据模块名精确匹配文件路径（路径段边界匹配）"""
        results = []
        module_lower = module_or_path.lower().replace(".", "/")
        module_parts = [p for p in module_lower.split("/") if p]
        if not module_parts:
            return results
        
        for filepath in self.edges:
            filepath_lower = filepath.lower().replace("\\", "/")
            filepath_parts = [p for p in filepath_lower.split("/") if p]
            
            basename = os.path.basename(filepath_lower)
            basename_no_ext = os.path.splitext(basename)[0].lower()
            if basename_no_ext == module_parts[-1]:
                results.append(filepath)
                continue
            
            if len(module_parts) <= len(filepath_parts):
                if filepath_parts[-len(module_parts):] == module_parts:
                    results.append(filepath)
        
        # v3.0.0: 取消 [:5] 截断，去重后全量返回，避免模块匹配 >5 文件时循环依赖漏检
        return list(dict.fromkeys(results))
    
    def find_cycles(self, max_depth=50):
        """DFS 检测循环依赖"""
        cycles = []
        all_nodes = list(self.edges.keys())
        
        for start in all_nodes:
            visited = set()
            path = [start]
            
            def dfs(node, depth):
                if depth > max_depth:
                    return
                for neighbor in self.edges.get(node, set()):
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
    
    def check_layer_violations(self, collector):
        """检查分层违规 + 检测循环依赖"""
        # 1. 分层违规
        for filepath, imps in self.edges.items():
            file_layer = self.layer_map.get(filepath, _infer_layer(filepath.lower()))
            file_type = _core.FileClassifier.classify(filepath)
            if file_type in ("generated", "doc", "config"):
                continue
            
            for imp in imps:
                imp_layer = _infer_layer(imp.lower())
                if file_layer == "domain" and imp_layer in ("infrastructure", "presentation"):
                    conf = 90 if self._find_matching_files(imp) else 78
                    collector.add("block", "architecture", filepath, 0,
                                  f"架构违规：Domain 层引用了 {imp_layer} 层 ({imp})",
                                  "Domain 层应定义接口，由 Infrastructure 层实现",
                                  confidence=conf)
                if file_layer == "application" and imp_layer == "infrastructure":
                    collector.add("warn", "architecture", filepath, 0,
                                  f"架构警告：Application 层直接引用 Infrastructure 层 ({imp})",
                                  "应通过接口/抽象类进行依赖倒置",
                                  confidence=88)
        
        # 2. 循环依赖
        cycles = self.find_cycles()
        reported_cycles = set()
        for cycle_files, cycle_path in cycles:
            cycle_key = tuple(sorted(cycle_files[:3]))
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
        file_type = _core.FileClassifier.classify(filepath)
        if file_type in ("generated", "doc", "config"):
            continue
        
        file_layer = _infer_layer(filepath_lower)
        file_lang = _detect_file_lang(filepath)
        graph.set_layer(filepath, file_layer)
        graph.set_lang(filepath, file_lang)
        
        try:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except (OSError, UnicodeDecodeError):
            continue
        
        # P0 修复：剥除 docstring/注释，避免 docstring 示例 import 被误判为真实 import
        ext = os.path.splitext(filepath)[1].lower()
        content = _core.strip_comments_and_strings(content, ext)
        # P0 修复（延续）：仅保留模块级 import（行首无缩进），忽略函数内惰性导入
        # （惰性导入是打破循环依赖的合法模式，不应被判为循环依赖）
        if ext == ".py":
            content = re.sub(
                r'^[ \t]+(?:from\s+\S+\s+import\s+\S+|import\s+\S+)',
                lambda m: ' ' * len(m.group()), content, flags=re.MULTILINE,
            )
        
        for pattern, lang in MULTILANG_IMPORT_PATTERNS:
            if lang == file_lang:
                for match in pattern.finditer(content):
                    module = match.group(1) or (match.group(2) if match.lastindex and match.lastindex >= 2 else None)
                    if module:
                        graph.add_edge(filepath, module)
                break
    
    return graph


def check_architecture(source_files, collector):
    """检测架构分层违规 + 循环依赖"""
    graph = build_dependency_graph(source_files)
    graph.check_layer_violations(collector)
