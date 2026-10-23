#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pin_checker.py — 飞控引脚冲突/复用/悬空检测

解析 STM32CubeMX 的 .ioc 文件，检测：
  - fc-pin-conflict: 同一物理引脚被多个外设 Signal 占用（block）
  - fc-pin-unused: 配置了引脚但未分配 Signal（warn）

.ioc 格式（真实样本）:
  Mcu.Pin0=PH0-OSC_IN
  Mcu.Pin1=PH1-OSC_OUT
  PA9.Signal=USART1_TX
  PA10.Signal=USART1_RX
"""
import re
from pathlib import Path

import fc_common


def _parse_ioc(root):
    """查找并解析 .ioc 文件，返回 (filepath, 解析结果 dict)。

    返回:
      (path, {"pins": {pin_name: [signals]}, "configured": {pin_name: bool}})
    """
    ioc_path = fc_common.find_ioc(root)
    if ioc_path is None:
        return None, {"pins": {}, "configured": {}}
    pins = {}        # pin_name -> [signals]
    configured = {}  # pin_name -> 是否显式声明了 Signal

    text = ioc_path.read_text(encoding="utf-8", errors="ignore")
    for line in text.splitlines():
        line = line.strip()
        # 匹配 PinN=XXX 形式（Mcu.Pin0=PH0-OSC_IN）
        m = re.match(r'^Mcu\.Pin\d+=([A-Z0-9_\-]+)$', line)
        if m:
            pin_full = m.group(1)
            # 跳过虚拟引脚（VP_ 前缀，无物理引脚）
            if pin_full.startswith("VP_"):
                continue
            # 提取物理引脚名（PH0-OSC_IN -> PH0）
            pin_name = pin_full.split("-")[0]
            configured.setdefault(pin_name, False)
            continue

        # 匹配 PA9.Signal=USART1_TX 形式
        # STM32 引脚命名 = P + 端口字母 + 引脚号（如 PA9/PH0/PC13）
        m = re.match(r'^([A-Z]+\d+(?:-[A-Z0-9_\-]+)?)\.Signal=(.+)$', line)
        if m:
            pin_full = m.group(1)
            signal = m.group(2)
            pin_name = pin_full.split("-")[0]
            pins.setdefault(pin_name, [])
            if signal not in pins[pin_name]:
                pins[pin_name].append(signal)
            configured[pin_name] = True

    return ioc_path, {"pins": pins, "configured": configured}


def check_pin_conflicts(ioc_path, parsed, collector):
    """检测引脚冲突：同一物理引脚有多个 Signal（排除系统引脚）。"""
    # 系统固定引脚（OSC_IN/OSC_OUT/SWDIO/SWCLK）不参与冲突检测
    system_pins = {"PH0", "PH1", "PA13", "PA14"}

    for pin, signals in parsed["pins"].items():
        if pin in system_pins:
            continue
        if len(signals) > 1:
            collector.add(
                "block", "fc_pin", str(ioc_path), 0,
                f"引脚 {pin} 被多个外设占用: {', '.join(signals)}",
                "检查 .ioc 引脚配置，同一物理引脚只能分配给一个外设",
                confidence=92,
            )


def check_unused_pins(ioc_path, parsed, collector):
    """检测悬空引脚：声明了但未分配 Signal。"""
    for pin, has_signal in parsed["configured"].items():
        if not has_signal:
            collector.add(
                "warn", "fc_pin", str(ioc_path), 0,
                f"引脚 {pin} 已配置但未分配功能（悬空）",
                "确认该引脚是否必要，否则设为浮空输入或删除配置",
                confidence=70,
            )


def scan_pins(root, collector):
    """引脚检测入口。"""
    ioc_path, parsed = _parse_ioc(root)
    if ioc_path is None:
        return
    check_pin_conflicts(ioc_path, parsed, collector)
    check_unused_pins(ioc_path, parsed, collector)
