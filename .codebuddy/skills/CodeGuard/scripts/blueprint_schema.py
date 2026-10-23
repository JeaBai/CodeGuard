#!/usr/bin/env python3
"""
CodeGuard Architecture Blueprint Schema (v1.0.0)
==================================================
定义 architecture_blueprint.json 的完整 Pydantic Model 用于运行时校验，
并提供 validate_blueprint(data) -> tuple[bool, list[str]] 函数。

用法：
  from blueprint_schema import Blueprint, validate_blueprint

  ok, errors = validate_blueprint(data)
  if not ok:
      for e in errors:
          print(f"  - {e}")

依赖：
  优先使用 pydantic>=2.0（pip install pydantic），若不可用则退化为纯标准库校验。

设计依据：
  - CodeGuard 架构蓝图：为 constraint_injector.py 生成前约束提供结构化输入
  - 与 quality_arch.py 的依赖图检测对齐（模块依赖、循环依赖、分层违规）
  - 与 rules.json 的 constraints 字段共享全局约束语义
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

# ============================================================
# Pydantic Model（优先使用 pydantic，不可用时退化为 dataclass）
# ============================================================

_PYDANTIC_AVAILABLE = False
try:
    from pydantic import BaseModel, Field, field_validator  # pydantic>=2.0

    _PYDANTIC_AVAILABLE = True
except ImportError:
    try:
        from pydantic import BaseModel, Field, validator as field_validator  # pydantic v1

        _PYDANTIC_AVAILABLE = True
    except ImportError:
        BaseModel = object  # type: ignore[assignment,misc]
        Field = None  # type: ignore[assignment]

_VALID_TAGS = frozenset(
    {"core", "leaf_only", "no_split", "allow_split", "frozen", "shared_util"}
)
_VALID_SCOPES = frozenset({"global", "local"})


# ============================================================
# 常量：Schema 元信息
# ============================================================

SCHEMA_VERSION = "1.0.0"
SCHEMA_FILE = Path(__file__).resolve().parent.parent.parent.parent / "schemas" / "architecture_blueprint.schema.json"


def load_json_schema() -> dict[str, Any]:
    """加载同级目录下的 JSON Schema 文件。"""
    if SCHEMA_FILE.exists():
        with open(SCHEMA_FILE, encoding="utf-8") as fh:
            return json.load(fh)
    return {}


# ============================================================
# Pydantic Model 定义
# ============================================================

if _PYDANTIC_AVAILABLE:

    class _ParamDef(BaseModel):
        """参数定义：每个参数的作用域与判定原因。"""
        scope: str = Field(..., description="参数作用域", pattern=r"^(global|local)$")
        reason: str = Field(..., description="作用域判定原因", min_length=1)

    class _PublicApi(BaseModel):
        """公共接口条目：函数名、参数列表描述、返回值类型 + 克隆检测四元组（v1.1.0）。"""
        name: str = Field(..., description="函数/方法名", min_length=1)
        params: str = Field(..., description="参数列表描述，如 'x: int, y: str'")
        return_type: str = Field(..., description="返回值类型，如 'bool'、'Optional[str]'")
        file: str = Field(default="", description="源码文件路径（克隆检测用）")
        line: int = Field(default=0, ge=0, description="函数起始行号")
        arity: int = Field(default=0, ge=0, description="参数个数")
        source: str = Field(default="", description="函数源码（AST body hash / 正则体捕获）")

    class _SharedUtil(BaseModel):
        """公共复用函数条目。"""
        name: str = Field(..., description="函数名", min_length=1)
        location: str = Field(..., description="文件路径", min_length=1)
        consumers: list[str] = Field(default_factory=list, description="消费该函数的模块名列表")
        signature: str = Field(..., description="函数签名", min_length=1)

    class _Constraints(BaseModel):
        """全局约束对象。"""
        forbid_duplicate_functions: bool = Field(..., description="禁止未经提取的重复函数定义")
        forbid_new_global_state: bool = Field(
            ..., description="禁止新增全局状态，global_config 标签变量除外"
        )
        max_files_per_module: int = Field(..., description="每模块最大文件数", ge=1)
        require_shared_util_extraction: bool = Field(
            ..., description="发现重复代码时必须提取为 shared_util"
        )
        max_complexity: int = Field(..., description="最大圈复杂度阈值", ge=1)
        max_function_lines: int = Field(..., description="单函数最大行数", ge=1)

    class _Module(BaseModel):
        """模块条目：描述单个模块的名称、路径、职责、依赖、接口、嵌套深度等。"""
        name: str = Field(..., description="模块名", min_length=1)
        path: str = Field(..., description="文件/目录路径", min_length=1)
        responsibility: str = Field(..., description="一句话职责描述", min_length=1)
        depends_on: list[str] = Field(default_factory=list, description="依赖的其他模块名")
        public_api: list[_PublicApi] = Field(default_factory=list, description="公共接口清单")
        params: dict[str, _ParamDef] = Field(default_factory=dict, description="参数清单")
        max_nesting: int = Field(..., description="当前最大嵌套深度", ge=0)
        allowed_nesting: int = Field(..., description="允许的最大嵌套深度", ge=0)
        tags: list[str] = Field(default_factory=list, description="模块标签")
        file_count: int = Field(..., description="文件数量", ge=1)
        total_lines: int = Field(..., description="总行数", ge=0)

        @field_validator("tags")
        @classmethod
        def _check_tags(cls, v: list[str]) -> list[str]:
            for tag in v:
                if tag not in _VALID_TAGS:
                    raise ValueError(f"无效标签 '{tag}'，允许值: {sorted(_VALID_TAGS)}")
            return v

    class _BlueprintPydantic(BaseModel):
        """架构蓝图 Pydantic 根模型。"""
        version: str = Field(default=SCHEMA_VERSION, description="Schema 版本号")
        project_name: str = Field(..., description="项目名称", min_length=1)
        generated_at: str = Field(..., description="ISO8601 时间戳")
        modules: list[_Module] = Field(..., description="模块清单", min_length=1)
        shared_utils: list[_SharedUtil] = Field(default_factory=list, description="公共复用函数清单")
        constraints: _Constraints = Field(..., description="全局约束")
        dependency_graph: dict[str, list[str]] = Field(
            default_factory=dict, description="模块依赖图（邻接表）"
        )

    Blueprint = _BlueprintPydantic  # type: ignore[misc]

else:
    Blueprint = None  # type: ignore[assignment]


# ============================================================
# 纯标准库校验函数（pydantic 不可用时的回退方案）
# ============================================================

def _validate_bool(value: Any, path: str, errors: list[str]) -> bool:
    """校验布尔类型。"""
    if isinstance(value, bool):
        return True
    errors.append(f"{path}: 期望 bool，实际为 {type(value).__name__}")
    return False


def _validate_str(value: Any, path: str, errors: list[str], allow_empty: bool = False) -> bool:
    """校验字符串类型与非空。"""
    if not isinstance(value, str):
        errors.append(f"{path}: 期望 str，实际为 {type(value).__name__}")
        return False
    if not allow_empty and not value:
        errors.append(f"{path}: 不能为空字符串")
        return False
    return True


def _validate_int(value: Any, path: str, errors: list[str], min_val: Optional[int] = None) -> bool:
    """校验整数类型与最小值。"""
    if not isinstance(value, int) or isinstance(value, bool):
        errors.append(f"{path}: 期望 int，实际为 {type(value).__name__}")
        return False
    if min_val is not None and value < min_val:
        errors.append(f"{path}: 值 {value} 小于最小值 {min_val}")
        return False
    return True


def _validate_list_of_str(value: Any, path: str, errors: list[str]) -> bool:
    """校验字符串数组。"""
    if not isinstance(value, list):
        errors.append(f"{path}: 期望 list，实际为 {type(value).__name__}")
        return False
    for i, item in enumerate(value):
        if not isinstance(item, str):
            errors.append(f"{path}[{i}]: 期望 str，实际为 {type(item).__name__}")
            return False
    return True


def _validate_module(module: Any, index: int, errors: list[str]) -> bool:
    """校验单个 module 对象。"""
    prefix = f"modules[{index}]"
    if not isinstance(module, dict):
        errors.append(f"{prefix}: 期望 object，实际为 {type(module).__name__}")
        return False

    ok = True
    # 必填字符串字段
    for field in ("name", "path", "responsibility"):
        ok &= _validate_str(module.get(field), f"{prefix}.{field}", errors)

    # depends_on
    ok &= _validate_list_of_str(module.get("depends_on"), f"{prefix}.depends_on", errors)

    # public_api
    api = module.get("public_api")
    if not isinstance(api, list):
        errors.append(f"{prefix}.public_api: 期望 list，实际为 {type(api).__name__}")
        ok = False
    else:
        for j, entry in enumerate(api):
            if not isinstance(entry, dict):
                errors.append(f"{prefix}.public_api[{j}]: 期望 object")
                ok = False
                continue
            for f in ("name", "params", "return_type"):
                ok &= _validate_str(entry.get(f), f"{prefix}.public_api[{j}].{f}", errors)
            # v1.1.0: 可选字段（file/line/arity/source）— 仅做类型校验，不强制非空
            if "line" in entry and not isinstance(entry["line"], (int, type(None))):
                errors.append(f"{prefix}.public_api[{j}].line: 期望 int")
                ok = False
            if "arity" in entry and not isinstance(entry["arity"], (int, type(None))):
                errors.append(f"{prefix}.public_api[{j}].arity: 期望 int")
                ok = False

    # params (dict of ParamDef)
    params_obj = module.get("params")
    if not isinstance(params_obj, dict):
        errors.append(f"{prefix}.params: 期望 object，实际为 {type(params_obj).__name__}")
        ok = False
    else:
        for pname, pval in params_obj.items():
            if not isinstance(pval, dict):
                errors.append(f"{prefix}.params.{pname}: 期望 object")
                ok = False
                continue
            scope = pval.get("scope", "")
            if scope not in _VALID_SCOPES:
                errors.append(
                    f"{prefix}.params.{pname}.scope: 无效值 '{scope}'，"
                    f"允许: {sorted(_VALID_SCOPES)}"
                )
                ok = False
            ok &= _validate_str(pval.get("reason"), f"{prefix}.params.{pname}.reason", errors)

    # 整数字段
    for int_field, min_val in (
        ("max_nesting", 0),
        ("allowed_nesting", 0),
        ("file_count", 1),
        ("total_lines", 0),
    ):
        ok &= _validate_int(module.get(int_field), f"{prefix}.{int_field}", errors, min_val)

    # tags
    tags = module.get("tags")
    if not isinstance(tags, list):
        errors.append(f"{prefix}.tags: 期望 list，实际为 {type(tags).__name__}")
        ok = False
    else:
        for tag in tags:
            if not isinstance(tag, str):
                errors.append(f"{prefix}.tags: 元素期望 str")
                ok = False
            elif tag not in _VALID_TAGS:
                errors.append(
                    f"{prefix}.tags: 无效标签 '{tag}'，允许: {sorted(_VALID_TAGS)}"
                )
                ok = False

    return ok


def _validate_shared_util(util: Any, index: int, errors: list[str]) -> bool:
    """校验单个 shared_util 对象。"""
    prefix = f"shared_utils[{index}]"
    if not isinstance(util, dict):
        errors.append(f"{prefix}: 期望 object，实际为 {type(util).__name__}")
        return False

    ok = True
    for field in ("name", "location", "signature"):
        ok &= _validate_str(util.get(field), f"{prefix}.{field}", errors)
    ok &= _validate_list_of_str(util.get("consumers"), f"{prefix}.consumers", errors)
    return ok


def _validate_constraints(constraints: Any, errors: list[str]) -> bool:
    """校验 constraints 对象。"""
    if not isinstance(constraints, dict):
        errors.append(f"constraints: 期望 object，实际为 {type(constraints).__name__}")
        return False

    ok = True
    # 布尔字段
    for bool_field in (
        "forbid_duplicate_functions",
        "forbid_new_global_state",
        "require_shared_util_extraction",
    ):
        ok &= _validate_bool(constraints.get(bool_field), f"constraints.{bool_field}", errors)

    # 整数字段
    for int_field, min_val in (("max_files_per_module", 1), ("max_complexity", 1), ("max_function_lines", 1)):
        ok &= _validate_int(constraints.get(int_field), f"constraints.{int_field}", errors, min_val)

    return ok


def _validate_dependency_graph(graph: Any, modules: list[dict], errors: list[str]) -> bool:
    """校验 dependency_graph 邻接表。"""
    if not isinstance(graph, dict):
        errors.append(f"dependency_graph: 期望 object，实际为 {type(graph).__name__}")
        return False

    ok = True
    module_names = {m.get("name", "") for m in modules if isinstance(m, dict)}

    for mod_name, deps in graph.items():
        if mod_name not in module_names:
            errors.append(f"dependency_graph['{mod_name}']: 引用了未在 modules 中定义的模块")
            ok = False
        if not isinstance(deps, list):
            errors.append(
                f"dependency_graph['{mod_name}']: 期望 list，实际为 {type(deps).__name__}"
            )
            ok = False
            continue
        for dep in deps:
            if not isinstance(dep, str):
                errors.append(f"dependency_graph['{mod_name}']: 依赖项期望 str")
                ok = False
            elif dep not in module_names:
                errors.append(
                    f"dependency_graph['{mod_name}']: 依赖 '{dep}' 未在 modules 中声明"
                )
                ok = False

    return ok


def _validate_fallback(data: dict[str, Any]) -> list[str]:
    """纯标准库校验（pydantic 不可用时的回退方案）。"""
    errors: list[str] = []

    if not isinstance(data, dict):
        errors.append(f"顶层: 期望 dict，实际为 {type(data).__name__}")
        return errors

    # 顶层必填字段
    for field in ("version", "project_name", "generated_at"):
        _validate_str(data.get(field), field, errors)

    # version 格式
    version = data.get("version", "")
    if isinstance(version, str) and version:
        import re
        if not re.match(r"^\d+\.\d+\.\d+$", version):
            errors.append(f"version: 格式应为 X.Y.Z，实际为 '{version}'")

    # generated_at 格式
    generated_at = data.get("generated_at", "")
    if isinstance(generated_at, str) and generated_at:
        for fmt in (
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%dT%H:%M:%S%z",
        ):
            try:
                datetime.strptime(generated_at.replace("Z", "+0000"), fmt.replace("Z", "+0000"))
                break
            except ValueError:
                continue
        else:
            errors.append(f"generated_at: 无法解析为 ISO8601 时间戳: '{generated_at}'")

    # modules
    modules = data.get("modules")
    if not isinstance(modules, list) or len(modules) == 0:
        errors.append("modules: 必须为非空数组")
    else:
        for i, module in enumerate(modules):
            _validate_module(module, i, errors)

    # shared_utils
    shared_utils = data.get("shared_utils")
    if not isinstance(shared_utils, list):
        errors.append(f"shared_utils: 期望 list，实际为 {type(shared_utils).__name__}")
    else:
        for i, util in enumerate(shared_utils):
            _validate_shared_util(util, i, errors)

    # constraints
    _validate_constraints(data.get("constraints"), errors)

    # dependency_graph
    _validate_dependency_graph(data.get("dependency_graph"), modules if isinstance(modules, list) else [], errors)

    return errors


# ============================================================
# 主校验函数
# ============================================================

def validate_blueprint(data: dict[str, Any]) -> tuple[bool, list[str]]:
    """校验 architecture_blueprint 数据是否合法。

    Args:
        data: 待校验的蓝图字典。

    Returns:
        (is_valid, errors) — is_valid 为 True 表示通过校验；
        errors 为错误信息列表（通过时为空列表）。
    """
    if _PYDANTIC_AVAILABLE and Blueprint is not None:
        try:
            Blueprint.model_validate(data) if hasattr(Blueprint, "model_validate") else Blueprint.parse_obj(data)  # type: ignore[union-attr]
            return True, []
        except Exception as exc:
            # 提取 pydantic 错误信息
            errors = str(exc).split("\n")
            return False, [e.strip() for e in errors if e.strip()]

    # 回退：纯标准库校验
    errors = _validate_fallback(data)
    return len(errors) == 0, errors


def validate_blueprint_file(filepath: str) -> tuple[bool, list[str]]:
    """从文件加载并校验 architecture_blueprint.json。

    Args:
        filepath: 蓝图 JSON 文件路径。

    Returns:
        (is_valid, errors)
    """
    try:
        with open(filepath, encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        return False, [f"文件不存在: {filepath}"]
    except json.JSONDecodeError as exc:
        return False, [f"JSON 解析失败: {exc}"]
    return validate_blueprint(data)


# ============================================================
# CLI 入口（调试用）
# ============================================================

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print(f"用法: python {Path(__file__).name} <blueprint.json>")
        sys.exit(1)

    ok, errors = validate_blueprint_file(sys.argv[1])
    if ok:
        print("✅ 校验通过")
        sys.exit(0)
    else:
        print(f"❌ 校验失败 ({len(errors)} 条错误):")
        for err in errors:
            print(f"  - {err}")
        sys.exit(1)
