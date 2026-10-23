#!/usr/bin/env python3
"""module_health 子模块 — 语义克隆检测 (v1.4.0)
============================================================
从 module_health.py 拆分的独立子模块，提供四层克隆检测：
  L1 AST body hash — Python AST dump(args+body) SHA256
  L2 body SHA256   — 闭包 { } 提取后归一化 SHA256 (6语言)
  L3 SimHash 64-bit — 函数源码字符级近似 + Hamming 距离 ≤ 3
  L4 名称归一化     — get_/set_/is_ 前缀剥离

函数：
  analyze_clones(modules)  → 克隆检测主入口
  _fmt_clones_text(data)   → 文本格式化

被 module_health.py 通过 re-export 聚合，外部仍可用：
  from module_health import analyze_clones
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, List, Optional

from _health_common import CLONE_EXTRACT_MIN_FILES

# AST 可选依赖（仅 Python 文件）
try:
    import ast as _ast  # codeguard: ignore AUTO_IMPORT
    _HAS_AST = True
except ImportError:
    _HAS_AST = False


# ============================================================
# v1.3.0 P1a/P1b: 语义克隆检测 (AST body hash + 复用建议)
# ============================================================

def _ast_body_hash(source_code: str) -> Optional[str]:
    """Python AST body 规范化 hash，用于 Type-2/3 克隆检测。

    非 Python 或无 AST 支持时返回 None（调用方降级为 _body_source_hash）。
    """
    if not _HAS_AST:
        return None
    try:
        tree = _ast.parse(source_code)
        for node in _ast.walk(tree):
            # 剥离 docstring
            if isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
                body_stmts = node.body
                if body_stmts and isinstance(body_stmts[0], _ast.Expr) and isinstance(body_stmts[0].value, _ast.Constant):
                    body_stmts = body_stmts[1:]
                # 仅 hash 除函数名外的 body + args 结构
                payload = _ast.dump(node.args, annotate_fields=False)
                for stmt in body_stmts:
                    payload += _ast.dump(stmt, annotate_fields=False)
                return hashlib.sha256(payload.encode()).hexdigest()[:20]
        return None
    except (SyntaxError, TypeError, RecursionError):
        return None


def _body_source_hash(source: str) -> Optional[str]:
    """非 Python 函数体 source hash (Type-2)。

    对闭包 { ... } 正则提取的 body 做归一化后 SHA256。
    归一化策略：去空格、去字符串字面量、去注释。
    """
    if not source or len(source) < 10:
        return None
    normalized = source
    # 去单行注释
    normalized = re.sub(r'//[^\n]*', '', normalized)
    # 去多行注释
    normalized = re.sub(r'/\*.*?\*/', '', normalized, flags=re.DOTALL)
    # 去字符串字面量
    normalized = re.sub(r'"[^"]*"', '""', normalized)
    normalized = re.sub(r"'[^']*'", "''", normalized)
    normalized = re.sub(r'`[^`]*`', '``', normalized)
    # 去空白
    normalized = re.sub(r'\s+', '', normalized)
    if len(normalized) < 10:
        return None
    return hashlib.sha256(normalized.encode()).hexdigest()[:20]


def _simhash_64(text: str) -> int:
    """64-bit SimHash 指纹 (Type-1 近似克隆检测)。"""
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


def _hamming_dist(fp1: int, fp2: int) -> int:
    """计算两个 64-bit SimHash 指纹的 Hamming 距离。"""
    x = fp1 ^ fp2
    dist = 0
    while x:
        dist += 1
        x &= x - 1  # Brian Kernighan 算法
    return dist


def _normalize_func_key(name: str) -> str:
    """简单归一化：去除公共前缀。"""
    key = name.lower().strip()
    for prefix in ("get_", "set_", "is_", "has_", "handle_", "process_", "build_"):
        if key.startswith(prefix):
            key = key[len(prefix):]
            break
    return key


def _compute_body_key(source, fname, file_path):
    """计算函数体克隆 hash key，返回 (body_key, hash_type)。

    L1 AST body hash（Python）→ L2 body source hash（非 Python）→ L4 名称归一化降级。
    """
    body_key = None
    hash_type = "name-normalize"
    if source:
        if file_path.endswith(".py"):
            body_key = _ast_body_hash(source)
            if body_key:
                hash_type = "ast-sha256"
        if not body_key:
            body_key = _body_source_hash(source)
            if body_key:
                hash_type = "body-sha256"
    if not body_key:
        body_key = _normalize_func_key(fname)
    return body_key, hash_type


def _group_by_body_hash(modules):
    """L1/L2 精确 body hash 分组。返回 (clone_groups, func_entries)。"""
    clone_groups = {}
    func_entries = []
    type_rank = {"ast-sha256": 3, "body-sha256": 2, "name-normalize": 1}

    for mod_name, mod_data in modules.items():
        for func in mod_data.get("public_api", []):
            if not isinstance(func, dict):
                continue
            fname = func.get("name", "")
            source = func.get("source", func.get("body", ""))
            file_path = func.get("file", "")

            body_key, hash_type = _compute_body_key(source, fname, file_path)

            if body_key not in clone_groups:
                clone_groups[body_key] = {
                    "signature": fname,
                    "locations": [],
                    "source_sample": source[:200] if source else "",
                    "hash_type": hash_type,
                }
            clone_groups[body_key]["locations"].append(f"{mod_name}::{fname}")
            if type_rank.get(hash_type, 0) > type_rank.get(clone_groups[body_key]["hash_type"], 0):
                clone_groups[body_key]["hash_type"] = hash_type
            func_entries.append({
                "mod_name": mod_name, "fname": fname, "source": source,
                "body_key": body_key, "hash_type": hash_type,
            })
    return clone_groups, func_entries


def _find_merged_key(fp, simhash_map):
    """在 SimHash 桶中查找 Hamming 距离 ≤3 的匹配，无匹配返回 None。"""
    for existing_fp, existing_key in list(simhash_map.items())[:500]:
        if _hamming_dist(fp, existing_fp) <= 3:
            return existing_key
    return None


def _merge_into_group(entry, src, merged_key, clone_groups):
    """将 entry 合并到 merged_key 对应的克隆组。"""
    bk = entry["body_key"]
    loc = f"{entry['mod_name']}::{entry['fname']}"
    if bk in clone_groups and loc in clone_groups[bk]["locations"]:
        clone_groups[bk]["locations"].remove(loc)
    if merged_key not in clone_groups:
        clone_groups[merged_key] = {
            "signature": entry["fname"],
            "locations": [],
            "source_sample": src[:200],
            "hash_type": "simhash-64",
        }
    if loc not in clone_groups[merged_key]["locations"]:
        clone_groups[merged_key]["locations"].append(loc)


def _merge_simhash_buckets(func_entries, clone_groups):
    """L3 SimHash Type-1 近似克隆桶合并（Hamming 距离 ≤ 3）。"""
    simhash_map = {}
    for entry in func_entries:
        src = entry.get("source", "")
        if len(src) < 30:
            continue
        fp = _simhash_64(src)
        merged_key = _find_merged_key(fp, simhash_map)
        if merged_key:
            _merge_into_group(entry, src, merged_key, clone_groups)
        else:
            simhash_map[fp] = entry["body_key"]


def _build_clone_result(clone_groups):
    """从克隆分组构建最终结果列表（含复用提取建议）。"""
    result = []
    for key, group in clone_groups.items():
        locs = group["locations"]
        if len(locs) < 2:
            continue

        entry = {
            "signature": group["signature"],
            "locations": locs,
            "count": len(locs),
            "body_key": key,
            "hash_type": group["hash_type"],
        }

        if len(locs) >= CLONE_EXTRACT_MIN_FILES:
            modules_in = sorted(set(loc.split("::")[0] for loc in locs))
            suggested = f"shared/{modules_in[0] if len(modules_in) == 1 else 'common'}/{group['signature']}.py"
            entry["suggested_extract_to"] = suggested
            entry["shared_by_modules"] = modules_in

        result.append(entry)

    result.sort(key=lambda x: x["count"], reverse=True)
    return result


def analyze_clones(modules: Dict[str, Any]) -> List[Dict[str, Any]]:
    """语义克隆检测 v1.3.1：三层策略对标 SonarQube Type-1/2/3。

    L1 (Type-3 语义): AST body hash — Python AST dump(args+body) SHA256
    L2 (Type-2 重命名): 正则体 source hash — 闭包 { } 提取后归一化 SHA256 (6语言)
    L3 (Type-1 精确): SimHash 64-bit 指纹 — 函数源码字符级近似 + Hamming 距离≤3
    L4 (降级): 名称归一化 — get_/set_/is_ 前缀剥离

    对 ≥ CLONE_EXTRACT_MIN_FILES 个位置的组，附加 suggested_extract_to 字段。
    """
    clone_groups, func_entries = _group_by_body_hash(modules)
    _merge_simhash_buckets(func_entries, clone_groups)
    return _build_clone_result(clone_groups)


def _fmt_clones_text(data: List[Dict[str, Any]]) -> str:
    if not data:
        return "## 语义克隆检测: 未发现 Type-2 克隆候选"

    lines = [f"## 语义克隆检测 (≥2 个文件共享相同函数): {len(data)} 组"]
    lines.append(f"  {'重复':<6} {'类型':<14} {'函数名':<25} {'位置'}")
    lines.append("  " + "─" * 90)

    for c in data:
        locs_short = ", ".join(c["locations"][:4])
        if len(c["locations"]) > 4:
            locs_short += f", +{len(c['locations']) - 4}"
        htype = c.get("hash_type", "name")[:14]
        lines.append(f"  {c['count']:<6} {htype:<14} {c['signature']:<25} {locs_short}")

    # 输出提取建议
    extract_candidates = [c for c in data if c.get("suggested_extract_to")]
    if extract_candidates:
        lines.append(f"\n  ── 复用提取建议 (≥{CLONE_EXTRACT_MIN_FILES} 文件共享) ──")
        for c in extract_candidates:
            lines.append(f"  💡 {c['signature']} ({c['count']}处) → {c['suggested_extract_to']}")
            lines.append(f"     涉及模块: {', '.join(c.get('shared_by_modules', []))}")

    return "\n".join(lines)
