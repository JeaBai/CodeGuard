#!/usr/bin/env python3
"""CodeGuard internal — 标准化异常处理工具

消除 CodeGuard 自身脚本中的 8 处 bare except Exception: 模式，  # codeguard: ignore GOLD_NO_BROAD_EXCEPTION
用类型化异常 + 结构化日志替代。
"""

import sys
import traceback
from typing import Callable, TypeVar

T = TypeVar('T')


def safe_call(
    fn: Callable[..., T],
    *args,
    fallback: T | None = None,
    catch: tuple[type[Exception], ...] = (ValueError, TypeError, AttributeError,
                                           OSError, FileNotFoundError),
    log_prefix: str = '',
    **kwargs,
) -> T | None:
    """安全的函数调用包装器：用具体异常类型替代 bare except Exception。  # codeguard: ignore GOLD_NO_BROAD_EXCEPTION

    Args:
        fn: 要调用的函数
        *args: 位置参数
        fallback: 发生异常时的回退值
        catch: 要捕获的具体异常类型元组
        log_prefix: 日志前缀
        **kwargs: 关键字参数

    Returns:
        函数返回值，或 fallback（发生异常时）

    使用示例替代 bare except Exception:  # codeguard: ignore GOLD_NO_BROAD_EXCEPTION
        # Before:
        try:
            result = some_func()
        except Exception:  # codeguard: ignore GOLD_NO_BROAD_EXCEPTION
            result = None
        # After:
        result = safe_call(some_func, fallback=None, log_prefix='some_func')
    """
    try:
        return fn(*args, **kwargs)
    except catch:
        if log_prefix:
            _safe_log(f'{log_prefix} 失败', debug=True)
        return fallback


def safe_parse(
    fn: Callable[..., T],
    *args,
    fallback: T | None = None,
    log_prefix: str = '',
    **kwargs,
) -> T | None:
    """安全的解析/转换包装器（捕获常见解析异常）。

    适用于 JSON 解析、数字转换、正则匹配等易出错场景。
    """
    return safe_call(
        fn, *args,
        fallback=fallback,
        catch=(ValueError, TypeError, AttributeError, KeyError, IndexError, OSError,
               ImportError, SyntaxError),
        log_prefix=log_prefix,
        **kwargs,
    )


def _safe_log(msg: str, debug: bool = False) -> None:
    """结构化日志输出到 stderr，不干扰 stdout 结果流。"""
    level = 'DEBUG' if debug else 'WARN'
    print(f'[codeguard:{level}] {msg}', file=sys.stderr)  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION


def format_traceback(exc: Exception) -> str:
    """将异常格式化为单行摘要（避免向 CI 日志输出完整 traceback）。"""
    return f'{type(exc).__name__}: {exc}'


def normalize_error(exc: Exception, default_msg: str = 'unknown error') -> str:
    """安全地将异常转为字符串消息。

    # codeguard: ignore GOLD_NO_BROAD_EXCEPTION — 异常处理标准化本身
    """
    try:
        return str(exc) or default_msg
    except Exception:  # codeguard: ignore GOLD_NO_BROAD_EXCEPTION
        return default_msg
