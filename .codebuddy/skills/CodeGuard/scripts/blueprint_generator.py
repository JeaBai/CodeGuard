#!/usr/bin/env python3
"""
CodeGuard Architecture Blueprint Generator (v1.0.0)
======================================================
从代码库自动提取模块结构、依赖关系、公共 API、嵌套层级，
生成符合 architecture_blueprint.schema.json 规范的蓝图 JSON。

用法：
  python blueprint_generator.py --path <项目根目录> --output <输出路径>

  增量更新模式（保留用户手动调整）：
  python blueprint_generator.py --path . --output blueprint.json --incremental

依赖：
  零外部依赖，仅 Python 标准库。复用 quality_core / quality_arch / blueprint_schema。
  文件提取/解析逻辑拆分至 blueprint_extractor.py（模块划分、依赖图、公共 API、
  参数流、嵌套层级、重复函数检测）。

设计依据：
  - CodeGuard 三层防线：生成前约束注入需要结构化的模块/依赖/约束蓝图
  - 与 quality_arch.py 共享 MULTILANG_IMPORT_PATTERNS 实现一致的多语言 import 提取
  - 与 blueprint_schema.py 的 validate_blueprint() 集成确保输出始终合法
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# ============================================================
# 内部模块导入（脚本运行目录为 scripts/，支持直接导入同目录模块）
# ============================================================

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from blueprint_extractor import (  # noqa: E402
    _build_dependency_graph,
    _collect_files,
    _detect_duplicates,
    _extract_modules,
    _extract_params_and_nesting,
    _extract_public_api,
    _get_quality_arch,
)

# 延迟导入避免循环依赖
_blueprint_schema = None


def _get_blueprint_schema():
    global _blueprint_schema
    if _blueprint_schema is None:
        import blueprint_schema as bs
        _blueprint_schema = bs
    return _blueprint_schema


# ============================================================
# 常量定义
# ============================================================

SCHEMA_VERSION = "1.0.0"

DEFAULT_CONSTRAINTS = {
    "forbid_duplicate_functions": True,
    "forbid_new_global_state": True,
    "max_files_per_module": 8,
    "require_shared_util_extraction": True,
    "max_complexity": 15,
    "max_function_lines": 80,
}

_VALID_TAGS = frozenset({
    "core", "leaf_only", "no_split", "allow_split", "frozen", "shared_util", "test_only",
})


# ============================================================
# 工具函数
# ============================================================

def _log(msg: str) -> None:
    """统一日志输出到 stderr。"""
    sys.stderr.write(f"[BlueprintGen] {msg}\n")
    sys.stderr.flush()


# ============================================================
# 标签推断
# ============================================================

def _infer_tags(
    module_name: str,
    module_info: dict,
    dependency_graph: dict[str, list[str]],
    shared_utils: list[dict],
) -> list[str]:
    """根据模块特征自动推断标签。

    规则：
      - 无依赖且不被依赖 → "leaf_only"
      - 被 >3 个模块依赖 → "core"
      - 文件数 >10 → "allow_split"
      - 路径含 test/spec → "test_only"
      - shared_util consumer → "shared_util"
    """
    tags: list[str] = []

    deps = dependency_graph.get(module_name, [])
    # 反向依赖：哪些模块依赖了当前模块
    reverse_deps = []
    for m, dlist in dependency_graph.items():
        if module_name in dlist:
            reverse_deps.append(m)

    # leaf_only：无依赖出边且无被依赖
    if not deps and not reverse_deps:
        tags.append("leaf_only")

    # core：被 >3 个模块依赖
    if len(reverse_deps) > 3:
        tags.append("core")

    # allow_split：文件数 >10
    if module_info.get("file_count", 0) > 10:
        tags.append("allow_split")

    # test_only：路径含 test/spec/__tests__
    module_path = module_info.get("path", "").lower()
    if any(kw in module_path for kw in ("test", "spec", "__tests__")):
        tags.append("test_only")

    # shared_util：该模块名出现在 shared_utils 的 consumers
    for util in shared_utils:
        if module_name in util.get("consumers", []):
            if "shared_util" not in tags:
                tags.append("shared_util")
            break

    # 验证标签在白名单内
    return [t for t in tags if t in _VALID_TAGS]


# ============================================================
# 增量更新支持
# ============================================================

def _load_existing_blueprint(filepath: str) -> dict | None:
    """加载已有蓝图文件。"""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _merge_user_overrides(existing: dict, generated: dict) -> dict:
    """增量更新：保留用户手动设置的 tags 和 constraints，合并 user_overrides。

    策略：
      - constraints: 以用户手动设置的值覆盖自动生成
      - tags: 以用户手动标签替换自动推断标签
      - modules/shared_utils/dependency_graph: 使用自动生成的最新值
      - user_overrides: 记录用户手动修改的字段
    """
    existing_overrides = existing.get("user_overrides", {})
    existing_modules = {m["name"]: m for m in existing.get("modules", [])}

    # 合并模块级 tags（用户手动 > 自动推断）
    for module in generated["modules"]:
        mod_name = module["name"]
        if mod_name in existing_modules:
            existing_tags = existing_modules[mod_name].get("tags", [])
            auto_tags = module.get("tags", [])
            # 用户手动标签覆盖自动标签
            module["tags"] = existing_tags if existing_tags else auto_tags

    # 合并 constraints（用户手动 > 自动默认）
    existing_constraints = existing.get("constraints", {})
    if existing_constraints:
        generated["constraints"] = existing_constraints

    # 合并 user_overrides
    user_constraint_keys = set(existing_constraints.keys())
    user_tag_modules = [
        m["name"] for m in existing.get("modules", [])
        if m.get("tags") and m["name"] in {g["name"] for g in generated["modules"]}
    ]
    generated["user_overrides"] = {
        "constraints_modified": sorted(user_constraint_keys),
        "tags_modified_modules": sorted(user_tag_modules),
        "last_manual_edit": existing_overrides.get("last_manual_edit", ""),
    }

    return generated


# ============================================================
# 主生成器
# ============================================================

def generate_blueprint(
    project_root: str,
    existing_blueprint: dict | None = None,
) -> dict:
    """从代码库生成 architecture_blueprint 数据。

    Args:
        project_root: 项目根目录路径。
        existing_blueprint: 已有的蓝图数据（增量更新模式）。

    Returns:
        符合 architecture_blueprint.schema.json 的字典。
    """
    project_root = os.path.abspath(project_root)
    project_name = os.path.basename(project_root.rstrip("/\\"))
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    _log(f"扫描项目: {project_root}")

    # 1. 收集文件
    all_files = _collect_files(project_root)
    _log(f"  发现 {len(all_files)} 个源码文件")

    # 2. 模块提取
    modules_raw = _extract_modules(project_root, all_files)
    _log(f"  提取 {len(modules_raw)} 个模块")

    # 3. 依赖分析
    dependency_graph, cycles = _build_dependency_graph(project_root, modules_raw)
    _log(f"  构建依赖图: {sum(len(v) for v in dependency_graph.values())} 条依赖边")
    if cycles:
        _log(f"  检测到 {len(cycles)} 个循环依赖")

    # 4. 每个模块提取详细信息
    modules_output: list[dict] = []
    total_public_api = 0

    for mname, minfo in modules_raw.items():
        # 公共 API
        public_api = []
        for fpath in minfo["files"]:
            api_items = _extract_public_api(fpath)
            public_api.extend(api_items)
        total_public_api += len(public_api)

        # 参数 + 嵌套深度
        params_dict, max_nesting, _ = _extract_params_and_nesting(minfo["files"])

        module_entry = {
            "name": mname,
            "path": minfo["path"],
            "responsibility": f"{mname} 模块职责待补充",
            "depends_on": dependency_graph.get(mname, []),
            "public_api": public_api,
            "params": params_dict,
            "max_nesting": max_nesting,
            "allowed_nesting": max_nesting,
            "tags": [],
            "file_count": minfo["file_count"],
            "total_lines": minfo["total_lines"],
        }
        modules_output.append(module_entry)

    # 5. 重复函数检测
    shared_utils = _detect_duplicates(modules_raw)
    _log(f"  检测到 {len(shared_utils)} 个跨文件重复函数")

    # 6. 标签推断
    for module in modules_output:
        module["tags"] = _infer_tags(
            module["name"], module, dependency_graph, shared_utils
        )

    # 7. 构建蓝图
    blueprint = {
        "version": SCHEMA_VERSION,
        "project_name": project_name,
        "generated_at": generated_at,
        "modules": modules_output,
        "shared_utils": shared_utils,
        "constraints": dict(DEFAULT_CONSTRAINTS),
        "dependency_graph": {m: sorted(deps) for m, deps in dependency_graph.items()},
    }

    # 8. 增量合并
    if existing_blueprint:
        blueprint = _merge_user_overrides(existing_blueprint, blueprint)
        _log("  增量更新: 保留用户手动修改的 tags 和 constraints")

    return blueprint


# ============================================================
# 输出 + 校验
# ============================================================

def save_blueprint(blueprint: dict, output_path: str, validate: bool = True) -> bool:
    """保存蓝图到文件，可选校验。

    Returns:
        True 表示写入成功。
    """
    if validate:
        bs = _get_blueprint_schema()
        ok, errors = bs.validate_blueprint(blueprint)
        if not ok:
            _log("校验失败！蓝图数据不合法：")
            for e in errors:
                _log(f"  - {e}")
            return False

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(blueprint, f, indent=2, ensure_ascii=False)
    _log(f"蓝图已保存至: {output_path}")
    return True


def print_summary(blueprint: dict) -> None:
    """控制台输出蓝图摘要。"""
    modules = blueprint.get("modules", [])
    deps = blueprint.get("dependency_graph", {})
    total_api = sum(len(m.get("public_api", [])) for m in modules)
    total_edges = sum(len(v) for v in deps.values())
    shared_count = len(blueprint.get("shared_utils", []))

    # 检测循环依赖（已在 dependency_graph 构建时检测，此处打印标记）
    qa = _get_quality_arch()
    # 从模块依赖图中检测循环
    _, cycles = _build_dependency_graph(
        os.getcwd(),
        {m["name"]: {"path": m["path"], "files": [], "file_count": 0, "total_lines": 0}
         for m in modules}
    ) if modules else ({}, [])

    print("\n" + "=" * 60)
    print("  Architecture Blueprint 生成摘要")
    print("=" * 60)
    print(f"  项目名称:     {blueprint.get('project_name', 'N/A')}")
    print(f"  蓝图版本:     {blueprint.get('version', 'N/A')}")
    print(f"  生成时间:     {blueprint.get('generated_at', 'N/A')}")
    print(f"  模块数:       {len(modules)}")
    print(f"  依赖关系数:   {total_edges}")
    print(f"  公共 API 数:  {total_api}")
    print(f"  循环依赖:     {len(cycles)} 个" +
          (f" ({', '.join('→'.join(c) for c in cycles[:3])})" if cycles else ""))
    print(f"  重复函数数:   {shared_count}")
    print(f"  约束集:       默认（金级）")
    print("=" * 60)

    # 模块详情
    print("\n  模块清单:")
    for m in modules:
        tags_str = ", ".join(m.get("tags", [])) or "(无标签)"
        print(f"    [{tags_str}] {m['name']}")
        print(f"       路径: {m['path']}  文件数: {m['file_count']}  行数: {m['total_lines']}")
        print(f"       嵌套深度: {m['max_nesting']}/{m['allowed_nesting']}  "
              f"公共 API: {len(m.get('public_api', []))}")
        deps_list = m.get("depends_on", [])
        if deps_list:
            print(f"       依赖: {', '.join(deps_list[:5])}" +
                  (f" (+{len(deps_list) - 5})" if len(deps_list) > 5 else ""))


# ============================================================
# CLI 入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="CodeGuard Architecture Blueprint Generator — 从代码库自动生成架构蓝图",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python blueprint_generator.py --path . --output blueprint.json
  python blueprint_generator.py --path /project --output blueprint.json --incremental
  python blueprint_generator.py --path . --output blueprint.json --no-validate
        """,
    )
    parser.add_argument("--path", required=True, help="项目根目录路径")
    parser.add_argument("--output", required=True, help="输出 JSON 文件路径")
    parser.add_argument("--incremental", action="store_true",
                        help="增量更新模式：读取已有蓝图并保留用户手动修改")
    parser.add_argument("--no-validate", action="store_true",
                        help="跳过蓝图合法性校验")
    parser.add_argument("--summary-only", action="store_true",
                        help="仅打印摘要不写文件")
    args = parser.parse_args()

    project_root = os.path.abspath(args.path)
    if not os.path.isdir(project_root):
        _log(f"错误: 路径不存在或不是目录: {project_root}")
        sys.exit(1)

    # 增量模式：加载已有蓝图
    existing = None
    if args.incremental:
        existing = _load_existing_blueprint(args.output)
        if existing:
            _log(f"增量更新模式: 从 {args.output} 加载已有蓝图")
        else:
            _log(f"增量更新模式: 未找到已有蓝图，将全量生成")

    # 生成蓝图
    blueprint = generate_blueprint(project_root, existing)

    # 打印摘要
    print_summary(blueprint)

    if args.summary_only:
        return

    # 保存
    validate = not args.no_validate
    success = save_blueprint(blueprint, args.output, validate=validate)
    if not success and validate:
        _log("蓝图校验未通过，文件未写入。使用 --no-validate 强制写入或修复数据。")
        sys.exit(2)
    elif not success:
        # 不校验模式仍写入
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(blueprint, f, indent=2, ensure_ascii=False)
        _log(f"蓝图已强制保存至: {args.output} (校验跳过)")


if __name__ == "__main__":
    main()
