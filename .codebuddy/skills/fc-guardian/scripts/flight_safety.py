#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""flight_safety.py — 飞控安全检测（看门狗/电机解锁/传感器校准）

检测：
  - fc-safety-no-watchdog: 缺看门狗（IWDG/WWDG）配置（block）
  - fc-safety-no-calibration: 缺传感器校准检查（IMU/GPS/磁力计/电调）（warn）

对标大疆安全标准：看门狗防跑飞，传感器校准保证姿态解算正确。
"""
import re
from pathlib import Path

import fc_common


def _find_sources(root):
    """查找飞控源码（排除库/资料目录，看门狗只查用户代码 + .ioc）。"""
    sources = fc_common.find_user_sources(root)
    ioc = fc_common.find_ioc(root)
    if ioc is not None:
        sources.append(ioc)
    return sources


_CALIBRATION_PATTERNS = [
    (r'(?<![a-z])calibrat', "传感器校准"),     # CalibrateGyro / calibrate_imu
    (r'(?<![a-z])imu_calib', "IMU 校准"),
    (r'(?<![a-z])mag_calib', "磁力计校准"),
    (r'(?<![a-z])esc_calib', "电调校准"),
    (r'(?<![a-z])gps_calib', "GPS 校准"),
    (r'校准', "校准检查"),
]


def _watchdog_in_ioc(text):
    """.ioc 中检查 Mcu.IP 外设列表是否含 IWDG/WWDG。"""
    return bool(re.search(r'^Mcu\.IP\d*=(IWDG|WWDG)\s*$', text, re.MULTILINE))


def _watchdog_in_code(text):
    """用户代码中检查 IWDG/WWDG 实际初始化调用。

    注意：HAL_IWDG_MODULE_ENABLED 只是模块使能宏，不代表已启用看门狗。
    """
    return bool(re.search(
        r'MX_IWDG\d*_Init\s*\(|HAL_IWDG_Init\s*\(|MX_WWDG\d*_Init\s*\(|HAL_WWDG_Init\s*\(',
        text))


def check_watchdog(root, collector):
    """检测看门狗配置（IWDG/WWDG）。

    只查用户代码 + .ioc 的 Mcu.IP 外设列表，不查 HAL 库自带驱动。
    """
    sources = _find_sources(root)
    if not sources:
        return

    has_watchdog = any(
        _watchdog_in_ioc(p.read_text(encoding="utf-8", errors="ignore")) if p.suffix == ".ioc"
        else _watchdog_in_code(p.read_text(encoding="utf-8", errors="ignore"))
        for p in sources
    )

    if not has_watchdog:
        main_c = fc_common.find_main_c(sources)
        if main_c is None:
            return
        collector.add(
            "block", "fc_safety", str(main_c), 0,
            "未检测到看门狗（IWDG/WWDG）配置",
            "启用 IWDG 独立看门狗（如 1s 超时），主循环定期喂狗；飞控死机时自动复位",
            confidence=92,
        )


def _calibration_labels(text):
    """提取文本中命中的校准信号标签列表。"""
    return [label for keyword, label in _CALIBRATION_PATTERNS
            if re.search(keyword, text, re.IGNORECASE)]


def check_calibration(root, collector):
    """检测传感器校准检查（IMU/GPS/磁力计/电调）。"""
    sources = [p for p in _find_sources(root) if p.suffix != ".ioc"]
    if not sources:
        return

    calibration_signals = []
    for p in sources:
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        calibration_signals.extend(_calibration_labels(text))

    if not calibration_signals:
        main_c = fc_common.find_main_c(sources)
        if main_c is None:
            return
        collector.add(
            "warn", "fc_safety", str(main_c), 0,
            "未检测到传感器校准检查（IMU/GPS/磁力计/电调校准缺失）",
            "实现上电校准检查：IMU 零偏/磁力计椭球拟合/电调行程校准",
            confidence=72,
        )


def scan_flight_safety(root, collector):
    """飞控安全检测入口。"""
    check_watchdog(root, collector)
    check_calibration(root, collector)
