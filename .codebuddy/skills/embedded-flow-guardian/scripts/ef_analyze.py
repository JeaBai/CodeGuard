#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ef_analyze.py — 遥测数据采集后的通用分析（零第三方依赖）

本机无 numpy / matplotlib，因此：
  - **FFT 自实现**（迭代式基-2 Cooley-Tukey）+ Hann 窗，用于振动频谱
  - **PNG 自实现**（zlib + struct 手写编码器），用于输出频谱/时序图
  - 统计、分箱、异常段、双采集对比全部用标准库

自动兼容工程里已有的三种 CSV 形态：
  1. 遥测 27 列：t_s,gyroX,…,sbus5,isArmed,flags
  2. 高频陀螺 4 列：t_pc_s,gx,gy,gz
  3. 倾斜 12 列：t_s,gyroX,…,roll,pitch,…
并会自动读取 `*.csv.meta.json` 旁车元数据（若存在）。

设计取向（源自调研结论）：**不只看均值**。
  - 看零偏（静置时是否漂移）
  - 看异常段（间歇性问题才是嵌入式最难缠的对手）
  - 看频谱峰值（机械振动/控制振荡在频域最清楚）
"""
from __future__ import annotations

import csv
import json
import math
import struct
import sys
import zlib
from pathlib import Path

# --------------------------------------------------------------------------
# 1. 载入
# --------------------------------------------------------------------------
def load_csv(path: str):
    """读取 CSV，返回 (header, columns: dict[str, list[float]], meta: dict)。

    自动跳过 `#` 注释行与空行；非数值单元格按缺失处理（记为 None 并从该列剔除）。
    """
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"CSV 不存在: {p}")
    header, rows = None, []
    with p.open(encoding="utf-8", errors="replace", newline="") as fh:
        for line in fh:
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            parts = next(csv.reader([s]))
            if header is None:
                header = parts
                continue
            rows.append(parts)
    if header is None:
        raise ValueError("空文件或无表头")

    cols = {h: [] for h in header}
    for r in rows:
        for i, h in enumerate(header):
            cell = r[i].strip() if i < len(r) else ""
            try:
                cols[h].append(float(cell))
            except ValueError:
                cols[h].append(None)

    meta_path = p.with_suffix(p.suffix + ".meta.json")
    meta = {}
    if meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            meta = {}
    meta["_source"] = str(p)
    meta["_rows"] = len(rows)
    return header, cols, meta


def numeric_cols(cols):
    return [k for k, v in cols.items()
            if any(x is not None for x in v)]


def clean(series):
    return [x for x in series if x is not None]


# --------------------------------------------------------------------------
# 2. 统计
# --------------------------------------------------------------------------
def describe(series):
    """基础统计（忽略缺失值）。"""
    xs = clean(series)
    n = len(xs)
    if n == 0:
        return {"n": 0}
    mean = sum(xs) / n
    var = sum((x - mean) ** 2 for x in xs) / n
    srt = sorted(xs)
    return {
        "n": n,
        "min": srt[0], "max": srt[-1],
        "mean": mean,
        "std": math.sqrt(var),
        "rms": math.sqrt(sum(x * x for x in xs) / n),
        "p50": srt[n // 2],
        "p95": srt[min(n - 1, int(n * 0.95))],
        "peak_to_peak": srt[-1] - srt[0],
    }


def by_bins(cols, xkey, ykeys, nbins: int = 6):
    """按 xkey 分箱，统计各 ykey 的均值/标准差。用于「按油门分档看振动」这类分析。"""
    xs = cols.get(xkey)
    if xs is None:
        return []
    xv = clean(xs)
    if not xv:
        return []
    lo, hi = min(xv), max(xv)
    if hi <= lo:
        return []
    width = (hi - lo) / nbins
    buckets = [[] for _ in range(nbins)]
    for i, x in enumerate(xs):
        if x is None:
            continue
        idx = min(nbins - 1, int((x - lo) / width))
        for k in ykeys:
            v = cols.get(k, [None] * len(xs))[i]
            if v is not None:
                buckets[idx].append((k, v))
    out = []
    for i, b in enumerate(buckets):
        if not b:
            continue
        row = {"bin": i, "x_lo": lo + i * width, "x_hi": lo + (i + 1) * width,
               "n": len(b) // max(len(ykeys), 1)}
        for k in ykeys:
            vals = [v for kk, v in b if kk == k]
            if vals:
                m = sum(vals) / len(vals)
                row[k] = round(m, 4)
                row[k + "_std"] = round(
                    math.sqrt(sum((v - m) ** 2 for v in vals) / len(vals)), 4)
        out.append(row)
    return out


def anomaly_segments(series, tkey=None, times=None, k: float = 3.0,
                     min_len: int = 3):
    """找出偏离均值 k 倍标准差的连续段。

    嵌入式最难缠的是**间歇性**问题（Heisenbug / NFF）——整段统计量往往完全正常，
    只有分段才看得见。
    """
    xs = clean(series)
    if len(xs) < 10:
        return []
    m = sum(xs) / len(xs)
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / len(xs))
    if sd == 0:
        return []
    hi, lo = m + k * sd, m - k * sd
    segs, cur = [], None
    for i, x in enumerate(series):
        if x is None:
            continue
        if x > hi or x < lo:
            if cur is None:
                cur = {"start_idx": i, "end_idx": i, "peak": x,
                       "t_start": times[i] if times else None}
            else:
                cur["end_idx"] = i
                if abs(x) > abs(cur["peak"]):
                    cur["peak"] = x
        else:
            if cur is not None:
                if cur["end_idx"] - cur["start_idx"] + 1 >= min_len:
                    cur["t_end"] = times[cur["end_idx"]] if times else None
                    segs.append(cur)
                cur = None
    if cur is not None and cur["end_idx"] - cur["start_idx"] + 1 >= min_len:
        if times:
            cur["t_end"] = times[cur["end_idx"]]
        segs.append(cur)
    for s in segs:
        s["peak"] = round(s["peak"], 4)
        s["over"] = round(abs(s["peak"] - m) / sd, 2) if sd else 0
    return segs


# --------------------------------------------------------------------------
# 3. FFT（自实现，基-2 迭代）
# --------------------------------------------------------------------------
def _fft(re, im, inverse=False):
    n = len(re)
    j = 0
    for i in range(1, n):
        bit = n >> 1
        while j & bit:
            j ^= bit
            bit >>= 1
        j |= bit
        if i < j:
            re[i], re[j] = re[j], re[i]
            im[i], im[j] = im[j], im[i]
    length = 2
    while length <= n:
        ang = 2.0 * math.pi / length * (1.0 if inverse else -1.0)
        wr, wi = math.cos(ang), math.sin(ang)
        half = length >> 1
        for start in range(0, n, length):
            cr, ci = 1.0, 0.0
            for k in range(start, start + half):
                ur, ui = re[k], im[k]
                vr = re[k + half] * cr - im[k + half] * ci
                vi = re[k + half] * ci + im[k + half] * cr
                re[k], im[k] = ur + vr, ui + vi
                re[k + half], im[k + half] = ur - vr, ui - vi
                cr, ci = cr * wr - ci * wi, cr * wi + ci * wr
        length <<= 1


def spectrum(series, fs: float, window: str = "hann", max_n: int = 1 << 15):
    """计算幅度谱。

    Args:
        series: 采样序列（缺失值将被剔除）
        fs: 采样率 (Hz)
        window: "hann" 或 "none"
    Returns:
        (freqs, mags, fs_used)
    """
    xs = clean(series)
    if len(xs) < 16:
        return [], [], fs
    n = 1
    while n * 2 <= min(len(xs), max_n):
        n *= 2
    xs = xs[-n:]                       # 取尾部最新段
    if window == "hann":
        xs = [x * (0.5 - 0.5 * math.cos(2 * math.pi * i / (n - 1)))
              for i, x in enumerate(xs)]
    re, im = [float(v) for v in xs], [0.0] * n
    _fft(re, im)
    half = n // 2
    scale = 2.0 / n
    freqs = [i * fs / n for i in range(half)]
    mags = [math.hypot(re[i], im[i]) * scale for i in range(half)]
    return freqs, mags, fs


def top_peaks(freqs, mags, k: int = 6, min_freq: float = 1.0):
    """提取显著谱峰（简单局部极大 + 幅度排序）。"""
    cand = []
    for i in range(1, len(mags) - 1):
        if mags[i] > mags[i - 1] and mags[i] >= mags[i + 1] and freqs[i] >= min_freq:
            cand.append((mags[i], freqs[i]))
    cand.sort(reverse=True)
    out, used = [], []
    for m, f in cand:
        if any(abs(f - u) < max(2.0, f * 0.08) for u in used):
            continue
        used.append(f)
        out.append({"freq_hz": round(f, 2), "mag": round(m, 5)})
        if len(out) >= k:
            break
    return out


def estimate_fs(times):
    """从时间列估计采样率，并给出时间戳质量诊断。

    ⚠️ 实测教训：PC 侧时间戳常被量化（如 1 µs 分辨率），导致大量相邻间隔为 0。
    此时「中位间隔」会被严重低估——本项目某文件 11954 个间隔中有 5981 个为 0，
    中位间隔 1 µs 推出 1 MHz 的荒谬采样率，频谱随之全是混叠伪峰。
    因此这里在量化严重时**改用平均速率**（(n-1)/(末-首)），并把诊断回传。

    Returns:
        (fs: float, info: dict)
    """
    ts = clean(times)
    if len(ts) < 3:
        return 0.0, {}
    span = ts[-1] - ts[0]
    overall = (len(ts) - 1) / span if span > 0 else 0.0

    d = [ts[i + 1] - ts[i] for i in range(len(ts) - 1)]
    dup = sum(1 for x in d if x <= 0)
    pos = sorted(x for x in d if x > 0)
    med = pos[len(pos) // 2] if pos else 0.0
    med_fs = (1.0 / med) if med > 0 else 0.0
    dup_ratio = dup / max(len(d), 1)

    info = {
        "duplicate_ts": dup,
        "duplicate_ratio": round(dup_ratio, 4),
        "median_delta_s": med,
        "median_fs": round(med_fs, 1),
        "overall_fs": round(overall, 1),
    }

    # 量化严重 → 中位法不可信，改用平均速率
    if med_fs > overall * 3 and dup_ratio > 0.05:
        info["note"] = (
            f"时间戳量化严重（{dup_ratio:.0%} 相邻间隔为 0，中位间隔 {med:.2e}s），"
            f"已改用平均速率 {overall:.1f} Hz 估计采样率")
        return overall, info

    fs = med_fs if med_fs > 0 else overall
    if dup_ratio > 0.05:
        info["note"] = f"存在 {dup_ratio:.0%} 重复时间戳，采样率估计可能有偏差"
    return fs, info


# --------------------------------------------------------------------------
# 4. PNG（自实现最小编码器）
# --------------------------------------------------------------------------
class Canvas:
    """极简 RGB 画布 + 折线绘制。白底深线，适合报告插图。

    像素存放在扁平 bytearray（每像素 3 字节），比嵌套 list 省一个数量级内存。
    """

    def __init__(self, w: int, h: int, bg=(255, 255, 255)):
        self.w, self.h = w, h
        self.buf = bytearray(bytes(bg) * (w * h))
        self.stride = w * 3

    def setpx(self, x, y, c):
        if 0 <= x < self.w and 0 <= y < self.h:
            i = (y * self.w + x) * 3
            self.buf[i] = c[0]
            self.buf[i + 1] = c[1]
            self.buf[i + 2] = c[2]

    def hline(self, x0, x1, y, c):
        for x in range(max(0, x0), min(self.w, x1) + 1):
            self.setpx(x, y, c)

    def vline(self, x, y0, y1, c):
        for y in range(max(0, y0), min(self.h, y1) + 1):
            self.setpx(x, y, c)

    def line(self, x0, y0, x1, y1, c):
        dx, dy = abs(x1 - x0), -abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx + dy
        while True:
            self.setpx(x0, y0, c)
            if x0 == x1 and y0 == y1:
                break
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x0 += sx
            if e2 <= dx:
                err += dx
                y0 += sy

    def rect(self, x0, y0, x1, y1, c):
        self.hline(x0, x1, y0, c)
        self.hline(x0, x1, y1, c)
        self.vline(x0, y0, y1, c)
        self.vline(x1, y0, y1, c)

    def save(self, path: str):
        raw = bytearray()
        for y in range(self.h):
            raw.append(0)                       # PNG 行过滤器类型 0（None）
            raw += self.buf[y * self.stride:(y + 1) * self.stride]

        def chunk(tag, data):
            return (struct.pack(">I", len(data)) + tag + data
                    + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

        png = (b"\x89PNG\r\n\x1a\n"
               + chunk(b"IHDR", struct.pack(">IIBBBBB", self.w, self.h, 8, 2, 0, 0, 0))
               + chunk(b"IDAT", zlib.compress(bytes(raw), 6))
               + chunk(b"IEND", b""))
        Path(path).write_bytes(png)
        return path


def plot_spectrum(path, freqs, mags, peaks=None, title=""):
    """绘制频谱图。"""
    if not freqs:
        return None
    w, h, pad = 900, 340, 46
    cv = Canvas(w, h)
    axis = (110, 120, 130)
    curve = (31, 95, 168)
    peak_c = (176, 42, 55)
    grid = (232, 236, 240)
    cv.rect(pad, 16, w - 20, h - pad, axis)
    xmax = max(freqs)
    ymax = max(mags) or 1.0
    for i in range(1, 5):
        y = 16 + int((h - pad - 16) * i / 5)
        cv.hline(pad, w - 20, y, grid)
        cv.vline(pad + int((w - 20 - pad) * i / 5), 16, h - pad, grid)

    def sx(f):
        return pad + int((f / xmax) * (w - 20 - pad))

    def sy(m):
        return h - pad - int((m / ymax) * (h - pad - 16))

    prev = None
    for f, m in zip(freqs, mags):
        p = (sx(f), sy(m))
        if prev:
            cv.line(prev[0], prev[1], p[0], p[1], curve)
        prev = p
    for pk in (peaks or []):
        x = sx(pk["freq_hz"])
        cv.vline(x, 16, h - pad, peak_c)
    cv.save(path)
    return path


def plot_series(path, series, times=None, title=""):
    """绘制时序折线（下采样到画布宽度）。"""
    xs = [(i, v) for i, v in enumerate(series) if v is not None]
    if len(xs) < 2:
        return None
    w, h, pad = 900, 300, 46
    cv = Canvas(w, h)
    axis = (110, 120, 130)
    curve = (31, 95, 168)
    zero = (200, 205, 210)
    cv.rect(pad, 16, w - 20, h - pad, axis)
    vals = [v for _, v in xs]
    vmin, vmax = min(vals), max(vals)
    span = (vmax - vmin) or 1.0
    step = max(1, len(xs) // (w - 20 - pad))

    def sy(v):
        return h - pad - int((v - vmin) / span * (h - pad - 20))

    if vmin <= 0 <= vmax:
        cv.hline(pad, w - 20, sy(0), zero)
    prev = None
    for i in range(0, len(xs), step):
        idx, v = xs[i]
        x = pad + int((i / max(len(xs) - 1, 1)) * (w - 20 - pad))
        p = (x, sy(v))
        if prev:
            cv.line(prev[0], prev[1], p[0], p[1], curve)
        prev = p
    cv.save(path)
    return path


# --------------------------------------------------------------------------
# 5. 报告
# --------------------------------------------------------------------------
def analyze(path: str, time_key: str | None = None, fft_keys=None,
            bin_key: str | None = None, outdir: str | None = None,
            top_n: int = 12, make_png: bool = True, fs_override: float | None = None):
    """主分析入口。返回 (report_dict, exit_code)。"""
    header, cols, meta = load_csv(path)
    nums = numeric_cols(cols)

    if time_key is None:
        for cand in ("t_s", "t_pc_s", "time", "t"):
            if cand in cols:
                time_key = cand
                break
    times = cols.get(time_key) if time_key else None
    fs, fs_info = estimate_fs(times) if times else (0.0, {})
    if fs_override:
        fs_info = dict(fs_info, override_hz=fs_override,
                       note=f"采样率由命令行指定为 {fs_override} Hz")
        fs = float(fs_override)

    report = {
        "source": path,
        "meta": meta,
        "rows": meta.get("_rows", 0),
        "time_key": time_key,
        "estimated_fs_hz": round(fs, 1),
        "fs_quality": fs_info,
        "total_estimated_s": round((times[-1] - times[0]), 3) if times and len(clean(times)) > 1 else None,
        "columns": {},
    }

    # 逐列统计（跳过纯时间列）
    targets = [c for c in nums if c != time_key][:top_n]
    for c in targets:
        report["columns"][c] = describe(cols[c])

    # 分箱
    if bin_key and bin_key in cols:
        yk = [c for c in targets if c != bin_key][:4]
        report["bins"] = {"x": bin_key, "y": yk,
                          "data": by_bins(cols, bin_key, yk)}

    # 异常段（对所有目标列做，取最显著的前几段）
    segs = {}
    for c in targets:
        s = anomaly_segments(cols[c], times=times, k=3.0)
        if s:
            segs[c] = s[:3]
    if segs:
        report["anomaly_segments"] = segs

    # FFT
    if fft_keys is None:
        fft_keys = [c for c in targets
                    if any(t in c.lower() for t in ("gyro", "gx", "gy", "gz",
                                                    "accel", "ax", "ay", "az"))][:3]
    if fs > 0 and fft_keys:
        report["fft"] = {}
        for c in fft_keys:
            if c not in cols:
                continue
            freqs, mags, _ = spectrum(cols[c], fs)
            if not freqs:
                continue
            pk = top_peaks(freqs, mags)
            report["fft"][c] = {"peaks": pk,
                                "bin_hz": round(fs / max(len(freqs) * 2, 1), 3)}
            if make_png:
                d = Path(outdir) if outdir else Path(path).parent
                png = d / f"{Path(path).stem}_fft_{c}.png"
                try:
                    plot_spectrum(str(png), freqs, mags, pk)
                    report["fft"][c]["png"] = str(png)
                except Exception as exc:
                    report["fft"][c]["png_error"] = str(exc)
    # 时序图（第一个目标列）
    if make_png and targets:
        d = Path(outdir) if outdir else Path(path).parent
        png = d / f"{Path(path).stem}_{targets[0]}.png"
        try:
            plot_series(str(png), cols[targets[0]], times)
            report["series_png"] = str(png)
        except Exception:
            pass

    return report, 0


def format_report(rep) -> str:
    L = []
    L.append("=" * 68)
    L.append("  ef_analyze 数据分析报告")
    L.append("=" * 68)
    L.append(f"  数据: {Path(rep['source']).name} | 行数 {rep['rows']}")
    if rep.get("meta", {}).get("port"):
        m = rep["meta"]
        L.append(f"  采集: {m.get('port')} @ {m.get('baudrate')} "
                 f"| {m.get('started_at')} → {m.get('ended_at')}")
        if m.get("reconnects"):
            L.append(f"  ⚠️ 采集期间断线重连 {m['reconnects']} 次（数据可能有缺口）")
        if m.get("dropped_bad_lines"):
            L.append(f"  ⚠️ 丢弃异常行 {m['dropped_bad_lines']} 条")
    L.append(f"  时间列: {rep.get('time_key')} | 采样率 {rep.get('estimated_fs_hz')} Hz"
             + (f" | 时长 {rep.get('total_estimated_s')} s" if rep.get("total_estimated_s") else ""))
    q = rep.get("fs_quality") or {}
    if q.get("note"):
        L.append(f"  ⚠️ 时间戳质量: {q['note']}")
        L.append(f"     重复时间戳 {q.get('duplicate_ts')} 个 "
                 f"({q.get('duplicate_ratio', 0):.1%})"
                 + f" | 中位法 {q.get('median_fs')} Hz vs 平均法 {q.get('overall_fs')} Hz")
        L.append("     若频谱峰值与物理常识不符（例如远高于 Nyquist），"
                 "请用 --fs 显式指定采样率")
    L.append("")
    L.append("  ── 列统计 ──")
    L.append(f"  {'列名':<14}{'均值':>12}{'标准差':>12}{'最小':>12}{'最大':>12}{'峰峰':>12}")
    for c, s in rep["columns"].items():
        if not s.get("n"):
            continue
        L.append(f"  {c:<14}{s['mean']:>12.3f}{s['std']:>12.3f}"
                 f"{s['min']:>12.3f}{s['max']:>12.3f}{s['peak_to_peak']:>12.3f}")

    if rep.get("anomaly_segments"):
        L.append("")
        L.append("  ── 异常段（>3σ，间歇性问题的第一线索）──")
        for c, segs in rep["anomaly_segments"].items():
            for s in segs:
                t0 = f"{s['t_start']:.2f}s" if s.get("t_start") is not None else f"idx {s['start_idx']}"
                t1 = f"{s['t_end']:.2f}s" if s.get("t_end") is not None else f"idx {s['end_idx']}"
                L.append(f"  {c:<12} {t0} → {t1}  峰值 {s['peak']:>10.3f} "
                         f"({s['over']}σ)")

    if rep.get("fft"):
        L.append("")
        L.append("  ── 频谱主峰 ──")
        for c, d in rep["fft"].items():
            names = "、".join(f"{p['freq_hz']}Hz" for p in d["peaks"][:5]) or "(无显著峰)"
            L.append(f"  {c:<12} {names}")
            if d.get("png"):
                L.append(f"               图: {Path(d['png']).name}")

    if rep.get("bins"):
        L.append("")
        L.append(f"  ── 按 {rep['bins']['x']} 分箱 ──")
        for row in rep["bins"]["data"]:
            vals = "  ".join(f"{k}={row[k]}" for k in rep["bins"]["y"] if k in row)
            L.append(f"  [{row['x_lo']:.2f},{row['x_hi']:.2f}) n={row['n']:<6} {vals}")

    L.append("")
    L.append("  提示：均值正常不等于没问题——间歇性故障只有分段/看 σ 倍数才显形。")
    return "\n".join(L)


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="ef_analyze — 遥测数据分析（零依赖）")
    ap.add_argument("csv", help="CSV 文件路径")
    ap.add_argument("--time-key", default=None, help="时间列名（默认自动识别 t_s/t_pc_s）")
    ap.add_argument("--fft", nargs="*", default=None, help="做 FFT 的列（默认自动选陀螺/加速度）")
    ap.add_argument("--bin", dest="bin_key", default=None,
                    help="按该列分箱（如 sbus3 油门）")
    ap.add_argument("--fs", type=float, default=None,
                    help="显式指定采样率 (Hz)，覆盖自动估计（时间戳量化严重时使用）")
    ap.add_argument("--outdir", default=None, help="PNG 与 JSON 输出目录")
    ap.add_argument("--json-out", default=None, help="把完整结果写入 JSON")
    ap.add_argument("--no-png", action="store_true", help="不生成图")
    args = ap.parse_args(argv)

    try:
        rep, rc = analyze(args.csv, args.time_key, args.fft, args.bin_key,
                          args.outdir, make_png=not args.no_png,
                          fs_override=args.fs)
    except Exception as exc:
        print(f"[ef_analyze] 分析失败: {exc}")
        return 2
    print(format_report(rep))
    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(rep, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8")
        print(f"\n[ef_analyze] JSON → {args.json_out}")
    if rep.get("series_png"):
        print(f"[ef_analyze] 时序图 → {rep['series_png']}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
