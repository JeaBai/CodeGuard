#!/usr/bin/env python3
"""quality_rule_registry.py — CodeGuard 规则统一注册表（单一事实源）

收敛三层防线共享的规则元数据，消除三处硬编码不一致（v3.0.0）：
  - 第一层：constraint_injector.load_skill_rules / generate_quick_checklist
  - 第二层：quality_mid_check.check_snippet（逐项自查置信度）
  - 第三层：IssueCollector.confidence_base + rule_id→category 闭环映射

规则元数据字段：
  rule_id      规则唯一标识（注入约束与检出违规闭环的锚点）
  name         规则中文名
  description  注入到 AI 上下文的规则描述
  severity     block/warn/info
  category     检出时的 category 名（对应 CONFIDENCE_BASE 的 key）
  file_types   适用文件类型（与 FileClassifier 五类对齐）
  checklist    自查清单简短文本
  pattern      可选，安全红线的正则（供生成中自查快速判定）
"""

# ============================================================
# 10 条规则元数据（单一事实源）
# ============================================================

RULE_SPECS = [
    {
        "rule_id": "SOLID_SRP",
        "name": "单一职责原则",
        "description": "类方法数 ≤15，类代码行数 ≤300（警告）/≤500（阻塞）",
        "severity": "warn",
        "category": "class_size",
        "file_types": ("source", "test"),
        "checklist": "类方法数 ≤15，类代码行数 ≤300",
    },
    {
        "rule_id": "SOLID_DIP",
        "name": "依赖倒置原则",
        "description": "Domain 层不得直接 import Infrastructure 层",
        "severity": "block",
        "category": "architecture",
        "file_types": ("source", "test", "config", "migration"),
        "checklist": "Domain 不依赖 Infrastructure",
    },
    {
        "rule_id": "LAYER_VIOLATION",
        "name": "分层架构约束",
        "description": "Domain → 不可依赖上层；Application → 只能依赖 Domain",
        "severity": "block",
        "category": "architecture",
        "file_types": ("source", "test", "config", "migration"),
        "checklist": "遵循分层架构，Domain 不依赖上层",
    },
    {
        "rule_id": "COMPLEXITY_CC",
        "name": "圈复杂度限制",
        "description": "CC >10 警告，CC >15 阻塞",
        "severity": "warn",
        "category": "complexity",
        "file_types": ("source", "test"),
        "checklist": "圈复杂度 ≤10",
    },
    {
        "rule_id": "DUPLICATE_CODE",
        "name": "重复代码检测",
        "description": "连续 6 行相同警告，10 行相同阻塞",
        "severity": "warn",
        "category": "duplication",
        "file_types": ("source", "test"),
        "checklist": "避免重复代码（DRY）",
    },
    {
        "rule_id": "SECURITY_HARDCODED",
        "name": "禁止硬编码密钥",
        "description": "禁止在代码中硬编码密码/API Key/Token",
        "severity": "block",
        "category": "security",
        "file_types": ("source", "config", "migration"),
        "checklist": "无硬编码密钥/密码",
        "pattern": r"(?:password|passwd|secret|api_key|apikey|token)\s*=\s*[\"'][^\"']+[\"']",
    },
    {
        "rule_id": "SECURITY_SQL_INJECTION",
        "name": "SQL注入防护",
        "description": "必须使用参数化查询，禁止字符串拼接SQL",
        "severity": "block",
        "category": "security",
        "file_types": ("source", "config", "migration"),
        "checklist": "SQL 使用参数化查询，禁止字符串拼接",
        "pattern": r"(?:execute|executemany|query|Query)\s*\(\s*[^)]*\+",
    },
    {
        "rule_id": "SECURITY_COMMAND_INJECTION",
        "name": "命令注入防护",
        "description": "禁止 eval/exec/os.system 接受外部输入",
        "severity": "block",
        "category": "security",
        "file_types": ("source", "config", "migration"),
        "checklist": "禁止 eval/exec/os.system 接受外部输入",
        "pattern": r"\beval\s*\(|\bexec\s*\(|os\.system\s*\(|subprocess\.(?:call|run|Popen)\s*\(",
    },
    {
        "rule_id": "NAMING_CONSISTENCY",
        "name": "命名一致性",
        "description": "同一概念使用统一命名，避免 getUserById/fetchUserById 混用",
        "severity": "info",
        "category": "naming",
        "file_types": ("source", "test", "config"),
        "checklist": "命名与现有风格一致",
    },
    {
        "rule_id": "ERROR_HANDLING",
        "name": "错误处理完整性",
        "description": "禁止空 except 块或仅 print(e) 的异常处理",
        "severity": "warn",
        "category": "error_handling",
        "file_types": ("source", "test", "config", "migration"),
        "checklist": "异常处理非空 except",
    },
    # ============================================================
    # v3.1.0 新增：模块化与接口设计 9 条（quality_modular.py 检出）
    # 对应《模块化与接口设计手册》§1.2/§2.1/§2.5/§4.3/§5.1/§6.1/§7.1
    # ============================================================
    {
        "rule_id": "MOD_CROSS_HARDCODE",
        "name": "跨模块硬编码路径",
        "description": "禁止在调用方写死被调模块的路径/位置；应依赖抽象并注入参数",
        "severity": "warn",
        "category": "modularity",
        "file_types": ('source',),
        "checklist": "跨模块调用走对外接口，路径由参数/配置传入",
    },
    {
        "rule_id": "MOD_PRIVATE_ACCESS",
        "name": "跨模块私有符号访问",
        "description": "禁止 from <他模块> import _私有符号；仅暴露对外接口",
        "severity": "block",
        "category": "modularity",
        "file_types": ('source',),
        "checklist": "只用对方公开接口，不用 _ 前缀私有符号",
    },
    {
        "rule_id": "MOD_DUP_STEMS",
        "name": "同名脚本歧义",
        "description": "同一语言下多模块出现同名脚本会造成 import 归属歧义",
        "severity": "warn",
        "category": "modularity",
        "file_types": ('source',),
        "checklist": "跨模块可复用脚本加模块前缀",
    },
    {
        "rule_id": "MOD_NO_INTERFACE_DOC",
        "name": "缺接口文档/模块索引",
        "description": "多模块工程须有模块索引与接口契约文档（文档即契约）",
        "severity": "warn",
        "category": "modularity_doc",
        "file_types": ('source', 'config'),
        "checklist": "补 MODULE_INDEX/ICD/OpenAPI；索引由脚本生成",
    },
    {
        "rule_id": "MOD_NO_TIMEOUT",
        "name": "跨进程调用无超时",
        "description": "网络/RPC/子进程调用必须设超时，且小于上游（逐层收敛）",
        "severity": "warn",
        "category": "resilience",
        "file_types": ('source',),
        "checklist": "加 timeout=，配有限重试+退避",
    },
    {
        "rule_id": "MOD_NO_TEST_SPLIT",
        "name": "单元/集成测试未分层",
        "description": "单元测试不出进程/不连网/不碰硬件，须与集成分层",
        "severity": "info",
        "category": "test_strategy",
        "file_types": ('test',),
        "checklist": "tests/unit 与 tests/integration 分离；CI 分 job 不互相阻塞",
    },
    {
        "rule_id": "MOD_NO_CONTRACT_TEST",
        "name": "缺接口契约校验",
        "description": "接口契约须可执行校验，避免文档与代码漂移",
        "severity": "warn",
        "category": "contract",
        "file_types": ('source', 'test'),
        "checklist": "JSON Schema/IDL 生成/CDC；嵌入式用 _Static_assert",
    },
    {
        "rule_id": "MOD_NO_LOCKFILE",
        "name": "缺依赖锁定",
        "description": "有依赖声明须提交 lockfile，保证可复现构建",
        "severity": "warn",
        "category": "reproducibility",
        "file_types": ('config',),
        "checklist": "生成并提交 poetry.lock / package-lock.json 等",
    },
    {
        "rule_id": "MOD_FLOATING_DEP",
        "name": "依赖版本浮动",
        "description": "依赖须锁精确版本，浮动版本会让两端构建结果不一致",
        "severity": "warn",
        "category": "reproducibility",
        "file_types": ('config',),
        "checklist": "用 == 或 lockfile 锁定版本",
    },
]

# ============================================================
# category → 置信度（第三层 IssueCollector 的单一事实源）
# ============================================================

CONFIDENCE_BASE = {
    "complexity": 90, "complexity_regex": 80,
    "nesting": 90, "nesting_regex": 80,
    "params": 90, "params_regex": 80,
    "class_size": 85, "class_size_regex": 75,
    "file_size": 95,
    "security": 85, "security_raw": 70,
    "duplication": 85,
    "architecture": 90, "architecture_cycle": 95, "architecture_regex": 78,
    "error_handling": 82, "naming": 75,
    "custom_rule": 85, "parse_error": 95, "custom_rule_config": 95,
    "no_files": 95,
    # v3.1.0 新增：模块化与接口设计维度（quality_modular）
    "modularity": 85,
    "modularity_doc": 75,
    "resilience": 85,
    "contract": 70,
    "test_strategy": 70,
    "reproducibility": 72,

}

# category → emoji（供 generate_quick_checklist 派生轻量清单）
CATEGORY_EMOJI = {
    "class_size": "🧩",
    "architecture": "🏗️",
    "complexity": "📏",
    "duplication": "🔄",
    "security": "🔒",
    "naming": "📝",
    "error_handling": "🛡️",
}


# ============================================================
# 纯函数查询接口
# ============================================================

def get_rules(file_type="source"):
    """返回该文件类型适用的规则（向后兼容 load_skill_rules 结构）。"""
    return [
        {"id": r["rule_id"], "name": r["name"],
         "description": r["description"], "severity": r["severity"]}
        for r in RULE_SPECS if file_type in r["file_types"]
    ]


def get_checklist(file_type="source"):
    """返回该文件类型的自查清单文本列表（保持注册表顺序）。"""
    return [r["checklist"] for r in RULE_SPECS if file_type in r["file_types"]]


def get_confidence(category):
    """返回 category 的置信度（默认 80）。"""
    return CONFIDENCE_BASE.get(category, 80)


def get_rule_ids_by_category(category):
    """返回 category 对应的 rule_id 列表（闭环映射）。"""
    return [r["rule_id"] for r in RULE_SPECS if r["category"] == category]


def get_rule_by_id(rule_id):
    """按 rule_id 返回规则元数据（未找到返回 None）。"""
    for r in RULE_SPECS:
        if r["rule_id"] == rule_id:
            return r
    return None


def get_patterns(file_type="source"):
    """返回该文件类型带正则的安全红线 (rule_id, pattern) 列表（供生成中自查）。"""
    return [(r["rule_id"], r["pattern"]) for r in RULE_SPECS
            if file_type in r["file_types"] and r.get("pattern")]


def get_category_emoji(category):
    """返回 category 对应的 emoji（默认圆点）。"""
    return CATEGORY_EMOJI.get(category, "•")
