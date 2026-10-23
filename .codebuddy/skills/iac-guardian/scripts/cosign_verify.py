#!/usr/bin/env python3
"""cosign_verify.py — 镜像签名验证（cosign CLI 包装器）

iac-guardian Roadmap P1-2: cosign 镜像签名验证
调用 cosign CLI 验证容器镜像签名，支持 keyless (Sigstore) 和 key-based 两种模式。

前置: 安装 cosign CLI: https://github.com/sigstore/cosign  # codeguard: ignore GOLD_NO_HARDCODED_URL
用法:
  python cosign_verify.py --image nginx:1.25
  python cosign_verify.py --image myreg.io/app:v1 --key cosign.pub --format json
  python cosign_verify.py --scan-dir deploy/ --format json
"""
import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

VERSION = "0.1.0"


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION


def find_cosign() -> str | None:
    """查找 cosign 可执行文件路径。"""
    try:
        r = subprocess.run(["cosign", "version"], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=10)
        if r.returncode == 0:
            return "cosign"
    except FileNotFoundError:  # codeguard: ignore GOLD_NO_EMPTY_EXCEPT
        pass
    return None


def extract_images_from_file(filepath: str) -> list[str]:
    """从 IaC 文件中提取镜像引用。"""
    path = Path(filepath)
    content = path.read_text(encoding="utf-8", errors="replace")

    # 匹配 Docker/K8s/TF 中的镜像引用模式
    patterns = [
        r'image:\s*["\']?([^\s"\'#]+:[^\s"\'#]+)',         # K8s image: xxx
        r'FROM\s+([^\s]+)',                                   # Dockerfile FROM
        r'"?(image)\s*=\s*["\']([^\s"\'#]+:[^\s"\'#]+)',    # TF image = "xxx"
    ]
    images = set()
    for p in patterns:
        for m in re.finditer(p, content, re.MULTILINE | re.IGNORECASE):
            groups = m.groups()
            img = groups[-1]  # 取最后一个捕获组（image 名）
            # 过滤变量引用
            if "$" not in img and "{" not in img:
                images.add(img)
    return sorted(images)


def verify_image(image: str, key: str = "", keyless: bool = True) -> dict:
    """验证单个镜像签名。

    Args:
        image: 镜像引用（如 nginx:1.25）
        key: 公钥路径（key-based 模式）
        keyless: 是否使用 keyless (Sigstore) 模式

    Returns:
        {image, verified, mode, details}
    """
    cmd = ["cosign", "verify"]

    if key:
        cmd += ["--key", key]
    elif keyless:
        cmd += ["--certificate-identity", "*", "--certificate-oidc-issuer", "*"]
    else:
        cmd += ["--key", "cosign.pub"]

    cmd.append(image)

    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=60)
        return {
            "image": image,
            "verified": r.returncode == 0,
            "mode": "keyless" if keyless and not key else "key",
            "details": r.stdout.strip()[:500] if r.returncode == 0 else r.stderr.strip()[:500],  # codeguard: ignore GOLD_NO_MAGIC_NUMBER
            "exit_code": r.returncode,
        }
    except FileNotFoundError:
        return {"image": image, "verified": False, "mode": "unknown",
                "details": "cosign CLI 未安装，请运行: brew install cosign 或 go install github.com/sigstore/cosign/v2/cmd/cosign@latest"}
    except Exception as e:  # codeguard: ignore GOLD_NO_BROAD_EXCEPTION
        return {"image": image, "verified": False, "mode": "error", "details": str(e)}


def scan_directory(root_path: str, key: str = "", keyless: bool = True) -> dict:
    """扫描目录中所有 IaC 文件，提取并验证镜像签名。

    Returns:
        {images, results, summary}
    """
    root = Path(root_path)
    all_images = set()

    for pattern in ["**/*.tf", "**/*.yaml", "**/*.yml", "**/Dockerfile*"]:
        for f in root.glob(pattern):
            if any(x in str(f) for x in (".git", ".terraform", "node_modules", "venv")):
                continue
            all_images.update(extract_images_from_file(str(f)))

    cosign_path = find_cosign()
    if not cosign_path:
        return {
            "version": VERSION,
            "cosign_installed": False,
            "images_found": len(all_images),
            "results": [{"image": img, "verified": False, "details": "cosign 未安装"} for img in all_images],
            "summary": {"total": len(all_images), "verified": 0, "unverified": len(all_images), "errors": len(all_images)},
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }

    results = [verify_image(img, key, keyless) for img in all_images]
    verified = sum(1 for r in results if r["verified"])
    unverified = len(results) - verified

    return {
        "version": VERSION,
        "cosign_installed": True,
        "images_found": len(all_images),
        "results": results,
        "summary": {"total": len(results), "verified": verified, "unverified": unverified, "errors": 0},
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


def main():
    parser = argparse.ArgumentParser(description=f"cosign 镜像签名验证 v{VERSION}")
    parser.add_argument("--image", default="", help="单个镜像引用（与 --scan-dir 二选一）")
    parser.add_argument("--scan-dir", default="", help="扫描目录提取所有镜像")
    parser.add_argument("--key", default="", help="公钥路径（key-based 模式）")
    parser.add_argument("--keyless", action="store_true", default=True, help="keyless 模式（Sigstore，默认开启）")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    args = parser.parse_args()

    if args.image:
        result = verify_image(args.image, args.key, args.keyless)
        if args.format == "json":
            print(json.dumps(result, ensure_ascii=False, indent=2))  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
        else:
            icon = "✅" if result["verified"] else "❌"
            print(f"{icon} {result['image']}: {'已验证' if result['verified'] else '未验证'} ({result['mode']})")  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
            print(f"   {result['details'][:200]}")  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
        return 0 if result["verified"] else 2

    scan_path = args.scan_dir or "."
    report = scan_directory(scan_path, args.key, args.keyless)

    if args.format == "json":
        print(json.dumps(report, ensure_ascii=False, indent=2))  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
    else:
        s = report["summary"]
        print(f"\ncosign 镜像签名验证报告")  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
        print(f"  发现镜像: {s['total']}")  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
        print(f"  已验证: {s['verified']} / 未验证: {s['unverified']}")  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
        for r in report["results"]:
            icon = "✅" if r["verified"] else "❌"
            print(f"  {icon} {r['image']}: {r['details'][:100]}")  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
    return 2 if report["summary"]["unverified"] > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
