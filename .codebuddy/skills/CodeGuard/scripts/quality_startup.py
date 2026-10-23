# .codebuddy/skills/CodeGuard/scripts/quality_startup.py
"""启动文件分析模块。

解析startup_*.s汇编文件，检查:
- 中断向量表完整性
- 栈/堆大小配置
- 复位向量地址
"""
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'internal'))
from detector_registry import register_detector


def parse_startup_file(file_path: str) -> dict:
    """解析ARM Cortex-M启动汇编文件。

    Returns:
        {
            'vectors': list,       # 中断向量表
            'stack_size': int,     # 栈大小(字节)
            'heap_size': int,      # 堆大小(字节)
            'reset_handler': str,  # 复位处理函数名
            'has_weak': bool,      # 是否包含weak定义
        }
    """
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    result = {
        'vectors': [],
        'stack_size': 0,
        'heap_size': 0,
        'reset_handler': None,
        'has_weak': False,
    }

    # 提取栈大小
    stack_match = re.search(r'Stack_Size\s+EQU\s+0x([0-9a-fA-F]+)', content)
    if stack_match:
        result['stack_size'] = int(stack_match.group(1), 16)
    else:
        stack_match = re.search(r'Stack_Size\s+EQU\s+(\d+)', content)
        if stack_match:
            result['stack_size'] = int(stack_match.group(1))

    # 提取堆大小
    heap_match = re.search(r'Heap_Size\s+EQU\s+0x([0-9a-fA-F]+)', content)
    if heap_match:
        result['heap_size'] = int(heap_match.group(1), 16)
    else:
        heap_match = re.search(r'Heap_Size\s+EQU\s+(\d+)', content)
        if heap_match:
            result['heap_size'] = int(heap_match.group(1))

    # 提取中断向量表
    vector_section = re.search(r'__Vectors\s.*?__Vectors_End', content, re.DOTALL)
    if vector_section:
        vec_text = vector_section.group(0)
        vectors = re.findall(r'(?:DCD|DCB)\s+(\w+)', vec_text)
        result['vectors'] = vectors
        if vectors:
            result['reset_handler'] = vectors[1] if len(vectors) > 1 else None

    # 检查weak定义
    result['has_weak'] = bool(re.search(r'\.weak\s+', content))

    return result


@register_detector("embedded", "startup")
def _check_startup_vectors(file_path, content, findings):
    """检查启动文件中断向量表完整性。"""
    if not file_path.endswith('.s') and not file_path.endswith('.S'):
        return findings
    if 'startup' not in os.path.basename(file_path).lower():
        return findings

    try:
        info = parse_startup_file(file_path)
    except Exception as e:
        findings.append({
            'rule_id': 'EMBEDDED-STARTUP-001',
            'severity': 'medium',
            'message': f'启动文件解析失败: {e}',
            'location': file_path,
        })
        return findings

    # 检查最小向量数 (Cortex-M: SP + Reset + NMI + HardFault + ... >= 16)
    if len(info['vectors']) < 16:
        findings.append({
            'rule_id': 'EMBEDDED-STARTUP-002',
            'severity': 'high',
            'message': f'中断向量表不完整: 仅 {len(info["vectors"])} 个向量，Cortex-M至少需要16个',
            'location': file_path,
        })

    # 检查复位向量是否存在
    if not info['reset_handler']:
        findings.append({
            'rule_id': 'EMBEDDED-STARTUP-003',
            'severity': 'critical',
            'message': '未找到复位向量(Reset_Handler)',
            'location': file_path,
        })

    return findings


def _check_stack_too_small(info, file_path, findings):
    """检查栈大小是否过小（最小推荐 1KB = 0x400）。"""
    if info['stack_size'] > 0 and info['stack_size'] < 0x400:
        findings.append({
            'rule_id': 'EMBEDDED-STARTUP-004',
            'severity': 'high',
            'message': f'栈大小过小: {info["stack_size"]} 字节，建议至少 1024 字节(0x400)',
            'location': file_path,
            'suggestion': '增大Stack_Size到至少0x400',
        })


def _check_stack_too_large(info, file_path, findings):
    """检查栈大小是否过大（超过 32KB 可能浪费 RAM）。"""
    if info['stack_size'] > 0x8000:
        findings.append({
            'rule_id': 'EMBEDDED-STARTUP-005',
            'severity': 'medium',
            'message': f'栈大小过大: {info["stack_size"]} 字节，可能浪费RAM',
            'location': file_path,
        })


def _check_heap_large(info, file_path, findings):
    """检查堆大小是否过大（嵌入式通常不需大堆）。"""
    if info['heap_size'] > 0x4000:
        findings.append({
            'rule_id': 'EMBEDDED-STARTUP-006',
            'severity': 'low',
            'message': f'堆大小较大: {info["heap_size"]} 字节，确认是否需要动态内存',
            'location': file_path,
        })


@register_detector("embedded", "startup")
def _check_stack_heap_config(file_path, content, findings):
    """检查启动文件栈/堆大小配置。"""
    if not file_path.endswith('.s') and not file_path.endswith('.S'):
        return findings
    if 'startup' not in os.path.basename(file_path).lower():
        return findings

    try:
        info = parse_startup_file(file_path)
    except Exception:
        return findings

    _check_stack_too_small(info, file_path, findings)
    _check_stack_too_large(info, file_path, findings)
    _check_heap_large(info, file_path, findings)
    return findings
