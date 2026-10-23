#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ef_serial.py — 串口检索、只读监听与数据采集（零第三方依赖）

设计前提：本机 Python 环境**没有安装 pyserial**。因此本模块：
  - 串口枚举：优先 pyserial（若可用，可获得 VID/PID/描述等富信息）；
    否则回退到 Windows 注册表 HKLM\\HARDWARE\\DEVICEMAP\\SERIALCOMM（标准库 winreg）。
  - 串口读写：Windows 走 ctypes 直接调用 Win32 API（CreateFileW / SetCommState /
    ReadFile / WriteFile）；POSIX 走 os.open + termios。**全程标准库**。

安全默认：所有操作**只读**。发送命令必须显式 `--yes`，
且本模块不做任何电机/舵机驱动——那类动作留给工程里已有的业务脚本。

采集时会生成**旁车元数据** `<csv>.meta.json`（端口/波特率/开始时间/固件版本/行数），
以保持 CSV 格式与既有管线完全兼容，同时满足「关键节点留痕」的工程要求。
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

IS_WIN = os.name == "nt"

# --------------------------------------------------------------------------
# 1. 串口枚举
# --------------------------------------------------------------------------
# 已知常见 USB-TTL / 调试器芯片（用于识别与优先级排序）
KNOWN_CHIPS = {
    "1a86": "WCH CH340/CH341",
    "10c4": "Silicon Labs CP210x",
    "0403": "FTDI FT232",
    "0483": "STMicroelectronics ST-Link",
    "2341": "Arduino",
    "2e8a": "Raspberry Pi Pico",
    "303a": "Espressif (ESP32)",
    "1a86:7523": "CH340",
}
# 通用默认：**不预设任何端口**。把某个项目的串口惯例写进通用代码，
# 会在换项目时变成隐蔽的错误来源。项目如需优先级，在 .ef-guardian.json 声明 preferredPorts。
DEFAULT_PREFERRED: list[str] = []


def cfg_preferred_ports(root=None):
    """从项目配置读取优先串口（.ef-guardian.json → preferredPorts）。"""
    try:
        import ef_common as C
        r = Path(root).resolve() if root else Path.cwd()
        return C.cfg_preferred_ports(C.load_config(r))
    except Exception:
        return []


def cfg_telemetry_fields(root=None):
    """从项目配置读取遥测字段数（.ef-guardian.json → telemetryFields）。"""
    try:
        import ef_common as C
        r = Path(root).resolve() if root else Path.cwd()
        return C.cfg_telemetry_fields(C.load_config(r))
    except Exception:
        return None


def list_ports():
    """枚举串口。

    Returns:
        list[dict]: [{device, description, hwid, vid, pid, chip, source}]
    """
    ports = []
    try:
        import serial.tools.list_ports as lp  # type: ignore
        for p in sorted(lp.comports(), key=lambda x: x.device):
            vid = f"{p.vid:04x}" if p.vid else ""
            pid = f"{p.pid:04x}" if p.pid else ""
            ports.append({
                "device": p.device,
                "description": p.description or "",
                "hwid": p.hwid or "",
                "vid": vid, "pid": pid,
                "chip": KNOWN_CHIPS.get(vid, ""),
                "source": "pyserial",
            })
        return ports
    except Exception:
        pass

    # 回退：Windows 注册表
    if IS_WIN:
        try:
            import winreg  # type: ignore
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                 r"HARDWARE\DEVICEMAP\SERIALCOMM")
            i = 0
            while True:
                try:
                    _name, value, _t = winreg.EnumValue(key, i)
                    i += 1
                except OSError:
                    break
                ports.append({
                    "device": str(value), "description": "(注册表枚举)",
                    "hwid": "", "vid": "", "pid": "", "chip": "",
                    "source": "winreg",
                })
        except Exception:
            pass

    # 再回退：POSIX /dev
    if not ports and not IS_WIN:
        for dev in sorted(Path("/dev").glob("ttyUSB*")) + sorted(Path("/dev").glob("ttyACM*")):
            ports.append({"device": str(dev), "description": "(devfs)", "hwid": "",
                          "vid": "", "pid": "", "chip": "", "source": "devfs"})
    return ports


def auto_detect(preferred=None, root=None):
    """按优先级挑选可用串口。

    顺序：显式 preferred > 项目配置 preferredPorts > 唯一可用端口 > 无（要求显式指定）。
    不设硬编码兜底端口——让"选错端口"成为显式错误而不是静默行为。
    """
    preferred = preferred or cfg_preferred_ports(root) or DEFAULT_PREFERRED
    ports = list_ports()
    if not ports:
        return None, ports
    avail = {p["device"].upper(): p for p in ports}
    for want in preferred:
        if str(want).upper() in avail:
            return avail[str(want).upper()]["device"], ports
    if len(ports) == 1:
        return ports[0]["device"], ports
    return None, ports


# --------------------------------------------------------------------------
# 2. 串口对象（Windows: ctypes Win32；POSIX: termios）
# --------------------------------------------------------------------------
if IS_WIN:
    import ctypes
    from ctypes import wintypes

    GENERIC_READ = 0x80000000
    GENERIC_WRITE = 0x40000000
    OPEN_EXISTING = 3
    INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

    NOPARITY, ODDPARITY, EVENPARITY, MARKPARITY, SPACEPARITY = 0, 1, 2, 3, 4
    ONESTOPBIT, ONE5STOPBITS, TWOSTOPBITS = 0, 1, 2
    PARITY_BITS = {"N": NOPARITY, "O": ODDPARITY, "E": EVENPARITY,
                   "M": MARKPARITY, "S": SPACEPARITY}
    STOP_BITS = {"1": ONESTOPBIT, "1.5": ONE5STOPBITS, "2": TWOSTOPBITS}

    class DCB(ctypes.Structure):
        _fields_ = [
            ("DCBlength", wintypes.DWORD),
            ("BaudRate", wintypes.DWORD),
            ("Flags", wintypes.DWORD),
            ("wReserved", wintypes.WORD),
            ("XonLim", wintypes.WORD),
            ("XoffLim", wintypes.WORD),
            ("ByteSize", ctypes.c_byte),
            ("Parity", ctypes.c_byte),
            ("StopBits", ctypes.c_byte),
            ("XonChar", ctypes.c_char),
            ("XoffChar", ctypes.c_char),
            ("ErrorChar", ctypes.c_char),
            ("EofChar", ctypes.c_char),
            ("EvtChar", ctypes.c_char),
            ("wReserved1", wintypes.WORD),
        ]

    class COMMTIMEOUTS(ctypes.Structure):
        _fields_ = [
            ("ReadIntervalTimeout", wintypes.DWORD),
            ("ReadTotalTimeoutMultiplier", wintypes.DWORD),
            ("ReadTotalTimeoutConstant", wintypes.DWORD),
            ("WriteTotalTimeoutMultiplier", wintypes.DWORD),
            ("WriteTotalTimeoutConstant", wintypes.DWORD),
        ]

    _K32 = None

    def _load_k32():
        """加载 kernel32 并**显式声明函数原型**。

        ⚠️ 关键：ctypes 默认把返回值当 32 位 int，而 Windows HANDLE 在 x64 上是 64 位。
        不声明 restype 会导致句柄被截断，CreateFileW 看似成功、
        后续 GetCommState/ReadFile 却全部失败（表现为 "GetCommState 失败"）。
        """
        global _K32
        if _K32 is not None:
            return _K32
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
                                  ctypes.c_void_p]
        k.CreateFileW.restype = wintypes.HANDLE
        k.CloseHandle.argtypes = [wintypes.HANDLE]
        k.CloseHandle.restype = wintypes.BOOL
        k.GetCommState.argtypes = [wintypes.HANDLE, ctypes.POINTER(DCB)]
        k.GetCommState.restype = wintypes.BOOL
        k.SetCommState.argtypes = [wintypes.HANDLE, ctypes.POINTER(DCB)]
        k.SetCommState.restype = wintypes.BOOL
        k.SetCommTimeouts.argtypes = [wintypes.HANDLE, ctypes.POINTER(COMMTIMEOUTS)]
        k.SetCommTimeouts.restype = wintypes.BOOL
        k.ReadFile.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
                               ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
        k.ReadFile.restype = wintypes.BOOL
        k.WriteFile.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
                                ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
        k.WriteFile.restype = wintypes.BOOL
        k.PurgeComm.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        k.PurgeComm.restype = wintypes.BOOL
        _K32 = k
        return k


class SerialPort:
    """最小可用的串口封装（无第三方依赖）。

    用法：
        with SerialPort("COM3", 921600) as sp:
            data = sp.read(512)
    """

    def __init__(self, device: str, baudrate: int = 115200,
                 bytesize: int = 8, parity: str = "N", stopbits: str = "1",
                 dtr: bool = True, rts: bool = True, timeout: float = 0.5):
        self.device = device
        self.baudrate = baudrate
        self.bytesize = bytesize
        self.parity = parity.upper()
        self.stopbits = str(stopbits)
        self.dtr = dtr
        self.rts = rts
        self.timeout = timeout
        self._handle = None
        self._fd = None

    # -- 生命周期 ---------------------------------------------------------
    def open(self):
        if IS_WIN:
            self._open_win()
        else:
            self._open_posix()
        return self

    def _open_win(self):
        k32 = _load_k32()
        path = self.device
        if not path.startswith("\\\\.\\"):
            path = "\\\\.\\" + path
        h = k32.CreateFileW(path,
                            GENERIC_READ | GENERIC_WRITE, 0, None,
                            OPEN_EXISTING, 0, None)
        if not h or h == INVALID_HANDLE_VALUE:
            err = ctypes.get_last_error()
            hint = ""
            if err == 5:
                hint = "（拒绝访问：端口可能被 Keil 调试器 / 串口助手 / 上位机占用）"
            elif err in (2, 3):
                hint = "（端口不存在：确认设备已连接且驱动已装）"
            elif err == 121:
                hint = ("（信号量超时：该端口很可能是**蓝牙虚拟串口**但设备未连接。"
                        "BLE 模块（如 JDY-23）需先在系统里完成配对并建立 SPP 连接）")
            elif err == 1167:
                hint = "（设备未连接：虚拟串口已注册但底层设备不在线）"
            raise OSError(f"无法打开 {self.device}（Win32 错误 {err}）{hint}")
        self._handle = h
        self._k32 = k32

        dcb = DCB()
        dcb.DCBlength = ctypes.sizeof(DCB)
        if not k32.GetCommState(h, ctypes.byref(dcb)):
            err = ctypes.get_last_error()
            self.close()
            raise OSError(
                f"GetCommState 失败：{self.device}（Win32 错误 {err}）。"
                f"该设备可能不是真正的串口（如未连接的蓝牙虚拟口），或已被独占")
        if ctypes.sizeof(DCB) != 28:
            print(f"[ef_serial][警告] DCB 尺寸 {ctypes.sizeof(DCB)} != 28，"
                  f"若串口行为异常请反馈", file=sys.stderr)

        dcb.BaudRate = int(self.baudrate)
        dcb.ByteSize = ctypes.c_byte(self.bytesize)
        dcb.Parity = ctypes.c_byte(PARITY_BITS.get(self.parity, 0))
        dcb.StopBits = ctypes.c_byte(STOP_BITS.get(self.stopbits, 0))
        flags = 0x00000001                      # fBinary = 1
        if self.parity != "N":
            flags |= 0x00000002                 # fParity = 1
        flags |= (0x1 if self.dtr else 0x0) << 4    # fDtrControl
        flags |= (0x1 if self.rts else 0x0) << 12   # fRtsControl
        dcb.Flags = flags
        dcb.XonChar = b"\x11"
        dcb.XoffChar = b"\x13"
        if not k32.SetCommState(h, ctypes.byref(dcb)):
            self.close()
            raise OSError(f"SetCommState 失败（检查波特率/校验位是否被驱动支持）：{self.device}")

        tmo = COMMTIMEOUTS()
        tmo.ReadIntervalTimeout = 50
        tmo.ReadTotalTimeoutMultiplier = 0
        tmo.ReadTotalTimeoutConstant = int(self.timeout * 1000)
        tmo.WriteTotalTimeoutMultiplier = 0
        tmo.WriteTotalTimeoutConstant = int(self.timeout * 1000)
        k32.SetCommTimeouts(h, ctypes.byref(tmo))
        k32.PurgeComm(h, 0x0008 | 0x0004)       # PURGE_RXCLEAR | PURGE_TXCLEAR

    def _open_posix(self):
        import termios
        fd = os.open(self.device, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        attrs = termios.tcgetattr(fd)
        speed = getattr(termios, f"B{self.baudrate}", termios.B115200)
        attrs[0] = attrs[1] = attrs[3] = 0
        attrs[2] = termios.CLOCAL | termios.CREAD | self.bytesize_to_csize()
        if self.parity == "E":
            attrs[2] |= termios.PARENB | termios.PARODD if False else termios.PARENB
        elif self.parity == "O":
            attrs[2] |= termios.PARENB | termios.PARODD
        attrs[4] = speed
        attrs[5] = speed
        vmin = int(self.stopbits == "2")
        attrs[6] = list(attrs[6])
        attrs[6][termios.VMIN] = 0
        attrs[6][termios.VTIME] = max(1, int(self.timeout * 10))
        termios.tcsetattr(fd, termios.TCSANOW, attrs)
        self._fd = fd

    def bytesize_to_csize(self):
        import termios
        return {5: termios.CS5, 6: termios.CS6, 7: termios.CS7, 8: termios.CS8}.get(
            self.bytesize, termios.CS8)

    def close(self):
        if self._handle and IS_WIN:
            try:
                self._k32.CloseHandle(self._handle)
            except Exception:
                pass
            self._handle = None
        if self._fd is not None and not IS_WIN:
            try:
                os.close(self._fd)
            except Exception:
                pass
            self._fd = None

    def __enter__(self):
        return self.open()

    def __exit__(self, *exc):
        self.close()

    # -- I/O --------------------------------------------------------------
    def read(self, size: int = 512) -> bytes:
        if IS_WIN:
            buf = ctypes.create_string_buffer(size)
            n = wintypes.DWORD(0)
            ok = self._k32.ReadFile(self._handle,
                                    ctypes.cast(buf, ctypes.c_void_p),
                                    size, ctypes.byref(n), None)
            if not ok:
                return b""
            return buf.raw[:n.value]
        else:
            try:
                return os.read(self._fd, size)
            except BlockingIOError:
                return b""

    def write(self, data: bytes) -> int:
        if IS_WIN:
            n = wintypes.DWORD(0)
            ok = self._k32.WriteFile(self._handle,
                                     ctypes.cast(ctypes.c_char_p(data),
                                                 ctypes.c_void_p),
                                     len(data), ctypes.byref(n), None)
            return n.value if ok else 0
        return os.write(self._fd, data)

    def reset_input(self):
        if IS_WIN:
            self._k32.PurgeComm(self._handle, 0x0008)   # PURGE_RXCLEAR

    def readline(self, max_len: int = 4096) -> bytes:
        """读一行（以 \\n 结束）。"""
        buf = b""
        deadline = time.time() + max(self.timeout * 4, 1.0)
        while time.time() < deadline and len(buf) < max_len:
            chunk = self.read(256)
            if chunk:
                buf += chunk
                if b"\n" in buf:
                    break
            else:
                time.sleep(0.005)
        return buf


# --------------------------------------------------------------------------
# 3. 高层操作
# --------------------------------------------------------------------------
def do_ports(as_json: bool = False, root=None) -> int:
    ports = list_ports()
    if as_json:
        print(json.dumps(ports, ensure_ascii=False, indent=2))
        return 0
    if not ports:
        print("未检测到任何串口。")
        print("  · 确认 USB-TTL / ST-Link 已连接")
        print("  · 确认驱动已安装（CH340 / CP210x / FTDI）")
        return 1
    print(f"检测到 {len(ports)} 个串口：")
    for p in ports:
        chip = f" [{p['chip']}]" if p["chip"] else ""
        vidpid = f" vid:pid={p['vid']}:{p['pid']}" if p["vid"] else ""
        print(f"  {p['device']:<8} {p['description']}{chip}{vidpid}")
    pref_cfg = cfg_preferred_ports(root)
    pref = [d for d in pref_cfg
            if str(d).upper() in {p['device'].upper() for p in ports}]
    if pref:
        print(f"\n优先候选（来自项目配置 preferredPorts）：{', '.join(pref)}")
    elif pref_cfg:
        print(f"\n⚠️ 项目配置的 preferredPorts（{', '.join(map(str, pref_cfg))}）"
              f"当前均未检测到")
        print("   → 自动探测会失败并要求显式 --port。这是刻意设计：不猜测端口，"
              "避免静默连错设备")
    else:
        print("\n注：项目未配置 preferredPorts（.ef-guardian.json），"
              "自动探测仅在「唯一端口」时才生效。")
    if any(p["source"] == "winreg" for p in ports):
        print("\n注：当前位置无 pyserial，端口由 Windows 注册表枚举。")
        print("    注册表会列出**未连接的蓝牙虚拟串口**，这类端口打开时会报 Win32 121；")
        print("    若 BLE 模块（如 JDY-23）需调试，请先在系统里配对并建立 SPP 连接。")
    return 0


def do_watch(port: str, baud: int, parity: str, seconds: float,
             expect_fields: int | None = None, raw: bool = False) -> int:
    """只读监听：不发送任何数据。"""
    collected = 0
    bad = 0
    t0 = time.time()
    try:
        sp = SerialPort(port, baud, parity=parity).open()
    except OSError as exc:
        print(f"[watch] 打开失败：{exc}")
        print("[watch] 提示：`ef_dev.py ports` 可列出可用串口；"
              "若端口被 Keil 调试器占用，请先断开调试会话")
        return 2
    with sp:
        print(f"[watch] 打开 {port} @ {baud} 8{parity}1（只读，不发送任何命令）")
        buf = b""
        while time.time() - t0 < seconds:
            chunk = sp.read(512)
            if not chunk:
                continue
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                text = line.decode("utf-8", "replace").strip().strip("\r")
                if not text:
                    continue
                collected += 1
                if raw:
                    print(text[:160])
                    continue
                n = len(text.split(","))
                if expect_fields and n != expect_fields:
                    bad += 1
                    if bad <= 5:
                        print(f"  [异常行 {n} 字段] {text[:100]}")
                elif collected <= 5 or collected % 50 == 0:
                    print(f"  [{collected}] {text[:120]}")
    dur = time.time() - t0
    rate = collected / dur if dur else 0
    print(f"[watch] 收到 {collected} 行 / {dur:.1f}s ≈ {rate:.1f} 行/秒")
    if expect_fields:
        print(f"[watch] 字段数不符 {bad} 行"
              + ("（若 >0 说明固件输出格式与预期不一致）" if bad else " ✅"))
        if bad == 0 and collected == 0:
            print("[watch] ⚠️ 一行都没收到：检查波特率、TX/RX 是否交叉、固件是否在输出")
    return 0 if collected else 1


def do_capture(port: str, baud: int, parity: str, out: str, seconds: float,
               expect_fields: int | None = None, max_lines: int | None = None,
               reconnect: int = 3, firmware: str | None = None) -> int:
    """采集到 CSV，并写旁车元数据。保持 CSV 格式与既有管线兼容。"""
    outp = Path(out)
    outp.parent.mkdir(parents=True, exist_ok=True)
    started = time.strftime("%Y-%m-%d %H:%M:%S")
    lines_written = 0
    bad_lines = 0
    reconnects = 0
    header = None

    attempt = 0
    t0 = time.time()
    with outp.open("w", encoding="utf-8", newline="") as fh:
        while attempt <= reconnect and time.time() - t0 < seconds:
            try:
                sp = SerialPort(port, baud, parity=parity).open()
            except OSError as exc:
                print(f"[capture] 打开失败：{exc}")
                return 2
            buf = b""
            port_closed = False
            while time.time() - t0 < seconds:
                if max_lines and lines_written >= max_lines:
                    port_closed = True
                    break
                try:
                    chunk = sp.read(512)
                except OSError:
                    port_closed = True
                    break
                if not chunk:
                    # 连续空读超过 15 秒视为掉线
                    if getattr(sp, "_idle", 0) > 15.0:
                        port_closed = True
                        break
                    sp._idle = getattr(sp, "_idle", 0) + 0.05
                    continue
                sp._idle = 0
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    text = line.decode("utf-8", "replace").strip().strip("\r")
                    if not text or text.startswith("["):
                        continue
                    if expected_fields and len(text.split(",")) != expected_fields:
                        bad_lines += 1
                        continue
                    if header is None and not text[0].isdigit() and not text[0] == "-":
                        header = text
                    fh.write(text + "\n")
                    lines_written += 1
            sp.close()
            if max_lines and lines_written >= max_lines:
                break
            if time.time() - t0 >= seconds:
                break
            if port_closed:
                attempt += 1
                if attempt > reconnect:
                    break
                reconnects += 1
                print(f"[capture] 连接中断，重连第 {attempt} 次…")
                time.sleep(1.0)

    meta = {
        "csv": str(outp),
        "port": port, "baudrate": baud, "frame": f"8{parity}1",
        "started_at": started,
        "ended_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "duration_s": round(time.time() - t0, 2),
        "lines": lines_written,
        "dropped_bad_lines": bad_lines,
        "reconnects": reconnects,
        "expected_fields": expect_fields,
        "header": header,
        "firmware_hint": firmware or "",
        "tool": "embedded-flow-guardian/ef_serial.py",
    }
    meta_path = outp.with_suffix(outp.suffix + ".meta.json")
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2),
                         encoding="utf-8")

    print(f"[capture] 写入 {lines_written} 行 → {outp}")
    if bad_lines:
        print(f"[capture] 丢弃字段数不符的行 {bad_lines} 条")
    if reconnects:
        print(f"[capture] 断线重连 {reconnects} 次（已记录到元数据）")
    print(f"[capture] 元数据 → {meta_path.name}")
    print("[capture] 提示：采集元数据是「关键节点留痕」的一部分；"
          "排障时应连同元数据一起归档")
    return 0 if lines_written else 1


def do_send(port: str, baud: int, parity: str, payload: str, confirm: bool) -> int:
    """发送一条命令。默认拒绝，必须显式 --yes。"""
    if not confirm:
        print("[send] 已拒绝：发送命令会驱动飞控，存在风险。")
        print("       确认安全（如桨叶已取下、无人靠近）后，加 --yes 重试。")
        return 2
    data = payload.encode("utf-8").decode("unicode_escape").encode("latin-1")
    if not data.endswith(b"\n"):
        data += b"\n"
    with SerialPort(port, baud, parity=parity) as sp:
        n = sp.write(data)
    print(f"[send] 已发送 {n} 字节到 {port}")
    return 0 if n else 1


# --------------------------------------------------------------------------
def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="ef_serial — 串口检索/监听/采集（只读优先）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("ports", help="枚举串口")
    p.add_argument("--json", action="store_true")
    p.add_argument("--path", default=".", help="项目根（用于读取 preferredPorts）")

    for name, help_text in (("watch", "只读监听"), ("capture", "采集到 CSV")):
        sp = sub.add_parser(name, help=help_text)
        sp.add_argument("--port", default=None,
                        help="串口号；缺省时按项目配置 preferredPorts 探测，"
                             "未配置则仅当存在唯一端口时自动选用")
        sp.add_argument("--baud", type=int, default=921600)
        sp.add_argument("--parity", default="N", choices=["N", "E", "O"])
        sp.add_argument("--seconds", type=float, default=6.0)
        sp.add_argument("--fields", type=int, default=None,
                        help="期望字段数（不符即告警/丢弃）；缺省读取项目配置 "
                             "telemetryFields，未配置则不校验")
        sp.add_argument("--path", default=".", help="项目根（用于读取配置）")
        if name == "watch":
            sp.add_argument("--raw", action="store_true", help="只打印原始行")
        else:
            sp.add_argument("--out", required=True, help="输出 CSV 路径")
            sp.add_argument("--max-lines", type=int, default=None)
            sp.add_argument("--reconnect", type=int, default=3, help="断线重连次数")
            sp.add_argument("--firmware", default=None, help="固件版本标注（写入元数据）")

    s = sub.add_parser("send", help="发送一条命令（需 --yes）")
    s.add_argument("--port", required=True)
    s.add_argument("--baud", type=int, default=921600)
    s.add_argument("--parity", default="N", choices=["N", "E", "O"])
    s.add_argument("--data", required=True)
    s.add_argument("--yes", action="store_true", help="确认已采取安全措施")

    args = ap.parse_args(argv)

    if args.cmd == "ports":
        return do_ports(args.json, args.path)

    if args.cmd in ("watch", "capture"):
        port = args.port
        if not port:
            port, ports = auto_detect(root=args.path)
            if not port:
                names = ", ".join(p["device"] for p in ports) or "(无)"
                print(f"[ef_serial] 未自动探测到唯一串口（候选：{names}）")
                print("           请用 --port 显式指定；用 `ef_dev.py ports` 查看列表；"
                      "或在 .ef-guardian.json 配置 preferredPorts")
                return 2
            print(f"[ef_serial] 自动选用 {port}")
        fields = args.fields if args.fields is not None else cfg_telemetry_fields(args.path)
        if args.cmd == "watch":
            return do_watch(port, args.baud, args.parity, args.seconds,
                            fields, args.raw)
        return do_capture(port, args.baud, args.parity, args.out, args.seconds,
                          fields, args.max_lines, args.reconnect, args.firmware)

    if args.cmd == "send":
        return do_send(args.port, args.baud, args.parity, args.data, args.yes)
    return 2


if __name__ == "__main__":
    sys.exit(main())
