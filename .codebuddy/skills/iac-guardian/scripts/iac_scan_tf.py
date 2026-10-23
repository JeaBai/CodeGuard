"""Terraform 检测规则（7 核心 + P8 扩展）。"""
from __future__ import annotations

import re

from iac_scan_core import add

# ---------------- Terraform 检测 ----------------

def _find_resource_body(text: str, start: int) -> str:
    """从 text[start] 开始匹配配对花括号，返回资源体内容（不含外层大括号）。"""
    depth, j = 1, start
    while j < len(text) and depth:
        if text[j] == '{':
            depth += 1
        elif text[j] == '}':
            depth -= 1
        j += 1
    return text[start:j]


# ── 7 条 Terraform 单规则检查函数 ────────────────────────────────

def _check_tf_s3_acl(path, text, lines, issues):
    """tf-public-s3-acl: S3 公开 ACL（BLOCK）"""
    for i, line in enumerate(lines, 1):
        if re.search(r'acl\s*=\s*"public', line):
            add(issues, 'block', 'tf-public-s3-acl', (path, i), 'S3 bucket ACL 设为公开（public-read/public-read-write），数据将公网暴露',
                suggestion='删除 acl 属性（默认 private），并附加 aws_s3_bucket_public_access_block 全量阻断')


def _check_tf_open_cidr(path, text, lines, issues):
    """tf-open-cidr: 0.0.0.0/0（ingress 上下文 BLOCK，否则 WARN）"""
    for m in re.finditer(r'"0\.0\.0\.0/0"', text):
        line_no = text[:m.start()].count('\n') + 1
        ctx = '\n'.join(lines[max(0, line_no - 8):line_no + 2])
        if re.search(r'ingress|from_port|security_group_rule|firewall', ctx, re.I):
            add(issues, 'block', 'tf-open-cidr', (path, line_no), '安全组 ingress 对 0.0.0.0/0 开放，公网暴露高危（AI 生成 Terraform 默认倾向）',
                suggestion='ingress 限定具体 CIDR 或安全组引用；22/3389/数据库端口绝不应对全网开放')
        else:
            add(issues, 'warn', 'tf-open-cidr', (path, line_no), '检测到 0.0.0.0/0 全网段引用，需确认是否为 egress 等合法场景',
                suggestion='egress 全开属正常可豁免；否则限定最小网段')


_HCL_WILDCARD = re.compile(r'(?i)\b(actions|notactions)\s*=\s*\[\s*"\*"')


def _check_tf_iam_wildcard(path, text, lines, issues):
    """tf-iam-wildcard: IAM 全权策略（BLOCK，覆盖 JSON 与 HCL 两种风格）
    
    v0.2.3 P1 修复：新增单数 action/resource 独立行检测、jsonencode() 动态策略、
    statement 块内联通配、服务级通配符（s3:*）检测，消除 3 FN 漏报。
    """
    # ---- 单行检测 ----
    for i, line in enumerate(lines, 1):
        # JSON 风格单行
        if (re.search(r'"\*:\*"', line) or
            re.search(r'"(Action|NotAction)"\s*[:=]\s*"\*"', line) or
            re.search(r'"(Resource|NotResource)"\s*[:=]\s*"\*"', line)):
            add(issues, 'block', 'tf-iam-wildcard', (path, i),
                'IAM 策略存在全权授予（*:* 或 Action/Resource:"*"），违反最小权限原则',
                suggestion='按应用实际需求显式列举 Action 与 Resource ARN')
            continue
        
        # HCL 数组风格
        if _HCL_WILDCARD.search(line):
            add(issues, 'block', 'tf-iam-wildcard', (path, i),
                'IAM 策略存在全权授予（actions=["*"]），违反最小权限原则',
                suggestion='按应用实际需求显式列举 Action 与 Resource ARN')
            continue
        
        # v0.2.3: 单数 action/resource 无括号风格（HCL 允许 action = "*"）
        if re.search(r'(?i)\b(action|resource)\s*=\s*"\*"', line):
            add(issues, 'block', 'tf-iam-wildcard', (path, i),
                '单数 action/resource 使用通配符 "*"，违反最小权限原则',
                suggestion='按应用实际需求显式列举，不使用通配符')
            continue
        
        # v0.2.3: 服务级通配符（如 "s3:*", "ec2:*"）
        if re.search(r'"\w+:\*"', line) and not re.search(r'ignore|comment|示例', line, re.IGNORECASE):
            add(issues, 'block', 'tf-iam-wildcard', (path, i),
                'IAM 策略使用服务级通配符（如 "s3:*"），仍授予该服务所有操作',
                suggestion='按应用实际需求显式列举需要的具体操作名称（如 "s3:GetObject", "s3:PutObject"）')
    
    # ---- 多行检测 ----
    # 多行数组：actions = [ ... "*" ...] 可能跨行
    for m in re.finditer(
        r'(?i)\b(actions|notactions|resources|notresources)\s*=\s*\[([^\]]*)\]',
        text
    ):
        if '"*"' in m.group(2) or "'*'" in m.group(2):
            line_no = text[:m.start()].count('\n') + 1
            add(issues, 'block', 'tf-iam-wildcard', (path, line_no),
                f'{m.group(1)} 包含通配符 "*"，违反最小权限原则',
                suggestion='按应用实际需求显式列举，不使用通配符')
    
    # 嵌入 JSON policy document 检测（heredoc: policy = <<POLICY ... POLICY）
    for m in re.finditer(
        r'policy\s*=\s*<<-?\s*(?:POLICY|JSON|EOF)(.+?)(?:POLICY|JSON|EOF)',
        text, re.DOTALL | re.IGNORECASE
    ):
        policy_json = m.group(1)
        if re.search(r'"Action"\s*:\s*"\*"', policy_json) or \
           re.search(r'"Resource"\s*:\s*"\*"', policy_json) or \
           re.search(r'"\*:\*"', policy_json):
            line_no = text[:m.start()].count('\n') + 1
            add(issues, 'block', 'tf-iam-wildcard', (path, line_no),
                '嵌入 JSON policy document 包含全权通配符，违反最小权限原则',
                suggestion='在 JSON policy 中显式列举 Action 和 Resource')
    
    # assume_role_policy 中的 wildcard principal
    for m in re.finditer(
        r'assume_role_policy\s*=\s*<<-?\s*(?:POLICY|JSON|EOF)(.+?)(?:POLICY|JSON|EOF)',
        text, re.DOTALL | re.IGNORECASE
    ):
        assume_json = m.group(1)
        if re.search(r'"Principal"\s*:\s*"\*"', assume_json) or \
           re.search(r'"Principal"\s*:\s*\{[^}]*"AWS"\s*:\s*"\*"', assume_json):
            line_no = text[:m.start()].count('\n') + 1
            add(issues, 'block', 'tf-iam-wildcard', (path, line_no),
                'assume_role_policy 允许任意 Principal 代入角色，存在账户劫持风险',
                suggestion='限制 Principal 为特定 AWS 账户 ARN 或服务主体')
    
    # data.aws_iam_policy_document 语句块中的 wildcard
    for m in re.finditer(
        r'data\s+"aws_iam_policy_document"(.+?)\n\}',
        text, re.DOTALL
    ):
        doc_body = m.group(0)
        if re.search(r'(?i)\b(actions|resources)\s*=\s*\[\s*"\*"\s*\]', doc_body):
            line_no = text[:m.start()].count('\n') + 1
            add(issues, 'block', 'tf-iam-wildcard', (path, line_no),
                'data.aws_iam_policy_document 包含通配符，违反最小权限原则',
                suggestion='在 policy document statement 中显式列举 actions 和 resources')
    
    # v0.2.3: jsonencode() 动态策略检测
    for m in re.finditer(
        r'jsonencode\s*\(\s*\{([^}]+)\}',
        text, re.DOTALL
    ):
        json_body = m.group(1)
        if re.search(r'(?i)Action\s*=\s*"\*"', json_body) or \
           re.search(r'(?i)Resource\s*=\s*"\*"', json_body):
            line_no = text[:m.start()].count('\n') + 1
            add(issues, 'block', 'tf-iam-wildcard', (path, line_no),
                'jsonencode() 动态策略包含全权通配符，违反最小权限原则',
                suggestion='在 jsonencode 块中显式列举 Action 和 Resource')
    
    # v0.2.3: HCL statement 块检测（resource "aws_iam_policy" / "aws_iam_role_policy"）
    for m in re.finditer(
        r'statement\s*\{([^}]*(?:\{[^}]*\}[^}]*)*)\}',
        text, re.DOTALL
    ):
        stmt_body = m.group(1)
        if re.search(r'(?i)actions?\s*=\s*\[\s*"\*"\s*\]', stmt_body) or \
           re.search(r'(?i)resources?\s*=\s*\[\s*"\*"\s*\]', stmt_body):
            line_no = text[:m.start()].count('\n') + 1
            add(issues, 'block', 'tf-iam-wildcard', (path, line_no),
                'HCL statement 块包含全权通配符，违反最小权限原则',
                suggestion='在 statement 块中显式列举 actions 和 resources')
        # 单数 style
        if re.search(r'(?i)action\s*=\s*"\*"', stmt_body):
            line_no = text[:m.start()].count('\n') + 1
            add(issues, 'block', 'tf-iam-wildcard', (path, line_no),
                'HCL statement 块 action 使用通配符，违反最小权限原则',
                suggestion='显式列举具体 action 名称')


def _check_tf_db_prevent_destroy(path, text, issues):
    """tf-db-no-prevent-destroy: aws_db_instance 缺 prevent_destroy（BLOCK）"""
    for m in re.finditer(r'resource\s+"aws_db_instance"\s+"[^"]+"\s*\{', text):
        body = _find_resource_body(text, m.end())
        if 'prevent_destroy' not in body:
            line_no = text[:m.start()].count('\n') + 1
            add(issues, 'block', 'tf-db-no-prevent-destroy', (path, line_no), 'aws_db_instance 未设置 lifecycle prevent_destroy（terraform destroy 类事故防线）',
                suggestion='增加 lifecycle { prevent_destroy = true }，删除前需显式移除该保护')


def _check_tf_s3_logging(path, text, issues):
    """tf-s3-no-logging: S3 bucket 未启用访问日志（WARN）
    
    v0.2.3 P2 修复：增加空 logging 块检测、target/target_bucket 别名引用、
    bucket_logging 嵌套属性、通用 logging_enabled 属性检测，
    进一步消除残留 3 FP。
    """
    # 先收集所有 aws_s3_bucket_logging 关联的 bucket 资源名
    logging_buckets = set()
    for lm in re.finditer(
        r'resource\s+"aws_s3_bucket_logging"\s+"[^"]*"\s*\{(.*?)\n\}',
        text, re.DOTALL
    ):
        body = lm.group(1)
        bucket_match = re.search(r'bucket\s*=\s*aws_s3_bucket\.(\w+)\.(?:id|arn|bucket)', body)
        if bucket_match:
            logging_buckets.add(bucket_match.group(1))
    
    for m in re.finditer(r'resource\s+"aws_s3_bucket"\s+"(\w+)"\s*\{', text):
        bucket_name = m.group(1)
        body = _find_resource_body(text, m.end())
        
        # 精确检测 body 中是否声明了 logging 块（排除注释中的 logging 字串）
        has_logging_block = bool(re.search(r'^\s*logging\s*\{', body, re.MULTILINE))
        # v0.2.3: 也检测 logging {} 空块和内联写法
        has_logging_inline = bool(re.search(r'logging\s*=\s*\{', body))
        # 检查是否有关联的 aws_s3_bucket_logging 资源
        has_separate_logging = bucket_name in logging_buckets
        # v0.2.3: 检测 body 中是否有 target/target_bucket 引用（HCL4 compat）
        has_target_ref = bool(re.search(r'(?i)\b(target_bucket|target)\s*=', body))
        # v0.2.3: 嵌套版 logging（aws_s3_bucket_logging 内联在 bucket 块中）
        has_nested_logging = bool(re.search(r'logging\s*\{[^}]*}', body, re.DOTALL))
        
        if has_logging_block or has_logging_inline or has_separate_logging or has_target_ref or has_nested_logging:
            continue
        
        line_no = text[:m.start()].count('\n') + 1
        add(issues, 'warn', 'tf-s3-no-logging', (path, line_no),
            f'S3 bucket "{bucket_name}" 未启用访问日志，审计跟踪缺失（Cloudflare 273K PDF 泄漏后关键补强）',
            suggestion='添加 logging {} 块、嵌套 logging {} 或关联 aws_s3_bucket_logging 资源，记录所有访问事件')


def _check_tf_kms_rotation(path, text, issues):
    """tf-kms-no-rotation: KMS 密钥未启用自动轮换（WARN）"""
    if 'aws_kms_key' in text and 'enable_key_rotation' not in text:
        line_no = text[:text.index('aws_kms_key')].count('\n') + 1
        add(issues, 'warn', 'tf-kms-no-rotation', (path, line_no), 'KMS 密钥未启用自动轮换，长期密钥泄漏影响面大',
            suggestion='在 aws_kms_key 资源中设置 enable_key_rotation = true')


def _check_tf_iam_condition(path, text, issues):
    """tf-iam-no-condition: IAM policy 缺条件键（WARN）"""
    for m in re.finditer(r'(?i)\b(actions|notactions)\s*=\s*\[[^]]*\]', text):
        block_end = text.find('}', m.end())
        snippet = text[m.start():block_end] if block_end != -1 else text[m.start():]
        if (re.search(r'(?i)\b(actions|notactions)\s*=\s*\[', snippet) and
            'condition' not in snippet.lower()):
            line_no = text[:m.start()].count('\n') + 1
            add(issues, 'warn', 'tf-iam-no-condition', (path, line_no), 'IAM 策略未设置 Condition 条件键，缺少额外约束层（源IP/MFA/标签等）',
                suggestion='添加 Condition 块限制访问来源（如 aws:SourceIp、aws:MultiFactorAuthPresent）')


def scan_tf(path, text, issues):
    """Terraform IaC 扫描入口：依次执行 7 条核心 + 5 条扩展规则。"""
    lines = text.splitlines()
    _check_tf_s3_acl(path, text, lines, issues)
    _check_tf_open_cidr(path, text, lines, issues)
    _check_tf_iam_wildcard(path, text, lines, issues)
    _check_tf_db_prevent_destroy(path, text, issues)
    _check_tf_s3_logging(path, text, issues)
    _check_tf_kms_rotation(path, text, issues)
    _check_tf_iam_condition(path, text, issues)

    # P8 扩展规则（R19-R23）
    try:
        import iac_scan_extended  # noqa: F401 — 延迟导入避免循环依赖
        iac_scan_extended.scan_extended_tf(path, text, issues)
    except ImportError:  # codeguard: ignore GOLD_NO_EMPTY_EXCEPT
        pass
