#!/usr/bin/env python3
"""检测器插件注册器。

提供装饰器接口，允许检测器函数自注册到全局注册表。
按方言(dialect)和类别(category)分组管理检测器。

用法:
    @register_detector("embedded", "isr")
    def _check_isr_priority(file_path, content, findings):
        ...

    detectors = get_detectors("embedded", "isr")
"""
from typing import Dict, List, Callable


# 全局注册表: {dialect: {category: [detector_func, ...]}}
_REGISTRY: Dict[str, Dict[str, List[Callable]]] = {}


def register_detector(dialect: str, category: str = 'general') -> Callable:
    """检测器注册装饰器。

    Args:
        dialect: 代码方言 (如 "c", "embedded", "rust-embedded", "generic")
        category: 检测类别 (如 "isr", "memory", "misra", "security")

    Returns:
        装饰器函数
    """
    def decorator(func: Callable) -> Callable:
        if dialect not in _REGISTRY:
            _REGISTRY[dialect] = {}
        if category not in _REGISTRY[dialect]:
            _REGISTRY[dialect][category] = []
        _REGISTRY[dialect][category].append(func)
        # 标记函数为已注册的检测器
        func._detector_dialect = dialect
        func._detector_category = category
        return func

    return decorator


def get_detectors(dialect: str, category: str = None) -> List[Callable]:
    """获取指定方言（和类别）的检测器列表。

    Args:
        dialect: 代码方言
        category: 检测类别（None则返回该方言所有类别的检测器）

    Returns:
        检测器函数列表
    """
    if dialect not in _REGISTRY:
        return []

    if category is not None:
        return _REGISTRY[dialect].get(category, [])

    # 返回所有类别的检测器
    all_detectors = []
    for cat_detectors in _REGISTRY[dialect].values():
        all_detectors.extend(cat_detectors)
    return all_detectors


def get_registered_dialects() -> List[str]:
    """获取所有已注册的方言列表。"""
    return list(_REGISTRY.keys())


def get_registered_categories(dialect: str) -> List[str]:
    """获取指定方言下所有已注册的类别。"""
    if dialect not in _REGISTRY:
        return []
    return list(_REGISTRY[dialect].keys())


def clear_registry():
    """清空注册表（仅用于测试）。"""
    _REGISTRY.clear()


def get_registry_info() -> Dict:
    """获取注册表统计信息。"""
    info = {}
    for dialect, categories in _REGISTRY.items():
        info[dialect] = {
            cat: len(dets) for cat, dets in categories.items()
        }
    return info
