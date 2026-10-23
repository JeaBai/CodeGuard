#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ef_build.py — Keil MDK 自动编译与烧录

把「命令行调用 UV4 编译/烧录」这件事做成可复用原子能力，供 ef_dev.py 调度，
也可独立使用。通用化了工程里原有的 `仿真测试/keil_build.py`，并补上三项关键能力：

1. **工程自动发现**：递归查找 *.uvprojx（排除 vendor / 参考代码树），
   并从工程 XML 中解析 TargetName，不必手填。
2. **构建期版本注入**：生成 version.h（默认由 `git describe --tags --always --dirty` 派生），
   直击「版本号写死在 version.h 不可追溯」这一高频问题。
3. **日志解析**：UV4 把详细日志写进 -o 文件、stdout 常为空，需按文件解析错误/警告。

必须保留的三条实战经验（踩过坑，勿改）：
  a. **烧录不能加 -j0**：隐藏 GUI 会取消下载对话框，报 "Target DLL has been cancelled"。
  b. **必须把 cwd 设为工程目录**：否则 -o 日志与 Flash "Load" 的相对路径会落到 UV4 安装目录，
     最终报 "error 56: cannot open file"。
  c. **UV4 的 stdout 通常为空**，日志只在 -o 文件里。
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

# UV4.exe 候选路径（按优先级）
UV4_CANDIDATES = [
    r"D:\Keil_v5\UV4\UV4.exe",
    r"C:\Keil_v5\UV4\UV4.exe",
    r"D:\Keil\UV4\UV4.exe",
    r"C:\Keil\UV4\UV4.exe",
    r"D:\MDK\UV4\UV4.exe",
    r"C:\MDK\UV4\UV4.exe",
]

ACTIONS = {"build": "-b", "rebuild": "-r", "flash": "-f", "debug": "-f"}


# --------------------------------------------------------------------------
# 发现
# --------------------------------------------------------------------------
def find_uv4(explicit: str | None = None):
    """定位 UV4.exe。顺序：显式指定 > 环境变量 KEIL_UV4 > 常见安装路径。"""
    if explicit and Path(explicit).is_file():
        return explicit
    env = os.environ.get("KEIL_UV4")
    if env and Path(env).is_file():
        return env
    for c in UV4_CANDIDATES:
        if Path(c).is_file():
            return c
    return None


def find_project(root: Path, explicit: str | None = None):
    """递归查找 .uvprojx 工程文件。

    排除 vendor / 参考代码树（避免误选到第三方工程）。若命中多个，
    优先路径更短者（通常离工程根更近），并返回全部候选供提示。
    """
    if explicit:
        p = Path(explicit)
        return (p if p.is_file() else None), []
    try:
        import ef_common as C
        excluded = C.is_vendor
    except Exception:
        excluded = lambda _p: False  # noqa: E731

    hits = []
    for p in root.rglob("*.uvprojx"):
        try:
            rel = p.relative_to(root)
        except ValueError:
            continue
        if excluded(rel):
            continue
        hits.append(p)
    if not hits:
        return None, []
    hits.sort(key=lambda p: (len(p.relative_to(root).parts), str(p)))
    return hits[0], hits


def read_target_names(uvprojx: Path):
    """从 Keil 工程 XML 解析 TargetName 列表。"""
    try:
        tree = ET.parse(str(uvprojx))
    except Exception:
        return []
    names = []
    for el in tree.iter():
        if el.tag.endswith("TargetName") and (el.text or "").strip():
            names.append(el.text.strip())
    return names


# --------------------------------------------------------------------------
# 版本注入
# --------------------------------------------------------------------------
def git_describe(root: Path):
    """取得构建期版本串：git describe --tags --always --dirty。

    返回 (version_str, is_dirty)；无 git 或无 tag 时优雅降级。
    """
    def _git(args):
        try:
            r = subprocess.run(["git", "-C", str(root)] + args,
                               capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=15)
            return r.stdout.strip() if r.returncode == 0 else ""
        except Exception:
            return ""

    desc = _git(["describe", "--tags", "--always", "--dirty"])
    if not desc:
        return "", False
    return desc, desc.endswith("-dirty")


def write_version_header(root: Path, out: str, name: str = "version.h",
                         include_date: bool = False) -> dict:
    """生成 version.h。

    ⚠️ 默认**不写入构建日期**：`__DATE__`/`__TIME__` 会破坏可复现构建
    （同一提交两次构建产出不同二进制）。需要时显式 `--with-date` 打开。

    Returns:
        dict: {path, version, dirty, hash, wrote}
    """
    ver, dirty = git_describe(root)
    if not ver:
        ver, dirty = "unknown", False
    m = re.search(r"-(g?[0-9a-f]{6,})(-dirty)?$", ver)
    ghash = m.group(1) if m else ""

    lines = [
        "/* 由 embedded-flow-guardian/ef_build.py 在构建期自动生成 —— 请勿手工编辑 */",
        "#ifndef EF_VERSION_H",
        "#define EF_VERSION_H",
        "",
        f'#define FW_VERSION_STR   "{ver}"',
        f"#define FW_VERSION_DIRTY {1 if dirty else 0}",
        f'#define FW_GIT_HASH      "{ghash}"',
    ]
    if include_date:
        lines += [
            "",
            "/* 注意：构建日期会破坏可复现构建，仅在明确需要时启用 */",
            f'#define FW_BUILD_DATE    "{time.strftime("%Y-%m-%d %H:%M:%S")}"',
        ]
    lines += ["", "#endif /* EF_VERSION_H */", ""]

    target = Path(out) if os.path.isabs(out) else (root / out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines), encoding="utf-8")
    return {"path": str(target), "version": ver, "dirty": dirty,
            "hash": ghash, "wrote": True}


# --------------------------------------------------------------------------
# 构建 / 烧录
# --------------------------------------------------------------------------
def run_keil(uv4: str, project: Path, target: str | None, action: str,
             log: Path, extra_args=None):
    """执行一次 UV4 调用，返回 (returncode, stdout, log_text)。"""
    flag = ACTIONS.get(action, "-b")
    cmd = [uv4, flag, str(project)]
    if target:
        cmd += ["-t", target]
    # 经验 a：烧录/调试不能加 -j0
    if action in ("build", "rebuild"):
        cmd.insert(2, "-j0")
    cmd += ["-o", str(log)]
    if action == "debug":
        cmd.append("-d")
    if extra_args:
        cmd += list(extra_args)

    # 经验 b：cwd 必须为工程目录
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace",
                           cwd=str(project.parent))
    except OSError as exc:
        return 1, "", f"[错误] 调用 UV4.exe 失败: {exc}"

    text = ""
    # 经验 c：详细日志在 -o 文件里
    if log.is_file():
        try:
            text = log.read_text(encoding="utf-8", errors="replace")
        except Exception:
            text = ""
    return r.returncode, r.stdout or "", text


def parse_log(text: str):
    """从 UV4 日志中提取错误/警告。"""
    errors, warnings = [], []
    for line in text.splitlines():
        low = line.lower()
        if not line.strip():
            continue
        if "error" in low or "错误" in line:
            errors.append(line.strip())
        elif "warning" in low or "警告" in line:
            warnings.append(line.strip())
    # Keil 结尾汇总形如 "0 Error(s), 0 Warning(s)."
    m = re.search(r"(\d+)\s*Error", text)
    n_err = int(m.group(1)) if m else len(errors)
    m = re.search(r"(\d+)\s*Warning", text)
    n_warn = int(m.group(1)) if m else len(warnings)
    return n_err, n_warn, errors, warnings


def build(root: Path, action: str = "build", project: str | None = None,
          target: str | None = None, log: str | None = None,
          inject_version: str | None = None, with_date: bool = False,
          uv4: str | None = None, quiet: bool = False) -> int:
    """执行构建/烧录，返回进程退出码语义（0 成功）。

    退出码：0 成功 / 2 失败（编译错误或环境缺失）
    """
    root = Path(root).resolve()
    proj, all_projects = find_project(root, project)
    if proj is None:
        print("[ef_build] 未找到 .uvprojx 工程文件（已排除 vendor/参考树）")
        print("          可用 --project 显式指定")
        return 2
    if len(all_projects) > 1 and not quiet:
        print(f"[ef_build] 发现 {len(all_projects)} 个工程，已选用最靠近根目录者：")
        for p in all_projects[:6]:
            print(f"           - {p.relative_to(root)}")

    uv4_path = find_uv4(uv4)
    if uv4_path is None:
        print("[ef_build] 未找到 UV4.exe。请确认 Keil MDK 已安装，")
        print("          或用 --uv4 指定路径，或设置环境变量 KEIL_UV4")
        return 2

    # 目标名自动解析
    if not target:
        names = read_target_names(proj)
        target = names[0] if names else None
        if target and not quiet:
            print(f"[ef_build] 自动识别 Target: {target}（共 {len(names)} 个）")

    # 版本注入（在编译之前，确保编译进去）
    ver_info = None
    if inject_version is not None:
        out = inject_version or "version.h"
        ver_info = write_version_header(root, out, include_date=with_date)
        if not quiet:
            print(f"[ef_build] 已生成版本头 {ver_info['path']}")
            print(f"           FW_VERSION_STR = {ver_info['version']}")
            if with_date:
                print("           ⚠️ 已启用构建日期，将破坏可复现构建")

    log_path = Path(log) if log else (proj.parent / f"ef_{action}.log")
    if not os.path.isabs(str(log_path)):
        log_path = (proj.parent / log_path).resolve()

    if not quiet:
        print(f"[ef_build] {action} | 工程 {proj.relative_to(root)} | UV4 {uv4_path}")

    rc, stdout, text = run_keil(uv4_path, proj, target, action, log_path)
    n_err, n_warn, errors, warnings = parse_log(text)

    if not text and not stdout:
        print("[ef_build] 未捕获到日志。检查 UV4 是否被安全软件拦截，或 -o 路径是否可写")

    print(f"[ef_build] 退出码 {rc} | 错误 {n_err} 条 / 警告 {n_warn} 条")
    if errors:
        print("  --- 错误摘要（前 20 条）---")
        for l in errors[:20]:
            print(f"    {l}")
    if warnings and not quiet:
        print("  --- 警告摘要（前 10 条）---")
        for l in warnings[:10]:
            print(f"    {l}")
    print(f"[ef_build] 完整日志: {log_path}")

    # UV4 成功时返回 0；返回 1 表示有警告，>=2 表示有错误
    ok = (rc == 0) and (n_err == 0)
    if ver_info:
        print(f"[ef_build] 版本 {ver_info['version']}"
              + ("  ⚠️ 工作区有未提交改动（-dirty）" if ver_info["dirty"] else ""))
    return 0 if ok else 2


# --------------------------------------------------------------------------
def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="ef_build — Keil MDK 自动编译/烧录")
    ap.add_argument("--path", default=".", help="项目根目录")
    ap.add_argument("--action", choices=list(ACTIONS.keys()), default="build")
    ap.add_argument("--project", default=None, help="显式指定 .uvprojx")
    ap.add_argument("--target", default=None, help="Target 名（默认从工程自动解析）")
    ap.add_argument("--log", default=None, help="日志文件路径")
    ap.add_argument("--uv4", default=None, help="UV4.exe 路径")
    ap.add_argument("--inject-version", nargs="?", const="version.h", default=None,
                    metavar="OUTFILE",
                    help="构建前生成版本头（默认 version.h，由 git describe 派生）")
    ap.add_argument("--with-date", action="store_true",
                    help="版本头中包含构建日期（会破坏可复现构建，慎用）")
    ap.add_argument("--discover", action="store_true", help="只列出发现的工程与 Target")
    args = ap.parse_args(argv)

    root = Path(args.path).resolve()
    if args.discover:
        proj, allp = find_project(root, args.project)
        if not proj:
            print("未找到 .uvprojx")
            return 2
        for p in allp:
            names = read_target_names(p)
            mark = " <- 默认选用" if p == proj else ""
            print(f"{p.relative_to(root)}  Target={names or ['(未解析)']}{mark}")
        print(f"UV4: {find_uv4(args.uv4) or '未找到'}")
        return 0

    return build(root, action=args.action, project=args.project, target=args.target,
                 log=args.log, inject_version=args.inject_version,
                 with_date=args.with_date, uv4=args.uv4)


if __name__ == "__main__":
    sys.exit(main())
