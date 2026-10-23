#!/usr/bin/env python3
"""模块健康分析器 — 孤儿扫描 / 利用率排名 / 膨胀告警 / 热点风险评分 / 死代码检测 / CODEOWNERS集成 / 语义克隆 (v1.4.0)
============================================================
基于 blueprint_generator.py 输出的 architecture_blueprint.json 提供：
  1. 孤儿模块扫描      — 被引用数为 0 且非 test_only 的模块
  2. 模块利用率排名    — 按被引用数分级 (core/hub/normal/orphan)
  3. 模块膨胀告警      — 文件数/总行数超出阈值的模块
  4. 热点风险评分      — complexity × churn × ownership 三维交叉（v1.1.0）
  5. 函数级死代码检测  — 遍历 public_api 反查是否被其他模块引用（v1.3.0 P0a）
  6. CODEOWNERS 集成   — 解析 CODEOWNERS 交叉验证 ownership 因子（v1.3.0 P0b）
  7. 四层克隆检测      — L1 AST body hash / L2 body SHA256 / L3 SimHash / L4 名称归一化（v1.4.0）
  8. 6语言函数体提取   — Python AST + JS/TS/Java/Go/C#/Rust 正则体捕获（v1.4.0）

对标：
  - Google Sesenmann 大规模死代码清除 → 孤儿 + 死代码
  - Qodo 2026 十大指标 Hotspot Risk Score → 热点 (含 CODEOWNERS)
  - SonarQube Type-1/2/3 Clone → 四层克隆检测 (AST + body hash + SimHash)
  - 跨国企业多语言标准 → 6语言函数体提取 + 跨语言克隆

用法：
  python module_health.py --blueprint blueprint.json [--focus all|orphans|utilization|bloat|hotspot|dead-code|clones|shared]
                          [--format text|json] [--max-files 10] [--max-lines 2000]
                          [--since-days 90] [--project-root .] [--codeowners PATH]

库模式：
  from module_health import load_blueprint, analyze_hotspot, analyze_dead_code, analyze_clones, run_report
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import math
import os
import subprocess
import sys
import textwrap
from typing import Any, Dict, List, Optional, Set

# 共享常量与工具函数（从 _health_common 导入）
from _health_common import (
    SCRIPT_DIR,
    DEFAULT_MAX_FILES,
    DEFAULT_MAX_LINES,
    UTIL_CORE,
    UTIL_HUB,
    UTIL_NORMAL,
    DEFAULT_SINCE_DAYS,
    GIT_TIMEOUT,
    HOTSPOT_W_COMPLEXITY,
    HOTSPOT_W_CHURN,
    HOTSPOT_W_OWNERSHIP,
    HOTSPOT_HOT_THRESHOLD,
    HOTSPOT_WARM_THRESHOLD,
    CLONE_EXTRACT_MIN_FILES,
    _log,
)

# 子模块 re-export（保持 from module_health import ... 向后兼容）
from clone_detector import analyze_clones, _fmt_clones_text
from health_codeowners import (
    parse_codeowners,
    _match_codeowners_pattern,
    compute_codeowners_ownership,
)


# ============================================================
# 蓝图加载
# ============================================================

def load_blueprint(bp_path: str) -> Dict[str, Any]:
    """加载并校验 architecture_blueprint.json。"""
    if not os.path.isfile(bp_path):
        raise FileNotFoundError(f"蓝图文件不存在: {bp_path}")

    with open(bp_path, "r", encoding="utf-8") as f:
        bp = json.load(f)

    if "modules" not in bp:
        raise ValueError("蓝图缺少 modules 字段，请先运行 blueprint_generator.py")

    modules_raw = bp["modules"]
    if isinstance(modules_raw, list):
        bp["modules"] = {m["name"]: m for m in modules_raw if isinstance(m, dict) and "name" in m}
    elif not isinstance(modules_raw, dict):
        raise ValueError(f"modules 字段类型无效: {type(modules_raw)}，需要 list 或 dict")

    _log(f"加载蓝图: 版本={bp.get('version','?')}, 模块数={len(bp['modules'])}")
    return bp


# ============================================================
# 反向依赖构建
# ============================================================

def compute_reverse_deps(modules: Dict[str, Any]) -> Dict[str, List[str]]:
    """构建反向依赖索引：{被引用模块: [引用方列表]}。

    depends_on 可能包含 module::function 格式的细粒度引用。
    使用集合去重避免同模块因 ::function 格式导致引用计数膨胀。
    """
    rev_set: Dict[str, set] = {}
    for mod_name, mod_data in modules.items():
        deps = mod_data.get("depends_on", [])
        for dep in deps:
            dep_name = dep.get("module", dep) if isinstance(dep, dict) else dep
            # 剥离函数引用前缀 (module::function → module)
            if "::" in dep_name:
                dep_name = dep_name.split("::", 1)[0]
            if dep_name not in rev_set:
                rev_set[dep_name] = set()
            rev_set[dep_name].add(mod_name)
    return {k: sorted(v) for k, v in rev_set.items()}


# ============================================================
# 分析函数：利用率 / 孤儿 / 膨胀 / 死代码 / 共享
# ============================================================

def classify_utilization(ref_count: int) -> str:
    if ref_count > 5:
        return "core"
    if ref_count >= 3:
        return "hub"
    if ref_count >= 1:
        return "normal"
    return "orphan"


def analyze_utilization(
    modules: Dict[str, Any],
    reverse_deps: Dict[str, List[str]],
    shared_utils: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    result = []
    for mod_name, mod_data in modules.items():
        refs = reverse_deps.get(mod_name, [])
        ref_count = len(refs)
        shared_funcs = []
        for su in shared_utils:
            for c in su.get("consumers", []):
                if c.get("module", "") == mod_name:
                    shared_funcs.append(su.get("name", "?"))
        result.append({
            "name": mod_name,
            "ref_count": ref_count,
            "tier": classify_utilization(ref_count),
            "file_count": mod_data.get("file_count", 0),
            "total_lines": mod_data.get("total_lines", 0),
            "public_api_count": len(mod_data.get("public_api", [])),
            "referenced_by": refs,
            "shared_util_consumers": shared_funcs,
        })
    result.sort(key=lambda x: x["ref_count"], reverse=True)
    return result


def analyze_orphans(
    modules: Dict[str, Any],
    reverse_deps: Dict[str, List[str]],
) -> List[Dict[str, Any]]:
    result = []
    for mod_name, mod_data in modules.items():
        ref_count = len(reverse_deps.get(mod_name, []))
        if ref_count != 0:
            continue
        tags = mod_data.get("tags", [])
        is_test = "test_only" in tags or "archived" in tags
        is_migration = "migration" in tags or "legacy" in tags
        if is_test and not is_migration:
            continue
        reason = "无引用方，已标记为 legacy/migration" if is_migration else "无引用方"
        result.append({
            "name": mod_name,
            "file_count": mod_data.get("file_count", 0),
            "total_lines": mod_data.get("total_lines", 0),
            "is_test_only": is_test,
            "reason": reason,
        })
    return result


def analyze_bloat(
    modules: Dict[str, Any],
    max_files: int = DEFAULT_MAX_FILES,
    max_lines: int = DEFAULT_MAX_LINES,
) -> List[Dict[str, Any]]:
    result = []
    for mod_name, mod_data in modules.items():
        file_count = mod_data.get("file_count", 0)
        total_lines = mod_data.get("total_lines", 0)
        bloat_types = []
        if file_count > max_files:
            bloat_types.append("file_count")
        if total_lines > max_lines:
            bloat_types.append("total_lines")
        if bloat_types:
            result.append({
                "name": mod_name,
                "file_count": file_count,
                "total_lines": total_lines,
                "bloat_type": "+".join(bloat_types),
                "exceeded_by_files": max(file_count - max_files, 0),
                "exceeded_by_lines": max(total_lines - max_lines, 0),
            })
    result.sort(key=lambda x: x["exceeded_by_lines"] + x["exceeded_by_files"] * 100, reverse=True)
    return result


# ============================================================
# v1.3.0 P0a: 函数级死代码检测
# ============================================================

def analyze_dead_code(
    modules: Dict[str, Any],
    reverse_deps: Dict[str, List[str]],
) -> List[Dict[str, Any]]:
    """函数级死代码检测。

    遍历每个模块的 public_api，反查该函数名是否出现在：
    1. 其他模块的 depends_on 中（粗检，依赖引用）
    2. 其他模块的 public_api 列表交叉引用中（细检）

    既非其他模块的依赖也未在任何模块中被 import 调用的函数标记为 dead。
    """
    # 构建全局函数引用索引：{函数名: {引用方模块集合}}
    # v1.3.1 修复：仅从 depends_on 中提取函数名令牌，不再混入 public_api 自身列表
    func_ref_index: Dict[str, Set[str]] = {}
    for mod_name, mod_data in modules.items():
        deps = mod_data.get("depends_on", [])
        for dep in deps:
            dep_name = dep.get("module", dep) if isinstance(dep, dict) else dep
            # 提取可能的函数引用 (支持 module.func / module::func / module func 格式)
            stripped = dep_name
            # 检查是否为 module.function 或 module::function 格式
            for sep in ("::", "."):
                if sep in stripped:
                    parts = stripped.split(sep, 1)
                    if len(parts) == 2 and parts[1].isidentifier():
                        func_ref_index.setdefault(parts[1], set()).add(mod_name)
                    stripped = parts[0]
            # 也添加模块名本身作为可能的引用令牌
            if stripped.isidentifier():
                func_ref_index.setdefault(stripped, set()).add(mod_name)

    result = []
    for mod_name, mod_data in modules.items():
        tags = mod_data.get("tags", [])
        if "test_only" in tags:
            continue  # test 模块不算死代码

        public_api = mod_data.get("public_api", [])
        if not public_api:
            continue

        for func in public_api:
            if not isinstance(func, dict):
                continue
            fname = func.get("name", "")
            if not fname:
                continue

            # 谁引用了这个函数？（排除自己）
            refs = func_ref_index.get(fname, set()) - {mod_name}
            if len(refs) == 0:
                result.append({
                    "module": mod_name,
                    "function": fname,
                    "file": func.get("file", ""),
                    "line": func.get("line", 0),
                    "arity": func.get("arity", 0),
                    "referenced_by": [],
                })

    result.sort(key=lambda x: x["module"] + x["function"])
    return result


# ============================================================
# 共享函数消费者分布
# ============================================================

def analyze_shared_utils(
    shared_utils: List[Dict[str, Any]],
) -> Dict[str, List[str]]:
    mapping: Dict[str, List[str]] = {}
    for su in shared_utils:
        name = su.get("name", "?")
        consumers = [c.get("module", str(c)) for c in su.get("consumers", [])]
        if isinstance(consumers, list):
            mapping[name] = consumers
    return mapping


# ============================================================
# v1.1.0: 热点风险评分
# ============================================================

def _safe_normalize(value: float, max_val: float) -> float:
    if max_val <= 0:
        return 0.0
    return min(value / max_val, 1.0)


def compute_complexity(modules: Dict[str, Any]) -> Dict[str, float]:
    raw: Dict[str, float] = {}
    for mod_name, mod_data in modules.items():
        nesting = mod_data.get("max_nesting", 0) if isinstance(mod_data.get("max_nesting"), (int, float)) else 3
        fc = mod_data.get("file_count", 1)
        api = len(mod_data.get("public_api", []))
        raw[mod_name] = float(nesting) * 1.5 + float(fc) * 2.0 + float(api) * 1.0
    max_raw = max(raw.values()) if raw else 1.0
    return {k: _safe_normalize(v, max_raw) for k, v in raw.items()}


def compute_churn(
    modules: Dict[str, Any],
    since_days: int,
    project_root: str,
) -> Dict[str, float]:
    try:
        r = subprocess.run(
            ["git", "--version"], capture_output=True, text=True, timeout=5,
        )
        if r.returncode != 0:
            raise FileNotFoundError("git not available")
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        _log("git 不可用，churn 因子降级为 0.5（中性）")
        return {m: 0.5 for m in modules}

    raw: Dict[str, float] = {}
    for mod_name, mod_data in modules.items():
        try:
            r = subprocess.run(
                ["git", "log", f"--since={since_days}d", "--shortstat", "--format=%H", "--", mod_name],
                capture_output=True, text=True, timeout=GIT_TIMEOUT,
                cwd=project_root,
            )
            if r.returncode != 0:
                raw[mod_name] = 0.0
                continue

            import re
            added = 0
            deleted = 0
            for line in r.stdout.split("\n"):
                line = line.strip()
                if "insertion" in line or "deletion" in line:
                    ins = re.search(r'(\d+)\s+insertion', line)
                    dlt = re.search(r'(\d+)\s+deletion', line)
                    if ins:
                        added += int(ins.group(1))
                    if dlt:
                        deleted += int(dlt.group(1))
            raw[mod_name] = float(added + deleted)
        except (subprocess.TimeoutExpired, OSError) as e:
            _log(f"git churn 超时/错误 ({mod_name}): {e}")
            raw[mod_name] = 0.0

    if not raw or all(v <= 0 for v in raw.values()):
        _log("git churn 无数据（可能是新仓库），全部降级为 0.5")
        return {m: 0.5 for m in modules}

    max_churn = max(raw.values()) if raw else 1.0
    return {k: _safe_normalize(v, max_churn) for k, v in raw.items()}


def compute_ownership(
    modules: Dict[str, Any],
    since_days: int,
    project_root: str,
    codeowners_path: str = "",
) -> Dict[str, float]:
    """计算所有权集中度风险（0-1）。

    优先使用 CODEOWNERS（精确归属），次选 git log 提交者分析。
    """
    # 尝试 CODEOWNERS
    co_map = {}
    if codeowners_path:
        co_map = compute_codeowners_ownership(modules, codeowners_path)

    # git 提交者作为 fallback
    git_ok = False
    try:
        r = subprocess.run(
            ["git", "--version"], capture_output=True, text=True, timeout=5,
        )
        if r.returncode == 0:
            git_ok = True
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass

    if not git_ok and not co_map:
        _log("git 不可用且无 CODEOWNERS，ownership 因子降级为 0.5")
        return {m: 0.5 for m in modules}

    risk: Dict[str, float] = {}
    for mod_name in modules:
        # CODEOWNERS 优先
        if mod_name in co_map and co_map[mod_name]["owner_count"] > 0:
            owner_count = co_map[mod_name]["owner_count"]
            uncovered = co_map[mod_name].get("uncovered_files", 0)
            # 文件覆盖不完全的模块附加风险
            files_total = co_map[mod_name].get("files_matched", 0) + uncovered
            coverage_penalty = uncovered / max(files_total, 1) * 0.3
            risk[mod_name] = min(1.0, (1.0 / owner_count) + coverage_penalty)
            continue

        # git fallback
        if not git_ok:
            risk[mod_name] = 0.5
            continue

        try:
            r = subprocess.run(
                ["git", "log", f"--since={since_days}d", "--format=%an", "--", mod_name],
                capture_output=True, text=True, timeout=GIT_TIMEOUT,
                cwd=project_root,
            )
            if r.returncode != 0:
                risk[mod_name] = 0.5
                continue

            authors = [a.strip() for a in r.stdout.split("\n") if a.strip()]
            total = len(authors)
            unique = len(set(authors))

            if total == 0:
                risk[mod_name] = 0.5
            elif unique == 1:
                risk[mod_name] = 1.0
            else:
                risk[mod_name] = 1.0 - min(unique / max(total, 1), 1.0)
        except (subprocess.TimeoutExpired, OSError) as e:
            _log(f"git ownership 错误 ({mod_name}): {e}")
            risk[mod_name] = 0.5

    return risk


def analyze_hotspot(
    modules: Dict[str, Any],
    since_days: int = DEFAULT_SINCE_DAYS,
    project_root: str = ".",
    codeowners_path: str = "",
) -> List[Dict[str, Any]]:
    complexity = compute_complexity(modules)
    churn = compute_churn(modules, since_days, project_root)
    ownership = compute_ownership(modules, since_days, project_root, codeowners_path)
    reverse_deps = compute_reverse_deps(modules)

    result = []
    for mod_name, mod_data in modules.items():
        c = complexity.get(mod_name, 0.5)
        h = churn.get(mod_name, 0.5)
        o = ownership.get(mod_name, 0.5)

        score_raw = c * HOTSPOT_W_COMPLEXITY + h * HOTSPOT_W_CHURN + o * HOTSPOT_W_OWNERSHIP
        score = round(score_raw * 10.0, 1)

        if score >= HOTSPOT_HOT_THRESHOLD:
            tier = "hot"
        elif score >= HOTSPOT_WARM_THRESHOLD:
            tier = "warm"
        else:
            tier = "cool"

        refs = len(reverse_deps.get(mod_name, []))

        result.append({
            "name": mod_name,
            "score": score,
            "tier": tier,
            "complexity": round(c, 3),
            "churn": round(h, 3),
            "ownership": round(o, 3),
            "file_count": mod_data.get("file_count", 0),
            "total_lines": mod_data.get("total_lines", 0),
            "referenced_by_count": refs,
        })

    result.sort(key=lambda x: x["score"], reverse=True)
    return result


# ============================================================
# 格式化输出
# ============================================================

def _fmt_utilization_text(data: List[Dict[str, Any]]) -> str:
    lines = ["## 模块利用率排名（按被引用次数降序）"]
    lines.append(f"  {'等级':<8} {'被引用':<6} {'模块名':<25} {'文件':<5} {'行数':<6} {'调用方'}")
    lines.append("  " + "─" * 90)
    icons = {"core": "★", "hub": "◆", "normal": "·", "orphan": "⊙"}
    for m in data:
        refs_short = ", ".join(m["referenced_by"][:3])
        if len(m["referenced_by"]) > 3:
            refs_short += f", +{len(m['referenced_by']) - 3}"
        icon = icons.get(m["tier"], "?")
        lines.append(
            f"  {icon} {m['tier']:<6} {m['ref_count']:<6} {m['name']:<25} "
            f"{m['file_count']:<5} {m['total_lines']:<6} ← {refs_short}"
        )
    return "\n".join(lines)


def _fmt_orphans_text(data: List[Dict[str, Any]]) -> str:
    if not data:
        return "## 孤儿模块: 0 个（所有模块均有引用方）"
    lines = [f"## 孤儿模块（0 引用，非 test_only）: {len(data)} 个"]
    for m in data:
        lines.append(f"  ⚠ {m['name']} — {m['reason']} "
                     f"({m['file_count']} 文件, {m['total_lines']} 行)")
    return "\n".join(lines)


def _fmt_bloat_text(data: List[Dict[str, Any]], max_files: int, max_lines: int) -> str:
    if not data:
        return f"## 膨胀告警: 0 个（阈值: ≤{max_files} 文件, ≤{max_lines} 行）"
    lines = [f"## 膨胀告警（阈值: ≤{max_files} 文件, ≤{max_lines} 行）: {len(data)} 个"]
    for m in data:
        outline = f"  ⚠ {m['name']}: "
        parts = []
        if "file_count" in m.get("bloat_type", ""):
            parts.append(f"文件数 {m['file_count']}（+{m['exceeded_by_files']}）")
        if "total_lines" in m.get("bloat_type", ""):
            parts.append(f"总行数 {m['total_lines']}（+{m['exceeded_by_lines']}）")
        outline += " / ".join(parts)
        lines.append(outline)
    return "\n".join(lines)


def _fmt_shared_utils_text(mapping: Dict[str, List[str]]) -> str:
    if not mapping:
        return "## shared_utils 消费者分布: 无共享函数"
    lines = ["## shared_utils 消费者分布"]
    for func, consumers in sorted(mapping.items()):
        lines.append(f"  {func} → {', '.join(consumers)}")
    return "\n".join(lines)


def _fmt_hotspot_text(data: List[Dict[str, Any]], since_days: int) -> str:
    if not data:
        return f"## 热点风险评分: 无数据（since {since_days}d）"
    lines = [f"## 热点风险评分（{since_days}d, 复杂度×churn×所有权）"]
    lines.append(f"  {'分数':<5} {'等级':<6} {'模块名':<25} {'复杂度':<8} {'churn':<8} {'所有权':<8}")
    lines.append("  " + "─" * 80)
    for m in data:
        tier_label = "🔥 HOT" if m["tier"] == "hot" else ("🌤 warm" if m["tier"] == "warm" else "❄ cool")
        lines.append(
            f"  {m['score']:<5.1f} {tier_label:<6} {m['name']:<25} "
            f"{m['complexity']:<8.3f} {m['churn']:<8.3f} {m['ownership']:<8.3f}"
        )
    hot_count = sum(1 for m in data if m["tier"] == "hot")
    warm_count = sum(1 for m in data if m["tier"] == "warm")
    lines.append(f"\n  🔥 HOT (≥{HOTSPOT_HOT_THRESHOLD}): {hot_count} 个  |  "
                 f"🌤 warm (≥{HOTSPOT_WARM_THRESHOLD}): {warm_count} 个  |  "
                 f"❄ cool: {len(data) - hot_count - warm_count} 个")
    return "\n".join(lines)


# ============================================================
# v1.3.0 P0a: 死代码格式化
# ============================================================

def _fmt_dead_code_text(data: List[Dict[str, Any]]) -> str:
    if not data:
        return "## 函数级死代码检测: 0 个（所有 public_api 函数均有引用）"
    lines = [f"## 函数级死代码检测（public_api 中无任何跨模块引用）: {len(data)} 个"]
    lines.append(f"  {'模块':<25} {'函数':<25} {'文件:行'}")
    lines.append("  " + "─" * 80)
    for d in data:
        location = f"{d.get('file','?')}:{d.get('line','?')}" if d.get("file") else "-"
        lines.append(f"  {d['module']:<25} {d['function']:<25} {location}")
    lines.append(f"\n  ⚠ 建议: 移除 or 添加 `@deprecated` 标记 → refactor_queue 入队 P1")
    return "\n".join(lines)


# ============================================================
# 统计摘要
# ============================================================

def _fmt_statistics_text(utilization: List[Dict[str, Any]], orphans: List[Dict[str, Any]],
                         bloat: List[Dict[str, Any]], dead_code: List[Dict[str, Any]]) -> str:
    total_modules = len(utilization)
    core_count = sum(1 for m in utilization if m["tier"] == "core")
    hub_count = sum(1 for m in utilization if m["tier"] == "hub")
    normal_count = sum(1 for m in utilization if m["tier"] == "normal")
    orphan_count = len(orphans)
    bloat_count = len(bloat)
    dead_count = len(dead_code)

    lines = ["## 统计摘要"]
    lines.append(f"  总模块数: {total_modules}")
    lines.append(f"  ★ core   (>5 引用): {core_count}  ({core_count*100//max(total_modules,1)}%)")
    lines.append(f"  ◆ hub    (3-5 引用): {hub_count}  ({hub_count*100//max(total_modules,1)}%)")
    lines.append(f"  · normal (1-2 引用): {normal_count}  ({normal_count*100//max(total_modules,1)}%)")
    lines.append(f"  ⊙ orphan (0 引用):   {orphan_count}  ({orphan_count*100//max(total_modules,1)}%)")
    lines.append(f"  膨胀模块: {bloat_count}")
    lines.append(f"  死代码函数: {dead_count}")
    return "\n".join(lines)


# ============================================================
# 主入口
# ============================================================

def run_report(
    bp: Dict[str, Any],
    focus: str = "all",
    fmt: str = "text",
    max_files: int = DEFAULT_MAX_FILES,
    max_lines: int = DEFAULT_MAX_LINES,
    since_days: int = DEFAULT_SINCE_DAYS,
    project_root: str = ".",
    codeowners_path: str = "",
) -> str:
    """主分析函数（库模式入口）。"""
    modules = bp.get("modules", {})
    shared_utils = bp.get("shared_utils", [])
    reverse_deps = compute_reverse_deps(modules)

    utilization = analyze_utilization(modules, reverse_deps, shared_utils)
    orphans = analyze_orphans(modules, reverse_deps)
    bloat = analyze_bloat(modules, max_files, max_lines) if focus in ("all", "bloat") else []
    hotspot = analyze_hotspot(modules, since_days, project_root, codeowners_path) if focus in ("all", "hotspot") else []
    dead_code = analyze_dead_code(modules, reverse_deps) if focus in ("all", "dead-code") else []
    clones = analyze_clones(modules) if focus in ("all", "clones") else []
    shared_map = analyze_shared_utils(shared_utils) if focus in ("all", "shared") else {}

    if fmt == "json":
        result: Dict[str, Any] = {"total_modules": len(modules)}
        if focus in ("all", "utilization"):
            result["utilization"] = utilization
        if focus in ("all", "orphans"):
            result["orphans"] = orphans
        if focus in ("all", "bloat"):
            result["bloat"] = bloat
            result["thresholds"] = {"max_files": max_files, "max_lines": max_lines}
        if focus in ("all", "hotspot"):
            result["hotspot"] = hotspot
            result["hotspot_params"] = {"since_days": since_days, "hot_threshold": HOTSPOT_HOT_THRESHOLD}
        if focus in ("all", "dead-code"):
            result["dead_code"] = dead_code
        if focus in ("all", "shared"):
            result["shared_utils"] = shared_map
        if focus in ("all", "clones"):
            result["clones"] = clones
        return json.dumps(result, ensure_ascii=False, indent=2)

    # text 输出
    sections = [_fmt_statistics_text(utilization, orphans, bloat, dead_code)]
    if focus in ("all", "utilization"):
        sections.append(_fmt_utilization_text(utilization))
    if focus in ("all", "orphans"):
        sections.append(_fmt_orphans_text(orphans))
    if focus in ("all", "bloat"):
        sections.append(_fmt_bloat_text(bloat if bloat else [], max_files, max_lines))
    if focus in ("all", "hotspot"):
        sections.append(_fmt_hotspot_text(hotspot, since_days))
    if focus in ("all", "dead-code"):
        sections.append(_fmt_dead_code_text(dead_code))
    if focus in ("all", "shared") and shared_map:
        sections.append(_fmt_shared_utils_text(shared_map))
    if focus in ("all", "clones"):
        sections.append(_fmt_clones_text(clones))

    return "\n\n".join(sections)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="模块健康分析器 — v1.3.0 含 死代码检测 / CODEOWNERS / AST克隆 / 复用建议",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
        示例:
          python module_health.py --blueprint blueprint.json
          python module_health.py --blueprint blueprint.json --focus dead-code
          python module_health.py --blueprint blueprint.json --focus hotspot --codeowners .github/CODEOWNERS
          python module_health.py --blueprint blueprint.json --focus clones --format json
        """),
    )
    parser.add_argument("--blueprint", "-b", required=True,
                        help="architecture_blueprint.json 文件路径")
    parser.add_argument(
        "--focus", choices=["all", "utilization", "orphans", "bloat", "hotspot", "dead-code", "clones", "shared"],
        default="all", help="分析焦点（默认 all 输出全部维度）")
    parser.add_argument("--format", "-f", choices=["text", "json"], default="text",
                        help="输出格式（默认 text 可读表格）")
    parser.add_argument("--max-files", type=int, default=DEFAULT_MAX_FILES,
                        help=f"膨胀告警的文件数阈值（默认 {DEFAULT_MAX_FILES}）")
    parser.add_argument("--max-lines", type=int, default=DEFAULT_MAX_LINES,
                        help=f"膨胀告警的总行数阈值（默认 {DEFAULT_MAX_LINES}）")
    parser.add_argument("--since-days", type=int, default=DEFAULT_SINCE_DAYS,
                        help=f"git churn/ownership 回溯天数（默认 {DEFAULT_SINCE_DAYS}）")
    parser.add_argument("--project-root", default=".",
                        help="项目根目录（git 执行上下文，默认当前目录）")
    parser.add_argument("--codeowners", default="",
                        help="CODEOWNERS 文件路径（如 .github/CODEOWNERS），用于交叉验证 ownership 因子")

    args = parser.parse_args()

    try:
        bp = load_blueprint(args.blueprint)
    except (FileNotFoundError, ValueError) as e:
        _log(f"错误: {e}")
        sys.exit(1)

    output = run_report(
        bp, args.focus, args.format,
        args.max_files, args.max_lines,
        args.since_days, args.project_root,
        args.codeowners,
    )
    sys.stdout.write(output + "\n")
    sys.stdout.flush()


if __name__ == "__main__":
    main()
