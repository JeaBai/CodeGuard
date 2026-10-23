"""generate_all — 生成全部 L0-L3 上下文文档。"""
from __future__ import annotations

import os

from context_compressor_core import generate_l0, _read_blueprint, _log, L0_FILENAME
from context_compressor_levels import generate_l1, generate_l2

# ============================================================
# generate_all: 生成全部 L0-L3
# ============================================================

def generate_all(project_path: str, blueprint_path: str, output_dir: str) -> dict:
    """生成全部 L0-L3 上下文文档。

    Returns:
        {"status": str, "l0": str, "l1_count": int, "l2_count": int}
    """
    os.makedirs(output_dir, exist_ok=True)
    bp = _read_blueprint(blueprint_path)
    modules = bp.get("modules", [])

    # L0
    l0_text = generate_l0(blueprint_path)
    l0_path = os.path.join(output_dir, L0_FILENAME)
    with open(l0_path, "w", encoding="utf-8") as f:
        f.write(l0_text)
    _log(f"L0 已生成: {l0_path}")

    # L1
    l1_dir = os.path.join(output_dir, "L1_modules")
    os.makedirs(l1_dir, exist_ok=True)
    l1_count = 0
    for m in modules:
        text = generate_l1(project_path, m.get("name", ""), blueprint_path)
        fpath = os.path.join(l1_dir, f"{m.get('name', 'unknown')}_contract.md")
        with open(fpath, "w", encoding="utf-8") as f:
            f.write(text)
        l1_count += 1
    _log(f"L1 已生成: {l1_count} 个模块组")

    # L2
    l2_dir = os.path.join(output_dir, "L2_details")
    os.makedirs(l2_dir, exist_ok=True)
    l2_count = 0
    for m in modules:
        text = generate_l2(project_path, m.get("name", ""), blueprint_path)
        # 跳过空模块
        if "*(不在蓝图中)*" in text or "*(无源文件)*" in text:
            continue
        fpath = os.path.join(l2_dir, f"{m.get('name', 'unknown')}_detail.md")
        with open(fpath, "w", encoding="utf-8") as f:
            f.write(text)
        l2_count += 1
    _log(f"L2 已生成: {l2_count} 个模块")

    return {
        "status": "generated",
        "l0": l0_path,
        "l1_count": l1_count,
        "l1_dir": l1_dir,
        "l2_count": l2_count,
        "l2_dir": l2_dir,
    }
