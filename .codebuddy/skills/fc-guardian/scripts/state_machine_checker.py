#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""state_machine_checker.py — 飞控状态机完整性检测

检测 arming/failsafe 状态机：
  - fc-state-no-arming: 缺 arming 解锁状态机（block）
  - fc-state-no-failsafe: 缺 failsafe 失控保护（block）

对标 ArduPilot failsafe 规范：
  arming = 解锁前校验（传感器/电调/遥控信号）
  failsafe = 信号丢失/低电量/传感器异常时的安全降级
"""
import re
from pathlib import Path

import fc_common


def _find_sources(root):
    """查找飞控核心源码（排除库/资料目录）。"""
    return fc_common.find_user_sources(root)


def _detect_arming(text):
    """检测 arming 解锁状态机信号。

    用 (?<![a-z]) 而非 \b，避免 snake_case/CamelCase 标识符
    （arming_check / isArmed / arm_state）因下划线破坏词边界而漏检。
    """
    patterns = [
        r'(?<![a-z])arming',          # arming / arming_check / is_arming
        r'(?<![a-z])is_?[Aa]rmed',    # isArmed / is_armed
        r'(?<![a-z])arm_state',       # arm_state / arm_status
        r'(?<![a-z])arm_status',
        r'(?<![a-z])disarm',          # disarm / disarmed
        r'(?<![a-z])motor_arm',       # motor_arm / arm_motors
        r'(?<![a-z])arm_motors',
        r'\b(?:ARMED|DISARMED)\b',
        r'解锁', r'锁定',
    ]
    return any(re.search(p, text, re.IGNORECASE) for p in patterns)


def _detect_failsafe(text):
    """检测 failsafe 失控保护信号。

    同样用 (?<![a-z]) 处理 fail_safe / failsafe_check 等下划线标识符。
    """
    patterns = [
        r'(?<![a-z])fail_?safe',      # failsafe / fail_safe / failSafe
        r'(?<![a-z])lost_signal',     # lost_signal / signal_lost
        r'(?<![a-z])signal_lost',
        r'(?<![a-z])rc_loss',         # rc_loss / rc_timeout
        r'(?<![a-z])rc_timeout',
        r'(?<![a-z])low_battery',     # low_battery / battery_low
        r'(?<![a-z])battery_low',
        r'(?<![a-z])emergency_stop',
        r'(?<![a-z])safety_landing',  # safety_landing / failsafe_land
        r'失控', r'失联', r'返航',
    ]
    return any(re.search(p, text, re.IGNORECASE) for p in patterns)


def check_arming(root, collector):
    """检测 arming 解锁状态机。"""
    sources = _find_sources(root)
    if not sources:
        return

    has_arming = False
    for p in sources:
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if _detect_arming(text):
            has_arming = True
            break

    if not has_arming:
        main_c = fc_common.find_main_c(sources)
        if main_c is None:
            return
        collector.add(
            "block", "fc_state", str(main_c), 0,
            "未检测到 arming 解锁状态机（电机解锁前置条件校验缺失）",
            "实现解锁状态机：校验传感器就绪/电调初始化/遥控信号后再启动电机",
            confidence=85,
        )


def check_failsafe(root, collector):
    """检测 failsafe 失控保护状态机。"""
    sources = _find_sources(root)
    if not sources:
        return

    has_failsafe = False
    for p in sources:
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if _detect_failsafe(text):
            has_failsafe = True
            break

    if not has_failsafe:
        main_c = fc_common.find_main_c(sources)
        if main_c is None:
            return
        collector.add(
            "block", "fc_state", str(main_c), 0,
            "未检测到 failsafe 失控保护（信号丢失/低电量/传感器异常处理缺失）",
            "实现 failsafe：遥控信号丢失→自动降落/悬停；低电量→返航；传感器异常→紧急停止",
            confidence=88,
        )


def scan_state_machine(root, collector):
    """状态机检测入口。"""
    check_arming(root, collector)
    check_failsafe(root, collector)
