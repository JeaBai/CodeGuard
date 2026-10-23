#!/usr/bin/env python3
"""reviewer.py — CodeGuard 质量审查 Agent（生成后阶段）

执行 quality_check 门禁并产出 {type: quality_report} 消息。
在 Team Mode 下作为独立 Agent 运行，接收 Generator 的代码输出，产出质量报告。

用法:
  python reviewer.py --path . --mode personal --format json
  python reviewer.py --path . --mode team --format report
"""
import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import quality_check


def run_review(project_root: str, mode: str = "personal", file_list: list = None) -> dict:
    """执行代码质量门禁审查。

    Args:
        project_root: 项目根目录
        mode: personal / team / diff
        file_list: 可选，指定要检测的文件列表（用于审查特定文件）

    Returns:
        质量报告消息 dict，符合 SKILL.md 定义的 quality_report 协议格式
    """
    if file_list and mode != "diff":
        # 指定文件列表的手动审查模式
        collector = quality_check.IssueCollector()
        for f in file_list:
            fpath = Path(f)
            if not fpath.exists():
                continue
            file_type = quality_check.FileClassifier.classify(str(fpath))
            if file_type in ("generated", "doc"):
                continue
            ext = fpath.suffix.lower()
            if ext == ".py":
                quality_check.check_python_file(str(fpath), collector)
            elif ext in (".js", ".ts", ".mjs"):
                quality_check.check_javascript_file(str(fpath), collector, ext)
            elif ext == ".java":
                quality_check.check_java_file(str(fpath), collector)
            elif ext == ".go":
                quality_check.check_go_file(str(fpath), collector)
            elif ext == ".cs":
                quality_check.check_csharp_file(str(fpath), collector)
            else:
                quality_check.check_generic_file(str(fpath), collector, ext)
            if mode == "team":
                quality_check.check_naming_consistency([str(fpath)], collector)
    else:
        # 标准模式：全量/增量/团队
        collector = quality_check.run_quality_check(project_root, mode=mode)

    summary = collector.summary()
    exit_code = 2 if collector.has_blocks() else (1 if collector.has_warns() else 0)

    verdicts = {0: "PASS", 1: "PASS_WITH_WARNINGS", 2: "BLOCK"}
    verdict = verdicts.get(exit_code, "UNKNOWN")

    return {
        "type": "quality_report",
        "version": "1.0",
        "exit_code": exit_code,
        "verdict": verdict,
        "summary": summary,
        "issues": [{
            "severity": i["severity"],
            "category": i["category"],
            "file": i["file"],
            "line": i["line"],
            "message": i["message"],
            "suggestion": i.get("suggestion", ""),
            "confidence": i.get("confidence", 0),
        } for i in collector.issues],
        "suggestions": [
            i["suggestion"] for i in collector.issues
            if i.get("suggestion") and i["severity"] in ("block", "warn")
        ][:5],
    }


def main():
    parser = argparse.ArgumentParser(description="CodeGuard Reviewer Agent — 质量门禁审查")
    parser.add_argument("--path", default=".", help="项目根目录")
    parser.add_argument("--mode", choices=["personal", "team", "diff"], default="personal")
    parser.add_argument("--files", nargs="*", default=None, help="指定要审查的文件（可选）")
    parser.add_argument("--format", choices=["json", "report"], default="json")
    args = parser.parse_args()

    report = run_review(args.path, args.mode, file_list=args.files)
    print(json.dumps(report, ensure_ascii=False, indent=2))  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
    return report["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
