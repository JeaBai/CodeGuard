#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""uart_checker.py — 飞控串口配置一致性检测

解析 .ioc 的 USART 配置 + usart.c 源码，检测：
  - fc-uart-rx-no-tx: USART 只配置 RX 无 TX（或反之）（warn）
  - fc-uart-baud-mismatch: USART 波特率异常（非标准值）（warn）

.ioc 格式:
  USART1.BaudRate=100000
  USART1.Mode=MODE_RX
  PA9.Signal=USART1_TX
  PA10.Signal=USART1_RX
"""
import re
from pathlib import Path

import fc_common

# 标准波特率集合（飞控常用）
_STANDARD_BAUDS = {9600, 19200, 38400, 57600, 115200, 230400, 460800, 921600,
                   100000, 400000, 500000, 1000000, 1500000, 2000000}


def _parse_usart_config(root):
    """解析 .ioc 的 USART 配置和引脚 Signal，返回 (ioc_path, usart_config)。

    返回:
      (ioc_path, {usart_name: {"baud": int|None, "mode": str, "tx_pin": str|None, "rx_pin": str|None}})
    """
    ioc_path = fc_common.find_ioc(root)
    if ioc_path is None:
        return None, {}
    text = ioc_path.read_text(encoding="utf-8", errors="ignore")

    usarts = {}
    for line in text.splitlines():
        line = line.strip()
        # USART1.BaudRate=100000
        m = re.match(r'^(USART\d+)\.BaudRate=(\d+)', line)
        if m:
            name = m.group(1)
            usarts.setdefault(name, {"baud": None, "mode": "", "tx_pin": None, "rx_pin": None})
            usarts[name]["baud"] = int(m.group(2))
            continue

        # USART1.Mode=MODE_RX / MODE_TX / MODE_TX_RX
        m = re.match(r'^(USART\d+)\.Mode=(MODE_\w+)', line)
        if m:
            name = m.group(1)
            usarts.setdefault(name, {"baud": None, "mode": "", "tx_pin": None, "rx_pin": None})
            usarts[name]["mode"] = m.group(2)
            continue

        # PA9.Signal=USART1_TX
        m = re.match(r'^(PA\d+|PB\d+|PC\d+|PD\d+|PE\d+)(?:-[A-Z0-9_\-]+)?\.Signal=(USART\d+)_(TX|RX)$', line)
        if m:
            _pin = m.group(1)
            usart = m.group(2)
            direction = m.group(3)
            usarts.setdefault(usart, {"baud": None, "mode": "", "tx_pin": None, "rx_pin": None})
            if direction == "TX":
                usarts[usart]["tx_pin"] = _pin
            else:
                usarts[usart]["rx_pin"] = _pin

    return ioc_path, usarts


def _pair_issue(name, cfg):
    """返回串口收发不对称的描述，无问题返回 None。

    用数据表映射 mode → 触发条件，避免多分支圈复杂度。
    """
    has_tx = cfg.get("tx_pin") is not None
    has_rx = cfg.get("rx_pin") is not None
    mode = cfg.get("mode", "")

    checks = {
        "MODE_RX": (not has_rx, "配置为 MODE_RX 但未找到 RX 引脚分配", "检查 RX 引脚 Signal 配置"),
        "MODE_TX": (not has_tx, "配置为 MODE_TX 但未找到 TX 引脚分配", "检查 TX 引脚 Signal 配置"),
        "MODE_TX_RX": (not has_tx or not has_rx,
                       f"配置为 MODE_TX_RX 但收发引脚不对称 (TX={has_tx}, RX={has_rx})",
                       "补齐缺失的 TX/RX 引脚分配"),
    }
    if mode not in checks:
        return None
    triggered, msg, suggestion = checks[mode]
    return (msg, suggestion) if triggered else None


def check_rx_tx_pairs(ioc_path, usarts, collector):
    """检测串口收发不对称：有 RX 无 TX 或反之。"""
    for name, cfg in usarts.items():
        issue = _pair_issue(name, cfg)
        if issue is not None:
            msg, suggestion = issue
            collector.add(
                "warn", "fc_uart", str(ioc_path), 0,
                f"{name} {msg}", suggestion, confidence=78,
            )


def check_baud_consistency(ioc_path, usarts, collector):
    """检测波特率异常：非标准值提示（飞控通信通常用标准波特率）。"""
    for name, cfg in usarts.items():
        baud = cfg.get("baud")
        if baud is None:
            continue
        if baud not in _STANDARD_BAUDS:
            collector.add(
                "warn", "fc_uart", str(ioc_path), 0,
                f"{name} 波特率 {baud} 为非标准值",
                "确认波特率与对端设备匹配（遥控/遥测/GPS 常见 115200/460800/921600）",
                confidence=65,
            )


def scan_uarts(root, collector):
    """串口检测入口。"""
    ioc_path, usarts = _parse_usart_config(root)
    if ioc_path is None:
        return
    check_rx_tx_pairs(ioc_path, usarts, collector)
    check_baud_consistency(ioc_path, usarts, collector)
