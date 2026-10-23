"""快照公共 API — 创建/对比/门禁/查询/回滚。"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from snapshot_store import (
    _GATE_NEUTRAL_THRESHOLD,
    _get_snapshots_dir,
    _snapshot_id,
    _load_snapshot,
    _save_snapshot,
    _list_snapshot_files,
    _log,
)
from snapshot_collect import (
    _collect_codeguard_metrics,
    _collect_file_hashes,
    _hash_blueprint,
    _get_git_commit,
    _is_git_repo,
)

# ============================================================
# 公共 API：create_snapshot()
# ============================================================

def create_snapshot(trigger: str, project_path: str = ".") -> dict:
    """创建架构快照。

    Args:
        trigger: 触发原因 (如 "pre-refactor:ADR-001")。
        project_path: 项目根目录。

    Returns:
        {"status": "created", "snapshot_id": str, "file": str}
    """
    project_path = os.path.abspath(project_path)
    snap_dir = _get_snapshots_dir(project_path)
    snap_id = _snapshot_id()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    _log(f"创建快照: {snap_id} (触发: {trigger})")

    # 采集指标
    _log("  采集指标...")
    metrics = _collect_codeguard_metrics(project_path)

    # 文件哈希
    _log("  计算文件哈希...")
    file_hashes = _collect_file_hashes(project_path)

    # 蓝图哈希
    bp_hash = _hash_blueprint(project_path)

    # Git commit
    git_commit = _get_git_commit(project_path)

    snapshot = {
        "snapshot_id": snap_id,
        "timestamp": now,
        "trigger": trigger,
        "git_commit": git_commit,
        "metrics": metrics,
        "file_hashes": file_hashes,
        "blueprint_hash": bp_hash,
        "file_count": len(file_hashes),
    }

    fpath = _save_snapshot(snap_dir, snapshot)
    _log(f"  快照已保存: {fpath}")
    _log(f"  指标摘要: {metrics['total_files']} 文件, {metrics['total_functions']} 函数, "
         f"CC(max={metrics['max_complexity']}, avg={metrics['avg_complexity']})")

    return {"status": "created", "snapshot_id": snap_id, "file": fpath, "metrics": metrics}


# ============================================================
# 公共 API：compare_snapshots()
# ============================================================

def compare_snapshots(before_id: str, after_id: str,
                      project_path: str = ".") -> dict:
    """对比两个快照的指标变化。

    Returns:
        {improved: [str], degraded: [str], unchanged: [str],
         verdict: "approve"|"reject"|"manual_review", reject_reasons: [str],
         file_changes: {added: [str], removed: [str], modified: [str]}}
    """
    project_path = os.path.abspath(project_path)
    snap_dir = _get_snapshots_dir(project_path)
    before = _load_snapshot(snap_dir, before_id)
    after = _load_snapshot(snap_dir, after_id)

    if before is None:
        return {"error": f"快照 '{before_id}' 不存在"}
    if after is None:
        return {"error": f"快照 '{after_id}' 不存在"}

    m1 = before.get("metrics", {})
    m2 = after.get("metrics", {})

    improved: list[str] = []
    degraded: list[str] = []
    unchanged: list[str] = []

    # 对比数值指标
    _compare_metric("total_files", m1, m2, improved, degraded, unchanged,
                    "文件数", higher_is_better=True)
    _compare_metric("total_functions", m1, m2, improved, degraded, unchanged,
                    "函数数", higher_is_better=True)
    _compare_metric("max_complexity", m1, m2, improved, degraded, unchanged,
                    "最大圈复杂度", higher_is_better=False, round_digits=0)
    _compare_metric("avg_complexity", m1, m2, improved, degraded, unchanged,
                    "平均圈复杂度", higher_is_better=False, round_digits=1)
    _compare_metric("duplicate_blocks", m1, m2, improved, degraded, unchanged,
                    "重复代码块", higher_is_better=False)
    _compare_metric("duplicate_lines", m1, m2, improved, degraded, unchanged,
                    "重复代码行", higher_is_better=False)
    _compare_metric("architecture_cycles", m1, m2, improved, degraded, unchanged,
                    "循环依赖", higher_is_better=False)
    _compare_metric("codeguard_blocks", m1, m2, improved, degraded, unchanged,
                    "CodeGuard阻塞", higher_is_better=False)
    _compare_metric("codeguard_warns", m1, m2, improved, degraded, unchanged,
                    "CodeGuard警告", higher_is_better=False)
    _compare_metric("global_vars", m1, m2, improved, degraded, unchanged,
                    "全局变量", higher_is_better=False)
    _compare_metric("test_coverage", m1, m2, improved, degraded, unchanged,
                    "测试覆盖率", higher_is_better=True, round_digits=1, unit="%")

    # 总行数对比
    _compare_metric("total_lines", m1, m2, improved, degraded, unchanged,
                    "总行数", higher_is_better=True)

    # 文件变更
    h1 = before.get("file_hashes", {})
    h2 = after.get("file_hashes", {})
    f1_keys = set(h1.keys())
    f2_keys = set(h2.keys())

    file_changes = {
        "added": sorted(f2_keys - f1_keys),
        "removed": sorted(f1_keys - f2_keys),
        "modified": sorted(k for k in (f1_keys & f2_keys) if h1[k] != h2[k]),
    }

    # 自动判断
    reject_reasons = []
    for d in degraded:
        desc = d.split(":")[0].strip() if ":" in d else d
        if any(kw in desc for kw in ["重复代码块", "循环依赖", "阻塞", "全局变量"]):
            reject_reasons.append(f"{desc} 恶化超过阈值")
        if "测试覆盖率" in desc:
            reject_reasons.append("测试覆盖率下降")

    if reject_reasons:
        verdict = "reject"
    elif degraded and not improved:
        verdict = "reject"
    elif degraded:
        verdict = "manual_review"
    else:
        verdict = "approve"

    return {
        "improved": improved,
        "degraded": degraded,
        "unchanged": unchanged,
        "file_changes": file_changes,
        "verdict": verdict,
        "reject_reasons": reject_reasons,
        "before_id": before_id,
        "after_id": after_id,
    }


def _compare_metric(name: str, m1: dict, m2: dict,
                    improved: list, degraded: list, unchanged: list,
                    label: str, higher_is_better: bool = False,
                    round_digits: int = 0, unit: str = ""):
    """对比单个指标。"""
    v1 = m1.get(name)
    v2 = m2.get(name)
    if v1 is None or v2 is None:
        return
    if v1 == v2:
        unchanged.append(f"{label}: {_fmt_val(v1, round_digits)}{unit}")
        return

    if v1 == 0:
        ratio = 2.0 if v2 > 0 else 1.0
    else:
        ratio = v2 / v1

    v1_str = f"{_fmt_val(v1, round_digits)}{unit}"
    v2_str = f"{_fmt_val(v2, round_digits)}{unit}"

    is_increase = ratio > _GATE_NEUTRAL_THRESHOLD
    is_decrease = ratio < 1.0 / _GATE_NEUTRAL_THRESHOLD

    if not is_increase and not is_decrease:
        unchanged.append(f"{label}: {v1_str} → {v2_str}")
    elif higher_is_better and is_increase:
        improved.append(f"{label}: {v1_str} → {v2_str}")
    elif higher_is_better and is_decrease:
        degraded.append(f"{label}: {v1_str} → {v2_str}")
    elif not higher_is_better and is_decrease:
        improved.append(f"{label}: {v1_str} → {v2_str}")
    elif not higher_is_better and is_increase:
        degraded.append(f"{label}: {v1_str} → {v2_str}")
    else:
        unchanged.append(f"{label}: {v1_str} → {v2_str}")


def _fmt_val(v: float | int, digits: int) -> str:
    if digits == 0:
        return str(int(v))
    return f"{v:.{digits}f}"


# ============================================================
# 公共 API：auto_gate()
# ============================================================

def auto_gate(before_id: str, after_id: str,
              project_path: str = ".") -> dict:
    """自动门禁判断。

    规则：
      - 任何指标恶化 >20% → reject
      - test_coverage 下降 → reject
      - architecture_cycles 新增 → reject
      - duplicate_blocks 增加 → reject
      - 其他改善或持平 → approve
      - 变化 ≤10% 但方向混合 → manual_review
    """
    comparison = compare_snapshots(before_id, after_id, project_path)
    if "error" in comparison:
        return comparison

    verdict = comparison.get("verdict", "manual_review")
    return {
        "gate_result": verdict.upper(),
        "verdict": verdict,
        "before_id": before_id,
        "after_id": after_id,
        "improved": comparison.get("improved", []),
        "degraded": comparison.get("degraded", []),
        "file_changes": comparison.get("file_changes", {}),
        "reject_reasons": comparison.get("reject_reasons", []),
        "should_rollback": verdict == "reject",
    }


# ============================================================
# 公共 API：get_snapshot() / list_snapshots() / rollback_to()
# ============================================================

def get_snapshot(snap_id: str, project_path: str = ".") -> dict | None:
    return _load_snapshot(_get_snapshots_dir(project_path), snap_id)


def list_snapshots(project_path: str = ".") -> dict:
    snap_dir = _get_snapshots_dir(project_path)
    files = _list_snapshot_files(snap_dir)
    result = []
    for fpath in files:
        snap = json.loads(fpath.read_text(encoding="utf-8"))
        m = snap.get("metrics", {})
        result.append({
            "snapshot_id": snap.get("snapshot_id", ""),
            "timestamp": snap.get("timestamp", ""),
            "trigger": snap.get("trigger", ""),
            "git_commit": (snap.get("git_commit", "") or "")[:8],
            "files": m.get("total_files", 0),
            "functions": m.get("total_functions", 0),
            "max_cc": m.get("max_complexity", 0),
            "avg_cc": m.get("avg_complexity", 0),
            "blocks": m.get("codeguard_blocks", 0),
            "warns": m.get("codeguard_warns", 0),
        })
    return {"snapshots": result, "total": len(result)}


def rollback_to(snap_id: str, project_path: str = ".") -> dict:
    """回滚到指定快照。"""
    snap = get_snapshot(snap_id, project_path)
    if snap is None:
        return {"status": "not_found", "id": snap_id}

    project_path = os.path.abspath(project_path)
    git_commit = snap.get("git_commit", "")
    is_git = _is_git_repo(project_path)

    if is_git and git_commit:
        rollback_cmd = f"git checkout {git_commit}"
        git_message = (
            f"检测到 git 仓库。快照关联 commit: {git_commit[:8]}\n"
            f"手动回滚命令: git checkout {git_commit}"
        )
    elif is_git:
        rollback_cmd = "git revert HEAD"
        git_message = "检测到 git 仓库但快照无 commit hash。建议: git revert HEAD"
    else:
        rollback_cmd = None
        git_message = "未检测到 git 仓库。请手动从备份恢复文件。"

    changed_files = snap.get("file_hashes", {})
    trigger = snap.get("trigger", "")

    return {
        "status": "pending_manual",
        "snapshot_id": snap_id,
        "trigger": trigger,
        "timestamp": snap.get("timestamp", ""),
        "file_count": len(changed_files),
        "git_available": is_git,
        "suggested_command": rollback_cmd,
        "message": git_message,
    }
