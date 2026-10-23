"""重构队列 CLI 入口。"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

from refactor_queue_store import _log
from refactor_queue_core import enqueue, dequeue
from refactor_queue_locks import lock_files, unlock_files, check_file_lock
from refactor_queue_tasks import (
    get_queue_status,
    complete_task,
    fail_task,
    get_blocked_tasks,
    reorder,
)
from refactor_queue_import import import_refactor_tasks

# ============================================================
# CLI 入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="Project Manager Refactor Queue — 渐进式重构队列管理",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python refactor_queue.py --action enqueue --title "修复嵌套深度" --files src/auth/auth.py --priority P0
  python refactor_queue.py --action dequeue
  python refactor_queue.py --action status
  python refactor_queue.py --action complete --id RF-001 --gate-result approve
  python refactor_queue.py --action fail --id RF-001 --reason "测试失败，回滚"
  python refactor_queue.py --action import --codeguard-output issues.json
  python refactor_queue.py --action check-lock --file src/auth/auth.py
  python refactor_queue.py --action lock --id RF-001
  python refactor_queue.py --action unlock --id RF-001
  python refactor_queue.py --action blocked
  python refactor_queue.py --action reorder --id RF-003 --priority P0
        """,
    )
    parser.add_argument("--action", required=True,
                        choices=["enqueue", "dequeue", "status", "complete",
                                 "fail", "lock", "unlock", "check-lock",
                                 "import", "blocked", "reorder"],
                        help="操作类型")
    parser.add_argument("--title", help="任务标题 (enqueue)")
    parser.add_argument("--files", help="逗号分隔的文件列表 (enqueue)")
    parser.add_argument("--priority", default="P2", help="优先级 P0-P3 (enqueue/reorder)")
    parser.add_argument("--description", default="", help="任务描述 (enqueue)")
    parser.add_argument("--depends-on", default="", help="逗号分隔的依赖任务ID (enqueue)")
    parser.add_argument("--id", help="任务 ID (complete/fail/lock/unlock/reorder)")
    parser.add_argument("--file", help="文件路径 (check-lock)")
    parser.add_argument("--reason", default="", help="失败原因 (fail)")
    parser.add_argument("--gate-result", default="", help="门禁结果 (complete)")
    parser.add_argument("--snapshot-after", default="", help="重构后快照ID (complete)")
    parser.add_argument("--codeguard-output", default="", help="CodeGuard 输出 JSON (import)")
    parser.add_argument("--blueprint", default="", help="architecture_blueprint.json (import)")
    parser.add_argument("--project", default=".", help="项目根目录")
    parser.add_argument("--format", default="text", choices=["text", "json"],
                        help="输出格式")
    args = parser.parse_args()

    root = os.path.abspath(args.project)

    if args.action == "enqueue":
        _check(args.title, "--title", "enqueue")
        _check(args.files, "--files", "enqueue")
        files = [f.strip() for f in args.files.split(",") if f.strip()]
        deps = [d.strip() for d in args.depends_on.split(",") if d.strip()] if args.depends_on else []
        result = enqueue(args.title, files, args.priority, args.description, deps, {}, root)
        _output(result, args.format)
    elif args.action == "dequeue":
        result = dequeue(root)
        _output(result, args.format, _fmt_dequeue)
    elif args.action == "status":
        result = get_queue_status(root)
        _output(result, args.format, _fmt_status)
    elif args.action == "complete":
        _check(args.id, "--id", "complete")
        result = complete_task(args.id, args.snapshot_after, args.gate_result, root)
        _output(result, args.format)
    elif args.action == "fail":
        _check(args.id, "--id", "fail")
        result = fail_task(args.id, args.reason, root)
        _output(result, args.format)
    elif args.action == "lock":
        _check(args.id, "--id", "lock")
        result = lock_files(args.id, root)
        _output(result, args.format)
    elif args.action == "unlock":
        _check(args.id, "--id", "unlock")
        result = unlock_files(args.id, root)
        _output(result, args.format)
    elif args.action == "check-lock":
        _check(args.file, "--file", "check-lock")
        result = check_file_lock(args.file, root)
        _output(result, args.format, _fmt_lock)
    elif args.action == "import":
        _check(args.codeguard_output, "--codeguard-output", "import")
        result = import_refactor_tasks(args.codeguard_output, args.blueprint, root)
        _output(result, args.format)
    elif args.action == "blocked":
        result = get_blocked_tasks(root)
        _output(result, args.format, _fmt_blocked)
    elif args.action == "reorder":
        _check(args.id, "--id", "reorder")
        result = reorder(args.id, args.priority, root)
        _output(result, args.format)


def _check(value: str | None, flag: str, action: str) -> None:
    if not value:
        _log(f"错误: --action {action} 需要 {flag}")
        sys.exit(1)


def _output(data: Any, fmt: str, text_fmt=None) -> None:
    if fmt == "json":
        print(json.dumps(data, indent=2, ensure_ascii=False, default=str))
    elif text_fmt:
        text_fmt(data)
    elif isinstance(data, dict):
        status = data.get("status", "")
        icon = {"enqueued": "✅", "dequeued": "📤", "completed": "✅", "failed": "❌",
                "locked": "🔒", "unlocked": "🔓", "not_found": "❌",
                "no_available_tasks": "⏸️", "reordered": "🔄"}.get(status, "")
        print(f"{icon} {status}: {data.get('id', data.get('message', ''))}")
        if data.get("task"):
            t = data["task"]
            print(f"   标题: {t.get('title', '')}")
            print(f"   优先级: {t.get('priority', '')} | 状态: {t.get('status', '')}")
    else:
        print(data)


def _fmt_dequeue(r: dict) -> None:
    if r["status"] == "no_available_tasks":
        print(f"⏸️ {r.get('message', '')}")
        return
    t = r.get("task", {})
    print(f"\n📤 出队任务: {t.get('id', '')}")
    print(f"   标题:   {t.get('title', '')}")
    print(f"   优先级: {t.get('priority', '')}")
    print(f"   文件:   {', '.join(t.get('files_locked', []))}")
    print(f"   描述:   {t.get('description', '')}")
    if t.get("tags_required"):
        print(f"   标签:   {json.dumps(t['tags_required'], ensure_ascii=False)}")
    if t.get("max_nesting_target"):
        print(f"   目标:   嵌套深度 ≤ {t['max_nesting_target']}")


def _fmt_status(r: dict) -> None:
    total = r.get("total_queue", 0) + r.get("completed", 0) + r.get("failed", 0)
    done = r.get("completed", 0)
    pct = f"{done * 100 // max(total, 1)}%" if total else "N/A"
    print(f"\n重构队列状态 ({pct} 完成)")
    print("-" * 45)
    for label, key in [("⏳ 待处理", "pending"), ("🔄 进行中", "in_progress"),
                       ("🔒 被阻塞(依赖)", "blocked_by_deps"),
                       ("🔒 被阻塞(锁)", "blocked_by_locks"),
                       ("✅ 已完成", "completed"), ("❌ 失败", "failed")]:
        val = r.get(key, 0)
        if val > 0:
            print(f"  {label}: {val}")
    print("-" * 45)


def _fmt_lock(r: dict) -> None:
    if r.get("locked"):
        print(f"🔒 已锁定: {r['file']}")
        print(f"   任务: {r.get('locked_by', '')}")
        print(f"   时间: {r.get('locked_at', '')}")
    else:
        print(f"✅ 可用: {r['file']} (未锁定)")


def _fmt_blocked(r: dict) -> None:
    print(f"\n阻塞任务: {r.get('count', 0)} 个")
    for t in r.get("blocked_tasks", []):
        print(f"  🔒 [{t['priority']}] {t['title']}")
        if t.get("blocked_by_deps"):
            print(f"     依赖未完成: {', '.join(t['blocked_by_deps'])}")
        if t.get("blocked_by_files"):
            print(f"     文件被锁: {', '.join(t['blocked_by_files'])}")


if __name__ == "__main__":
    main()
