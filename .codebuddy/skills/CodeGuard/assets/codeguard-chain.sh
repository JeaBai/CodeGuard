#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────
# CodeGuard CI 三步连环门禁（跨平台 shell 版）
# ==============================================================
# 步骤 1: iac-guardian — IaC 安全扫描
# 步骤 2: governance-hub — 发布治理检视
# 步骤 3: CodeGuard — 金级质量门禁
#
# 退出码：0=全部通过 / 1=WARN / 2=BLOCK
# 用法：bash codeguard-chain.sh [--path .] [--mode full|diff]
# ──────────────────────────────────────────────────────────────
set -euo pipefail

MODE="${2:-full}"
ROOT="${1:-.}"
EXIT_CODE=0
FAIL_ANY=0

echo "============================================"
echo " CodeGuard CI 三步连环门禁"
echo " 模式: $MODE | 路径: $ROOT"
echo "============================================"

# ── 步骤 1: IaC 安全扫描 ──────────────────────────────────
echo ""
echo "[1/3] iac-guardian IaC 安全扫描..."
IAC_SCRIPT="$ROOT/.codebuddy/skills/iac-guardian/scripts/iac_scan.py"
IAC_EXIT=0
if [ -f "$IAC_SCRIPT" ]; then
    python "$IAC_SCRIPT" --path "$ROOT" --format text || IAC_EXIT=$?
    if [ "$IAC_EXIT" -eq 2 ]; then
        echo "❌ iac-guardian BLOCK — 发布已阻断"
        FAIL_ANY=1
    elif [ "$IAC_EXIT" -eq 1 ]; then
        echo "⚠️  iac-guardian WARN — 请注意风险"
        EXIT_CODE=1
    else
        echo "✅ iac-guardian PASS"
    fi
else
    echo "ℹ️  iac-guardian 脚本未找到，跳过（非 IaC 项目）"
fi

# ── 步骤 2: 发布治理检视 ─────────────────────────────────
echo ""
echo "[2/3] governance-hub 发布治理检视..."
GOV_SCRIPT="$ROOT/.codebuddy/skills/governance-hub/scripts/governance_gate.py"
GOV_EXIT=0
if [ -f "$GOV_SCRIPT" ]; then
    python "$GOV_SCRIPT" --mode release --path "$ROOT" --format text || GOV_EXIT=$?
    if [ "$GOV_EXIT" -eq 2 ]; then
        echo "❌ governance-hub BLOCK — 发布已阻断"
        FAIL_ANY=1
    elif [ "$GOV_EXIT" -eq 1 ]; then
        echo "⚠️  governance-hub WARN — 请注意治理风险"
        EXIT_CODE=1
    else
        echo "✅ governance-hub PASS"
    fi
else
    echo "ℹ️  governance-hub 脚本未找到，跳过"
fi

# ── 步骤 3: CodeGuard 质量门禁 ───────────────────────────
echo ""
echo "[3/3] CodeGuard 金级质量门禁..."
CG_SCRIPT="$ROOT/.codebuddy/skills/CodeGuard/scripts/quality_check.py"
CG_EXIT=0
if [ -f "$CG_SCRIPT" ]; then
    python "$CG_SCRIPT" --path "$ROOT" --mode "$MODE" --format json > codeguard_chain_result.json || CG_EXIT=$?
    if [ "$CG_EXIT" -eq 2 ]; then
        echo "❌ CodeGuard BLOCK — 质量门禁未通过"
        FAIL_ANY=1
    elif [ "$CG_EXIT" -eq 1 ]; then
        echo "⚠️  CodeGuard WARN — 存在质量问题"
        EXIT_CODE=1
    else
        echo "✅ CodeGuard PASS"
    fi
else
    echo "ℹ️  CodeGuard 脚本未找到，跳过"
fi

# ── 汇总 ─────────────────────────────────────────────────
echo ""
echo "============================================"
if [ "$FAIL_ANY" -eq 1 ]; then
    echo "❌ 三步连环门禁 BLOCK — 存在阻断项"
    echo "============================================"
    exit 2
elif [ "$EXIT_CODE" -eq 1 ]; then
    echo "⚠️  三步连环门禁 WARN — 存在警告项"
    echo "============================================"
    exit 1
else
    echo "✅ 三步连环门禁 PASS — 全部通过"
    echo "============================================"
    exit 0
fi
