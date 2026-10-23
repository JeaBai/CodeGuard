#!/usr/bin/env python3
"""external_scan.py — Checkov / Trivy 结果聚合器

iac-guardian Roadmap P1-3: Checkov/Trivy 外部扫描器结果聚合
聚合外部扫描器输出，生成统一的安全报告格式（SARIF 导入）。

支持的扫描器:
  - Checkov (bridgecrewio/checkov)
  - Trivy (aquasecurity/trivy)
  输出格式: SARIF 2.1.0 / iac-guardian 统一 JSON

用法:
  python external_scan.py --checkov checkov_output.json --trivy trivy_output.json
  python external_scan.py --checkov checkov_output.json --format sarif -o report.sarif
  python external_scan.py --run-checkov --path terraform/
"""
import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

VERSION = "0.1.0"


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION


# ── 解析器 ────────────────────────────────────────────────────

def parse_checkov_output(filepath: str) -> list[dict]:
    """解析 Checkov JSON 输出，转换为 iac-guardian 统一格式。"""
    results = []
    if not Path(filepath).exists():
        return results

    data = json.loads(Path(filepath).read_text(encoding="utf-8", errors="replace"))
    for result in data.get("results", {}).get("failed_checks", []):
        sev_map = {"CRITICAL": "block", "HIGH": "block", "MEDIUM": "warn", "LOW": "warn", "INFO": "info"}
        results.append({
            "source": "checkov",
            "rule": result.get("check_id", "?"),
            "severity": sev_map.get(result.get("check_result", {}).get("result", "FAILED") if result.get("severity") == "CRITICAL" else result.get("severity", "MEDIUM"), "warn"),
            "file": result.get("file_path", ""),
            "line": result.get("file_line_range", [0])[0] if result.get("file_line_range") else 0,
            "message": result.get("check_name", result.get("check_id", "")),
            "suggestion": result.get("guideline", ""),
            "dimension": "D8",
        })
    return results


def parse_trivy_output(filepath: str) -> list[dict]:
    """解析 Trivy JSON 输出，转换为 iac-guardian 统一格式。"""
    results = []
    if not Path(filepath).exists():
        return results

    data = json.loads(Path(filepath).read_text(encoding="utf-8", errors="replace"))
    for result in data.get("Results", []):
        for misconfig in result.get("Misconfigurations", []):
            sev_map = {"CRITICAL": "block", "HIGH": "block", "MEDIUM": "warn", "LOW": "warn"}
            results.append({
                "source": "trivy",
                "rule": misconfig.get("ID", "?"),
                "severity": sev_map.get(misconfig.get("Severity", "MEDIUM"), "warn"),
                "file": result.get("Target", ""),
                "line": misconfig.get("CauseMetadata", {}).get("StartLine", 0) or 0,
                "message": misconfig.get("Title", misconfig.get("ID", "")),
                "suggestion": misconfig.get("Description", ""),
                "dimension": "D8",
            })
    return results


# ── 扫描器运行 ────────────────────────────────────────────────

def run_checkov(scan_path: str, output_file: str = "") -> tuple[list[dict], str]:
    """运行 Checkov 扫描并返回结果。"""
    cmd = ["checkov", "-d", scan_path, "-o", "json"]
    if output_file:
        cmd += ["--output-file-path", output_file]

    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=300)
        if output_file and Path(output_file).exists():
            return parse_checkov_output(output_file), output_file
        # 尝试从 stdout 解析
        try:
            data = json.loads(r.stdout)
            temp_file = "/tmp/_checkov_temp.json"
            Path(temp_file).write_text(r.stdout, encoding="utf-8")
            return parse_checkov_output(temp_file), temp_file
        except json.JSONDecodeError:
            return [], ""
    except FileNotFoundError:
        _log("Checkov 未安装: pip install checkov")
        return [], ""
    except Exception as e:  # codeguard: ignore GOLD_NO_BROAD_EXCEPTION
        _log(f"Checkov 运行失败: {e}")
        return [], ""


def run_trivy(scan_path: str, output_file: str = "") -> tuple[list[dict], str]:
    """运行 Trivy 扫描并返回结果。"""
    cmd = ["trivy", "config", scan_path, "--format", "json"]
    if output_file:
        cmd += ["--output", output_file]

    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=300)
        if output_file and Path(output_file).exists():
            return parse_trivy_output(output_file), output_file
        try:
            data = json.loads(r.stdout)
            temp_file = "/tmp/_trivy_temp.json"
            Path(temp_file).write_text(r.stdout, encoding="utf-8")
            return parse_trivy_output(temp_file), temp_file
        except json.JSONDecodeError:
            return [], ""
    except FileNotFoundError:
        _log("Trivy 未安装: pip install trivy 或 brew install trivy")
        return [], ""
    except Exception as e:  # codeguard: ignore GOLD_NO_BROAD_EXCEPTION
        _log(f"Trivy 运行失败: {e}")
        return [], ""


# ── SARIF 输出 ────────────────────────────────────────────────

def to_sarif(all_issues: list[dict], scan_path: str) -> dict:
    """转换为 SARIF 2.1.0 格式。"""
    severity_map = {"block": "error", "warn": "warning", "info": "note"}
    results = []
    for i, issue in enumerate(all_issues):
        results.append({
            "ruleId": issue.get("rule_id", issue.get("rule", "unknown")),
            "level": severity_map.get(issue.get("severity", "warn"), "warning"),
            "message": {"text": issue.get("message", "")},
            "locations": [{"physicalLocation": {
                "artifactLocation": {"uri": issue.get("file", "")},
                "region": {"startLine": issue.get("line", 1)},
            }}],
        })

    return {
        "version": "2.1.0",
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",  # codeguard: ignore GOLD_NO_HARDCODED_URL
        "runs": [{
            "tool": {
                "driver": {
                    "name": "iac-guardian-external-aggregator",
                    "version": VERSION,
                    "informationUri": "https://github.com/JeaBai/SKILL-project-management",  # codeguard: ignore GOLD_NO_HARDCODED_URL
                },
            },
            "results": results,
        }],
    }


# ── 主流程 ────────────────────────────────────────────────────

def aggregate(scanners: dict, scan_path: str = ".") -> dict:
    """聚合所有扫描器结果。

    Args:
        scanners: {scanner_name: filepath} dict
        scan_path: 扫描目录（用于运行扫描器）

    Returns:
        聚合报告
    """
    parsers = {"checkov": parse_checkov_output, "trivy": parse_trivy_output}
    all_issues = []

    for name, result_file in scanners.items():
        parser = parsers.get(name)
        if parser and result_file:
            issues = parser(result_file)
            all_issues.extend(issues)

    blocks = [i for i in all_issues if i["severity"] == "block"]
    warns = [i for i in all_issues if i["severity"] == "warn"]
    exit_code = 2 if blocks else (1 if warns else 0)

    return {
        "version": VERSION,
        "exit_code": exit_code,
        "summary": {
            "total": len(all_issues),
            "blocks": len(blocks),
            "warnings": len(warns),
            "by_source": {
                name: sum(1 for i in all_issues if i.get("source") == name)
                for name in scanners
            },
        },
        "issues": all_issues,
        "aggregated_at": datetime.now(timezone.utc).isoformat(),
    }


def main():
    parser = argparse.ArgumentParser(description=f"Checkov/Trivy 聚合器 v{VERSION}")
    parser.add_argument("--checkov", default="", help="Checkov JSON 输出文件")
    parser.add_argument("--trivy", default="", help="Trivy JSON 输出文件")
    parser.add_argument("--run-checkov", action="store_true", help="运行 Checkov 扫描")
    parser.add_argument("--run-trivy", action="store_true", help="运行 Trivy 扫描")
    parser.add_argument("--path", default=".", help="扫描目录")
    parser.add_argument("--format", choices=["json", "sarif", "text"], default="json")
    parser.add_argument("-o", "--output", default="", help="输出文件")
    args = parser.parse_args()

    scanners = {}
    if args.checkov:
        scanners["checkov"] = args.checkov
    if args.trivy:
        scanners["trivy"] = args.trivy

    # 如果需要运行扫描器
    if args.run_checkov:
        checkov_results, checkov_file = run_checkov(args.path)
        if checkov_file:
            scanners["checkov"] = checkov_file
    if args.run_trivy:
        trivy_results, trivy_file = run_trivy(args.path)
        if trivy_file:
            scanners["trivy"] = trivy_file

    report = aggregate(scanners, args.path)

    if args.format == "sarif":
        sarif = to_sarif(report["issues"], args.path)
        output = json.dumps(sarif, ensure_ascii=False, indent=2)
    else:
        output = json.dumps(report, ensure_ascii=False, indent=2)

    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
        print(f"报告已写入 {args.output}", file=sys.stderr)  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION

    if args.format == "text":
        s = report["summary"]
        print(f"\n聚合报告: {s['total']} 发现 ({s['blocks']} BLOCK / {s['warnings']} WARN)")  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
        for i in report["issues"][:10]:
            print(f"  [{i['severity'].upper()}] {i['source']}:{i['rule']} {i['file']}:{i['line']}")  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
    else:
        print(output)  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION

    return report["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
