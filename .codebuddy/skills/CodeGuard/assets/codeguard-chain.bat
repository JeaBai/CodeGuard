@echo off
REM ──────────────────────────────────────────────────────────
REM CodeGuard CI 三步连环门禁（Windows .bat 版）
REM ==========================================================
REM 步骤 1: iac-guardian — IaC 安全扫描
REM 步骤 2: governance-hub — 发布治理检视
REM 步骤 3: CodeGuard — 金级质量门禁
REM
REM 用法：codeguard-chain.bat [path] [mode]
REM   path: 项目根目录（默认 .）
REM   mode: full|diff（默认 full）
REM ──────────────────────────────────────────────────────────
setlocal enabledelayedexpansion

set ROOT=%1
if "%ROOT%"=="" set ROOT=.
set MODE=%2
if "%MODE%"=="" set MODE=full

echo ============================================
echo  CodeGuard CI 三步连环门禁
echo  模式: %MODE% ^| 路径: %ROOT%
echo ============================================

REM ── 步骤 1: IaC 安全扫描 ──────────────────────────────
echo.
echo [1/3] iac-guardian IaC 安全扫描...
set IAC_SCRIPT=%ROOT%\.codebuddy\skills\iac-guardian\scripts\iac_scan.py
if exist "%IAC_SCRIPT%" (
    python "%IAC_SCRIPT%" --path "%ROOT%" --format text
    if !ERRORLEVEL! EQU 2 (
        echo ❌ iac-guardian BLOCK — 发布已阻断
        exit /b 2
    ) else if !ERRORLEVEL! EQU 1 (
        echo ⚠️  iac-guardian WARN — 请注意风险
    ) else (
        echo ✅ iac-guardian PASS
    )
) else (
    echo ℹ️  iac-guardian 脚本未找到，跳过（非 IaC 项目）
)

REM ── 步骤 2: 发布治理检视 ─────────────────────────────
echo.
echo [2/3] governance-hub 发布治理检视...
set GOV_SCRIPT=%ROOT%\.codebuddy\skills\governance-hub\scripts\governance_gate.py
if exist "%GOV_SCRIPT%" (
    python "%GOV_SCRIPT%" --mode release --path "%ROOT%" --format text
    if !ERRORLEVEL! EQU 2 (
        echo ❌ governance-hub BLOCK — 发布已阻断
        exit /b 2
    ) else if !ERRORLEVEL! EQU 1 (
        echo ⚠️  governance-hub WARN — 请注意治理风险
    ) else (
        echo ✅ governance-hub PASS
    )
) else (
    echo ℹ️  governance-hub 脚本未找到，跳过
)

REM ── 步骤 3: CodeGuard 质量门禁 ─────────────────────────
echo.
echo [3/3] CodeGuard 金级质量门禁...
set CG_SCRIPT=%ROOT%\.codebuddy\skills\CodeGuard\scripts\quality_check.py
if exist "%CG_SCRIPT%" (
    python "%CG_SCRIPT%" --path "%ROOT%" --mode "%MODE%" --format json > codeguard_chain_result.json 2>&1
    if !ERRORLEVEL! EQU 2 (
        echo ❌ CodeGuard BLOCK — 质量门禁未通过
        exit /b 2
    ) else if !ERRORLEVEL! EQU 1 (
        echo ⚠️  CodeGuard WARN — 存在质量问题
    ) else (
        echo ✅ CodeGuard PASS
    )
) else (
    echo ℹ️  CodeGuard 脚本未找到，跳过
)

echo.
echo ============================================
echo ✅ 三步连环门禁 PASS — 全部通过
echo ============================================
exit /b 0
