#!/usr/bin/env python3
"""
CodeGuard Quality Security
===========================
安全检查 + 异常处理空块检测。
三扫描管线：原始→剥离后逐行→多行 DOTALL 双通道。
"""

import os
import re

import quality_core as _core


def _check_security(content, filepath, collector, file_type=None):
    """安全检查 — 三扫描模式
    
    第一遍：原始内容逐行扫描 → 置信度 70 (security_raw)
    第二遍：剥离注释和字符串后逐行扫描 → 置信度 85 (security)
    第三遍：剥离后全文 DOTALL 多行扫描 → 置信度 85 (security)
    三遍结果合并去重，只有剥离后仍匹配的才报 block。
    """
    ext = os.path.splitext(filepath)[1].lower()
    if file_type is None:
        file_type = _core.FileClassifier.classify(filepath)
    
    if file_type == "test":
        return
    
    # 第一遍：原始扫描
    lines = content.split("\n")
    raw_matches = []
    for i, line in enumerate(lines, 1):
        for idx, (pattern, description) in enumerate(_core.SECURITY_RED_FLAGS):
            match = re.search(pattern, line, re.IGNORECASE)
            if match:
                raw_matches.append((i, idx, match.group(), description))
    
    # 第二遍：剥离后扫描
    stripped = _core.strip_comments_and_strings(content, ext) if ext in (
        ".py", ".js", ".ts", ".mjs", ".java", ".cs", ".go", ".rs", ".cpp", ".c", ".h"
    ) else content
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
    
    # 第三遍：多行 DOTALL 双通道扫描
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
    
    # 仅在原始扫描中发现的低置信度警告
    for line_no, idx, matched, desc in raw_matches:
        key = (line_no, idx)
        if key not in confirmed:
            collector.add("warn", "security_raw", filepath, line_no,
                          f"安全问题(低置信度，可能在注释/字符串中): {desc}",
                          "确认该匹配不在注释或字符串中",
                          confidence=70)


# ============================================================
# 异常处理检测
# ============================================================

def _check_empty_except(content, filepath, collector, file_type="source"):
    """检测空的或过于简单的异常处理（Python 专用）"""
    lines = content.split("\n")
    
    in_except = False
    except_line = 0
    except_indent = 0
    in_docstring = False
    
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        
        # 同行检测：except SomeError: pass
        if re.match(r'except\b', stripped):
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
            if current_indent <= except_indent:
                in_except = False
                in_docstring = False
                continue
            if in_docstring:
                if stripped.startswith('"""') or stripped.startswith("'''"):
                    in_docstring = False
                continue
            if stripped == "" or stripped.startswith('#'):
                continue
            if stripped.startswith('"""') or stripped.startswith("'''"):
                if stripped.endswith('"""') or stripped.endswith("'''"):
                    if len(stripped) <= 6:
                        continue
                quote3 = stripped[:3]
                if len(stripped) > 3 and stripped.endswith(quote3) and len(stripped) > 6:
                    continue
                else:
                    in_docstring = True
                    continue
            if stripped in ("pass", "") or re.match(r'print\s*\(', stripped):
                collector.add("warn", "error_handling", filepath, except_line,
                              "异常处理过于简单（pass 或仅 print）",
                              "添加适当的日志记录和错误处理逻辑",
                              confidence=82)
            in_except = False


def _check_empty_except_generic(content, filepath, collector, ext):
    """多语言空异常处理检测"""
    lines = content.split("\n")
    
    _LANG_CONFIG = {
        ".py":  (re.compile(r'except\b'), ("pass", "")),
        ".js":  (re.compile(r'catch\s*\('), ("{}", "")),
        ".ts":  (re.compile(r'catch\s*\('), ("{}", "")),
        ".java": (re.compile(r'catch\s*\('), ("{}", "", "// TODO", "// ignore")),
        ".cs":   (re.compile(r'catch\b'), ("{}", "", "// TODO")),
        ".go":   (re.compile(r'if\s+err\s*!=\s*nil'),
                   ("return", "return err", "return nil", "return nil, err",
                    "return 0, err", "return false, err", "return \"\", err")),
        ".rs":   (re.compile(r'catch\b'), ("{}", "")),
        ".cpp":  (re.compile(r'catch\b'), ("{}", "")),
        ".c":    (re.compile(r'catch\b'), ("{}", "")),
        ".h":    (re.compile(r'catch\b'), ("{}", "")),
    }
    
    config = _LANG_CONFIG.get(ext)
    if not config:
        return
    
    except_pattern, empty_body = config
    in_handler = False
    handler_line = 0
    
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if except_pattern.search(stripped):
            handler_line = i
            # 同行空体
            if ')' in stripped:
                body_after = stripped[stripped.rfind(')') + 1:].strip()
                if body_after in empty_body or body_after in ("{}", "{ }"):
                    collector.add("warn", "error_handling", filepath, handler_line,
                                  "异常处理过于简单（同行空体）",
                                  "添加适当的日志记录和错误处理逻辑",
                                  confidence=82)
                    continue
            in_handler = True
            continue
        if in_handler:
            if stripped == "" or stripped.startswith('//') or stripped.startswith('#'):
                continue
            if stripped in empty_body or re.match(r'print\s*\(', stripped):
                collector.add("warn", "error_handling", filepath, handler_line,
                              "异常处理过于简单",
                              "添加适当的日志记录和错误处理逻辑",
                              confidence=82)
            in_handler = False
