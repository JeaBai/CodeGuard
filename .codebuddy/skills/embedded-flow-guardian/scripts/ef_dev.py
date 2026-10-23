#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ef_dev.py — embedded-flow-guardian 的「日常工作台」统一入口

把三类高频动作收进一个命令：
  1. 构建与烧录   build / rebuild / flash / debug / discover
  2. 串口与数据   ports / watch / capture / send
  3. 数据分析     analyze
  4. 工具盘点     inventory —— 扫描工程里已有的脚本并归类

为什么需要 inventory：工程里往往已经有几十个业务脚本（本项目就有 36 个），
重复造轮子既是浪费也会造成口径分裂。inventory 的作用是**先把家底盘清楚**，
让后续判断建立在「已有能力 vs Skill 通用能力」的对照之上。

用法示例：
    python ef_dev.py ports
    python ef_dev.py build --inject-version version.h
    python ef_dev.py flash
    python ef_dev.py capture --out data/run1.csv --seconds 60 --fields 27 --firmware v0.3.0
    python ef_dev.py analyze data/run1.csv --bin sbus3
    python ef_dev.py inventory
"""
from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import ef_build      # noqa: E402
import ef_serial     # noqa: E402
import ef_analyze    # noqa: E402
import ef_registry   # noqa: E402

# 脚本用途分类规则：(类别, 命中关键词)
# 注意：「诊断」只挂在「分析」下；串口侧用「串口」而非「诊断」，
# 否则 analyze_*_诊断 类脚本会被误归到串口组。
CATEGORIES = [
    ("构建/烧录", ["keil", "build", "flash", "uv4", "make", "cmake"]),
    ("串口/采集", ["serial", "uart", "capture", "record", "logger", "port",
                   "monitor", "watch", "串口"]),
    ("分析", ["analyze", "analysis", "fft", "diag", "体检", "诊断", "verify",
              "check"]),
    ("激励/驱动", ["motor", "rc_cmd", "sbus_sim", "drive", "tilt_test", "stress",
                   "fuzz", "chaos", "bench", "sender"]),
    ("可视化", ["visual", "可视化", "plot", "report", "dashboard", "html"]),
]

SKILL_EQUIVALENT = {
    "构建/烧录": "ef_build.py（通用化封装，含工程自动发现 / 版本注入 / 日志解析）",
    "串口/采集": "ef_serial.py（零依赖枚举+监听+采集，带旁车元数据与断线重连）",
    "分析": "ef_analyze.py（自实现 FFT + PNG，统计/分箱/异常段）",
    "激励/驱动": "无通用实现 —— 属业务专项，保留在工程内（且涉及安全，不宜通用化）",
    "可视化": "ef_analyze.py 的 PNG 输出（基础图）；复杂报告仍由工程脚本负责",
}


def _first_docline(path: Path) -> str:
    try:
        mod = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        doc = ast.get_docstring(mod)
        return (doc or "").strip().splitlines()[0][:64] if doc else ""
    except Exception:
        return ""


def _classify(name: str, doc: str):
    """归类脚本用途。

    文件名优先于 docstring：文件名是作者给出的强信号，
    docstring 常夹带其他类别的词（如分析脚本描述里出现「采集」）。
    """
    low_name = name.lower()
    for cat, kws in CATEGORIES:
        if any(k in low_name for k in kws):
            return cat
    low_doc = (doc or "").lower()
    for cat, kws in CATEGORIES:
        if any(k in low_doc for k in kws):
            return cat
    return "其他"


def do_inventory(root: Path, as_json: bool = False) -> int:
    """盘点工程内已有脚本，按用途归类，并标注 Skill 是否已提供通用实现。"""
    try:
        import ef_common as C
    except Exception:
        C = None

    scripts = []
    exts = {".py", ".bat", ".cmd", ".ps1", ".sh"}
    for p in (C.iter_project_files(root, max_files=6000) if C else root.rglob("*")):
        if p.suffix.lower() not in exts:
            continue
        if p.name.startswith("ef_"):        # 排除本 Skill 自身
            continue
        scripts.append(p)

    groups: dict[str, list] = {}
    for p in sorted(scripts):
        name = p.name
        doc = _first_docline(p) if p.suffix == ".py" else ""
        cat = _classify(name, doc)
        try:
            rel = str(p.relative_to(root)).replace("\\", "/")
        except ValueError:
            rel = str(p)
        groups.setdefault(cat, []).append({"path": rel, "desc": doc})

    if as_json:
        import json
        print(json.dumps({"total": len(scripts), "groups": groups,
                          "skill_equivalent": SKILL_EQUIVALENT},
                         ensure_ascii=False, indent=2))
        return 0

    print("=" * 68)
    print("  ef_dev inventory — 工程内已有工具盘点")
    print("=" * 68)
    print(f"  共发现 {len(scripts)} 个脚本（已排除 Skill 自身 ef_* ）")
    print()
    for cat, _kws in CATEGORIES + [("其他", [])]:
        items = groups.get(cat)
        if not items:
            continue
        print(f"  ── {cat}（{len(items)} 个）──")
        for it in items[:14]:
            desc = f"  {it['desc']}" if it["desc"] else ""
            print(f"    {it['path']}{desc}")
        if len(items) > 14:
            print(f"    … 另有 {len(items) - 14} 个")
        eq = SKILL_EQUIVALENT.get(cat)
        if eq:
            print(f"    ↳ Skill 对应能力: {eq}")
        print()
    print("  说明：Skill 只提供「通用原子能力」；业务专项脚本保留在工程内，")
    print("        两者互补而非替换。改动既有脚本前请先确认是否已覆盖该需求。")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="ef_dev",
        description="embedded-flow-guardian 日常工作台（构建/串口/分析/盘点）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("用法示例：")[-1])
    sub = ap.add_subparsers(dest="cmd", required=True)

    # 构建
    for name in ("build", "rebuild", "flash", "debug"):
        b = sub.add_parser(name, help=f"Keil {name}")
        b.add_argument("--path", default=".")
        b.add_argument("--project", default=None)
        b.add_argument("--target", default=None)
        b.add_argument("--log", default=None)
        b.add_argument("--uv4", default=None)
    # 版本注入只对编译类动作有意义
    for nm in ("build", "rebuild"):
        sub.choices[nm].add_argument("--inject-version", nargs="?", const="version.h",
                                     default=None, metavar="OUTFILE",
                                     help="构建前生成版本头（git describe 派生）")
        sub.choices[nm].add_argument("--with-date", action="store_true",
                                     help="版本头写入构建日期（会破坏可复现构建）")

    d = sub.add_parser("discover", help="列出工程与 Target")
    d.add_argument("--path", default=".")

    # 串口
    p = sub.add_parser("ports", help="枚举串口")
    p.add_argument("--json", action="store_true")
    p.add_argument("--path", default=".", help="项目根（读取 preferredPorts）")

    for name in ("watch", "capture"):
        s = sub.add_parser(name, help="只读监听 / 采集")
        s.add_argument("--port", default=None)
        s.add_argument("--baud", type=int, default=921600)
        s.add_argument("--parity", default="N", choices=["N", "E", "O"])
        s.add_argument("--seconds", type=float, default=6.0)
        s.add_argument("--fields", type=int, default=None)
        s.add_argument("--path", default=".", help="项目根（读取配置）")
    sub.choices["watch"].add_argument("--raw", action="store_true")
    sub.choices["capture"].add_argument("--out", required=True)
    sub.choices["capture"].add_argument("--max-lines", type=int, default=None)
    sub.choices["capture"].add_argument("--reconnect", type=int, default=3)
    sub.choices["capture"].add_argument("--firmware", default=None)

    sd = sub.add_parser("send", help="发送一条命令（需 --yes）")
    sd.add_argument("--port", required=True)
    sd.add_argument("--baud", type=int, default=921600)
    sd.add_argument("--parity", default="N", choices=["N", "E", "O"])
    sd.add_argument("--data", required=True)
    sd.add_argument("--yes", action="store_true")

    # 分析
    a = sub.add_parser("analyze", help="分析采集到的 CSV")
    a.add_argument("csv")
    a.add_argument("--time-key", default=None)
    a.add_argument("--fft", nargs="*", default=None)
    a.add_argument("--bin", dest="bin_key", default=None)
    a.add_argument("--fs", type=float, default=None,
                   help="显式指定采样率（时间戳量化严重时使用）")
    a.add_argument("--outdir", default=None)
    a.add_argument("--json-out", default=None)
    a.add_argument("--no-png", action="store_true")

    # 盘点
    v = sub.add_parser("inventory", help="盘点工程内已有脚本")
    v.add_argument("--path", default=".")
    v.add_argument("--json", action="store_true")

    # 注册表（统一调用入口）
    rg = sub.add_parser("registry", help="工具注册表：list/show/run/scan/verify")
    rg.add_argument("--path", default=".", help="项目根（需写在子命令之前）")
    rg.add_argument("rest", nargs=argparse.REMAINDER,
                    help="传给注册表的参数，如 `list --nonportable`")

    args = ap.parse_args(argv)

    if args.cmd == "registry":
        # 允许 --path 出现在子命令前后任意位置：提取后统一前置（否则会被
        # argparse 的 REMAINDER 吞掉，导致 "unrecognized arguments"）
        rest = [x for x in args.rest if x != "--"]
        path, out, i = args.path, [], 0
        while i < len(rest):
            tok = rest[i]
            if tok == "--path" and i + 1 < len(rest):
                path = rest[i + 1]
                i += 2
                continue
            if tok.startswith("--path="):
                path = tok.split("=", 1)[1]
                i += 1
                continue
            out.append(tok)
            i += 1
        return ef_registry.main(["--path", path] + out)

    if args.cmd in ("build", "rebuild", "flash", "debug"):
        return ef_build.build(
            Path(args.path).resolve(), action=args.cmd, project=args.project,
            target=args.target, log=args.log, uv4=args.uv4,
            inject_version=getattr(args, "inject_version", None),
            with_date=getattr(args, "with_date", False))
    if args.cmd == "discover":
        return ef_build.main(["--path", args.path, "--discover"])
    if args.cmd == "ports":
        return ef_serial.do_ports(args.json, args.path)
    if args.cmd == "inventory":
        return do_inventory(Path(args.path).resolve(), args.json)

    if args.cmd in ("watch", "capture", "send", "analyze"):
        if args.cmd == "analyze":
            # analyze 的首个参数是位置参数（CSV 路径），需单独处理
            argv2 = [args.csv]
            if args.time_key:
                argv2 += ["--time-key", args.time_key]
            if args.fft:
                argv2 += ["--fft"] + [str(x) for x in args.fft]
            if args.bin_key:
                argv2 += ["--bin", args.bin_key]
            if args.fs:
                argv2 += ["--fs", str(args.fs)]
            if args.outdir:
                argv2 += ["--outdir", args.outdir]
            if args.json_out:
                argv2 += ["--json-out", args.json_out]
            if args.no_png:
                argv2.append("--no-png")
            return ef_analyze.main(argv2)

        argv2 = [args.cmd]
        for k, v_ in vars(args).items():
            if k == "cmd" or v_ is None or v_ is False:
                continue
            flag = "--" + k.replace("_", "-")
            if isinstance(v_, bool):
                argv2.append(flag)
            elif isinstance(v_, list):
                argv2.append(flag)
                argv2 += [str(x) for x in v_]
            else:
                argv2 += [flag, str(v_)]
        return ef_serial.main(argv2)
    return 2


if __name__ == "__main__":
    sys.exit(main())
