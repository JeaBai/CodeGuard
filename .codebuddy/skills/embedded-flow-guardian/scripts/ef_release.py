#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ef_release.py — 检测器 ⑤ 发布准出与可复现构建

回答：能不能证明「这次放行的固件 = 这个源码提交 = 这些验证结论」。

设计依据（见 references/engineering.md 3.3、references/lifecycle.md 2.3）：
  - "未经重建两次并 diff 过的一致性，只是一个声明，不是属性"
  - 可复现构建是固件服役 5-10 年的硬门槛（需支持数年后重建同一版本补丁）
  - 准出清单缺失 → 真飞/量产缺乏可核验的放行依据
  - 复盘：某项目 HIL 阶段写在托管 runner 上、根本没连目标板，空跑数月仍"报告覆盖率"

边界：不替代实际构建与测试，只检查「是否有可核验的证据链」。
"""
from __future__ import annotations

import re
from pathlib import Path

import ef_common as C

# 可复现构建的关键痕迹
REPRO_MARKERS = {
    "SOURCE_DATE_EPOCH": re.compile(r"SOURCE_DATE_EPOCH"),
    "容器化构建": re.compile(r"dockerfile|docker-compose|container", re.IGNORECASE),
    "工具链固定": re.compile(r"TOOLCHAIN|GCC_VERSION|arm-none-eabi|toolchain.*pin",
                             re.IGNORECASE),
    "确定性链接": re.compile(r"ffile-prefix-map|fdebug-prefix-map|-Wl,--build-id=none"),
    "哈希校验": re.compile(r"sha256|sha1sum|checksum|md5sum", re.IGNORECASE),
    "SBOM": re.compile(r"sbom|cyclonedx|spdx", re.IGNORECASE),
}

# 发布产物目录
ARTIFACT_DIRS = ["release", "releases", "dist", "artifacts", "output",
                 "build_output", "发布", "产物"]

# 固件二进制扩展名
BINARY_EXTS = {".hex", ".bin", ".elf", ".axf", ".s19", ".dfu", ".uf2"}

# 验证/测试报告关键词
VERIFY_KEYWORDS = ["验证报告", "测试报告", "test_report", "verification",
                   "体检报告", "复测", "测试结果", "test result"]


def scan_release(root: Path, collector, profile: C.ProjectProfile, cfg: dict):
    level = cfg.get("defaultLevel", C.DEFAULT_LEVEL)

    # ---- 1) 发布准出清单 ----
    checklist, _ev = C.find_deliverable(profile, ["准出", "发布检查", "release_checklist",
                                                  "release-checklist", "checklist",
                                                  "放行", "交付检查", "准出准则",
                                                  "放行准则"])
    if checklist is None:
        collector.add(
            C.severity_for("missing", level),
            "flow_release_no_checklist",
            str(root), 0,
            "未发现发布准出清单",
            "每次真飞/量产前应有可核验的书面准出准则（含：构建可复现、"
            "静态分析无新增 BLOCK、单元测试通过、覆盖率达阈值、已知问题已审批）。"
            "模板见 assets/templates/release_checklist.md",
            confidence=82,
        )
    else:
        collector.add(
            "info", "flow_release_checklist_present",
            profile.rel(checklist), 0,
            f"已发现准出清单：{profile.rel(checklist)}",
            "确认清单含『准出准则』而非仅『检查项罗列』——每条应有明确的通过判据",
            confidence=78,
        )

    # ---- 2) 可复现构建证据 ----
    markers_found = _scan_repro_markers(root, profile)
    build = profile.build_systems
    if not build:
        collector.add(
            C.severity_for("weak", level),
            "flow_release_no_build_script",
            str(root), 0,
            "未发现任何构建系统（Keil/CMake/Make/PlatformIO）",
            "命令行可构建是自动化的前提；手工点 IDE 构建无法进入 CI，"
            "也无法验证可复现性",
            confidence=75,
        )
    else:
        if not markers_found:
            collector.add(
                C.severity_for("weak", level),
                "flow_release_no_repro",
                str(root), 0,
                f"已有构建系统（{'、'.join(build)}），但未发现可复现构建痕迹",
                "可复现构建需固定：工具链版本（镜像 digest）、"
                "SOURCE_DATE_EPOCH、-ffile-prefix-map/-fdebug-prefix-map、"
                "锁定依赖。验证方式是同一 commit 在两台机器各构建两次并 diff 哈希",
                confidence=70,
            )
        else:
            collector.add(
                "info", "flow_release_repro_partial",
                str(root), 0,
                f"可复现构建痕迹：{'、'.join(sorted(markers_found))}",
                _repro_advice(markers_found),
                confidence=72,
            )

    # ---- 3) 产物归档 ----
    artifact_hits = []
    for name in ARTIFACT_DIRS:
        d = root / name
        if d.is_dir():
            artifact_hits.append(d)
    binaries = [p for p in C.iter_project_files(root, exts=BINARY_EXTS,
                                                include_vendor=True, max_files=8000)]
    if not artifact_hits and not binaries:
        collector.add(
            C.severity_for("weak", level),
            "flow_release_no_artifact",
            str(root), 0,
            "未发现固件产物归档（无 release/dist 目录，也无 .hex/.bin/.elf）",
            "每个出厂固件应与源码提交绑定归档（建议：产物名带 git describe 版本号 + SHA256）",
            confidence=68,
        )
    else:
        collector.add(
            "info", "flow_release_artifact",
            str(root), 0,
            f"产物痕迹：目录 {len(artifact_hits)} 个 / 固件二进制 {len(binaries)} 个",
            "确认归档产物带版本号与校验和，且与 tag 一一对应",
            confidence=70,
        )

    # ---- 4) 验证记录 ----
    verify = None
    for p in profile.doc_files:
        if any(k.lower() in p.name.lower() for k in VERIFY_KEYWORDS):
            verify = p
            break
    if verify is None:
        collector.add(
            C.severity_for("weak", level),
            "flow_release_no_verify_record",
            str(root), 0,
            "未发现验证/测试报告类文档",
            "发布准出需要验证证据（静态分析报告、单元测试结果、覆盖率、真飞/台架记录）；"
            "证据应随开发持续产生，而不是发布前补写",
            confidence=72,
        )
    else:
        collector.add(
            "info", "flow_release_verify_present",
            profile.rel(verify), 0,
            f"已发现验证记录：{profile.rel(verify)}",
            "确认验证记录与本版本源码提交绑定，而非跨版本复用",
            confidence=70,
        )

    # ---- 5) 回滚 / 防降级规划（仅当存在升级通道时才提示） ----
    if _has_update_channel(root, profile):
        has_rollback_plan = _doc_mentions(profile,
                                          ["回滚", "rollback", "防降级",
                                           "anti-rollback", "a/b 分区", "分区"])
        if not has_rollback_plan:
            collector.add(
                "hint", "flow_release_no_rollback",
                str(root), 0,
                "项目存在固件升级通道，但未见回滚/防降级方案",
                "注意：「可回滚」（启动失败回旧分区）≠「防降级」"
                "（需设备侧可信非易失单调计数器）。"
                "另注意 HTTPS 不能替代签名验证——镜像离开发布服务器后即失去链路保护",
                confidence=65,
            )


# --------------------------------------------------------------------------
def _scan_repro_markers(root: Path, profile: C.ProjectProfile) -> set[str]:
    found = set()
    candidates = [p for p in C.iter_project_files(root, max_files=4000)
                  if p.suffix.lower() in {".py", ".sh", ".bat", ".cmd", ".ps1",
                                          ".mk", ".txt", ".yml", ".yaml", ".md",
                                          ".cfg", ".toml", ".ini"}]
    for p in candidates[:800]:
        try:
            text = p.read_text(encoding="utf-8", errors="replace")[:60000]
        except Exception:
            continue
        for name, rx in REPRO_MARKERS.items():
            if name in found:
                continue
            if rx.search(text):
                found.add(name)
    return found


def _repro_advice(found: set[str]) -> str:
    want = {"SOURCE_DATE_EPOCH", "容器化构建", "工具链固定", "确定性链接"}
    lack = want - found
    if not lack:
        return "四项关键要素齐备；仍建议实机验证：同 commit 两台机器各构建两次并 diff"
    return "仍缺：" + "、".join(sorted(lack)) + \
           "。可复现性必须实测（构建两次 diff 哈希），不能仅凭配置声明"


def _has_update_channel(root: Path, profile: C.ProjectProfile) -> bool:
    """项目是否存在 OTA / 升级通道迹象。"""
    tokens = ["ota", "bootloader", "iap", "升级", "dfu", "mcuboot", "rauc",
              "swupdate", "mender", "ble", "蓝牙"]
    for p in C.iter_project_files(root, max_files=3000):
        nm = p.name.lower()
        if any(t in nm for t in tokens):
            return True
    return False


def _doc_mentions(profile: C.ProjectProfile, keywords) -> bool:
    kws = [k.lower() for k in keywords]
    for p in profile.doc_files:
        if p.suffix.lower() not in C.DOC_EXTS:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")[:150000].lower()
        except Exception:
            continue
        if any(k in text for k in kws):
            return True
    return False
