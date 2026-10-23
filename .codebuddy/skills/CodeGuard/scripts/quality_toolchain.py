# .codebuddy/skills/CodeGuard/scripts/quality_toolchain.py
"""工具链感知模块。

解析Makefile/CMakeLists.txt，检查:
- 交叉编译配置
- 优化级别
- LTO配置
- 编译警告配置
"""
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'internal'))
from detector_registry import register_detector


def parse_makefile(file_path: str) -> dict:
    """解析Makefile，提取工具链配置。

    Returns:
        {
            'cross_compiler': str,    # 交叉编译器前缀
            'cflags': list,           # 编译选项列表
            'ldflags': list,          # 链接选项列表
            'optimization': str,      # 优化级别
            'has_lto': bool,          # 是否启用LTO
            'warning_flags': list,    # 警告选项
        }
    """
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    result = {
        'cross_compiler': None,
        'cflags': [],
        'ldflags': [],
        'optimization': None,
        'has_lto': False,
        'warning_flags': [],
    }

    # 提取交叉编译器前缀 (如 arm-none-eabi-)
    cc_match = re.search(r'(?:CC|CROSS_COMPILE)\s*[?:]?=\s*(\S+?-)gcc', content)
    if cc_match:
        result['cross_compiler'] = cc_match.group(1)
    else:
        cc_match = re.search(r'(?:CC|CROSS_COMPILE)\s*[?:]?=\s*(\S+?-)g\+\+', content)
        if cc_match:
            result['cross_compiler'] = cc_match.group(1)

    # 提取CFLAGS
    cflags_match = re.search(r'CFLAGS\s*[?:]?=\s*(.+)', content)
    if cflags_match:
        cflags = cflags_match.group(1).split()
        result['cflags'] = cflags

        # 提取优化级别
        for flag in cflags:
            if flag.startswith('-O'):
                result['optimization'] = flag

        # 检查LTO
        if '-flto' in cflags:
            result['has_lto'] = True

        # 提取警告选项
        result['warning_flags'] = [f for f in cflags if f.startswith('-W')]

    # 提取LDFLAGS
    ldflags_match = re.search(r'LDFLAGS\s*[?:]?=\s*(.+)', content)
    if ldflags_match:
        result['ldflags'] = ldflags_match.group(1).split()

    return result


def parse_cmake(file_path: str) -> dict:
    """解析CMakeLists.txt，提取工具链配置。"""
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    result = {
        'cross_compiler': None,
        'cflags': [],
        'optimization': None,
        'has_lto': False,
        'warning_flags': [],
    }

    # 提取交叉编译工具链文件
    toolchain_match = re.search(r'CMAKE_TOOLCHAIN_FILE\s+["\']?([^"\']+)', content)
    if toolchain_match:
        result['cross_compiler'] = toolchain_match.group(1)

    # 提取编译选项
    for add_match in re.finditer(r'add_compile_options\s*\(([^)]+)\)', content):
        flags = add_match.group(1).split()
        result['cflags'].extend(flags)
        for flag in flags:
            if flag.startswith('-O'):
                result['optimization'] = flag
            if flag == '-flto':
                result['has_lto'] = True
            if flag.startswith('-W'):
                result['warning_flags'].append(flag)

    # 检查CMAKE_C_FLAGS
    cflags_match = re.search(r'set\s*\(\s*CMAKE_C_FLAGS[^)]*?"([^"]+)"', content)
    if cflags_match:
        flags = cflags_match.group(1).split()
        result['cflags'].extend(flags)
        for flag in flags:
            if flag.startswith('-O'):
                result['optimization'] = flag

    return result


@register_detector("embedded", "toolchain")
def _check_cross_compile_config(file_path, content, findings):
    """检查交叉编译配置。"""
    basename = os.path.basename(file_path)

    if basename == 'Makefile' or file_path.endswith('.mk'):
        config = parse_makefile(file_path)
    elif basename == 'CMakeLists.txt':
        config = parse_cmake(file_path)
    else:
        return findings

    # 检查是否配置了交叉编译器
    if not config['cross_compiler']:
        findings.append({
            'rule_id': 'EMBEDDED-TOOLCHAIN-001',
            'severity': 'high',
            'message': '未检测到交叉编译器配置，可能使用宿主机编译器',
            'location': file_path,
            'suggestion': '配置CROSS_COMPILE或CMAKE_TOOLCHAIN_FILE指向目标平台工具链',
        })

    # 检查优化级别
    opt = config.get('optimization', '')
    if opt == '-O0':
        findings.append({
            'rule_id': 'EMBEDDED-TOOLCHAIN-002',
            'severity': 'medium',
            'message': '使用-O0优化级别，可能增大代码体积',
            'location': file_path,
            'suggestion': '发布版本建议使用-Os(优化大小)或-O2(优化速度)',
        })
    elif opt == '-O3':
        findings.append({
            'rule_id': 'EMBEDDED-TOOLCHAIN-003',
            'severity': 'low',
            'message': '使用-O3优化级别，可能过度展开代码导致Flash占用增加',
            'location': file_path,
            'suggestion': '嵌入式环境建议使用-Os优化代码大小',
        })
    elif opt == '-Os':
        pass  # Os是嵌入式推荐级别，不报警
    elif not opt:
        findings.append({
            'rule_id': 'EMBEDDED-TOOLCHAIN-004',
            'severity': 'medium',
            'message': '未指定优化级别，编译器默认可能不是最优',
            'location': file_path,
        })

    return findings


@register_detector("embedded", "toolchain")
def _check_lto_config(file_path, content, findings):
    """检查LTO(链接时优化)配置。"""
    basename = os.path.basename(file_path)

    if basename == 'Makefile' or file_path.endswith('.mk'):
        config = parse_makefile(file_path)
    elif basename == 'CMakeLists.txt':
        config = parse_cmake(file_path)
    else:
        return findings

    # 检查LTO配置
    if not config.get('has_lto', False):
        findings.append({
            'rule_id': 'EMBEDDED-TOOLCHAIN-005',
            'severity': 'low',
            'message': '未启用LTO(链接时优化)，启用后可减小代码体积',
            'location': file_path,
            'suggestion': '在CFLAGS中添加-flto启用链接时优化',
        })

    # 检查警告配置
    warning_flags = config.get('warning_flags', [])
    if not any(f == '-Wall' for f in warning_flags):
        findings.append({
            'rule_id': 'EMBEDDED-TOOLCHAIN-006',
            'severity': 'low',
            'message': '未启用-Wall警告选项',
            'location': file_path,
            'suggestion': '添加-Wall -Wextra启用更多编译警告',
        })

    return findings
