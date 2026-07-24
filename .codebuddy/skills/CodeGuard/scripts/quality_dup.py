#!/usr/bin/env python3
"""
CodeGuard Quality Duplication
==============================
跨文件 + 文件内重复代码块检测。
支持多语言，剥离注释后比较提升准确度。
"""

from collections import defaultdict

import quality_core as _core


def check_duplicates(source_files, collector):
    """检测重复代码块（支持跨文件检测）"""
    block_map = defaultdict(list)
    
    for filepath in source_files:
        try:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                raw_lines = f.readlines()
                lines = []
                for l in raw_lines:
                    stripped_line = l.strip()
                    if stripped_line.startswith('#') or stripped_line.startswith('//'):
                        lines.append('')
                    else:
                        lines.append(stripped_line)
        except Exception:
            continue
        
        for i in range(len(lines)):
            for length in [_core.THRESHOLDS["duplicate_lines_block"],
                           _core.THRESHOLDS["duplicate_lines_warn"]]:
                if i + length <= len(lines):
                    block = "\n".join(lines[i:i+length])
                    if len(block) > 20:
                        block_map[block].append((filepath, i+1, length))
    
    reported = set()
    for block, occurrences in block_map.items():
        if len(occurrences) > 1:
            unique_files = set(occ[0] for occ in occurrences)
            is_cross_file = len(unique_files) > 1
            
            for filepath, line, length in occurrences:
                key = (filepath, line)
                if key in reported:
                    continue
                reported.add(key)
                
                if is_cross_file and length >= _core.THRESHOLDS["cross_file_duplicate_block"]:
                    severity = "block"
                elif length >= _core.THRESHOLDS["duplicate_lines_block"]:
                    severity = "block"
                else:
                    severity = "warn"
                
                cross_tag = "跨文件" if is_cross_file else "文件内"
                collector.add(severity, "duplication", filepath, line,
                              f"{cross_tag}重复代码块（{length}行），共出现 {len(occurrences)} 次（{len(unique_files)} 个文件）",
                              "提取为共享函数或模块")
