#!/usr/bin/env python3
"""
Project Manager Template Engine (v1.0.0)
===========================================
场景模板引擎 — 根据项目类型快速生成 architecture_blueprint.json。
预置 6 大场景模板，支持关键词匹配、定制、应用。

模板存储于 .codebuddy/templates/，每个模板一个 JSON 文件。

功能：
  list_templates()                        列出所有可用模板
  get_template(template_id)               获取模板详情
  apply_template(template_id, project)    应用模板 → 生成 architecture_blueprint.json
  customize_template(template_id, mods)   定制模板（增减模块、修改约束）
  match_template(description)             自然语言匹配最佳模板
  export_template_summary(template_id)    导出人话版模板说明

用法：
  python template_engine.py --action list
  python template_engine.py --action get --id e-commerce-minimal
  python template_engine.py --action apply --id e-commerce-minimal --project .
  python template_engine.py --action match --description "我要做一个卖衣服的小程序"
  python template_engine.py --action customize --id e-commerce-minimal --add-module '{"name":"coupon"}'
  python template_engine.py --action summary --id e-commerce-minimal
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ============================================================
# 常量
# ============================================================

_TEMPLATES_DIR = ".codebuddy/templates"
_BLUEPRINT_OUTPUT = "architecture_blueprint.json"


# ============================================================
# 工具函数
# ============================================================

def _log(msg: str) -> None:
    sys.stderr.write(f"[Template] {msg}\n")
    sys.stderr.flush()


def _get_templates_dir(project_root: str = ".") -> Path:
    return Path(project_root) / _TEMPLATES_DIR


def _list_template_files(tmpl_dir: Path) -> list[Path]:
    if not tmpl_dir.exists():
        return []
    return sorted([f for f in tmpl_dir.iterdir() if f.suffix == ".json"])


def _load_template(tmpl_dir: Path, template_id: str) -> dict | None:
    fpath = tmpl_dir / f"{template_id}.json"
    if not fpath.exists():
        return None
    try:
        return json.loads(fpath.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _save_template(tmpl_dir: Path, data: dict) -> None:
    tmpl_dir.mkdir(parents=True, exist_ok=True)
    tid = data.get("template_id", "custom")
    fpath = tmpl_dir / f"{tid}.json"
    fpath.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


# ============================================================
# 公共 API：list_templates()
# ============================================================

def list_templates(project_root: str = ".") -> dict:
    tmpl_dir = _get_templates_dir(project_root)
    files = _list_template_files(tmpl_dir)
    result = []
    for fpath in files:
        tmpl = json.loads(fpath.read_text(encoding="utf-8"))
        result.append({
            "template_id": tmpl.get("template_id", ""),
            "template_name": tmpl.get("template_name", ""),
            "icon": tmpl.get("icon", ""),
            "description": tmpl.get("description", ""),
            "difficulty": tmpl.get("difficulty", ""),
            "security_level": tmpl.get("security_level", 0),
            "estimated_files": tmpl.get("estimated_files", ""),
        })
    return {"templates": result, "total": len(result)}


# ============================================================
# 公共 API：get_template()
# ============================================================

def get_template(template_id: str, project_root: str = ".") -> dict | None:
    return _load_template(_get_templates_dir(project_root), template_id)


# ============================================================
# 公共 API：apply_template()
# ============================================================

def apply_template(template_id: str, project_path: str = ".") -> dict:
    """应用模板生成 architecture_blueprint.json。"""
    tmpl_dir = _get_templates_dir(project_path)
    tmpl = _load_template(tmpl_dir, template_id)
    if tmpl is None:
        return {"status": "not_found", "template_id": template_id}

    project_name = os.path.basename(os.path.abspath(project_path))
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # 构建蓝图
    modules = []
    dep_graph: dict[str, list[str]] = {}
    for m in tmpl.get("modules", []):
        mname = m.get("name", "")
        modules.append({
            "name": mname,
            "path": f"src/{mname}",
            "responsibility": m.get("responsibility", f"{mname} 模块职责待补充"),
            "depends_on": m.get("depends_on", []),
            "public_api": [{"name": a, "params": "", "return_type": ""}
                           for a in m.get("public_api", [])],
            "params": {},
            "max_nesting": m.get("max_nesting", 3),
            "allowed_nesting": m.get("max_nesting", 3),
            "tags": m.get("tags", []),
            "file_count": 1,
            "total_lines": 0,
        })
        if m.get("depends_on"):
            dep_graph[mname] = m["depends_on"]

    blueprint = {
        "version": "1.0.0",
        "project_name": project_name,
        "generated_at": now,
        "template_id": template_id,
        "template_name": tmpl.get("template_name", ""),
        "modules": modules,
        "shared_utils": [{"name": s["name"], "location": f"src/shared/{s['name']}.py",
                          "consumers": s.get("consumers", []),
                          "signature": f"def {s['name']}(...) -> Any"}
                         for s in tmpl.get("shared_utils", [])],
        "constraints": tmpl.get("constraints", {}),
        "dependency_graph": dep_graph,
        "security_baseline": tmpl.get("security_baseline", {}),
        "test_template": tmpl.get("test_template", {}),
        "user_overrides": {"template_applied": template_id, "last_manual_edit": ""},
    }

    # 写入文件
    bp_path = os.path.join(project_path, _BLUEPRINT_OUTPUT)
    with open(bp_path, "w", encoding="utf-8") as f:
        json.dump(blueprint, f, indent=2, ensure_ascii=False)

    _log(f"模板已应用: {template_id} → {bp_path}")
    _log(f"  生成 {len(modules)} 个模块, {len(tmpl.get('shared_utils', []))} 个共享工具")
    return {"status": "applied", "template_id": template_id, "file": bp_path,
            "modules": len(modules), "shared_utils": len(tmpl.get("shared_utils", []))}


# ============================================================
# 公共 API：customize_template()
# ============================================================

def customize_template(template_id: str, modifications: dict,
                       project_root: str = ".") -> dict:
    """定制模板：增减模块、修改约束。

    modifications:
      {"add_module": {"name":"coupon","responsibility":"优惠券"},
       "remove_module": "admin",
       "update_constraints": {"max_files_per_module": 8},
       "add_shared_util": {"name":"send_sms","consumers":["user"]}}
    """
    tmpl_dir = _get_templates_dir(project_root)
    tmpl = _load_template(tmpl_dir, template_id)
    if tmpl is None:
        return {"status": "not_found", "template_id": template_id}

    changed = []

    # 添加模块
    add_mod = modifications.get("add_module")
    if add_mod and isinstance(add_mod, dict):
        existing = {m.get("name", "") for m in tmpl.get("modules", [])}
        if add_mod.get("name", "") not in existing:
            tmpl.setdefault("modules", []).append(add_mod)
            changed.append(f"+模块 {add_mod.get('name', '')}")

    # 移除模块
    remove_mod = modifications.get("remove_module")
    if remove_mod:
        before = len(tmpl.get("modules", []))
        tmpl["modules"] = [m for m in tmpl.get("modules", [])
                           if m.get("name") != remove_mod]
        if len(tmpl["modules"]) < before:
            changed.append(f"-模块 {remove_mod}")

    # 更新约束
    update_cons = modifications.get("update_constraints")
    if update_cons and isinstance(update_cons, dict):
        tmpl.setdefault("constraints", {}).update(update_cons)
        changed.append(f"约束: {list(update_cons.keys())}")

    # 添加共享工具
    add_util = modifications.get("add_shared_util")
    if add_util and isinstance(add_util, dict):
        tmpl.setdefault("shared_utils", []).append(add_util)
        changed.append(f"+工具 {add_util.get('name', '')}")

    # 保存为自定义模板
    custom_id = f"{template_id}-custom"
    tmpl["template_id"] = custom_id
    tmpl["template_name"] = tmpl.get("template_name", "") + " (定制)"
    tmpl["_based_on"] = template_id
    _save_template(tmpl_dir, tmpl)

    _log(f"模板已定制: {template_id} → {custom_id}")
    return {"status": "customized", "template_id": custom_id,
            "based_on": template_id, "changes": changed}


# ============================================================
# 公共 API：match_template()
# ============================================================

def match_template(description: str, project_root: str = ".") -> dict:
    """根据自然语言描述匹配最佳模板。

    关键词映射（按优先级排序）：
      电商/卖/购物/商品 → e-commerce-minimal
      官网/企业/公司/品牌 → corporate-website
      后台/管理/内部/权限/角色 → admin-dashboard
      API/接口/服务/微服务 → api-service
      数据/分析/BI/报表/ETL → data-platform
      设备/IoT/物联网/传感器/硬件 → iot-controller
    """
    desc_lower = description.lower()

    # 关键词 → 模板映射（顺序定义优先级）
    keyword_map: list[tuple[str, list[str]]] = [
        ("e-commerce-minimal", ["电商", "卖", "购物", "商品", "店铺", "网店", "商城", "下单", "支付"]),
        ("iot-controller", ["iot", "物联网", "设备", "传感器", "硬件", "遥控", "智能家居", "mqtt"]),
        ("data-platform", ["数据", "分析", "bi", "报表", "etl", "统计", "可视化", "看板", "数仓"]),
        ("api-service", ["api", "接口", "服务", "微服务", "rest", "后端", "rpc", "网关"]),
        ("admin-dashboard", ["后台", "管理", "内部", "权限", "角色", "rbac", "admin", "操作台"]),
        ("corporate-website", ["官网", "企业", "公司", "品牌", "展示", "网站", "主页"]),
    ]

    # 计算每个模板的匹配度
    scores: dict[str, float] = {}
    for tid, keywords in keyword_map:
        score = 0.0
        matched_kw: list[str] = []
        for kw in keywords:
            if kw in desc_lower:
                score += 1.0 / len(keywords)
                matched_kw.append(kw)
        # 小程序/轻量/简单等关键词偏向电商
        if tid == "e-commerce-minimal":
            for kw in ["小程序", "轻量", "简单", "入门", "小白", "衣服", "外卖"]:
                if kw in desc_lower:
                    score += 0.3
        scores[tid] = score

    best_id = max(scores, key=scores.get)  # type: ignore[arg-type]
    best_score = scores.get(best_id, 0)

    # 排名前2的备选
    sorted_scores = sorted(scores.items(), key=lambda x: -x[1])
    alternatives = [tid for tid, s in sorted_scores[1:3] if s > 0]

    confidence = round(min(1.0, best_score * 1.5 + 0.1), 2)

    return {
        "best_match": best_id,
        "confidence": confidence,
        "alternatives": alternatives,
        "scores": {tid: round(s, 2) for tid, s in scores.items()},
    }


# ============================================================
# 公共 API：export_template_summary()
# ============================================================

def export_template_summary(template_id: str, project_root: str = ".") -> str:
    """导出人话版模板说明。"""
    tmpl = get_template(template_id, project_root)
    if tmpl is None:
        return f"模板 '{template_id}' 不存在"

    icon = tmpl.get("icon", "")
    name = tmpl.get("template_name", "")
    desc = tmpl.get("description", "")
    difficulty = tmpl.get("difficulty", "")
    sec = "⭐" * tmpl.get("security_level", 3)
    tech = tmpl.get("tech_stack", {})
    modules = tmpl.get("modules", [])
    files = tmpl.get("estimated_files", "")

    lines = [
        f"{icon} {name}",
        "",
        f"{desc}",
        f"预估文件数: {files}    安全等级: {sec}    难度: {difficulty}",
        "",
        "你的项目将包含：",
    ]
    for m in modules:
        tags = ", ".join(m.get("tags", [])) or "无限制"
        lines.append(f"  • {m.get('responsibility', m.get('name', ''))} ({tags})")

    if tech:
        tech_str = ", ".join(f"{k}: {v}" for k, v in tech.items())
        lines.extend(["", f"技术选型: {tech_str}"])

    lines.extend(["", "[开始生成] [我要调整]"])
    return "\n".join(lines)


# ============================================================
# CLI 入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="Project Manager Template Engine — 场景模板引擎",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python template_engine.py --action list
  python template_engine.py --action get --id e-commerce-minimal
  python template_engine.py --action apply --id e-commerce-minimal --project .
  python template_engine.py --action match --description "我要做一个卖衣服的小程序"
  python template_engine.py --action customize --id e-commerce-minimal --add-module '{"name":"coupon","responsibility":"优惠券"}'
  python template_engine.py --action summary --id e-commerce-minimal
        """,
    )
    parser.add_argument("--action", required=True,
                        choices=["list", "get", "apply", "match", "customize", "summary"],
                        help="操作类型")
    parser.add_argument("--id", help="模板 ID")
    parser.add_argument("--project", default=".", help="项目根目录")
    parser.add_argument("--description", help="自然语言描述 (match)")
    parser.add_argument("--add-module", help="添加模块 JSON (customize)")
    parser.add_argument("--remove-module", help="移除模块名 (customize)")
    parser.add_argument("--add-util", help="添加共享工具 JSON (customize)")
    parser.add_argument("--update-constraints", help="更新约束 JSON (customize)")
    parser.add_argument("--format", default="text", choices=["text", "json"],
                        help="输出格式")
    args = parser.parse_args()

    root = os.path.abspath(args.project)

    if args.action == "list":
        result = list_templates(root)
        _output(result, args.format, _fmt_list)
    elif args.action == "get":
        _check(args.id, "--id", "get")
        tmpl = get_template(args.id, root)
        if tmpl is None:
            print(f"模板 '{args.id}' 不存在"); sys.exit(1)
        _output(tmpl, args.format)
    elif args.action == "apply":
        _check(args.id, "--id", "apply")
        result = apply_template(args.id, root)
        _output(result, args.format)
    elif args.action == "match":
        _check(args.description, "--description", "match")
        result = match_template(args.description, root)
        if args.format == "json":
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            tmpl = get_template(result["best_match"], root)
            icon = tmpl.get("icon", "") if tmpl else ""
            name = tmpl.get("template_name", "") if tmpl else ""
            conf = result.get("confidence", 0)
            print(f"\n最佳匹配: {icon} {name} (置信度: {conf:.0%})")
            if result.get("alternatives"):
                print(f"备选: {', '.join(result['alternatives'])}")
            # 输出简要摘要
            if tmpl:
                modules = [m.get("responsibility", m.get("name", ""))
                           for m in tmpl.get("modules", [])]
                print(f"包含模块: {', '.join(modules)}")
                print(f"技术栈: {json.dumps(tmpl.get('tech_stack',{}), ensure_ascii=False)}")
            print(f"\n[开始生成] [我要调整]")
    elif args.action == "customize":
        _check(args.id, "--id", "customize")
        mods: dict[str, Any] = {}
        if args.add_module:
            mods["add_module"] = _parse_json(args.add_module)
        if args.remove_module:
            mods["remove_module"] = args.remove_module
        if args.add_util:
            mods["add_shared_util"] = _parse_json(args.add_util)
        if args.update_constraints:
            mods["update_constraints"] = _parse_json(args.update_constraints)
        result = customize_template(args.id, mods, root)
        _output(result, args.format)
    elif args.action == "summary":
        _check(args.id, "--id", "summary")
        text = export_template_summary(args.id, root)
        print(text)


def _check(value: str | None, flag: str, action: str) -> None:
    if not value:
        _log(f"错误: --action {action} 需要 {flag}")
        sys.exit(1)


def _parse_json(value: str) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        _log(f"警告: JSON 解析失败: {value[:50]}")
        return {}


def _output(data: Any, fmt: str, text_fmt=None) -> None:
    if fmt == "json":
        print(json.dumps(data, indent=2, ensure_ascii=False, default=str))
    elif text_fmt:
        text_fmt(data)
    elif isinstance(data, dict):
        status = data.get("status", "")
        icon_map = {"applied": "✅", "customized": "✏️", "not_found": "❌"}
        print(f"{icon_map.get(status, '')} {status}: {data.get('template_id', data.get('id', ''))}")
        for k, v in data.items():
            if k not in ("status", "template_id", "id"):
                print(f"  {k}: {v}")
    else:
        print(data)


def _fmt_list(r: dict) -> None:
    print(f"\n可用模板 ({r.get('total', 0)} 个)")
    print("-" * 60)
    for t in r.get("templates", []):
        icon = t.get("icon", "📄")
        name = t.get("template_name", "")
        tid = t.get("template_id", "")
        diff = t.get("difficulty", "")
        sec = "⭐" * t.get("security_level", 0)
        desc = t.get("description", "")
        print(f"  {icon} [{tid}] {name}   {sec} {diff}")
        print(f"      {desc}")
        print(f"      预估: {t.get('estimated_files', '')} 文件")
        print()


if __name__ == "__main__":
    main()
