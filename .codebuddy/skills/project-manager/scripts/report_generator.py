"""
报告生成模块 — 支持 Markdown、JSON、HTML 格式的项目报告生成
"""

import json
import logging
from datetime import date
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)  # codeguard: ignore GOLD_NO_GLOBAL_STATE


# ============================================================
# 公共辅助函数
# ============================================================

def _to_json_report(report_type: str, project_name: str, date_str: str, phase: int, answers: dict, **extra) -> str:
    """统一的 JSON 格式报告输出，消除重复的 json.dumps 模式"""
    data = {
        "type": report_type,
        "project": project_name,
        "date": date_str,
        "phase": phase,
        "answers": answers,
    }
    data.update(extra)
    return json.dumps(data, ensure_ascii=False, indent=2)


# ============================================================
# Report Templates
# ============================================================


def generate_feasibility_report(
    project_name: str = "未命名项目",
    answers: dict = None,
    output_format: str = "markdown",
) -> str:
    """生成项目可行性评估报告"""
    answers = answers or {}
    today = date.today().isoformat()

    if output_format == "json":
        return _to_json_report("feasibility_report", project_name, today, 1, answers)

    report = f"""# 项目可行性评估报告

**项目名称**：{project_name}
**评估日期**：{today}
**评估阶段**：第一阶段 — 判断「值不值得做」

---

## 1. 市场需求分析

| # | 维度 | 评估结果 |
|---|------|----------|
| 1 | 目标用户与核心痛点 | {answers.get('1', '待调研')} |
| 2 | 现有竞品分析 | {answers.get('2', '待调研')} |
| 3 | 差异化切入点 | {answers.get('3', '待调研')} |
| 4 | 付费意愿验证 | {answers.get('4', '待调研')} |
| 5 | 市场规模与趋势 | {answers.get('5', '待调研')} |

## 2. 资源与能力评估

| # | 维度 | 评估结果 |
|---|------|----------|
| 6 | 资源瓶颈识别 | {answers.get('6', '待评估')} |
| 7 | 能力匹配度 | {answers.get('7', '待评估')} |
| 8 | MVP范围定义 | {answers.get('8', '待定义')} |

## 3. 风险评估

| # | 维度 | 评估结果 |
|---|------|----------|
| 9 | TOP3风险 | {answers.get('9', '待识别')} |
| 10 | 止损底线 | {answers.get('10', '待定义')} |
| 11 | 合规红线 | {answers.get('11', '待确认')} |

---

## 4. 综合决策矩阵

| 维度 | 得分(1-5) | 说明 |
|------|-----------|------|
| 需求真实性 | | |
| 市场空间 | | |
| 资源匹配度 | | |
| 风险可控性 | | |
| **总分** | **/20** | |

> 决策规则：≥15分启动 | 10-14分补充调研 | <10分建议暂缓

---

*报告生成于 {today}*
"""
    return report


def generate_planning_report(
    project_name: str = "未命名项目",
    deadline: str = "待定",
    answers: dict = None,
    output_format: str = "markdown",
) -> str:
    """生成项目启动规划书"""
    answers = answers or {}
    today = date.today().isoformat()

    if output_format == "json":
        return _to_json_report(
            "planning_report", project_name, today, 2, answers,
            deadline=deadline,
        )

    report = f"""# 项目启动规划书

**项目名称**：{project_name}
**目标交付日期**：{deadline}
**规划日期**：{today}

---

## 1. 质量标准定义

| 维度 | 定义 |
|------|------|
| 高质量标准 | {answers.get('12', '待定义')} |
| 最低验收标准 | {answers.get('13', '待定义')} |
| 非功能需求 | {answers.get('14', '待定义')} |
| 用户体验标准 | {answers.get('15', '待定义')} |

## 2. 里程碑计划

| 里程碑 | 目标日期 | 交付物 | 验收人 | 验收标准 |
|--------|----------|--------|--------|----------|
| M1 | | | | |
| M2 | | | | |
| M3 | | | | |
| M4 (MVP) | | | | |

## 3. MVP vs V2.0 范围

### MVP 必须功能
{answers.get('17_mvp', '- 待定义')}

### V2.0 推迟功能
{answers.get('17_v2', '- 待定义')}

## 4. 技术选型决策

| 方案 | 优势 | 劣势 | 社区活跃度 | 学习曲线 | 维护成本 | 推荐度 |
|------|------|------|-----------|----------|----------|--------|
| | | | | | | |

### 选型结论
{answers.get('20', '待完成技术调研')}

### 新技术采用评估
{answers.get('22', '待评估')}

## 5. 偏差预警机制

- **10%延期预警**：{answers.get('19', '待定义')}
- **应急负责人**：待指定
- **升级路径**：待定义

---

*规划书生成于 {today}*
"""
    return report


def generate_retrospective_report(
    project_name: str = "未命名项目",
    answers: dict = None,
    output_format: str = "markdown",
) -> str:
    """生成项目复盘报告"""
    answers = answers or {}
    today = date.today().isoformat()

    if output_format == "json":
        return _to_json_report("retrospective_report", project_name, today, 4, answers)

    report = f"""# 项目复盘报告

**项目名称**：{project_name}
**复盘日期**：{today}

---

## 📊 目标达成率

| 目标 | 计划 | 实际 | 达成率 | 偏差原因 |
|------|------|------|--------|----------|
| | | | | |

**总体评估**：{answers.get('38', '待评估')}

## ✅ 经验资产化

### 做对了 — 下次复用
{answers.get('39_good', '待整理')}

### 做错了 — 下次避免
{answers.get('39_bad', '待整理')}

## ⏱️ 时间偏差分析

| 环节 | 预估时间 | 实际时间 | 偏差 | 原因分析 |
|------|----------|----------|------|----------|
| | | | | |

**偏差最大环节**：{answers.get('40', '待分析')}

## 💬 用户反馈分析

### 超出预期
{answers.get('41_exceed', '待整理')}

### 低于预期
{answers.get('41_below', '待整理')}

## 🔮 续投决策

**是否启动V2.0**：{answers.get('42', '待决策')}

**依据**：
{answers.get('42_reason', '待说明')}

## 🗂️ 知识沉淀

### 可复用资产
{answers.get('43', '待整理')}

### 踩坑记录
{answers.get('44', '待整理')}

### 工具链升级
{answers.get('45', '无')}

### 💡 核心经验
> {answers.get('46', '待提炼')}

---

*复盘报告生成于 {today}*
"""
    return report


def save_report(report: str, project_name: str, report_type: str, output_dir: str = "."):
    """保存报告到文件"""
    safe_name = project_name.replace(" ", "_").replace("/", "_")
    filename = f"{safe_name}_{report_type}_{date.today().isoformat()}.md"
    filepath = Path(output_dir) / filename

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(report)

    return str(filepath)


# ============================================================
# CLI
# ============================================================


def main():
    import argparse

    parser = argparse.ArgumentParser(description="项目报告生成器")
    parser.add_argument("--type", choices=["feasibility", "planning", "retrospective"], required=True)
    parser.add_argument("--project", type=str, default="未命名项目")
    parser.add_argument("--deadline", type=str, default="待定")
    parser.add_argument("--answers", type=str, default="{}", help="JSON格式的回答数据")
    parser.add_argument("--output", type=str, default=".", help="输出目录")
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown")

    args = parser.parse_args()

    try:
        answers = json.loads(args.answers)
    except json.JSONDecodeError:
        logger.debug("CLI 参数 answers JSON 解析失败，使用空字典")
        answers = {}

    if args.type == "feasibility":
        report = generate_feasibility_report(args.project, answers, args.format)
        report_type = "feasibility"
    elif args.type == "planning":
        report = generate_planning_report(args.project, args.deadline, answers, args.format)
        report_type = "planning"
    else:
        report = generate_retrospective_report(args.project, answers, args.format)
        report_type = "retrospective"

    if args.format == "markdown":
        filepath = save_report(report, args.project, report_type, args.output)
        print(f"报告已生成: {filepath}")  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION
    else:
        print(report)  # codeguard: ignore GOLD_NO_PRINT_PRODUCTION


if __name__ == "__main__":
    main()
