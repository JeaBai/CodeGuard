#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ef_registry.py — 工具注册表：通用能力与项目专项工具的**统一调用入口**

## 为什么要注册表

一个 Skill 会同时面对两类工具：

  · **通用能力**（可移植）：编译烧录、串口采集、数据分析、流程审计 —— 应随 Skill 分发，
    换项目即用，不应含任何项目特定硬编码。
  · **项目专项工具**（不可移植）：针对特定机型/板卡/试验场景写的一次性脚本 ——
    它们**不应塞进 Skill**（会污染通用性、抬高维护与 token 成本），
    但也不该放任散落（会重复造轮子、口径分裂）。

注册表解决这个矛盾：**项目专项工具留在工程内单独管理，但登记到注册表，通过统一入口调用。**

## 三层数据来源（后者覆盖前者）

  1. `BUILTIN`          —— Skill 自带通用工具（随版本发布）
  2. **自动扫描**        —— 扫描工程内脚本，判定可移植性并自动登记
  3. `.ef-registry.json` —— 项目级策展覆盖（可改名、加说明、标记废弃、排除误报）

## 可移植性判定（关键）

不做"猜"，而是**在源码里找证据**：硬编码盘符路径、COM 端口、芯片型号、
工程目录名等。命中即判为不可移植，并回传**具体原因**（可审计，不是黑箱标签）。

## 安全分级

  read    —— 只读（分析、验证、体检）
  write   —— 会改文件或构建产物（编译、烧录、采集落盘）
  actuate —— 会驱动执行机构（电机、舵机、SBUS 注入）—— **调用前必须确认安全措施**

用法：
    python ef_registry.py list                    # 列出全部工具
    python ef_registry.py list --type skill       # 只看通用能力
    python ef_registry.py list --type project     # 只看项目专项
    python ef_registry.py show ef.build
    python ef_registry.py scan                    # 重新扫描并写入 .ef-registry.json
    python ef_registry.py verify                  # 校验注册项路径是否仍存在
    python ef_registry.py run proj.sim.analyze_tilt_sign -- --help
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

REGISTRY_FILE = ".ef-registry.json"
SCAN_EXTS = {".py", ".bat", ".cmd", ".ps1", ".sh"}

# --------------------------------------------------------------------------
# 1. Skill 自带通用工具（随版本发布，必须保持可移植）
# --------------------------------------------------------------------------
BUILTIN = [
    {"id": "ef.scan", "type": "skill", "path": "scripts/ef_scan.py", "safety": "read",
     "summary": "流程审计主入口（交付物/需求追溯/版本绑定/变更/发布/自动化）",
     "entry": "python scripts/ef_scan.py --path <project>", "tags": ["flow", "audit"]},
    {"id": "ef.build", "type": "skill", "path": "scripts/ef_build.py", "safety": "write",
     "summary": "Keil 编译/烧录（工程自动发现、Target 解析、版本头注入、日志解析）",
     "entry": "python scripts/ef_build.py --path <project> --action build",
     "tags": ["build", "keil"]},
    {"id": "ef.dev", "type": "skill", "path": "scripts/ef_dev.py", "safety": "read",
     "summary": "工作台统一入口（build/flash/ports/watch/capture/analyze/inventory/registry）",
     "entry": "python scripts/ef_dev.py <subcommand>", "tags": ["workbench", "entry"]},
    {"id": "ef.serial", "type": "skill", "path": "scripts/ef_serial.py", "safety": "write",
     "summary": "串口枚举/探测/只读监听/CSV 采集（元数据 + 断线重连）；send 需 --yes",
     "entry": "python scripts/ef_serial.py ports", "tags": ["serial"]},
    {"id": "ef.analyze", "type": "skill", "path": "scripts/ef_analyze.py", "safety": "read",
     "summary": "遥测分析（统计/分箱/FFT/异常段/PNG），自实现无第三方依赖",
     "entry": "python scripts/ef_analyze.py <csv>", "tags": ["analysis"]},
    {"id": "ef.registry", "type": "skill", "path": "scripts/ef_registry.py", "safety": "read",
     "summary": "工具注册表（本注册表自身）",
     "entry": "python scripts/ef_registry.py list", "tags": ["registry"]},
]

# --------------------------------------------------------------------------
# 2. 可移植性证据检测
# --------------------------------------------------------------------------
# 硬编码盘符路径（绝对路径几乎必然不可移植）
RE_ABS_PATH = re.compile(r'["\']\s*[A-Za-z]:[\\/]')
# 硬编码 COM 端口
RE_COMPORT = re.compile(r'\bCOM\d+\b')
# 芯片/模组型号
RE_MCU = re.compile(r'\b(STM32[A-Z]?\d{3}[A-Z0-9]*|ESP32[A-Z0-9\-]*|nRF\d+[A-Z0-9]*|'
                    r'ATmega\d+|RP2040|GD32[A-Z0-9]+|MM32[A-Z0-9]+)\b')
# 板卡版本
RE_BOARDREV = re.compile(r'\bRev\s*[A-Z]\b|\brev[-_]?\d+\.\d+\b', re.IGNORECASE)
# 常见工程目录词（**启发式清单**，非本项目专有值）：用于识别脚本里硬编码的工程目录名。
# 任意清单都是不完备的，这里取中文嵌入式工程里最常见的一组；项目可按需扩充。
PROJECT_DIR_WORDS = ["固件源码", "仿真测试", "测试数据", "覆盖率检测报告", "试飞", "装机"]

# 安全分级关键词
SAFETY_ACTUATE = ["motor", "drive", "sbus_sim", "rc_cmd", "bench", "sender",
                  "stress", "fuzz", "chaos", "tilt_test", "解锁", "台架"]
SAFETY_WRITE = ["build", "flash", "capture", "record", "logger", "download",
                "烧录", "编译"]
SAFETY_READ = ["analyze", "verify", "diag", "check", "health", "visual", "report",
               "体检", "诊断", "分析", "可视化"]

# Skill 通用能力对项目专项的"可替代"映射
SUPERSEDE_MAP = [
    (SAFETY_ACTUATE, None),                       # 激励类：无通用实现，必须留在工程内
    (["build", "flash", "keil"], "ef.build"),
    (["capture", "record", "logger", "serial", "uart"], "ef.serial"),
    (["analyze", "fft", "diag", "verify", "check"], "ef.analyze"),
]


def assess_portability(path: Path, root: Path) -> tuple[bool, list[str]]:
    """在源码中找"不可移植"的证据。返回 (是否可移植, 原因列表)。"""
    reasons = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")[:200000]
    except Exception:
        return True, []

    if RE_ABS_PATH.search(text):
        reasons.append("硬编码绝对路径（含盘符）")
    comports = sorted(set(RE_COMPORT.findall(text)))
    if comports:
        reasons.append("硬编码串口 " + "/".join(comports[:4]))
    mcus = sorted(set(RE_MCU.findall(text)))
    if mcus:
        reasons.append("硬编码芯片型号 " + "/".join(mcus[:3]))
    if RE_BOARDREV.search(text):
        reasons.append("硬编码板卡版本号")
    for w in PROJECT_DIR_WORDS:
        if w in text:
            reasons.append(f"硬编码工程目录「{w}」")
            break
    # 工程根目录名出现在脚本里（说明写死了本项目）
    rn = root.name
    if len(rn) >= 3 and rn in text:
        reasons.append(f"硬编码工程名「{rn}」")
    # 同目录的兄弟脚本被硬编码引用
    return (len(reasons) == 0), reasons


def classify_safety(name: str, doc: str) -> str:
    """判定安全等级。

    关键规则：**分析类脚本即使提到 motor/舵机，也只是消费已采集数据**，
    不应被误标为"会驱动执行机构"——错标会稀释真实的安全告警。
    因此 `analyze*` / `analysis*` 前缀优先判为只读。
    """
    low = name.lower()
    if low.startswith(("analyze", "analysis", "分析")):
        return "read"
    hay = f"{name} {doc}".lower()
    if any(k in hay for k in SAFETY_ACTUATE):
        return "actuate"
    if any(k in hay for k in SAFETY_WRITE):
        return "write"
    if any(k in hay for k in SAFETY_READ):
        return "read"
    return "read"


def resolve_path(root: Path, tool: dict) -> Path:
    """按工具类型解析真实路径。

    ⚠️ 通用能力的 path 是**相对 Skill 目录**的，项目专项是**相对项目根**的。
    若都用 root 解析，`verify` 会把 Skill 自带工具全部误报为"路径缺失"。
    """
    if tool.get("type") == "skill":
        return (SCRIPT_DIR.parent / tool["path"]).resolve()
    return (root / tool["path"]).resolve()


def superseded_by(name: str, doc: str) -> str | None:
    hay = f"{name} {doc}".lower()
    if any(k in hay for k in SAFETY_ACTUATE):
        return None                     # 激励类无通用替代
    for kws, target in SUPERSEDE_MAP[1:]:
        if any(k in hay for k in kws):
            return target
    return None


def _first_docline(path: Path) -> str:
    try:
        import ast
        mod = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        doc = ast.get_docstring(mod)
        return (doc or "").strip().splitlines()[0][:78] if doc else ""
    except Exception:
        return ""


def _tool_id(rel: str) -> str:
    """由相对路径生成稳定 id：proj.<去扩展名>.<去特殊字符>。"""
    p = Path(rel)
    stem = str(p.with_suffix("")).replace("\\", "/")
    safe = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", ".", stem).strip(".").lower()
    return "proj." + safe


# --------------------------------------------------------------------------
# 3. 扫描与注册
# --------------------------------------------------------------------------
def scan_project(root: Path, skip_skill_scripts: bool = True) -> list[dict]:
    """扫描工程内脚本，判定可移植性并生成注册项。"""
    try:
        import ef_common as C
    except Exception:
        C = None

    tools = []
    files = []
    if C is not None:
        files = [p for p in C.iter_project_files(root, max_files=8000)
                 if p.suffix.lower() in SCAN_EXTS]
    else:
        files = [p for p in root.rglob("*") if p.suffix.lower() in SCAN_EXTS]

    for p in sorted(files):
        try:
            rel = str(p.relative_to(root)).replace("\\", "/")
        except ValueError:
            continue
        if skip_skill_scripts and "/skills/" in f"/{rel}" or rel.startswith(".workbuddy"):
            continue
        if p.name.startswith("ef_"):
            continue
        doc = _first_docline(p) if p.suffix == ".py" else ""
        portable, reasons = assess_portability(p, root)
        tools.append({
            "id": _tool_id(rel),
            "type": "project",
            "portable": portable,
            "portability_reasons": reasons,
            "path": rel,
            "summary": doc,
            "entry": f"python {rel}",
            "safety": classify_safety(p.name, doc),
            "superseded_by": superseded_by(p.name, doc),
            "tags": sorted({Path(rel).suffix.lstrip(".")} |
                           ({reasons[0].split()[0]} if reasons else set())),
        })
    return tools


def load_registry(root: Path):
    """合并三层来源：BUILTIN ← 自动扫描 ← .ef-registry.json 覆盖。"""
    builtin = [dict(t, portable=True, portability_reasons=[]) for t in BUILTIN]
    scanned = scan_project(root)

    reg_path = root / REGISTRY_FILE
    overrides = {}
    if reg_path.is_file():
        try:
            data = json.loads(reg_path.read_text(encoding="utf-8"))
            for item in data.get("overrides", []):
                if isinstance(item, dict) and item.get("id"):
                    overrides[item["id"]] = item
            excluded = set(data.get("exclude", []))
        except Exception:
            excluded = set()
    else:
        excluded = set()

    merged = {}
    for t in builtin + scanned:
        if t["id"] in excluded:
            continue
        merged[t["id"]] = t
    for tid, ov in overrides.items():
        if tid in merged:
            merged[tid].update(ov)
        else:
            merged[tid] = dict(ov, type=ov.get("type", "project"))
    return sorted(merged.values(), key=lambda t: (t["type"] != "skill", t["id"]))


def write_registry(root: Path) -> Path:
    """把扫描结果落盘为 .ef-registry.json（保留已有覆盖项）。"""
    reg_path = root / REGISTRY_FILE
    existing = {"overrides": [], "exclude": []}
    if reg_path.is_file():
        try:
            existing = json.loads(reg_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    payload = {
        "_comment": "由 ef_registry.py scan 生成：项目专项工具清单。"
                    "overrides 可人工策展（改名/加说明/纠正判定），exclude 可排除误报。",
        "generated_by": "embedded-flow-guardian/ef_registry.py",
        "project_tools": [
            {k: t[k] for k in ("id", "path", "portable", "portability_reasons",
                               "summary", "safety", "superseded_by")}
            for t in scan_project(root)
        ],
        "overrides": existing.get("overrides", []),
        "exclude": existing.get("exclude", []),
    }
    reg_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    return reg_path


# --------------------------------------------------------------------------
# 4. CLI
# --------------------------------------------------------------------------
ICON = {"read": "R", "write": "W", "actuate": "!!"}


def cmd_list(root: Path, type_filter=None, tag=None, only_nonportable=False,
             as_json=False):
    tools = load_registry(root)
    if type_filter:
        tools = [t for t in tools if t["type"] == type_filter]
    if tag:
        tools = [t for t in tools if tag in (t.get("tags") or [])]
    if only_nonportable:
        tools = [t for t in tools if not t.get("portable", True)]

    if as_json:
        print(json.dumps(tools, ensure_ascii=False, indent=2))
        return 0

    if not tools:
        print("（无匹配工具）")
        return 0
    skill = [t for t in tools if t["type"] == "skill"]
    proj = [t for t in tools if t["type"] != "skill"]
    print(f"工具注册表 · 通用 {len(skill)} 个 / 项目专项 {len(proj)} 个")
    print(f"（安全分级：R=只读  W=会写文件/产物  !! =驱动执行机构）\n")
    if skill:
        print("── 通用能力（可移植，随 Skill 分发）──")
        for t in skill:
            print(f"  [{ICON.get(t['safety'], '?'):>2}] {t['id']:<18} {t['summary'][:56]}")
    if proj:
        print("\n── 项目专项（不可移植，留在工程内，经注册表调用）──")
        for t in proj:
            flag = "" if t.get("portable", True) else "  ⚠不可移植"
            sup = f"  → 可用 {t['superseded_by']} 替代" if t.get("superseded_by") else ""
            print(f"  [{ICON.get(t['safety'], '?'):>2}] {t['id']:<34} {t['summary'][:46]}{flag}")
            if t.get("portability_reasons"):
                print(f"       原因: {'；'.join(t['portability_reasons'][:2])}")
            if sup:
                print(f"      {sup.strip()}")
    print("\n提示：`registry show <id>` 查看详情；`registry run <id>` 统一调用。")
    return 0


def cmd_show(root: Path, tool_id: str):
    tools = {t["id"]: t for t in load_registry(root)}
    t = tools.get(tool_id)
    if not t:
        near = [k for k in tools if tool_id in k][:5]
        print(f"未找到 {tool_id}" + (f"，相近: {', '.join(near)}" if near else ""))
        return 1
    print(json.dumps(t, ensure_ascii=False, indent=2))
    rp = resolve_path(root, t)
    print(f"\n实际路径: {rp}")
    print(f"存在: {'✅' if rp.exists() else '❌ 路径不存在'}")
    print(f"调用: {t.get('entry')}")
    if t.get("safety") == "actuate":
        print("\n⚠️ 该工具会驱动执行机构（电机/舵机/SBUS）。调用前必须确认：")
        print("   · 桨叶已取下或已采取等效安全隔离")
        print("   · 机体固定、无人靠近")
        print("   · 已明确失败时的中止手段")
    return 0


def cmd_run(root: Path, tool_id: str, extra: list[str]):
    """统一调用：按注册项执行，并透传附加参数。"""
    import subprocess
    tools = {t["id"]: t for t in load_registry(root)}
    t = tools.get(tool_id)
    if not t:
        print(f"未找到 {tool_id}。用 `registry list` 查看可用项。")
        return 2
    path = resolve_path(root, t)
    if not path.exists():
        print(f"路径不存在：{path}")
        return 2
    if t["type"] == "project" and not t.get("portable", True):
        print(f"[registry] 提示：{tool_id} 为项目专项工具（不可移植）")
        for r in t.get("portability_reasons") or []:
            print(f"           · {r}")
    if t.get("safety") == "actuate":
        print("[registry] ⚠️ 该工具会驱动执行机构，请确认已采取安全隔离后继续。")

    if path.suffix == ".py":
        cmd = [sys.executable, str(path)] + list(extra)
    elif path.suffix in (".bat", ".cmd"):
        cmd = ["cmd", "/c", str(path)] + list(extra)
    elif path.suffix == ".ps1":
        cmd = ["powershell", "-NoProfile", "-File", str(path)] + list(extra)
    else:
        cmd = [str(path)] + list(extra)

    print(f"[registry] 执行：{' '.join(cmd)}")
    try:
        r = subprocess.run(cmd, cwd=str(root))
    except OSError as exc:
        print(f"[registry] 启动失败：{exc}")
        return 2
    return r.returncode


def cmd_verify(root: Path):
    tools = load_registry(root)
    missing = [t for t in tools if not resolve_path(root, t).exists()]
    print(f"校验 {len(tools)} 个注册项（通用能力相对 Skill 目录、项目专项相对项目根）：")
    if not missing:
        print("  ✅ 全部路径存在")
        return 0
    print(f"  ❌ {len(missing)} 个路径缺失（建议在 .ef-registry.json 的 exclude 中移除）：")
    for t in missing:
        print(f"     {t['id']}  →  {t['path']}")
    return 1


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(
        prog="ef_registry",
        description="工具注册表 —— 通用能力与项目专项工具的统一调用入口")
    ap.add_argument("--path", default=".", help="项目根目录")
    sub = ap.add_subparsers(dest="cmd", required=True)

    l = sub.add_parser("list", help="列出工具")
    l.add_argument("--type", dest="type_filter", choices=["skill", "project"])
    l.add_argument("--tag", default=None)
    l.add_argument("--nonportable", action="store_true", help="只看不可移植项")
    l.add_argument("--json", action="store_true")

    s = sub.add_parser("show", help="查看某项详情")
    s.add_argument("tool_id")

    r = sub.add_parser("run", help="统一调用")
    r.add_argument("tool_id")
    r.add_argument("extra", nargs=argparse.REMAINDER,
                   help="附加参数（建议前面加 -- 分隔）")

    sub.add_parser("scan", help="重新扫描并写入 .ef-registry.json")
    sub.add_parser("verify", help="校验注册项路径")

    args = ap.parse_args(argv)
    root = Path(args.path).resolve()

    if args.cmd == "list":
        return cmd_list(root, args.type_filter, args.tag, args.nonportable, args.json)
    if args.cmd == "show":
        return cmd_show(root, args.tool_id)
    if args.cmd == "run":
        extra = [x for x in args.extra if x != "--"]
        return cmd_run(root, args.tool_id, extra)
    if args.cmd == "scan":
        p = write_registry(root)
        n = len(json.loads(p.read_text(encoding="utf-8"))["project_tools"])
        print(f"已写入 {p}（项目专项工具 {n} 个）")
        print("提示：可编辑其中的 overrides / exclude 进行人工策展")
        return 0
    if args.cmd == "verify":
        return cmd_verify(root)
    return 2


if __name__ == "__main__":
    sys.exit(main())
