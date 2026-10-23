#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ef_compat.py — 检测器 ③ 硬件-固件版本绑定

回答：能不能回答「这个固件该烧到哪块板」以及「这块板能跑哪些固件」。

设计依据（见 references/lifecycle.md 2.4、references/anti-patterns.md）：
  - 缺少兼容矩阵时，面向 Rev B 准备的 OTA 包可能被错发到 Rev A 设备
  - 每个出厂 BIN/HEX 必须唯一对应一组源码版本，才能做到故障 100% 可回溯
  - 版本号写死在 version.h 是「不可追溯 + 易人为出错」的典型坏味道，
    正解是构建期用 git describe --tags --always --dirty 注入

边界：不解析具体寄存器/引脚正确性（那是 fc-guardian 的 pin_checker 负责），
      只判断「版本绑定关系是否被显式记录」。
"""
from __future__ import annotations

import re
from pathlib import Path

import ef_common as C

# 板卡版本痕迹
BOARD_REV_RE = re.compile(
    r"\b(?:BOARD|PCB|HW|HARDWARE)_(?:REV|VERSION|VER)\b|"
    r"\bRev\s*[A-Z]\b|\brev[-_ ]?\d+(?:\.\d+)?\b|板卡版本|硬件版本|板子版本",
    re.IGNORECASE,
)

# 固件版本定义痕迹
FW_VERSION_DEF_RE = re.compile(
    r"#define\s+(?:FW_|FIRMWARE_|APP_)?VERSION(?:_STR|_STRING|_MAJOR|_MINOR|_PATCH)?\b",
    re.IGNORECASE,
)

# 构建脚本类文件（版本注入通常在这里）
BUILD_SCRIPT_EXTS = {".py", ".sh", ".bat", ".cmd", ".ps1", ".mk"}
BUILD_SCRIPT_NAMES = {"makefile", "cmakelists.txt", "platformio.ini", "build.sh",
                      "build.bat", "keil_build.py"}


def scan_compat(root: Path, collector, profile: C.ProjectProfile, cfg: dict):
    level = cfg.get("defaultLevel", C.DEFAULT_LEVEL)

    # ---- 1) 兼容矩阵是否存在 ----
    matrix, _ev = C.find_deliverable(profile, ["兼容矩阵", "兼容性矩阵", "compat_matrix",
                                               "compat-matrix", "compatibility_matrix",
                                               "版本矩阵", "hw_sw", "板卡版本"])
    if matrix is None:
        # 先看项目里到底有没有「多板卡/多版本」的迹象，避免对小项目误报
        revs = _collect_board_revs(profile)
        if len(revs) >= 2:
            collector.add(
                C.severity_for("missing", level),
                "flow_compat_no_matrix",
                str(root), 0,
                f"检测到 {len(revs)} 个板卡/硬件版本痕迹（{'、'.join(sorted(revs)[:6])}），"
                f"但未发现硬件-固件兼容矩阵",
                "多版本并行而无矩阵时，固件极易烧错板卡。"
                "建议用 assets/templates/compat_matrix.csv 建立 板卡Rev × 固件版本 × 可追溯提交 的对应表",
                confidence=82,
            )
        else:
            collector.add(
                C.severity_for("weak", level),
                "flow_compat_no_matrix",
                str(root), 0,
                "未发现硬件-固件兼容矩阵",
                "即使当前只有单一板卡版本，也建议先建立矩阵骨架——"
                "第一轮硬件改版（Rev B）时它会立刻产生价值",
                confidence=70,
            )

    # ---- 2) 版本号注入方式 ----
    hardcoded, injected = _inspect_version_mechanism(profile)

    if injected:
        collector.add(
            "info", "flow_compat_version_injected",
            profile.rel(injected[0]), 0,
            "版本号采用构建期注入（git describe / SOURCE_DATE_EPOCH 等），机制正确",
            "工程构建带短哈希、Tag 构建给纯净版本号——两者应区分",
            confidence=85,
        )
    elif hardcoded:
        collector.add(
            C.severity_for("weak", level),
            "flow_compat_hardcoded_version",
            profile.rel(hardcoded[0][0]), hardcoded[0][1],
            f"版本号疑似硬编码：{profile.rel(hardcoded[0][0])}:{hardcoded[0][1]}",
            "写死在 version.h 的版本号不可追溯且易人为出错。"
            "改用构建期注入：git describe --tags --always --dirty → 形如 "
            "v1.2.3-8-g6f239e1-dirty，并区分「工程构建」与「Tag 发布构建」",
            confidence=72,
        )
    else:
        collector.add(
            "hint", "flow_compat_no_version",
            str(root), 0,
            "未发现明确的固件版本号定义或注入机制",
            "无法从固件本身判断其版本，现场问题将无法回溯到具体源码提交",
            confidence=60,
        )

    # ---- 3) 多板卡版本散落在源码中的风险 ----
    if len(_collect_board_revs(profile)) >= 2 and matrix is None:
        collector.add(
            "hint", "flow_compat_rev_scattered",
            str(root), 0,
            "板卡版本判断散落在源码中（如按 Rev 分支配置引脚/时钟）",
            "散落的 Rev 分支会让「烧错版本」难以发现；"
            "建议在构建期把板卡 Rev 固化为可校验的编译期常量或配置项",
            confidence=62,
        )


# --------------------------------------------------------------------------
def _collect_board_revs(profile: C.ProjectProfile) -> set[str]:
    """在用户源码与文档中收集板卡/硬件版本痕迹。"""
    revs = set()
    scanned = 0
    for p in profile.source_files:
        if scanned >= 400:
            break
        scanned += 1
        if p.suffix.lower() not in (".c", ".h", ".cpp", ".hpp"):
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")[:100000]
        except Exception:
            continue
        for m in BOARD_REV_RE.finditer(text):
            revs.add(m.group(0).strip())
    return revs


def _inspect_version_mechanism(profile: C.ProjectProfile):
    """返回 (hardcoded_hits, injected_hits)。

    hardcoded_hits: [(Path, lineno)] 疑似硬编码版本
    injected_hits:  [Path]            具备构建期注入机制
    """
    hardcoded, injected = [], []

    for p in profile.source_files[:600]:
        try:
            lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception:
            continue
        for idx, line in enumerate(lines, 1):
            if FW_VERSION_DEF_RE.search(line) and C.HARDCODED_VERSION_RE.search(line):
                hardcoded.append((p, idx))
                break
            if C.GIT_DESCRIBE_RE.search(line):
                if p not in injected:
                    injected.append(p)

    # 构建脚本中的版本注入
    for p in C.iter_project_files(profile.root, max_files=4000):
        if p.suffix.lower() not in BUILD_SCRIPT_EXTS and \
           p.name.lower() not in BUILD_SCRIPT_NAMES:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")[:60000]
        except Exception:
            continue
        if C.GIT_DESCRIBE_RE.search(text) and p not in injected:
            injected.append(p)

    return hardcoded, injected
