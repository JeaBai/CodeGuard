#!/usr/bin/env python3
"""
CodeGuard Quality Checks
=========================
文件级质量检测：圈复杂度、嵌套深度、参数数量、类大小、文件大小。
覆盖 Python (AST精确) + JS/TS/Java/Go/C# (正则近似) 多语言派发。
"""

import ast
import os
import re

import quality_core as _core

import os
import sys as _sys
_sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'internal'))
from detector_registry import register_detector, get_detectors


# ============================================================
# 语言分支关键词（圈复杂度近似）
# ============================================================

LANG_CC_PATTERNS = {
    # v2.2.1: 移除 r'\belse\s+if\s*\(' 重复模式（else if 中的 if 已被 r'\bif\s*\( 匹配，
    # 导致每个 else-if 被重复计 1 次）；Go 移除 r'if\s+err\s*!=\s*nil'（与 r'\bif\s+' 重复）
    ".js": [r'\bif\s*\(', r'\bfor\s*\(', r'\bwhile\s*\(',
            r'\bswitch\s*\(', r'\bcase\s+', r'&&', r'\|\|', r'\?\?', r'\bcatch\s*\('],
    ".ts": [r'\bif\s*\(', r'\bfor\s*\(', r'\bwhile\s*\(',
            r'\bswitch\s*\(', r'\bcase\s+', r'&&', r'\|\|', r'\?\?', r'\bcatch\s*\('],
    ".mjs": [r'\bif\s*\(', r'\bfor\s*\(', r'\bwhile\s*\(',
             r'\bswitch\s*\(', r'\bcase\s+', r'&&', r'\|\|', r'\?\?', r'\bcatch\s*\('],
    ".java": [r'\bif\s*\(', r'\bfor\s*\(', r'\bwhile\s*\(',
              r'\bswitch\s*\(', r'\bcase\s+', r'&&', r'\|\|', r'\bcatch\s*\('],
    ".go": [r'\bif\s+', r'\bfor\s+', r'\bswitch\s+', r'&&', r'\|\|',
            r'\bcase\s+'],
    ".cs": [r'\bif\s*\(', r'\bfor\s*\(', r'\bforeach\s*\(',
            r'\bwhile\s*\(', r'\bswitch\s*\(', r'\bcase\s+', r'&&', r'\|\|', r'\bcatch\b'],
    ".rs": [r'\bif\s+', r'\bfor\s+', r'\bwhile\s+', r'\bmatch\s+', r'&&', r'\|\|'],
    ".cpp": [r'\bif\s*\(', r'\bfor\s*\(', r'\bwhile\s*\(',
             r'\bswitch\s*\(', r'\bcase\s+', r'&&', r'\|\|', r'\bcatch\s*\('],
    ".c": [r'\bif\s*\(', r'\bfor\s*\(', r'\bwhile\s*\(',
           r'\bswitch\s*\(', r'\bcase\s+', r'&&', r'\|\|'],
    ".h": [r'\bif\s*\(', r'\bfor\s*\(', r'\bwhile\s*\(',
           r'\bswitch\s*\(', r'\bcase\s+', r'&&', r'\|\|'],
}

LANG_PARAM_PATTERNS = {
    ".js": re.compile(r'(?:function\s+\w+\s*|=>\s*|\(\s*)\(([^)]*)\)'),
    ".ts": re.compile(r'(?:function\s+\w+\s*|=>\s*|\(\s*)\(([^)]*)\)'),
    ".mjs": re.compile(r'(?:function\s+\w+\s*|=>\s*|\(\s*)\(([^)]*)\)'),
    ".java": re.compile(r'(?:public|private|protected|static|\s)+\w+\s+(\w+)\s*\(([^)]*)\)'),
    ".go": re.compile(r'func\s+(?:\(\w+\s+\*?\w+\)\s+)?(\w+)\s*\(([^)]*)\)'),
    ".cs": re.compile(r'(?:public|private|protected|internal|static|\s)+\w+\s+(\w+)\s*\(([^)]*)\)'),
    ".rs": re.compile(r'fn\s+(\w+)\s*\(([^)]*)\)'),
    ".cpp": re.compile(r'\w+\s+(\w+)\s*\(([^)]*)\)'),
    ".c": re.compile(r'\w+\s+(\w+)\s*\(([^)]*)\)'),
    ".h": re.compile(r'\w+\s+(\w+)\s*\(([^)]*)\)'),
}

LANG_NESTING_KEYWORDS = {
    # v2.2.1: 移除 class/function 结构关键字，仅保留控制流关键字，
    # 避免类/方法定义的大括号被误计入嵌套深度（FP-03/07/08/09）
    ".js": r'\b(?:if|for|while|switch|catch)\b',
    ".ts": r'\b(?:if|for|while|switch|catch)\b',
    ".mjs": r'\b(?:if|for|while|switch|catch)\b',
    ".java": r'\b(?:if|for|while|switch|catch|try)\b',
    ".cs": r'\b(?:if|for|foreach|while|switch|catch|try)\b',
    ".cpp": r'\b(?:if|for|while|switch|catch|try)\b',
    ".c": r'\b(?:if|for|while|switch|catch|try)\b',
    ".h": r'\b(?:if|for|while|switch|catch|try)\b',
}


# ============================================================
# 正则近似检测器
# ============================================================

def _compute_cc_regex(content, ext, *, stripped=None):
    """正则近似圈复杂度（基础值=1），先在剥离注释的内容上运行"""
    if stripped is None:
        stripped = _core.strip_comments_and_strings(content, ext)
    patterns = LANG_CC_PATTERNS.get(ext, [])
    cc = 1
    for pattern in patterns:
        cc += len(re.findall(pattern, stripped, re.IGNORECASE))
    return cc


# ---- _compute_nesting_regex 子函数 ----

def _process_nesting_kw_line(current_depth, pending_depth, pending_releases, opens, closes, kw_count, line_content):
    """处理含嵌套关键字的行，返回 (current_depth, pending_depth, pending_releases)"""
    current_depth += pending_depth
    pending_depth = 0
    
    if pending_releases:
        current_depth -= sum(pending_releases)
        pending_releases.clear()
    
    if '{' in line_content:
        current_depth += opens
        current_depth -= closes
    else:
        pending_depth = kw_count
        pending_releases.extend([1] * kw_count)
    
    return current_depth, pending_depth, pending_releases


def _process_nesting_brace_line(current_depth, pending_depth, pending_releases, opens, closes):
    """处理无嵌套关键字的行，返回 (current_depth, pending_depth, pending_releases)"""
    current_depth += pending_depth
    pending_depth = 0
    current_depth += opens - closes
    
    if current_depth <= 0:
        if pending_releases:
            current_depth -= sum(pending_releases)
        current_depth = 0
        pending_depth = 0
        pending_releases.clear()
    
    return current_depth, pending_depth, pending_releases


def _process_pending_release(current_depth, pending_releases, nesting_kw, line_content, opens, closes):
    """处理待释放的嵌套深度"""
    if pending_releases and not re.search(nesting_kw, line_content, re.IGNORECASE) and opens == 0 and closes == 0:
        return current_depth - pending_releases.pop(), pending_releases
    return current_depth, pending_releases


def _compute_nesting_regex(content, ext, *, stripped=None):
    """大括号计数近似最大嵌套深度 — v2.0.10: CC=18→10"""
    if ext not in LANG_NESTING_KEYWORDS:
        return 0
    
    if stripped is None:
        stripped = _core.strip_comments_and_strings(content, ext)
    nesting_kw = LANG_NESTING_KEYWORDS[ext]
    lines = stripped.split('\n')
    max_depth = 0
    current_depth = 0
    pending_depth = 0
    pending_releases = []
    
    for line in lines:
        line_content = line.strip()
        if not line_content or line_content.startswith('//') or line_content.startswith('#'):
            continue
        
        opens = len(re.findall(r'\{', line_content))
        closes = len(re.findall(r'\}', line_content))
        
        current_depth, pending_releases = _process_pending_release(
            current_depth, pending_releases, nesting_kw, line_content, opens, closes)
        
        kw_matches = re.findall(nesting_kw, line_content, re.IGNORECASE)
        kw_count = len(kw_matches)
        
        if kw_count > 0:
            current_depth, pending_depth, pending_releases = _process_nesting_kw_line(
                current_depth, pending_depth, pending_releases, opens, closes, kw_count, line_content)
        else:
            current_depth, pending_depth, pending_releases = _process_nesting_brace_line(
                current_depth, pending_depth, pending_releases, opens, closes)
        
        current_depth = max(0, current_depth)
        max_depth = max(max_depth, current_depth)
    
    return max_depth


def _count_params_regex(content, ext, *, stripped=None):
    """正则提取函数参数数量"""
    if stripped is None:
        stripped = _core.strip_comments_and_strings(content, ext)
    pattern = LANG_PARAM_PATTERNS.get(ext)
    if not pattern:
        return {}
    
    results = {}
    lines = stripped.split('\n')
    for i, line in enumerate(lines, 1):
        for match in pattern.finditer(line):
            groups = match.groups()
            params_str = groups[-1] if groups else ""
            count = 0 if not params_str or params_str.isspace() else params_str.count(',') + 1
            func_name = groups[0] if len(groups) >= 2 and groups[0] else "unknown"
            results[(func_name, i)] = count
    return results


def _count_java_methods(content, *, stripped=None):
    """统计 Java/C# 类方法数"""
    if stripped is None:
        stripped = _core.strip_comments_and_strings(content, ".java")
    method_pattern = re.compile(
        r'(?:public|private|protected|static|final|abstract|synchronized)\s+\S+\s+(\w+)\s*\([^)]*\)\s*(\{|throws)',
        re.IGNORECASE
    )
    return len(method_pattern.findall(stripped))


# ============================================================
# 函数级圈复杂度 / 嵌套深度（v2.2.1）
# ============================================================
# 根因：文件级 CC/nesting 累加导致多函数 clean 文件被误报（FP-01~10）。
# 修复：分割函数体（含嵌套函数/方法），对每个函数独立计算 CC/nesting，
#       并屏蔽内部嵌套函数体，避免外层函数重复累加嵌套控制流。

# 控制流关键字（负向前瞻排除，避免 if/for/while 被误判为函数定义）
# 注意：function 必须排除，否则 JS 匿名函数 `function (x) {` 会被误判为名为
# function 的"方法"，导致其嵌套体被屏蔽、深层嵌套漏检（js_hard_violations 回归）
_CONTROL_FLOW_KW = (
    r'if|for|while|switch|catch|foreach|else|do|return|new|throw|case|'
    r'sizeof|typeof|await|delete|void|instanceof|in|of|using|namespace|'
    r'match|where|class|struct|enum|interface|try|finally|lock|synchronized|'
    r'import|export|package|public|private|protected|static|const|let|var|'
    r'extends|implements|async|abstract|final|override|virtual|sealed|default|'
    r'function|fn|func'
)


def _method_def_pattern(return_type=False):
    """匹配 标识符(参数) { 形式的方法定义，排除控制流关键字。

    Args:
        return_type: 是否允许参数列表后跟可选返回类型注解（TS 需要）
    """
    suffix = r'(?::\s*[^{]*?)?' if return_type else ''
    return (
        r'(?<![.\w])(?!\b(?:' + _CONTROL_FLOW_KW + r')\b)'
        r'([A-Za-z_$][\w$]*)\s*\([^)]*\)\s*' + suffix + r'\s*\{'
    )


LANG_FUNC_DEF_PATTERNS = {
    # Go 函数定义允许返回类型（如 `func f(x int) int {` / `func f() (int, error) {`）
    ".go": re.compile(r'\bfunc\s+(?:\(\s*\w+\s+\*?[\w.]+\s*\)\s+)?(\w+)\s*\([^)]*\)\s*[^{]*?\{'),
    ".rs": re.compile(r'\bfn\s+(\w+)\s*(?:<[^>]*>)?\s*\([^)]*\)\s*(?:->\s*[^{]*?)?\s*\{'),
    ".js": re.compile(
        r'(?:\bfunction\s*\*?\s*([A-Za-z_$][\w$]*)\s*\([^)]*\)\s*\{'
        r'|' + _method_def_pattern() + r')'
    ),
    ".mjs": re.compile(
        r'(?:\bfunction\s*\*?\s*([A-Za-z_$][\w$]*)\s*\([^)]*\)\s*\{'
        r'|' + _method_def_pattern() + r')'
    ),
    ".ts": re.compile(
        r'(?:\bfunction\s*\*?\s*([A-Za-z_$][\w$]*)\s*\([^)]*\)\s*(?::\s*[^{]*?)?\s*\{'
        r'|' + _method_def_pattern(return_type=True) + r')'
    ),
    ".cs": re.compile(_method_def_pattern()),
    ".java": re.compile(_method_def_pattern()),
}


def _iter_all_function_bodies(stripped, ext):
    """分割所有函数体（含嵌套），yield (name, start, end, line)。

    start/end 为函数体大括号（含外层 {}）在 stripped 中的字符偏移。
    """
    pattern = LANG_FUNC_DEF_PATTERNS.get(ext)
    if pattern is None:
        return
    for m in pattern.finditer(stripped):
        groups = [g for g in m.groups() if g]
        name = groups[0] if groups else ""
        brace = m.end() - 1  # 正则以 \{ 结尾，m.end()-1 即 '{' 位置
        depth = 1
        i = brace + 1
        while i < len(stripped) and depth > 0:
            if stripped[i] == '{':
                depth += 1
            elif stripped[i] == '}':
                depth -= 1
            i += 1
        if depth != 0:
            continue  # 未闭合，跳过
        line = stripped[:m.start()].count("\n") + 1
        yield name, brace, i, line


def _compute_function_cc(content, ext, *, stripped=None):
    """函数级圈复杂度（正则近似）— 替代文件级累加，消除大文件误报。

    对每个函数体独立计算 CC，并屏蔽内部嵌套函数体，避免外层函数重复累加。
    Returns: [(func_name, line, cc), ...]
    """
    if stripped is None:
        stripped = _core.strip_comments_and_strings(content, ext)
    patterns = LANG_CC_PATTERNS.get(ext, [])
    funcs = list(_iter_all_function_bodies(stripped, ext))
    results = []
    for name, start, end, line in funcs:
        # 屏蔽嵌套在 (start, end) 内的其他函数体
        nested = sorted((s, e) for (_, s, e, _) in funcs if s > start and e < end)
        body = stripped[start:end]
        effective = []
        prev = start
        for s, e in nested:
            effective.append(body[prev - start:s - start])
            prev = e
        effective.append(body[prev - start:])
        clean = "".join(effective)
        cc = 1
        for pat in patterns:
            cc += len(re.findall(pat, clean, re.IGNORECASE))
        results.append((name, line, cc))
    return results


def _compute_function_nesting(content, ext, *, stripped=None):
    """函数级嵌套深度（大括号配对，函数体内部，屏蔽嵌套函数体）。

    Returns: [(func_name, line, max_depth), ...]
    """
    if stripped is None:
        stripped = _core.strip_comments_and_strings(content, ext)
    funcs = list(_iter_all_function_bodies(stripped, ext))
    results = []
    for name, start, end, line in funcs:
        nested = sorted((s, e) for (_, s, e, _) in funcs if s > start and e < end)
        body = stripped[start:end]
        effective = []
        prev = start
        for s, e in nested:
            effective.append(body[prev - start:s - start])
            prev = e
        effective.append(body[prev - start:])
        clean = "".join(effective)
        depth = 0
        max_depth = 0
        for ch in clean:
            if ch == '{':
                depth += 1
                max_depth = max(max_depth, depth)
            elif ch == '}':
                depth -= 1
        results.append((name, line, max_depth))
    return results


# ============================================================
# 语言专属检测规则（v2.2.1 — FN 漏检补齐）
# ============================================================
# 结构：ext -> [(compiled_pattern, severity, category, message, use_raw), ...]
# use_raw=True 表示在原始内容上匹配（如 @ts-ignore 是注释指令，stripped 会剥离）

LANG_SPECIFIC_RULES = {
    ".go": [
        (re.compile(r'\bpanic\s*\('), "warn", "custom_rule",
         "使用 panic 进行错误处理（应使用 error 返回值）", False),
        (re.compile(r'\bgo\s+func\s*\('), "warn", "custom_rule",
         "匿名 goroutine 缺少 context 取消/超时控制，可能泄漏", False),
    ],
    ".java": [
        (re.compile(r'System\.exit\s*\('), "warn", "custom_rule",
         "库代码中使用 System.exit()（应抛出异常交由调用方处理）", False),
        (re.compile(r'while\s*\(\s*true\s*\)'), "warn", "custom_rule",
         "无限循环无退出条件（应提供中断/退出机制）", False),
    ],
    ".ts": [
        (re.compile(r'@ts-ignore'), "warn", "custom_rule",
         "使用 @ts-ignore 抑制类型检查（应显式处理类型）", True),
        (re.compile(r'@ts-nocheck'), "warn", "custom_rule",
         "使用 @ts-nocheck 关闭整文件类型检查", True),
    ],
    ".js": [
        (re.compile(r'@ts-ignore'), "warn", "custom_rule",
         "使用 @ts-ignore 抑制类型检查", True),
    ],
    ".cs": [
        (re.compile(r'catch\s*\([^)]*\)\s*\{\s*\}', re.DOTALL), "warn", "custom_rule",
         "空 catch 块吞掉所有异常（应记录或处理）", False),
        (re.compile(r'\.(?:Result|GetResult|Wait)\b'), "warn", "custom_rule",
         "同步阻塞异步调用（.Result/.Wait()/.GetResult()，死锁风险）", False),
    ],
    ".rs": [
        (re.compile(r'\bunsafe\s*[{fn]'), "warn", "security",
         "使用 unsafe 块（裸指针解引用，内存不安全）", False),
        (re.compile(r'\btransmute\b'), "warn", "security",
         "使用 transmute 重解释内存（可能 UB）", False),
        (re.compile(r'extern\s+"C"'), "warn", "security",
         "使用 extern \"C\" FFI 边界（需谨慎校验输入）", False),
    ],
    ".cpp": [
        (re.compile(r'\bnew\s+(?!std::)'), "warn", "security",
         "使用裸 new（建议改用智能指针/RAII）", False),
        (re.compile(r'class\s+\w+\s*:\s*public\s+\w+\s*,\s*public\s+\w+'),
         "warn", "custom_rule", "菱形继承（多继承）可能导致成员歧义", False),
    ],
    ".c": [
        (re.compile(r'\bgoto\s+\w+\s*;'), "warn", "custom_rule",
         "使用 goto 语句（建议改用结构化控制流）", False),
    ],
}


def _check_language_rules(content, filepath, collector, ext):
    """执行语言专属检测规则（FN 漏检补齐）。

    规则默认在剥离注释/字符串后的内容上匹配；use_raw=True 的规则在原始内容匹配。
    """
    rules = LANG_SPECIFIC_RULES.get(ext)
    if not rules:
        return
    stripped = _core.strip_comments_and_strings(content, ext)
    for pattern, severity, category, message, use_raw in rules:
        text = content if use_raw else stripped
        for m in pattern.finditer(text):
            line = text[:m.start()].count("\n") + 1
            collector.add(severity, category, filepath, line, message,
                          "见语言最佳实践文档", confidence=80)
