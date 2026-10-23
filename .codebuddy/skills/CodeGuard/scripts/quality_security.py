#!/usr/bin/env python3
"""
CodeGuard Quality Security
===========================
安全检查 + 异常处理空块检测。
三扫描管线：原始→剥离后逐行→多行 DOTALL 双通道。
"""

import os
import re
from pathlib import Path

import quality_core as _core


# ---- 三遍扫描子函数 ----

def _scan_raw(lines):
    """第一遍：原始内容逐行扫描 → 返回 (raw_matches) 列表"""
    raw_matches = []
    for i, line in enumerate(lines, 1):
        # 识别豁免标记：含 # codeguard: ignore 或 # noqa 的行跳过
        if '# codeguard: ignore' in line or '# noqa' in line:
            continue
        for idx, (pattern, description) in enumerate(_core.SECURITY_RED_FLAGS):
            match = re.search(pattern, line, re.IGNORECASE)
            if match:
                raw_matches.append((i, idx, match.group(), description))
    return raw_matches


def _scan_stripped_lines(stripped, lines, collector, filepath):
    """第二遍：剥离后逐行扫描 → 返回 confirmed set"""
    stripped_lines = stripped.split("\n")
    confirmed = set()
    for i, line in enumerate(stripped_lines, 1):
        if i > len(lines):
            break
        for idx, (pattern, description) in enumerate(_core.SECURITY_RED_FLAGS):
            match = re.search(pattern, line, re.IGNORECASE)
            if match:
                key = (i, idx)
                if key not in confirmed:
                    confirmed.add(key)
                    collector.add("block", "security", filepath, i,
                                  f"安全问题: {description}",
                                  "使用环境变量/密钥管理服务存储凭证，使用参数化查询",
                                  confidence=85)
    return confirmed


def _scan_multiline(stripped, collector, filepath, confirmed):
    """第三遍：多行 DOTALL 双通道扫描 → 追加到 confirmed"""
    PASSWORD_CHANNEL_INDICES = {0}
    normalized_pwd = stripped.replace('\n', ' ').replace('(', ' ').replace(')', ' ').replace('\\', ' ')
    normalized_func = stripped.replace('\n', ' ').replace('\\', ' ')
    
    for idx, (pattern, description) in enumerate(_core.SECURITY_RED_FLAGS):
        normalized = normalized_pwd if idx in PASSWORD_CHANNEL_INDICES else normalized_func
        for match in re.finditer(pattern, normalized, re.IGNORECASE):
            line_no = stripped[:match.start()].count('\n') + 1
            key = (line_no, idx)
            if key not in confirmed:
                confirmed.add(key)
                collector.add("block", "security", filepath, line_no,
                              f"安全问题(多行检测): {description}",
                              "使用环境变量/密钥管理服务存储凭证，使用参数化查询",
                              confidence=85)
    return confirmed


def _report_raw_unmatched(raw_matches, confirmed, collector, filepath):
    """报告仅在原始扫描中发现的低置信度警告"""
    for line_no, idx, matched, desc in raw_matches:
        key = (line_no, idx)
        if key not in confirmed:
            collector.add("warn", "security_raw", filepath, line_no,
                          f"安全问题(低置信度，可能在注释/字符串中): {desc}",
                          "确认该匹配不在注释或字符串中",
                          confidence=70)


def _check_security(content, filepath, collector, file_type=None):
    """安全检查 — 三扫描管线编排器（v2.0.10: CC=16→4）"""
    ext = os.path.splitext(filepath)[1].lower()
    if file_type is None:
        file_type = _core.FileClassifier.classify(filepath)
    if file_type == "test":
        return
    
    lines = content.split("\n")
    raw_matches = _scan_raw(lines)
    
    _strippable = {".py", ".js", ".ts", ".mjs", ".java", ".cs", ".go", ".rs", ".cpp", ".c", ".h"}
    stripped = _core.strip_comments_and_strings(content, ext) if ext in _strippable else content
    
    confirmed = _scan_stripped_lines(stripped, lines, collector, filepath)
    _scan_multiline(stripped, collector, filepath, confirmed)
    _report_raw_unmatched(raw_matches, confirmed, collector, filepath)


# ============================================================
# 异常处理检测
# ============================================================

# ---- _check_empty_except 子函数 ----

def _is_except_inline_pass(stripped):
    """检测同行 except: pass 模式 → 返回 True 表示已处理"""
    if not re.match(r'except\b', stripped):
        return False
    code_only = re.sub(r'#.*$', '', stripped).rstrip()
    rest = re.sub(r'^.*:\s*', '', code_only)
    # 只检测真正的同行 pass（rest 非空且为 pass），
    # 排除多行 except（rest 为空，体在下一行）
    return rest == "pass" or code_only.endswith(": pass")


def _is_triple_quote_start(s):
    """检测三引号开始"""
    return s.startswith('"""') or s.startswith("'''")

def _is_triple_quote_end(s):
    """检测三引号结束"""
    return s.endswith('"""') or s.endswith("'''")

def _is_self_closing_docstring(stripped):
    """单行自闭合文档字符串 (e.g. \"\"\"doc\"\"\") → True 表示无需跟踪状态"""
    if not (_is_triple_quote_start(stripped) and _is_triple_quote_end(stripped)):
        return False
    if len(stripped) <= 6:
        return True
    quote3 = stripped[:3]
    if len(stripped) > 3 and stripped.endswith(quote3) and len(stripped) > 6:
        return True
    return False

def _handle_docstring_state(stripped, in_docstring):
    """处理文档字符串边界，返回 (updated_in_docstring, skip_this_line) — v2.0.10: CC=16→2"""
    if in_docstring:
        return (False, True) if _is_triple_quote_start(stripped) else (True, True)
    if _is_triple_quote_start(stripped):
        return (False, True) if _is_self_closing_docstring(stripped) else (True, True)
    return False, False


def _is_simple_body(stripped):
    """检测"过于简单"的异常处理体（pass / print / return None / continue）。

    2026-10-04 修复三处漏报（实测得出的 A/B 结论）：
      1. **未剥离行尾注释** → `pass  # 说明` 不匹配，被整条漏掉
         （而带注释的 `pass` 恰恰是最常见写法——作者越是想说明"我是故意吞的"，越检不出）
      2. **未识别 `return None`** → 在 except 里静默返回 None 等价于吞掉错误
      3. **未识别 `continue`** → 在循环里 `except: continue` 会静默跳过出错项

    注意：`return None` 判据限定"独占一行"，避免误伤 `return None if ... else f()` 之类表达式。
    """
    code = re.sub(r'#.*$', '', stripped).strip()      # 先剥行尾注释
    if code in ("pass", "", "continue"):
        return True
    if re.match(r'return\s+None\s*$', code):
        return True
    return bool(re.match(r'print\s*\(', code))


def _check_empty_except(content, filepath, collector, file_type="source"):
    """检测空的或过于简单的异常处理（Python 专用）— v2.0.10: CC=29→7"""
    lines = content.split("\n")
    in_except = False
    except_line = 0
    except_indent = 0
    in_docstring = False
    
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        
        # 同行检测
        if _is_except_inline_pass(stripped):
            collector.add("warn", "error_handling", filepath, i,
                          "异常处理过于简单（except 行直接 pass）",
                          "添加适当的日志记录和错误处理逻辑", confidence=82)
            continue
        
        if re.match(r'except\b', stripped):
            in_except = True
            except_line = i
            except_indent = len(line) - len(line.lstrip())
            in_docstring = False
            continue
        
        if not in_except:
            continue
        
        current_indent = len(line) - len(line.lstrip())
        if current_indent <= except_indent:
            in_except = False
            in_docstring = False
            continue
        
        in_docstring, skip = _handle_docstring_state(stripped, in_docstring)
        if skip:
            continue
        
        if stripped == "" or stripped.startswith('#'):
            continue
        
        if _is_simple_body(stripped):
            collector.add("warn", "error_handling", filepath, except_line,
                          "异常处理过于简单（pass 或仅 print）",
                          "添加适当的日志记录和错误处理逻辑", confidence=82)
        in_except = False


# ---- _check_empty_except_generic 辅助 ----

_LANG_CONFIG = {
    ".py":   (re.compile(r'except\b'), ("pass", "")),
    ".js":   (re.compile(r'catch\s*\('), ("{}", "")),
    ".ts":   (re.compile(r'catch\s*\('), ("{}", "")),
    ".java": (re.compile(r'catch\s*\('), ("{}", "", "// TODO", "// ignore")),  # codeguard: ignore GOLD_NO_TODO_WITHOUT_TICKET
    ".cs":   (re.compile(r'catch\b'), ("{}", "", "// TODO")),  # codeguard: ignore GOLD_NO_TODO_WITHOUT_TICKET
    ".go":   (re.compile(r'if\s+err\s*!=\s*nil'),
               ("return", "return err", "return nil", "return nil, err",
                "return 0, err", "return false, err", "return \"\", err")),
    ".rs":   (re.compile(r'catch\b'), ("{}", "")),
    ".cpp":  (re.compile(r'catch\b'), ("{}", "")),
    ".c":    (re.compile(r'catch\b'), ("{}", "")),
    ".h":    (re.compile(r'catch\b'), ("{}", "")),
}


def _check_inline_empty_body(stripped, empty_body):
    """检测同行空体: catch(Exception) {} → True 表示已空"""
    if ')' not in stripped:
        return False
    body_after = stripped[stripped.rfind(')') + 1:].strip()
    return body_after in empty_body or body_after in ("{}", "{ }")


def _is_skip_line(stripped):
    """空行或注释行"""
    return stripped == "" or stripped.startswith('//') or stripped.startswith('#')


def _check_empty_except_generic(content, filepath, collector, ext):
    """多语言空异常处理检测 — v2.0.10: CC=16→5"""
    config = _LANG_CONFIG.get(ext)
    if not config:
        return
    
    except_pattern, empty_body = config
    lines = content.split("\n")
    in_handler = False
    handler_line = 0
    
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if except_pattern.search(stripped):
            handler_line = i
            if _check_inline_empty_body(stripped, empty_body):
                collector.add("warn", "error_handling", filepath, handler_line,
                              "异常处理过于简单（同行空体）",
                              "添加适当的日志记录和错误处理逻辑", confidence=82)
                continue
            in_handler = True
            continue
        if not in_handler:
            continue
        if _is_skip_line(stripped):
            continue
        if stripped in empty_body or re.match(r'print\s*\(', stripped):
            collector.add("warn", "error_handling", filepath, handler_line,
                          "异常处理过于简单",
                          "添加适当的日志记录和错误处理逻辑", confidence=82)
        in_handler = False


# ============================================================
# SAST 结果聚合器（D5 增强：Semgrep → CodeGuard 统一格式）
# ============================================================

SAST_SEVERITY_MAP = {
    "ERROR": ("block", 92),
    "WARNING": ("warn", 80),
    "INFO": ("info", 65),
}

# SAST 分类关键词映射表（check_id 子串 → CodeGuard 类别）
# 用查表 + 循环替代多分支 if，圈复杂度从 16 降至 2
_SAST_CATEGORY_MAP = (
    (("xss", "injection", "sqli", "rce", "command-injection"), "security"),
    (("deserialization", "pickle", "yaml-load", "eval-"), "security_raw"),
    (("hardcoded", "credential", "secret", "password", "api-key", "token"), "security"),
    (("csrf", "ssrf", "xxe", "path-traversal", "open-redirect"), "security"),
    (("crypto", "hash", "ssl", "tls", "certificate"), "security"),
    (("permission", "authorization", "access-control"), "security"),
    (("error", "except"), "error_handling"),
)


def _classify_sast_finding(check_id, message):
    """分类 Semgrep 发现到 CodeGuard 类别（查表驱动，圈复杂度=2）"""
    cid = check_id.lower()
    for keywords, category in _SAST_CATEGORY_MAP:
        if any(k in cid for k in keywords):
            return category
    return "sast"


def aggregate_sast_results(sast_json_path, collector, file_map=None):
    """将 Semgrep JSON 扫描结果聚合到 CodeGuard 问题收集器。
    
    Args:
        sast_json_path: Semgrep --json 输出文件路径
        collector: CodeGuard IssueCollector 实例
        file_map: 可选 dict {filepath: file_type} 用于文件分类
    
    Returns:
        dict: {'total': int, 'block': int, 'warn': int, 'info': int}
    """
    import json as _json
    import os as _os
    
    stats = {'total': 0, 'block': 0, 'warn': 0, 'info': 0}
    try:
        data = _json.loads(Path(sast_json_path).read_text(encoding='utf-8'))
    except (FileNotFoundError, json.JSONDecodeError, ValueError) as e:
        collector.add("warn", "sast", "SAST Report", 0,
                      f"无法解析 SAST 结果文件: {e}",
                      "确认 Semgrep 已正确生成 JSON 输出", confidence=60)
        return stats
    
    results = data.get('results', []) if isinstance(data, dict) else []
    if not results:
        collector.add("info", "sast", "SAST Report", 0,
                      "SAST 扫描未发现缺陷", "", confidence=90)
        return stats
    
    for finding in results:
        check_id = finding.get('check_id', 'semgrep.unknown')
        extra = finding.get('extra', {})
        message = extra.get('message', check_id)
        path_str = finding.get('path', 'unknown')
        start = finding.get('start', {})
        line_no = start.get('line', 1)
        severity = extra.get('severity', 'WARNING').upper()
        sev_level, confidence = SAST_SEVERITY_MAP.get(severity, ("warn", 75))
        
        category = _classify_sast_finding(check_id, message)
        suggestion = extra.get('fix', '') or extra.get('metadata', {}).get('fix_regex', {}).get('regex', '') or '参考 Semgrep 规则文档修复该问题'
        
        collector.add(sev_level, category, path_str, line_no,
                      f"[SAST] {check_id}: {message}",
                      suggestion, confidence=confidence)
        stats['total'] += 1
        stats[sev_level] = stats.get(sev_level, 0) + 1
    
    return stats
