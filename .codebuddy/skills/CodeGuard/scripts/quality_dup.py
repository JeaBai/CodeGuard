#!/usr/bin/env python3
"""
CodeGuard Quality Duplication
==============================
跨文件 + 文件内重复代码块检测。
支持多语言，剥离注释后比较提升准确度。
"""

from collections import defaultdict

import quality_core as _core


# ---- check_duplicates 子函数 ----

def _load_clean_lines(filepath):
    """读取文件并返回剥离注释的行列表"""
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            raw_lines = f.readlines()
    except Exception:
        return None
    
    lines = []
    for l in raw_lines:
        stripped_line = l.strip()
        if stripped_line.startswith('#') or stripped_line.startswith('//'):
            lines.append('')
        else:
            lines.append(stripped_line)
    return lines


def _extract_blocks(lines):
    """从行列表提取所有长度≥6/≥10行的代码块 → {block_text: [(filepath, start_line, length)]}"""
    blocks = []
    for i in range(len(lines)):
        for length in [_core.THRESHOLDS["duplicate_lines_block"],
                       _core.THRESHOLDS["duplicate_lines_warn"]]:
            if i + length <= len(lines):
                block = "\n".join(lines[i:i+length])
                if len(block) > 20:
                    blocks.append((block, i + 1, length))
    return blocks


def _classify_dup_severity(length, is_cross_file):
    """根据长度和跨文件标志确定严重级别"""
    if is_cross_file and length >= _core.THRESHOLDS["cross_file_duplicate_block"]:
        return "block"
    if length >= _core.THRESHOLDS["duplicate_lines_block"]:
        return "block"
    return "warn"


def check_duplicates(source_files, collector):
    """检测重复代码块（支持跨文件检测）— v2.0.10: CC=20→5"""
    block_map = defaultdict(list)
    
    for filepath in source_files:
        lines = _load_clean_lines(filepath)
        if lines is None:
            continue
        for block, start_line, length in _extract_blocks(lines):
            block_map[block].append((filepath, start_line, length))
    
    reported = set()
    for block, occurrences in block_map.items():
        if len(occurrences) <= 1:
            continue
        unique_files = set(occ[0] for occ in occurrences)
        is_cross_file = len(unique_files) > 1
        
        for filepath, line, length in occurrences:
            key = (filepath, line)
            if key in reported:
                continue
            reported.add(key)
            severity = _classify_dup_severity(length, is_cross_file)
            cross_tag = "跨文件" if is_cross_file else "文件内"
            collector.add(severity, "duplication", filepath, line,
                          f"{cross_tag}重复代码块（{length}行），共出现 {len(occurrences)} 次（{len(unique_files)} 个文件）",
                          "提取为共享函数或模块")
