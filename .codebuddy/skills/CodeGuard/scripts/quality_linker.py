# .codebuddy/skills/CodeGuard/scripts/quality_linker.py
"""链接脚本分析模块。

解析.ld(GNU Linker Script)文件，检查:
- RAM/Flash大小提取
- section布局合理性
- 栈/堆配置与启动文件交叉验证
"""
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'internal'))
from detector_registry import register_detector


def _parse_size(size_str: str) -> int:
    """解析大小字符串 (如 '256K', '0x10000', '1024')。"""
    size_str = size_str.strip()
    multipliers = {'K': 1024, 'M': 1024*1024, 'G': 1024*1024*1024,
                   'k': 1024, 'm': 1024*1024, 'g': 1024*1024*1024}
    for suffix, mult in multipliers.items():
        if size_str.endswith(suffix):
            return int(size_str[:-1], 0) * mult
    return int(size_str, 0)


def parse_linker_script(file_path: str) -> dict:
    """解析GNU链接脚本(.ld)文件。

    Returns:
        {
            'flash_origin': int,   # Flash起始地址
            'flash_length': int,   # Flash大小(字节)
            'ram_origin': int,     # RAM起始地址
            'ram_length': int,     # RAM大小(字节)
            'sections': list,      # section定义列表
            'stack_size': int,     # 栈大小(从链接脚本提取)
        }
    """
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    result = {
        'flash_origin': 0,
        'flash_length': 0,
        'ram_origin': 0,
        'ram_length': 0,
        'sections': [],
        'stack_size': 0,
    }

    # 提取MEMORY定义
    memory_match = re.search(r'MEMORY\s*\{([^}]+)\}', content, re.DOTALL)
    if memory_match:
        mem_text = memory_match.group(1)
        # FLASH定义
        flash_match = re.search(
            r'(?:FLASH|ROM)\s*(?:\([^)]*\))?\s*:\s*ORIGIN\s*=\s*(0x[0-9a-fA-F]+|\d+).*?LENGTH\s*=\s*(0x[0-9a-fA-F]+|\d+\s*[KMGkmg])',
            mem_text, re.DOTALL)
        if flash_match:
            result['flash_origin'] = int(flash_match.group(1), 0)
            result['flash_length'] = _parse_size(flash_match.group(2))

        # RAM定义
        ram_match = re.search(
            r'RAM\s*(?:\([^)]*\))?\s*:\s*ORIGIN\s*=\s*(0x[0-9a-fA-F]+|\d+).*?LENGTH\s*=\s*(0x[0-9a-fA-F]+|\d+\s*[KMGkmg])',
            mem_text, re.DOTALL)
        if ram_match:
            result['ram_origin'] = int(ram_match.group(1), 0)
            result['ram_length'] = _parse_size(ram_match.group(2))

    # 提取section定义
    for sec_match in re.finditer(r'\.(\w+)\s*(?:[^\{]*)?\{([^}]*)\}', content):
        result['sections'].append({
            'name': sec_match.group(1),
            'content': sec_match.group(2).strip(),
        })

    # 提取栈大小 (从_stack_size符号)
    stack_match = re.search(
        r'_stack_size\s*=\s*(?:DEFINED\s*\(\s*_stack_size\s*\)\s*\?\s*_stack_size\s*:\s*)?(0x[0-9a-fA-F]+|\d+)',
        content)
    if stack_match:
        result['stack_size'] = _parse_size(stack_match.group(1))

    return result


def _check_flash_ram_defined(info, file_path, findings):
    """检查 Flash/RAM 是否已定义。"""
    if info['flash_length'] == 0:
        findings.append({
            'rule_id': 'EMBEDDED-LINKER-002',
            'severity': 'high',
            'message': '未找到FLASH/ROM内存定义',
            'location': file_path,
        })
    if info['ram_length'] == 0:
        findings.append({
            'rule_id': 'EMBEDDED-LINKER-003',
            'severity': 'high',
            'message': '未找到RAM内存定义',
            'location': file_path,
        })


def _check_ram_size(info, file_path, findings):
    """检查 RAM 大小合理性（最小 1KB）。"""
    if 0 < info['ram_length'] < 1024:
        findings.append({
            'rule_id': 'EMBEDDED-LINKER-004',
            'severity': 'medium',
            'message': f'RAM大小异常: {info["ram_length"]} 字节',
            'location': file_path,
        })


def _check_overlap(info, file_path, findings):
    """检查 Flash 和 RAM 地址是否重叠。"""
    if info['flash_length'] > 0 and info['ram_length'] > 0:
        flash_end = info['flash_origin'] + info['flash_length']
        ram_end = info['ram_origin'] + info['ram_length']
        if not (flash_end <= info['ram_origin'] or ram_end <= info['flash_origin']):
            findings.append({
                'rule_id': 'EMBEDDED-LINKER-005',
                'severity': 'critical',
                'message': 'FLASH和RAM地址区域重叠',
                'location': file_path,
            })


@register_detector("embedded", "linker")
def _check_memory_layout(file_path, content, findings):
    """检查链接脚本内存布局合理性。"""
    if not file_path.endswith('.ld'):
        return findings

    try:
        info = parse_linker_script(file_path)
    except Exception as e:
        findings.append({
            'rule_id': 'EMBEDDED-LINKER-001',
            'severity': 'medium',
            'message': f'链接脚本解析失败: {e}',
            'location': file_path,
        })
        return findings

    _check_flash_ram_defined(info, file_path, findings)
    _check_ram_size(info, file_path, findings)
    _check_overlap(info, file_path, findings)
    return findings


@register_detector("embedded", "linker")
def _check_section_layout(file_path, content, findings):
    """检查section布局合理性。"""
    if not file_path.endswith('.ld'):
        return findings

    try:
        info = parse_linker_script(file_path)
    except Exception:
        return findings

    section_names = [s['name'] for s in info['sections']]

    # 检查必要的section
    required_sections = ['text', 'data', 'bss']
    for req in required_sections:
        if req not in section_names:
            findings.append({
                'rule_id': 'EMBEDDED-LINKER-006',
                'severity': 'high',
                'message': f'缺少必需的section: .{req}',
                'location': file_path,
            })

    # 检查.data是否配置了加载地址(AT>)
    if 'data' in section_names:
        if 'AT' not in content and '_sidata' not in content:
            findings.append({
                'rule_id': 'EMBEDDED-LINKER-007',
                'severity': 'medium',
                'message': '.data section未配置加载地址(AT>)，可能导致初始化数据丢失',
                'location': file_path,
                'suggestion': '在.data section中添加 AT> FLASH 指定加载地址',
            })

    return findings
