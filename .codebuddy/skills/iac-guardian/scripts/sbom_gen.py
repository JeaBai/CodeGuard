#!/usr/bin/env python3
"""sbom_gen.py — SBOM 生成与归档（CycloneDX 1.4 格式）

iac-guardian Roadmap P1-1: SBOM 生成与归档（对接 syft）
纯 Python 标准库实现，零第三方依赖。
从项目文件生成 CycloneDX 1.4 SBOM (Software Bill of Materials) JSON。

用法:
  python sbom_gen.py --path . --name my-project --version 1.0.0
  python sbom_gen.py --path . --name my-project --version 1.0.0 -o sbom.json
"""
import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

VERSION = "0.1.0"


def generate_sbom(project_root: str, project_name: str, project_version: str,
                  output_file: str = "") -> dict:
    """生成 CycloneDX 1.4 SBOM JSON。

    扫描项目目录中所有跟踪文件，为每个文件生成:
    - sha256 哈希
    - 类型分类（application/test/config/documentation）
    - CycloneDX 1.4 兼容组件条目

    Args:
        project_root: 项目根目录
        project_name: 项目名称
        project_version: 项目版本
        output_file: 可选输出文件路径

    Returns:
        CycloneDX 1.4 SBOM dict
    """
    root = Path(project_root).resolve()
    components = []

    # 扫描文件（排除 .git / __pycache__ / node_modules / .terraform / venv）
    skip_dirs = {".git", "__pycache__", "node_modules", ".terraform", "venv", ".venv", ".idea", ".vscode"}
    skip_exts = {".pyc", ".pyo", ".pyd", ".class", ".exe", ".dll", ".so", ".o", ".ttf", ".woff", ".woff2"}

    for f in sorted(root.rglob("*")):
        if not f.is_file():
            continue
        if any(sd in f.parts for sd in skip_dirs):
            continue
        if f.suffix.lower() in skip_exts:
            continue

        rel = str(f.relative_to(root)).replace("\\", "/")
        content = f.read_bytes()
        sha256 = hashlib.sha256(content).hexdigest()

        # 类型分类
        ext = f.suffix.lower()
        if ext in (".py", ".js", ".ts", ".java", ".go", ".cs", ".rs", ".tf", ".yaml", ".yml", ".json"):
            comp_type = "application"
        elif "test" in rel.lower() or ext == ".md":
            comp_type = "test" if "test" in rel.lower() else "documentation"
        else:
            comp_type = "application"

        components.append({
            "type": comp_type,
            "name": rel,
            "version": project_version,
            "hashes": [{"alg": "SHA-256", "content": sha256}],
            "purl": f"pkg:generic/{project_name}/{rel}@v{project_version}",
        })

    sbom = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.4",
        "serialNumber": f"urn:uuid:{hashlib.md5(project_name.encode()).hexdigest()}",
        "version": 1,
        "metadata": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "tools": [{"vendor": "iac-guardian", "name": "sbom_gen.py", "version": VERSION}],
            "component": {
                "type": "application",
                "name": project_name,
                "version": project_version,
            },
        },
        "components": components,
    }

    if output_file:
        Path(output_file).write_text(
            json.dumps(sbom, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    return sbom


def main():
    parser = argparse.ArgumentParser(description=f"SBOM 生成器 (CycloneDX 1.4) v{VERSION}")
    parser.add_argument("--path", default=".", help="项目根目录")
    parser.add_argument("--name", required=True, help="项目名称")
    parser.add_argument("--version", required=True, help="项目版本")
    parser.add_argument("-o", "--output", default="", help="输出 JSON 文件路径")
    args = parser.parse_args()

    sbom = generate_sbom(args.path, args.name, args.version, args.output)

    if not args.output:
        print(json.dumps(sbom, ensure_ascii=False, indent=2))  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION

    print(f"\nSBOM 生成完成: {len(sbom['components'])} 个组件", file=sys.stderr)  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
    return 0


if __name__ == "__main__":
    sys.exit(main())
