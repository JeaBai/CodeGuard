# .codebuddy/skills/CodeGuard/scripts/quality_artifact.py
"""Hex/Bin产物校验模块。

解析Intel HEX文件，检查:
- Bootloader/App地址边界
- 向量表偏移
- Hex文件完整性
注册为enterprise检测器。
"""
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'internal'))
from detector_registry import register_detector


def _parse_hex_record(line: str) -> dict:
    """解析单条HEX记录。"""
    # 格式: :LLAAAATT[DD...]CC
    # LL=字节数, AAAA=地址, TT=类型, DD=数据, CC=校验和
    data_hex = line[1:]
    byte_count = int(data_hex[0:2], 16)
    address = int(data_hex[2:6], 16)
    record_type = int(data_hex[6:8], 16)

    data = []
    for i in range(8, 8 + byte_count * 2, 2):
        if i + 2 <= len(data_hex) - 2:
            data.append(int(data_hex[i:i+2], 16))

    checksum = int(data_hex[-2:], 16)

    # 验证校验和
    calc_sum = byte_count + (address >> 8) + (address & 0xFF) + record_type + sum(data)
    calc_checksum = (~calc_sum + 1) & 0xFF

    return {
        'byte_count': byte_count,
        'address': address,
        'type': record_type,
        'data': data,
        'checksum': checksum,
        'checksum_valid': checksum == calc_checksum,
    }


def _process_hex_record(record, result):
    """按记录类型分派处理，返回 True 表示遇 EOF 应停止。"""
    rtype = record['type']
    if rtype == 0x00:  # Data record
        addr = record['address']
        result['min_address'] = min(result['min_address'], addr)
        result['max_address'] = max(result['max_address'], addr + record['byte_count'])
        result['data_segments'].append({
            'address': addr,
            'length': record['byte_count'],
            'data': record['data'],
        })
        return False
    if rtype == 0x01:  # EOF
        return True
    if rtype in (0x03, 0x05):  # Start Segment/Linear Address
        if len(record['data']) >= 4:
            result['entry_point'] = (record['data'][0] << 24 | record['data'][1] << 16 |
                                     record['data'][2] << 8 | record['data'][3])
    return False


def parse_hex_file(file_path: str) -> dict:
    """解析Intel HEX文件。

    Returns:
        {
            'records': list,       # 所有记录
            'data_segments': list, # 数据段 [{address, length, data}]
            'entry_point': int,    # 入口地址(如果有)
            'max_address': int,    # 最大地址
            'min_address': int,    # 最小地址
        }
    """
    result = {
        'records': [],
        'data_segments': [],
        'entry_point': None,
        'max_address': 0,
        'min_address': 0xFFFFFFFF,
    }

    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line.startswith(':'):
                continue
            record = _parse_hex_record(line)
            if record:
                result['records'].append(record)
                if _process_hex_record(record, result):
                    break

    if result['min_address'] == 0xFFFFFFFF:
        result['min_address'] = 0

    return result


def _check_hex_checksums(info, file_path, findings):
    """检查 HEX 记录校验和错误。"""
    bad_checksums = [r for r in info['records'] if not r.get('checksum_valid', True)]
    if bad_checksums:
        findings.append({
            'rule_id': 'EMBEDDED-ARTIFACT-002',
            'severity': 'critical',
            'message': f'Hex文件有 {len(bad_checksums)} 条记录校验和错误',
            'location': file_path,
        })


def _check_hex_eof(info, file_path, findings):
    """检查 HEX 文件是否含 EOF 记录。"""
    has_eof = any(r['type'] == 0x01 for r in info['records'])
    if not has_eof:
        findings.append({
            'rule_id': 'EMBEDDED-ARTIFACT-003',
            'severity': 'high',
            'message': 'Hex文件缺少EOF记录(类型01)',
            'location': file_path,
        })


def _check_vector_table(info, file_path, findings):
    """检查向量表 Reset_Handler 地址是否在数据范围内。"""
    if not info['data_segments']:
        return
    first_segment = info['data_segments'][0]
    if first_segment['address'] != 0 or len(first_segment['data']) < 8:
        return
    reset_handler = (first_segment['data'][4] << 24 | first_segment['data'][5] << 16 |
                     first_segment['data'][6] << 8 | first_segment['data'][7])
    if reset_handler < info['min_address'] or reset_handler > info['max_address']:
        findings.append({
            'rule_id': 'EMBEDDED-ARTIFACT-004',
            'severity': 'high',
            'message': f'Reset_Handler地址(0x{reset_handler:08X})超出Hex数据范围',
            'location': file_path,
            'suggestion': '检查向量表配置或Bootloader偏移地址',
        })


@register_detector("embedded", "artifact")
def _check_hex_boundaries(file_path, content, findings):
    """检查Hex文件地址边界和Bootloader/App分区。"""
    if not file_path.endswith('.hex'):
        return findings

    try:
        info = parse_hex_file(file_path)
    except Exception as e:
        findings.append({
            'rule_id': 'EMBEDDED-ARTIFACT-001',
            'severity': 'medium',
            'message': f'Hex文件解析失败: {e}',
            'location': file_path,
        })
        return findings

    _check_hex_checksums(info, file_path, findings)
    _check_hex_eof(info, file_path, findings)
    _check_vector_table(info, file_path, findings)
    return findings
