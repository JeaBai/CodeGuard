#!/usr/bin/env python3
"""
CodeGuard Quality Coverage — 测试覆盖率门禁模块 (v2.0.10)
=========================================================
纯 Python 标准库实现，零第三方依赖。
扫描项目中的覆盖率报告文件（coverage.xml / .coverage / lcov.info / coverage/coverage.json），
提取覆盖率数值并与阈值比对。

退出码：0 = PASS（达标）/ 1 = WARN（低于阈值）/ 2 = BLOCK（无覆盖率文件）
用法：python quality_coverage.py [--path .] [--threshold 80] [--format json|text]
"""
import argparse
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

DEFAULT_THRESHOLD = 80  # 默认覆盖率阈值（%）
CRITICAL_RATIO = 0.7    # 线性衰减临界比：低于此比例则升格为 block


def find_coverage_files(root: Path) -> list[Path]:
    """搜索覆盖率报告文件（支持 coverage.xml / lcov.info / .coverage / JSON）。"""
    candidates: list[Path] = []

    # 精确文件名
    exact_names = [
        'coverage.xml', 'cobertura.xml', 'lcov.info',
        '.coverage', 'coverage.json', 'cov.xml',
    ]
    for name in exact_names:
        for p in root.rglob(name):
            if p.is_file():
                candidates.append(p)
        # 也查 coverage/ 子目录
        coverage_dir = root / 'coverage'
        if coverage_dir.is_dir():
            for p in coverage_dir.rglob(name):
                if p.is_file():
                    candidates.append(p)

    # 通用模式
    for pattern in ['**/coverage/coverage-final.json', '**/.nyc_output/**/*.json']:
        for p in root.glob(pattern):
            if p.is_file():
                candidates.append(p)

    return sorted(set(candidates))


def parse_coverage_xml(xml_path: Path) -> dict:
    """解析 Cobertura XML 覆盖率报告。"""
    try:
        tree = ET.parse(xml_path)
        root_el = tree.getroot()
    except (ET.ParseError, OSError):
        return {}

    result = {'line_rate': 0.0, 'branch_rate': 0.0, 'lines_covered': 0,
              'lines_valid': 0, 'branches_covered': 0, 'branches_valid': 0}

    # Cobertura: <coverage line-rate="0.85" branch-rate="0.72" ...>
    for attr in ['line-rate', 'branch-rate', 'lines-covered', 'lines-valid',
                 'branches-covered', 'branches-valid']:
        val = root_el.get(attr)
        if val is not None:
            try:
                result[attr.replace('-', '_')] = float(val)
            except ValueError:  # codeguard: ignore GOLD_NO_EMPTY_EXCEPT
                pass

    # 统计 <package> 汇总
    if result['lines_valid'] == 0:
        lines_total = 0
        lines_hit = 0
        for package in root_el.iter('package'):
            for attr in ['line-rate', 'lines-covered', 'lines-valid']:
                val = package.get(attr)
                if val is not None and 'rate' not in attr:
                    try:
                        if 'covered' in attr:
                            lines_hit += int(val)
                        else:
                            lines_total += int(val)
                    except ValueError:  # codeguard: ignore GOLD_NO_EMPTY_EXCEPT
                        pass
        if lines_total > 0:
            result['line_rate'] = lines_hit / lines_total
            result['lines_valid'] = lines_total
            result['lines_covered'] = lines_hit

    return result


def parse_lcov(lcov_path: Path) -> dict:
    """解析 LCOV tracefile。"""
    try:
        text = lcov_path.read_text(encoding='utf-8', errors='ignore')
    except OSError:
        return {}

    lines_total = 0
    lines_hit = 0
    in_section = False

    for line in text.splitlines():
        line = line.strip()
        if line == 'end_of_record':
            in_section = False
            continue
        if line.startswith('SF:'):
            in_section = True
            continue
        if not in_section:
            continue
        if line.startswith('LF:'):
            try:
                lines_total += int(line.split(':')[1])
            except (ValueError, IndexError):  # codeguard: ignore GOLD_NO_EMPTY_EXCEPT
                pass
        if line.startswith('LH:'):
            try:
                lines_hit += int(line.split(':')[1])
            except (ValueError, IndexError):  # codeguard: ignore GOLD_NO_EMPTY_EXCEPT
                pass

    line_rate = (lines_hit / lines_total) if lines_total > 0 else 0.0
    return {'line_rate': line_rate, 'lines_covered': lines_hit,
            'lines_valid': lines_total, 'source': str(lcov_path)}


def parse_coverage_json(json_path: Path) -> dict:
    """解析 Istanbul/Vitest JSON 覆盖率报告。"""
    data = load_json(json_path)
    if not data:
        return {}

    lines_total = 0
    lines_hit = 0

    for file_data in data.values() if isinstance(data, dict) else []:
        if not isinstance(file_data, dict):
            continue
        # Istanbul 格式：{ s: { lineNum: hits } }
        stmts = file_data.get('s', {})
        if isinstance(stmts, dict):
            lines_total += len(stmts)
            lines_hit += sum(1 for v in stmts.values() if v and v > 0)

        # 嵌套格式：total.lines
        total = file_data.get('total', {})
        if isinstance(total, dict):
            lines = total.get('lines', {})
            if isinstance(lines, dict):
                lines_total += lines.get('total', 0)
                lines_hit += lines.get('covered', 0)

    line_rate = (lines_hit / lines_total) if lines_total > 0 else 0.0
    return {'line_rate': line_rate, 'lines_covered': lines_hit,
            'lines_valid': lines_total, 'source': str(json_path)}


def load_json(path: Path) -> dict | None:
    """安全加载 JSON 文件。"""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (json.JSONDecodeError, OSError):
        return None


def run_test_coverage(root: Path, threshold: int = DEFAULT_THRESHOLD) -> dict:
    """执行测试覆盖率门禁检查。
    
    返回：{
        'exit_code': int, 'threshold': int, 'line_rate': float,
        'issues': [...], 'source': str
    }
    """
    coverage_files = find_coverage_files(root)
    if not coverage_files:
        return {
            'exit_code': 2,
            'threshold': threshold,
            'line_rate': 0.0,
            'lines_covered': 0,
            'lines_valid': 0,
            'source': '',
            'issues': [{
                'severity': 'block',
                'rule': 'coverage-no-files',
                'message': '未找到覆盖率报告文件（coverage.xml / lcov.info / coverage.json）',
                'suggestion': ('运行测试并生成覆盖率报告：'
                               'pytest --cov --cov-report=xml 或 vitest --coverage'),
            }],
        }

    best = {'line_rate': 0.0, 'lines_covered': 0, 'lines_valid': 0, 'source': ''}
    issues = []

    for cf in coverage_files:
        ext = cf.suffix.lower()
        name = cf.name.lower()

        if ext == '.xml' or 'cobertura' in name:
            parsed = parse_coverage_xml(cf)
        elif ext == '.info' or 'lcov' in name:
            parsed = parse_lcov(cf)
        elif ext == '.json':
            parsed = parse_coverage_json(cf)
        else:
            continue

        lr = parsed.get('line_rate', 0.0)
        if lr > best['line_rate']:
            best = parsed

    line_rate = best['line_rate']
    line_pct = line_rate * 100

    if line_rate <= 0:
        return {
            'exit_code': 2,
            'threshold': threshold,
            'line_rate': 0.0,
            'lines_covered': 0,
            'lines_valid': 0,
            'source': '',
            'issues': [{
                'severity': 'block',
                'rule': 'coverage-zero',
                'message': '覆盖率文件存在但行覆盖率为 0%',
                'suggestion': '检查测试套件是否正确执行并产生覆盖率数据',
            }],
        }

    if line_pct < threshold:
        issues.append({
            'severity': 'warn' if line_pct >= threshold * CRITICAL_RATIO else 'block',
            'rule': 'coverage-below-threshold',
            'message': (f'行覆盖率 {line_pct:.0f}% 低于门禁阈值 {threshold}% '
                        f'({best.get("lines_covered", "?")}/{best.get("lines_valid", "?")})'),
            'suggestion': f'补充测试用例以提高覆盖率至 {threshold}%+',
        })
    else:
        issues.append({
            'severity': 'info',
            'rule': 'coverage-ok',
            'message': (f'行覆盖率 {line_pct:.0f}% ≥ 门禁阈值 {threshold}% '
                        f'({best.get("lines_covered", "?")}/{best.get("lines_valid", "?")})'),
            'suggestion': '',
        })

    exit_code = 2 if any(i['severity'] == 'block' for i in issues) else \
               (1 if any(i['severity'] == 'warn' for i in issues) else 0)

    return {
        'exit_code': exit_code,
        'threshold': threshold,
        'line_rate': line_rate,
        'lines_covered': best.get('lines_covered', 0),
        'lines_valid': best.get('lines_valid', 0),
        'source': best.get('source', str(coverage_files[0]) if coverage_files else ''),
        'issues': issues,
    }


def main():
    ap = argparse.ArgumentParser(description='CodeGuard 测试覆盖率门禁')
    ap.add_argument('--path', default='.', help='项目根目录（默认当前目录）')
    ap.add_argument('--threshold', type=int, default=DEFAULT_THRESHOLD,
                    help=f'覆盖率阈值百分比（默认 {DEFAULT_THRESHOLD}）')
    ap.add_argument('--format', choices=['json', 'text'], default='text',
                    help='输出格式')
    args = ap.parse_args()

    root = Path(args.path).resolve()
    if not root.exists():
        print(f'路径不存在: {root}', file=sys.stderr)  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
        sys.exit(2)

    result = run_test_coverage(root, args.threshold)

    if args.format == 'json':
        print(json.dumps(result, ensure_ascii=False, indent=2))  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
    else:
        for issue in result.get('issues', []):
            tag = f"[{issue['severity'].upper():5}]"
            print(f"{tag} {issue.get('rule', '')}")  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
            print(f"        {issue['message']}")  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
            if issue.get('suggestion'):
                print(f"        修复: {issue['suggestion']}")  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
        pct = result['line_rate'] * 100
        print(f"\n覆盖率门禁: {pct:.0f}% (阈值 {args.threshold}%) → 退出码 {result['exit_code']}")  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION

    sys.exit(result['exit_code'])


if __name__ == '__main__':
    main()
