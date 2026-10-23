#!/usr/bin/env python3
"""
CodeGuard Quality Custom Rules
===============================
自定义规则加载 + 声明式模式匹配引擎 + 命名一致性检测。
支持 .code-guardian/rules.json 金/银/铜级门禁阈值覆盖。
v2.0.12: 增加 CLI 工具自动识别、codeguard:ignore 内联豁免、规则上下文过滤。

# codeguard: ignore GOLD_NO_LAZY_IMPORT — 必要的延迟导入避免循环依赖
"""

import fnmatch
import json
import os
import re
from collections import defaultdict
from pathlib import Path

import quality_core as _core
from internal import rules_loader


# ============================================================
# CLI 工具识别与豁免标记检测
# ============================================================

def _is_cli_tool(content: str) -> bool:
    """检测文件是否为 CLI 工具入口（含 argparse/click/__main__ 特征）"""
    return bool(
        re.search(r'import\s+argparse', content) or
        re.search(r'import\s+click', content) or
        re.search(r'from\s+click\s+import', content) or
        re.search(r"if\s+__name__\s*==\s*['\"]__main__['\"]", content) or
        re.search(r'@click\.(?:command|group)', content) or
        re.search(r'argparse\.(?:ArgumentParser|add_argument)', content)
    )


def _has_codeguard_ignore(line: str, rule_id: str = None) -> bool:
    """检查行中是否包含 codeguard:ignore 豁免标记"""
    if '# codeguard: ignore' not in line and '# noqa' not in line:
        return False
    if rule_id and f'# codeguard: ignore {rule_id}' in line:
        return True
    if '# codeguard: ignore' in line:
        return True
    return '# noqa' in line


def _is_commented_or_docstring(line: str) -> bool:
    """判断行是否在注释或文档字符串中"""
    stripped = line.strip()
    if stripped.startswith('#'):
        return True
    if stripped.startswith('"""') or stripped.startswith("'''"):
        return True
    return False


# ---- P1-3: URL 上下文感知过滤 ----

def _should_skip_hardcoded_url(line: str) -> bool:
    """判断硬编码 URL 行是否属于可豁免的上下文"""
    # 大写常量赋值：SARIF_SCHEMA_URI = "https://..."  # codeguard: ignore GOLD_NO_HARDCODED_URL
    if re.match(r'^\s*[A-Z_][A-Z0-9_]*\s*=', line):
        return True
    # 注释中的 URL
    if line.strip().startswith('#'):
        return True
    # SARIF/schema 标准规范 URL
    if re.search(r'sarif|schema|oasis-open', line, re.IGNORECASE):
        return True
    # 文档说明中的 URL（如 README/建议文本）
    if re.search(r'安装|文档|参考|见\s', line):
        return True
    return False


# ---- P1-4: 空 except 容错场景识别 ----

def _is_data_parsing_tolerance(pre_context: str) -> bool:
    """检测空 except 块上方的 try 块是否为数据解析操作（可接受的容错）"""
    return bool(
        re.search(r'\bint\(|\bfloat\(|\bjson\.loads\(|\bjson\.load\b', pre_context) or
        re.search(r'\.split\(|\.strip\(|str\(', pre_context)
    )


# ---- P1-6: 大写常量排除 ----

def _is_const_assignment(line: str) -> bool:
    """检测行是否为纯大写常量赋值"""
    return bool(re.match(r'^\s*[A-Z_][A-Z0-9_]*\s*=', line))


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
    """加载 .code-guardian/rules.json 中的自定义规则 + 阈值覆盖 + 忽略路径
    
    v2.0.11: 使用 internal/rules_loader 统一加载逻辑，消除 repetition。
    """
    root = Path(root_path)
    data = rules_loader.load_rules_json(root)
    rules = data.get('rules', []) if data else []
    raw_thresholds = data.get('thresholds') if data else None
    ignore_paths = data.get('ignorePaths', {}) if data else {}
    ignore_patterns = ignore_paths.get('patterns', []) if isinstance(ignore_paths, dict) else []
    custom_thresholds = _validate_thresholds(raw_thresholds) if raw_thresholds else None
    return rules, custom_thresholds, ignore_patterns


def _match_target(filepath, target):
    """检查文件是否匹配自定义规则的作用域

    支持格式:
      - "all"                    → 全部文件
      - "python"                 → 单语言
      - "python|javascript|java" → 管道多语言（v0.2.3 新增）
      - "domain"                 → 架构层级
      - "**/foo/**/*.ext"        → glob 模式
    """
    if target == "all":
        return True
    
    filepath_lower = filepath.lower()
    
    # 按语言过滤
    from quality_arch import _detect_file_lang
    file_lang = _detect_file_lang(filepath)
    lang_targets = {"python", "javascript", "java", "go", "csharp", "rust"}
    if target in lang_targets:
        return file_lang == target
    
    # v0.2.3: 管道多语言 target（如 "python|javascript|java|go|csharp|rust"）
    if "|" in target:
        parts = target.split("|")
        return any(part in lang_targets and file_lang == part for part in parts)
    
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
    """根据自定义规则执行检测（声明式模式匹配引擎）
    
    v2.0.12 修复：
    - P0-1: message 始终包含 [rule_id] 前缀，确保 extract_rule_id() 可正确提取
    - P0-2: GOLD_NO_PRINT_PRODUCTION 自动识别 CLI 工具并跳过
    - P0-3: # codeguard: ignore / # noqa 内联豁免解析
    - P1-3: GOLD_NO_HARDCODED_URL 跳过注释/常量/SARIF schema URL
    - P1-4: GOLD_NO_EMPTY_EXCEPT 识别数据解析容错场景
    - P1-6: GOLD_NO_GLOBAL_STATE 排除纯大写常量赋值
    - P1-5: 基于 expected_precision 元数据的置信度校准
    """
    if not custom_rules:
        return
    
    for rule in custom_rules:
        rule_id = rule.get("id", "?")
        severity = rule.get("severity", "warn")
        target = rule.get("target", "all")
        pattern_str = rule.get("pattern", "")
        message = rule.get("message", f"自定义规则 [{rule_id}]: {rule.get('description', '')}")
        suggestion = rule.get("suggestion", "")
        
        # P1-5: 置信度校准 — 基于规则 expected_precision 元数据动态调整
        expected_precision = rule.get("expected_precision", None)
        base_confidence = 80  # 正则匹配默认置信度
        if expected_precision is not None and isinstance(expected_precision, (int, float)):
            calibrated = base_confidence * min(float(expected_precision), 1.0)
            confidence = max(40, min(95, int(calibrated)))
        else:
            confidence = base_confidence  # 未指定时使用默认值
        
        if not pattern_str:
            collector.add("info", "custom_rule_config", "", 0,
                          f"自定义规则 [{rule_id}] 缺少 pattern 字段，跳过",
                          "在 rules.json 中为该规则添加 pattern 正则表达式")
            continue
        
        try:
            # v0.2.3: 支持 per-rule case_sensitive 标记（默认 false，保持 IGNORECASE 向后兼容）
            _flags = re.MULTILINE
            if not rule.get("case_sensitive", False):
                _flags |= re.IGNORECASE
            pattern = re.compile(pattern_str, _flags)
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
            except (OSError, UnicodeDecodeError) as e:
                _core._log(f"[CodeGuard] 无法读取文件 {filepath}: {e}")
                continue
            
            # P0-2: CLI 工具整体跳过 GOLD_NO_PRINT_PRODUCTION
            if rule_id == "GOLD_NO_PRINT_PRODUCTION" and _is_cli_tool(content):
                continue
            
            lines = content.split("\n")
            
            for match in pattern.finditer(content):
                line_no = content[:match.start()].count("\n") + 1
                matched_text = match.group(0)[:80]
                target_line = lines[line_no - 1] if line_no <= len(lines) else ""
                
                # ---- P0-3: codeguard:ignore 内联豁免 ----
                # 检查目标行及上方 3 行是否存在豁免注释
                check_start = max(0, line_no - 4)
                check_range = lines[check_start:line_no]
                if any(_has_codeguard_ignore(l, rule_id) for l in check_range):
                    continue
                if _has_codeguard_ignore(target_line, rule_id):
                    continue
                
                # ---- P1-3: GOLD_NO_HARDCODED_URL 上下文过滤 ----
                if rule_id == "GOLD_NO_HARDCODED_URL" and _should_skip_hardcoded_url(target_line):
                    continue
                
                # ---- P1-4: GOLD_NO_EMPTY_EXCEPT 数据解析容错 ----
                if rule_id == "GOLD_NO_EMPTY_EXCEPT":
                    pre_context = "\n".join(lines[max(0, line_no - 8):line_no])
                    if _is_data_parsing_tolerance(pre_context):
                        continue  # 数据解析容错 pass 是可接受模式
                
                # ---- P1-6: GOLD_NO_GLOBAL_STATE 大写常量排除 ----
                if rule_id == "GOLD_NO_GLOBAL_STATE" and _is_const_assignment(target_line):
                    continue
                
                # ---- v0.2.3: GOLD_NO_BROAD_EXCEPTION 块体上下文过滤 ----
                # 若 except Exception 块体内有 raise 或 logger 调用，说明异常被正确处理，跳过报告  # codeguard: ignore GOLD_NO_BROAD_EXCEPTION
                if rule_id == "GOLD_NO_BROAD_EXCEPTION":
                    post_context = "\n".join(lines[line_no:min(len(lines), line_no + 6)])
                    if re.search(r'\braise\b', post_context):
                        continue  # 异常被重新抛出
                    if re.search(r'\b(logger|logging)\b.*\b(?:error|exception|warning|critical)\b', post_context):
                        continue  # 异常已被记录日志
                
                # P0-1: message 始终包含 [rule_id] 前缀，确保规则 ID 可被正确提取
                # P1-5: 传递校准后的置信度
                collector.add(severity, "custom_rule", filepath, line_no,
                              f"[{rule_id}] {message} (匹配: {matched_text})",
                              suggestion,
                              confidence=confidence)


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
        except (OSError, UnicodeDecodeError) as e:
            _core._log(f"[CodeGuard] 命名检测 无法读取文件 {filepath}: {e}")
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
