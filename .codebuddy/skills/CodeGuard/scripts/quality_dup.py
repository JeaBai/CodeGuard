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
    except (OSError, UnicodeDecodeError):
        return None
    
    lines = []
    for l in raw_lines:
        stripped_line = l.strip()
        if stripped_line.startswith('#') or stripped_line.startswith('//'):
            lines.append('')
        else:
            lines.append(stripped_line)
    return lines


def _is_import_only_block(block_text):
    """判断代码块是否包含导入语句（跨文件 import 重复属正常，非真正代码重复）"""
    non_empty = [l for l in block_text.split("\n") if l.strip()]
    if not non_empty:
        return False
    import_count = sum(1 for l in non_empty if l.startswith(('import ', 'from ', 'require(', 'include ')))
    # 包含任何 import 语句的跨文件块视为 import 相关重复（正常）
    return import_count >= 1


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
        # 过滤导入语句组成的重复块（跨文件 import 重复属正常）
        if _is_import_only_block(block):
            continue
        unique_files = set(occ[0] for occ in occurrences)
        is_cross_file = len(unique_files) > 1
        
        for filepath, line, length in occurrences:
            key = (filepath, line)
            if key in reported:
                continue
            # 文件内重复要求 ≥block 阈值才报告，降低相似代码模式的误报；
            # 跨文件重复保持 ≥warn 阈值（4行）以捕获跨模块复制粘贴
            if not is_cross_file and length < _core.THRESHOLDS["duplicate_lines_block"]:
                continue
            reported.add(key)
            severity = _classify_dup_severity(length, is_cross_file)
            cross_tag = "跨文件" if is_cross_file else "文件内"
            collector.add(severity, "duplication", filepath, line,
                          f"{cross_tag}重复代码块（{length}行），共出现 {len(occurrences)} 次（{len(unique_files)} 个文件）",
                          "提取为共享函数或模块")


# ============================================================
# Type-1 近似克隆检测：SimHash 指纹 + Hamming 距离 (v1.1.0)
# ============================================================

def simhash_64(text: str) -> int:
    """64-bit SimHash 指纹 — 字符 3-gram 加权求和。

    对标 SonarQube Type-1 克隆（精确文本/微小差异）。
    使用字符级 3-gram 确保对变量重命名、空格变化有良好容忍度。
    """
    v = [0] * 64
    for i in range(len(text) - 2):
        h = hash(text[i:i + 3]) & 0xFFFFFFFFFFFFFFFF
        for j in range(64):
            v[j] += 1 if (h & (1 << j)) else -1
    fp = 0
    for j in range(64):
        if v[j] > 0:
            fp |= (1 << j)
    return fp


def hamming_dist(fp1: int, fp2: int) -> int:
    """两个 64-bit SimHash 指纹的 Hamming 距离（Brian Kernighan 算法）。"""
    x = fp1 ^ fp2
    dist = 0
    while x:
        dist += 1
        x &= x - 1
    return dist


def detect_type1_clones(source_files, collector, min_block_lines=10, max_hamming=3):
    """Type-1 近似克隆检测 — SimHash 指纹分组 + Hamming 距离阈值。

    Args:
        source_files: 源文件列表
        collector: 问题收集器
        min_block_lines: 最小块行数（默认 10，避免微小片段误报）
        max_hamming: Hamming 距离阈值（≤3 视为近似克隆）

    策略：
      1. 归一化函数体 → 计算 SimHash 指纹
      2. 指纹 Hamming 距离 ≤ max_hamming → 合并为克隆组
      3. 输出跨文件的 Type-1 克隆候选
    """
    # 按文件收集归一化块
    block_fingerprints: dict[int, list[tuple[str, int, str]]] = {}
    # {fingerprint: [(filepath, line, block_text)]}

    for filepath in source_files:
        lines = _load_clean_lines(filepath)
        if lines is None:
            continue
        # 归一化：去空白、去 import/package 行
        normalized = []
        for l in lines:
            stripped = l.strip()
            if not stripped or stripped.startswith(("import ", "from ", "package ", "using ", "#include")):
                continue
            normalized.append(stripped)

        if len(normalized) < min_block_lines:
            continue

        # 滑动窗口提取块
        for i in range(len(normalized) - min_block_lines + 1):
            block = "\n".join(normalized[i:i + min_block_lines])
            if len(block) < 50:
                continue
            fp = simhash_64(block)
            if fp not in block_fingerprints:
                block_fingerprints[fp] = []
            block_fingerprints[fp].append((filepath, i + 1, block))

    # 两两比较近似指纹
    fingerprints = list(block_fingerprints.keys())
    reported_blocks: set[tuple[str, int]] = set()

    for i in range(min(len(fingerprints), 200)):  # 限制比较规模
        for j in range(i + 1, min(len(fingerprints), 200)):
            fp_i, fp_j = fingerprints[i], fingerprints[j]
            if hamming_dist(fp_i, fp_j) <= max_hamming:
                # 近似克隆组 → 报告所有跨文件出现
                all_entries = block_fingerprints[fp_i] + block_fingerprints[fp_j]
                unique_files = set(e[0] for e in all_entries)
                if len(unique_files) <= 1:
                    continue  # 仅限跨文件

                for fpath, line, block_text in all_entries:
                    key = (fpath, line)
                    if key in reported_blocks:
                        continue
                    reported_blocks.add(key)
                    collector.add(
                        "warn", "type1_duplication", fpath, line,
                        f"Type-1 近似克隆（SimHash Hamming≤{max_hamming}, "
                        f"共 {len(all_entries)} 处, {len(unique_files)} 个文件）",
                        "考虑提取为共享模块/函数 → refactor_queue 入队 P2",
                    )
