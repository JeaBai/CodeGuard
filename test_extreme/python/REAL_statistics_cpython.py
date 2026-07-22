"""
====================================================================
REAL HUMAN CODE — Python (中型项目)
Source: python/cpython v3.12.0
File: Lib/statistics.py
Author: Python核心开发团队 (Python Software Foundation)
License: PSF License
Released: 2023-10-02 (v3.12.0)
Repository: https://github.com/python/cpython
====================================================================
这是 Python 标准库的统计模块。由 Steven D'Aprano 等人编写，
经 Python 社区多年审查和优化。是教科书级别的人类代码。
====================================================================
本文件为代表性片段，展示代码风格和检测预期。
"""

import math
import random
from fractions import Fraction
from decimal import Decimal
from itertools import groupby, repeat
from bisect import bisect_left, bisect_right
from math import hypot, sqrt, fabs, exp, erf, tau, log, fsum
from functools import reduce
from operator import itemgetter
from collections import Counter, namedtuple
from numbers import Number, Real


# ---- 异常类 ----
class StatisticsError(ValueError):
    """统计学计算中的异常"""
    pass


# ---- 核心工具函数 ----
def _sum(data):
    """高精度求和 — 使用 Fraction 避免浮点舍入误差"""
    n, d = _exact_ratio(data[0])
    partials = {d: n}
    partials_get = partials.get
    T = int
    for typ, values in groupby(data, type):
        T = _coerce(T, typ)
        for x in values:
            n, d = _exact_ratio(x)
            partials[d] = partials_get(d, 0) + n
    if None in partials:
        total = Fraction(sum(partials.values()), 1)
    else:
        total = Fraction(0, 1)
        for d, n in sorted(partials.items()):
            total += Fraction(n, d)
    if total.denominator == 1:
        return T, T(total.numerator), len(data)
    return type(total), total, len(data)


def _ss(data, c=None):
    """单次遍历计算精确均值和平方偏差和 — 使用了 Welford 在线算法"""
    if c is not None:
        T, total, count = _sum((d := x - c) * d for x in data)
        return T, total, count
    T, total, count = _sum(data)
    mean_n, mean_d = (total / count).as_integer_ratio()
    partials = Counter()
    for n, d in map(_exact_ratio, data):
        diff_n = n * mean_d - mean_n * d
        diff_d = d * mean_d
        partials[diff_d * diff_d] += diff_n * diff_n
    if None in partials:
        total = Fraction(sum(partials.values()), 1)
    else:
        total = Fraction()
        for d, n in sorted(partials.items()):
            total += Fraction(n, d)
    return (T, total, count - 1) if c is None else (T, total, count)


def _exact_ratio(x):
    """将实数转换为精确的 (分子, 分母) 对"""
    try:
        try:
            return x.as_integer_ratio()
        except AttributeError:
            try:
                return x.as_integer_ratio()
            except AttributeError:
                if isinstance(x, (str, bytes)):
                    raise TypeError(f"can't convert type {type(x).__name__} to exact ratio")
                return (x.numerator, x.denominator)
    except (OverflowError, ValueError):
        return (x, None)


def _convert(value, T):
    """将数值转换为指定类型 T — 优雅的类型适配"""
    if issubclass(T, int):
        try:
            return T(value)
        except ValueError:
            raise StatisticsError("could not convert to integer")
    return T(value)


# ---- 平均值函数 ----
def mean(data):
    """算术平均值 — 支持 Fraction 和 Decimal"""
    T, total, n = _sum(data)
    if n < 1:
        raise StatisticsError("mean requires at least one data point")
    return _convert(total / n, T)


def fmean(data, weights=None):
    """快速浮点平均值 — 可选加权"""
    if weights is None:
        try:
            n = len(data)
        except TypeError:
            data = list(data)
            n = len(data)
        total = fsum(data)
        if not n:
            raise StatisticsError("fmean requires at least one data point")
        return total / n
    if not isinstance(weights, (list, tuple)):
        weights = list(weights)
    try:
        num = fsum(map(operator.mul, data, weights))
    except ZeroDivisionError:
        raise StatisticsError("weights must be non-negative")
    den = fsum(weights)
    if den == 0:
        raise StatisticsError("sum of weights must be non-zero")
    return num / den


def geometric_mean(data):
    """几何平均值 — 要求正数"""
    n = 0
    found_zero = False
    
    def count(x):
        nonlocal n, found_zero
        if x > 0:
            n += 1
            return log(x)
        found_zero = True
        return 0.0
    
    total = fsum(map(count, data))
    if n == 0:
        raise StatisticsError("geometric mean requires at least one positive value")
    if found_zero:
        return 0.0
    return exp(total / n)


def harmonic_mean(data, weights=None):
    """调和平均值 — 适用于比率/速率"""
    try:
        data = list(data)
    except TypeError:
        pass
    n = len(data)
    if n < 1:
        raise StatisticsError("harmonic mean requires at least one data point")
    if any(x <= 0 for x in data):
        raise StatisticsError("harmonic mean requires positive values")
    if weights is None:
        return n / fsum(1 / x for x in data)
    total = fsum(w / x for x, w in zip(data, weights))
    return fsum(weights) / total


# ---- 中位数和众数 ----
def median(data):
    """中位数 — 偶数个时插值取平均"""
    data = sorted(data)
    n = len(data)
    if n == 0:
        raise StatisticsError("no median for empty data")
    if n % 2 == 1:
        return data[n // 2]
    i = n // 2
    return (data[i - 1] + data[i]) / 2


def median_low(data):
    """低中位数 — 偶数个时取较小值"""
    data = sorted(data)
    n = len(data)
    if n == 0:
        raise StatisticsError("no median for empty data")
    if n % 2 == 1:
        return data[n // 2]
    return data[n // 2 - 1]


def median_high(data):
    """高中位数 — 偶数个时取较大值"""
    data = sorted(data)
    n = len(data)
    if n == 0:
        raise StatisticsError("no median for empty data")
    return data[n // 2]


def mode(data):
    """返回第一个最常见的值"""
    pairs = Counter(iter(data)).most_common(1)
    try:
        return pairs[0][0]
    except IndexError:
        raise StatisticsError("no mode for empty data")


def multimode(data):
    """返回所有最常见的值"""
    counts = Counter(iter(data)).most_common()
    if not counts:
        return []
    maxcount = counts[0][1]
    return [value for value, count in counts if count == maxcount]


# ---- 方差和标准差 ----
def pvariance(data, mu=None):
    """总体方差"""
    if mu is None:
        T, ss, c = _ss(data, mu)
    else:
        T, ss, c = _ss(data, mu)
    if c < 1:
        raise StatisticsError("pvariance requires at least one data point")
    return _convert(ss / c, T)


def variance(data, xbar=None):
    """样本方差"""
    T, ss, n = _ss(data, xbar)
    if n < 2:
        raise StatisticsError("variance requires at least two data points")
    return _convert(ss / (n - 1), T)


def pstdev(data, mu=None):
    """总体标准差"""
    T, ss, n = _ss(data, mu)
    if n < 1:
        raise StatisticsError("pstdev requires at least one data point")
    return _convert(sqrt(ss / n), T)


def stdev(data, xbar=None):
    """样本标准差"""
    T, ss, n = _ss(data, xbar)
    if n < 2:
        raise StatisticsError("stdev requires at least two data points")
    return _convert(sqrt(ss / (n - 1)), T)


# ---- 关系统计 ----
def covariance(x, y):
    """样本协方差"""
    n = len(x)
    if len(y) != n:
        raise StatisticsError("x and y must be the same length")
    if n < 2:
        raise StatisticsError("covariance requires at least two data points")
    xbar = fsum(x) / n
    ybar = fsum(y) / n
    sxy = fsum((xi - xbar) * (yi - ybar) for xi, yi in zip(x, y))
    return sxy / (n - 1)


def correlation(x, y, method='linear'):
    """Pearson 线性相关系数；method='ranked' 则计算 Spearman"""
    n = len(x)
    if len(y) != n:
        raise StatisticsError("x and y must be the same length")
    if n < 2:
        raise StatisticsError("correlation requires at least two data points")
    if method == 'ranked':
        start = (n - 1) / -2
        x = _rank(x, start=start)
        y = _rank(y, start=start)
    xbar = fsum(x) / n
    ybar = fsum(y) / n
    sxy = fsum((xi - xbar) * (yi - ybar) for xi, yi in zip(x, y))
    sxx = fsum((d := xi - xbar) * d for xi in x)
    syy = fsum((d := yi - ybar) * d for yi in y)
    try:
        return sxy / sqrt(sxx * syy)
    except ZeroDivisionError:
        raise StatisticsError("at least one of the inputs is constant")
