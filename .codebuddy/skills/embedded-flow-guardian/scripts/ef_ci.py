#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ef_ci.py — 检测器 ⑥ 工程自动化基线

回答：这套工程能不能「自动地、可重复地」验证自己。

设计依据（见 references/engineering.md 3.3、references/anti-patterns.md）：
  - 门禁必须基于**增量指标**，且只拦「快且确定」的信号；门禁一切 → 红=噪声 → 沦为剧场
  - Flaky test 是 CI 头号敌人（Google：1.5% 运行 flaky、≈16% 测试 flaky、
    ≈84% 的 pass→fail 涉及 flaky），需自动隔离而非「3 连败才报」
  - 构建时间的 10 分钟阈值（超时后开发者会切走，平均 23 分钟才能回神）
  - 中小企业档位：cppcheck + clang-tidy 半小时可接入
  - Jenkins 维护成本：当维护占用某工程师 >20% 时间即应迁移

本检测器是 per-module 门禁级别（moduleLevels）的主要受益者：
  同一项缺失，在核心固件目录下可判 block，在仿真/工具目录下仅判 warn。
"""
from __future__ import annotations

import re
from pathlib import Path

import ef_common as C

# CI 中「只拦快且确定信号」的正面痕迹
GATE_HYGIENE = {
    "flaky隔离": re.compile(r"quarantine|flaky|retry|重试", re.IGNORECASE),
    "分阶段": re.compile(r"nightly|nightly-build|schedule|cron|定时|每晚",
                        re.IGNORECASE),
    "缓存": re.compile(r"cache|ccache|缓存", re.IGNORECASE),
}

# 「门禁一切」的坏味道：CI 里出现重活
HEAVY_IN_CI = re.compile(
    r"\b(hil|hardware.in.the.loop|emulator|full.?regression|soak)\b",
    re.IGNORECASE,
)


def scan_ci(root: Path, collector, profile: C.ProjectProfile, cfg: dict):
    # ---- 1) CI 配置 ----
    if not profile.ci_systems:
        collector.add(
            C.severity_for("weak", C.resolve_level("", cfg)),
            "flow_ci_none",
            str(root), 0,
            "未发现持续集成配置（GitHub Actions / GitLab CI / Jenkins 等）",
            "CI 是「可复现」与「增量门禁」的载体。小团队最低成本组合："
            "GitHub Actions 免费额度 + 自建 runner（板卡连接）+ cppcheck + Unity。"
            "注意：云 runner 无法插 USB，烧录与 HIL 必须自建 runner",
            confidence=78,
        )
    else:
        collector.add(
            "info", "flow_ci_present",
            str(root), 0,
            f"已配置 CI：{'、'.join(profile.ci_systems)}",
            _ci_advice(profile),
            confidence=80,
        )
        _check_gate_hygiene(root, collector, profile)

    # ---- 2) 构建脚本（命令行可构建） ----
    if not profile.build_systems:
        collector.add(
            C.severity_for("weak", C.resolve_level("", cfg)),
            "flow_ci_no_cli_build",
            str(root), 0,
            "未发现命令行构建入口",
            "CI 与自动化测试都要求「无 GUI 可构建」；"
            "Keil 工程可用 UV4.exe -b 命令行包装（本项目已有 keil_build.py 的正确做法）",
            confidence=75,
        )

    # ---- 3) 单元测试 ----
    if not profile.test_frameworks and not profile.has_tests_dir:
        # per-module：核心目录下判得重，工具/仿真目录判得轻。
        # 核心目录来自项目配置 corePaths，通用代码不硬编码任何项目目录名。
        cores = C.cfg_core_paths(cfg)
        lv_core = C.resolve_level(cores[0] if cores else "", cfg)
        collector.add(
            C.severity_for("missing", lv_core),
            "flow_ci_no_unit_test",
            str(root), 0,
            "未发现单元测试框架与测试目录",
            "性价比最高的可测对象是「零硬件依赖的纯逻辑」：姿态解算(Slerp/四元数)、"
            "滤波器、PID、协议编解码。建议 Unity + CMock 或 CppUTest，"
            "在 host 侧跑（约 30 秒），把硬件迭代(3-7 天)的反馈周期压缩掉",
            confidence=80,
        )
    else:
        collector.add(
            "info", "flow_ci_unit_test",
            str(root), 0,
            f"单元测试基础设施：框架={profile.test_frameworks or '未识别'} "
            f"测试目录={'有' if profile.has_tests_dir else '无'}",
            "检查测试是否在 host 侧可跑；目标侧测试应保持极少量（无堆、无 stdout）",
            confidence=78,
        )

    # ---- 4) 覆盖率采集能力 ----
    if not profile.coverage_tools:
        collector.add(
            C.severity_for("weak", C.resolve_level("", cfg)),
            "flow_ci_no_coverage",
            str(root), 0,
            "未发现覆盖率采集痕迹（gcov/lcov/Bullseye 等）",
            "覆盖率工具链需「生成 + 读取」闭环：常见问题是门禁只读不产，导致 0 覆盖率即 BLOCK "
            "却无工具补数据。注意区分：标准要的是结构化覆盖(MC/DC)，而不是语句覆盖；"
            "且覆盖率必须与变异/边界测试配套——只调用不断言也能做到 100% 覆盖、0% 变异得分",
            confidence=72,
        )
    else:
        collector.add(
            "info", "flow_ci_coverage",
            str(root), 0,
            f"覆盖率工具：{'、'.join(profile.coverage_tools)}",
            "插桩会消耗 ROM/RAM 并可能破坏实时性；集成/系统测试建议改用硬件 trace",
            confidence=75,
        )

    # ---- 5) 大二进制管理 ----
    if profile.has_git and not profile.has_lfs:
        collector.add(
            "hint", "flow_ci_no_lfs",
            str(root), 0,
            "仓库未配置 Git LFS",
            "若纳入原理图/PCB/STEP/厂商 SDK/二进制库，建议启用 LFS；"
            "否则仓库会膨胀且无法 review。注意 CI runner 需先 git lfs install，"
            "否则 LFS 文件被检出为指针文本",
            confidence=62,
        )

    # ---- 6) 增量门禁意识（配置项体检） ----
    if not cfg:
        collector.add(
            "hint", "flow_ci_default_level",
            str(root), 0,
            "未找到门禁配置（.ef-guardian.json），当前使用默认单一门禁级别",
            "建议在项目根创建 .ef-guardian.json，声明本项目的核心目录与端口等，"
            "避免通用代码里出现项目特定值：\n"
            '  {"defaultLevel":"silver",\n'
            '   "corePaths":["<你的核心固件目录>"],\n'
            '   "preferredPorts":["<COMx>","<COMy>"],\n'
            '   "telemetryFields":27}\n'
            "corePaths 会自动展开为 gold 门禁规则（核心目录从严、其余从宽）",
            confidence=70,
        )


# --------------------------------------------------------------------------
def _check_gate_hygiene(root: Path, collector, profile: C.ProjectProfile):
    """检查 CI 是否有「只在短检查上门禁」的卫生习惯。"""
    texts, ci_paths = [], []
    for p in C.iter_project_files(root, max_files=4000):
        low = str(p).lower()
        if any(m in low for m in (".github", ".gitlab-ci", "jenkinsfile",
                                  "azure-pipelines", ".circleci")):
            try:
                texts.append(p.read_text(encoding="utf-8", errors="replace")[:60000])
                ci_paths.append(p)
            except Exception:
                continue
    if not texts:
        return
    blob = "\n".join(texts)

    if HEAVY_IN_CI.search(blob) and not GATE_HYGIENE["分阶段"].search(blob):
        collector.add(
            "warn", "flow_ci_heavy_gate",
            profile.rel(ci_paths[0]), 0,
            "CI 中似乎包含了 HIL / 全量回归等重活，但未见分阶段（nightly/cron）安排",
            "门禁只应拦「快且确定」的信号（编译、单测、lint、依赖扫描）；"
            "慢且易抖的 HIL 与 soak 测试应移到定时流水线。"
            "否则流水线又慢又 flaky → 工程师学会「红≠坏」→ 门禁沦为剧场",
            confidence=70,
        )

    if not GATE_HYGIENE["flaky隔离"].search(blob):
        collector.add(
            "hint", "flow_ci_no_flaky_policy",
            profile.rel(ci_paths[0]), 0,
            "CI 中未见 flaky 治理痕迹（重试/隔离/quarantine）",
            "Google 实测：约 84% 的 pass→fail 转变涉及 flaky test。"
            "治理要点是「自动隔离 + 开单 + 限时修复/删除」，"
            "而不是把测试标记为「连续失败 3 次才报警」——后者会鼓励开发者忽视 flakiness",
            confidence=65,
        )


def _ci_advice(profile: C.ProjectProfile) -> str:
    bits = []
    if not profile.static_analysis:
        bits.append("建议接入 cppcheck（含 misra.py 插件）+ clang-tidy，半小时可起步")
    if "github-actions" in profile.ci_systems:
        bits.append("GitHub Actions 需自建 runner 才能接板卡（云 runner 无 USB）")
    if not bits:
        return "持续检查门禁是否只拦快且确定的信号；构建时间控制在 10 分钟内"
    return "；".join(bits)
