#!/usr/bin/env python3
"""
CodeGuard Quality Custom Rules
===============================
自定义规则加载 + 声明式模式匹配引擎 + 命名一致性检测。
支持 .code-guardian/rules.json 金/银/铜级门禁阈值覆盖。
"""

import fnmatch
import json
import os
import re
from collections import defaultdict
from pathlib import Path

import quality_core as _core


# ---- load_custom_quality_rules 子函数 ----

def _read_rules_json(config_path):
    """读取 .code-guardian/rules.json，返回 (rules, raw_thresholds)"""
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        rules = data.get("rules", [])
        thresholds = data.get("thresholds")
        return rules, thresholds
    except FileNotFoundError:
        return [], None
    except json.JSONDecodeError as e:
        _core._log(f"[CodeGuard] 自定义规则 JSON 解析失败: {config_path} - {e}")
        return [], None
    except Exception as e:
        _core._log(f"[CodeGuard] 加载自定义规则异常: {config_path} - {e}")
        return [], None


def _validate_thresholds(custom_thresholds):
    """验证并过滤自定义阈值，记录未知键"""
    if not isinstance(custom_thresholds, dict):
        return None
    valid_keys = set(_core.THRESHOLDS.keys())
    unknown = {k for k in custom_thresholds if k not in valid_keys and not k.startswith('_')}
    if unknown:
        _core._log(f"[CodeGuard] ⚠️ 未知阈值键将被忽略: {', '.join(sorted(unknown))}")
    return {k: v for k, v in custom_thresholds.items()
            if k in valid_keys and isinstance(v, (int, float)) and v > 0} or None


def load_custom_quality_rules(root_path):
    """加载 .code-guardian/rules.json 中的自定义规则 + 阈值覆盖 — v2.0.10: CC=16→3"""
    config_path = Path(root_path) / ".code-guardian" / "rules.json"
    custom_rules, raw_thresholds = _read_rules_json(config_path)
    custom_thresholds = _validate_thresholds(raw_thresholds) if raw_thresholds else None
    return custom_rules, custom_thresholds


def _match_target(filepath, target):
    """检查文件是否匹配自定义规则的作用域"""
    if target == "all":
        return True
    
    filepath_lower = filepath.lower()
    
    # 按语言过滤
    from quality_arch import _detect_file_lang
    file_lang = _detect_file_lang(filepath)
    lang_targets = {"python", "javascript", "java", "go", "csharp", "rust"}
    if target in lang_targets:
        return file_lang == target
    
    # 按架构层级过滤
    from quality_arch import _infer_layer
    layer_targets = {"domain", "application", "infrastructure", "presentation"}
    if target in layer_targets:
        return _infer_layer(filepath_lower) == target
    
    # 按文件模式过滤 (glob-like)
    pattern_lower = target.lower()
    if "**" in pattern_lower:
        parts = pattern_lower.split("**")
        for part in parts:
            part = part.strip("/\\")
            if part and part not in filepath_lower.replace("\\", "/"):
                return False
        return True
    
    if "*" in pattern_lower:
        return fnmatch.fnmatch(os.path.basename(filepath_lower), pattern_lower)
    
    return pattern_lower in filepath_lower


def check_custom_rules(source_files, custom_rules, collector):
    """根据自定义规则执行检测（声明式模式匹配引擎）"""
    if not custom_rules:
        return
    
    for rule in custom_rules:
        rule_id = rule.get("id", "?")
        severity = rule.get("severity", "warn")
        target = rule.get("target", "all")
        pattern_str = rule.get("pattern", "")
        message = rule.get("message", f"自定义规则 [{rule_id}]: {rule.get('description', '')}")
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
            if not _match_target(filepath, target):
                continue
            
            try:
                with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
            except Exception:
                continue
            
            for match in pattern.finditer(content):
                line_no = content[:match.start()].count("\n") + 1
                matched_text = match.group(0)[:80]
                collector.add(severity, "custom_rule", filepath, line_no,
                              f"{message} (匹配: {matched_text})",
                              suggestion)


# ============================================================
# 命名一致性检测
# ============================================================

def check_naming_consistency(source_files, collector):
    """检测命名一致性（支持多语言函数声明）"""
    name_map = defaultdict(set)
    
    func_patterns = [
        (re.compile(r'def\s+(\w+)'), "python"),
        (re.compile(r'(?:async\s+)?function\s+(\w+)'), "javascript"),
        (re.compile(r'(?:public|private|protected|static)?\s*(?:async\s+)?(?:[\w<>\[\]]+\s+)?(\w+)\s*\([^)]*\)\s*\{'), "java/csharp"),
        (re.compile(r'func\s+(?:\(\w+\s+\*?\w+\)\s+)?(\w+)\s*\('), "go"),
        (re.compile(r'fn\s+(\w+)\s*\('), "rust"),
    ]
    
    _NAME_PREFIXES = [
        "get_", "fetch_", "retrieve_", "find_", "query_",
        "set_", "update_", "modify_", "save_", "create_",
        "delete_", "remove_", "destroy_",
        "get", "fetch", "retrieve", "find", "query",
        "set", "update", "modify", "save", "create",
        "delete", "remove", "destroy",
    ]
    
    for filepath in source_files:
        try:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except Exception:
            continue
        
        for pattern, lang in func_patterns:
            for match in pattern.finditer(content):
                func_name = match.group(1)
                if func_name.startswith("__") or func_name.startswith("_"):
                    continue
                for prefix in _NAME_PREFIXES:
                    if func_name.lower().startswith(prefix.lower()):
                        suffix = func_name[len(prefix):]
                        name_map[("verb", prefix)].add((suffix, filepath))
                        break
    
    for (_, prefix), entries in name_map.items():
        suffixes = defaultdict(list)
        for suffix, fpath in entries:
            suffixes[suffix].append(fpath)
        for suffix, paths in suffixes.items():
            if len(paths) > 1:
                collector.add("info", "naming", paths[0], 0,
                              f"命名不一致：实体 '{suffix}' 在多处使用前缀 '{prefix}'，"
                              f"请确认是否有更合适的统一命名")
