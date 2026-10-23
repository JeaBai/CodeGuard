#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_fc_tests.py — fc-guardian 单元测试运行器

用场景式 mock 飞控项目（临时目录），验证 5 类检测：
  1. 引脚冲突（fc-pin-conflict）
  2. 串口收发不对称（fc-uart-rx-no-tx）
  3. 阻塞延时（fc-refresh-blocking-delay）
  4. 缺 failsafe（fc-state-no-failsafe）
  5. 缺看门狗（fc-safety-no-watchdog）

判定：期望规则 ID + 严重度 命中为 TP，误报 FP，漏报 FN。
"""
import shutil
import sys
import tempfile
from pathlib import Path

for s in (sys.stdout, sys.stderr):
    try:
        s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):  # codeguard: ignore GOLD_NO_EMPTY_EXCEPT — Python<3.7 无 reconfigure，静默降级默认编码
        pass

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import fc_scan

# ── 场景定义：每个场景基于「健康基线」，只注入一种缺陷 ─────

_HEALTHY_IOC = (
    "Mcu.IP0=GPIO\n"
    "Mcu.IP1=RCC\n"
    "Mcu.IP2=IWDG\n"               # 有看门狗
    "PA9.Signal=USART1_TX\n"
    "PA10.Signal=USART1_RX\n"
    "USART1.Mode=MODE_TX_RX\n"
    "USART1.BaudRate=115200\n"
)

_HEALTHY_MAIN = (
    "void MX_IWDG_Init(void) {}\n"                          # 看门狗初始化
    "void HAL_TIM_PeriodElapsedCallback(void) { control_loop(); }\n"  # 固定周期
    "void main(void) {\n"
    "  HAL_Init();\n"
    "  MX_IWDG_Init();\n"
    "  MPU6050_CalibrateGyro();\n"                          # 传感器校准
    "  arming_check();\n"                                   # arming
    "  failsafe_check();\n"                                 # failsafe
    "  while (1) {\n"
    "    IWDG_ReloadCounter();\n"                           # 喂狗（嵌入式看门狗检测「真正健康」）
    "  }\n"
    "}\n"
)


def _make_healthy_project(root):
    """健康飞控基线：应 0 条检测。"""
    (root / "Core").mkdir(parents=True, exist_ok=True)
    (root / "Core" / "Src").mkdir(parents=True, exist_ok=True)
    (root / "healthy.ioc").write_text(_HEALTHY_IOC, encoding="utf-8")
    (root / "Core" / "Src" / "main.c").write_text(_HEALTHY_MAIN, encoding="utf-8")


def _make_pin_conflict_project(root):
    """引脚冲突：PA9 同时分配给 USART1_TX 和 TIM1_CH1。"""
    _make_healthy_project(root)
    (root / "healthy.ioc").write_text(
        _HEALTHY_IOC + "PA9.Signal=TIM1_CH1\n",  # 注入冲突：PA9 双 Signal
        encoding="utf-8")


def _make_uart_rx_no_tx_project(root):
    """串口收发不对称：USART1 MODE_TX_RX 但缺 RX 引脚。"""
    _make_healthy_project(root)
    ioc = _HEALTHY_IOC.replace("PA10.Signal=USART1_RX\n", "")  # 移除 RX 引脚
    (root / "healthy.ioc").write_text(ioc, encoding="utf-8")


def _make_blocking_delay_project(root):
    """阻塞延时：控制循环内 HAL_Delay。"""
    _make_healthy_project(root)
    main = _HEALTHY_MAIN.replace(
        "void HAL_TIM_PeriodElapsedCallback(void) { control_loop(); }\n",
        "void HAL_TIM_PeriodElapsedCallback(void) { HAL_Delay(100); }\n",  # 注入阻塞延时
    )
    (root / "Core" / "Src" / "main.c").write_text(main, encoding="utf-8")


def _make_no_failsafe_project(root):
    """缺 failsafe：移除 failsafe 信号。"""
    _make_healthy_project(root)
    main = _HEALTHY_MAIN.replace("  failsafe_check();\n", "")
    (root / "Core" / "Src" / "main.c").write_text(main, encoding="utf-8")


def _make_no_watchdog_project(root):
    """缺看门狗：移除 IWDG 配置。"""
    _make_healthy_project(root)
    ioc = _HEALTHY_IOC.replace("Mcu.IP2=IWDG\n", "")
    main = _HEALTHY_MAIN.replace("void MX_IWDG_Init(void) {}\n", "").replace("  MX_IWDG_Init();\n", "")
    (root / "healthy.ioc").write_text(ioc, encoding="utf-8")
    (root / "Core" / "Src" / "main.c").write_text(main, encoding="utf-8")


# ── 嵌入式管理层场景（复用 CodeGuard quality_embedded 的 9 项检测）─────

def _make_embedded_malloc_project(root):
    """嵌入式：动态内存分配（MISRA Dir 21 禁用）。"""
    _make_healthy_project(root)
    main = _HEALTHY_MAIN.replace(
        "  failsafe_check();\n",
        "  failsafe_check();\n  void* buf = malloc(1024);\n",  # 注入动态内存
    )
    (root / "Core" / "Src" / "main.c").write_text(main, encoding="utf-8")


def _make_embedded_recursion_project(root):
    """嵌入式：递归调用（MISRA 17.2 禁用，栈溢出风险）。"""
    _make_healthy_project(root)
    main = _HEALTHY_MAIN + "int recurse(int n) { return recurse(n - 1); }\n"
    (root / "Core" / "Src" / "main.c").write_text(main, encoding="utf-8")


def _make_embedded_isr_project(root):
    """嵌入式：ISR 内阻塞调用（HAL_Delay 在 IRQHandler 中，独立 it 文件）。"""
    _make_healthy_project(root)
    # 真实 STM32 项目结构：ISR 定义在 stm32f4xx_it.c，而非 main.c
    (root / "Core" / "Src" / "stm32f4xx_it.c").write_text(
        "void EXTI0_IRQHandler(void) { HAL_Delay(10); }\n", encoding="utf-8")


def _make_post_loop_delay_project(root):
    """回归：while(1) 块闭合后的普通函数 HAL_Delay 不应误报（修复状态不复位缺陷）。"""
    _make_healthy_project(root)
    main = _HEALTHY_MAIN + "void post_loop(void) { HAL_Delay(50); }\n"
    (root / "Core" / "Src" / "main.c").write_text(main, encoding="utf-8")


SCENARIOS = [
    ("pin_conflict", _make_pin_conflict_project,
     [("fc_pin", "block")], "引脚冲突"),
    ("uart_rx_no_tx", _make_uart_rx_no_tx_project,
     [("fc_uart", "warn")], "串口收发不对称"),
    ("blocking_delay", _make_blocking_delay_project,
     [("fc_refresh", "block")], "阻塞延时"),
    ("no_failsafe", _make_no_failsafe_project,
     [("fc_state", "block")], "缺 failsafe"),
    ("no_watchdog", _make_no_watchdog_project,
     [("fc_safety", "block")], "缺看门狗"),
    ("embedded_malloc", _make_embedded_malloc_project,
     [("embedded_memory", "block")], "嵌入式动态内存禁用"),
    ("embedded_recursion", _make_embedded_recursion_project,
     [("embedded_recursion", "block")], "嵌入式递归禁用"),
    ("embedded_isr", _make_embedded_isr_project,
     [("embedded_isr", "block")], "ISR 内阻塞调用"),
    ("post_loop_delay", _make_post_loop_delay_project,
     [], "while 后普通函数延时无误报"),
]


def _run_scenario(name, builder, expected, desc):
    """运行单个场景，返回结果 dict。"""
    tmp = tempfile.mkdtemp(prefix="fc_test_")
    try:
        builder(Path(tmp))
        issues, exit_code, _summary = fc_scan.scan_project(tmp)

        actual = sorted({(i["category"], i["severity"]) for i in issues})
        exp_set = set(expected)
        tp = sorted(e for e in exp_set if e in actual)
        fn = sorted(e for e in exp_set if e not in actual)
        exp_cats = {e[0] for e in expected}
        fp = sorted(a for a in actual if a[0] not in exp_cats)

        return {
            "name": name, "desc": desc,
            "passed": len(fn) == 0 and len(fp) == 0,
            "tp": tp, "fn": fn, "fp": fp,
            "actual": actual, "exit_code": exit_code,
        }
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def run_all():
    return [_run_scenario(name, builder, expected, desc)
            for name, builder, expected, desc in SCENARIOS]


def main():
    print("=" * 60)
    print("  fc-guardian 单元测试")
    print("=" * 60)

    results = run_all()
    total = len(results)
    passed = sum(1 for r in results if r["passed"])

    for r in results:
        mark = "PASS" if r["passed"] else "FAIL"
        print(f"\n  [{mark}] {r['name']} ({r['desc']})")
        print(f"       TP={len(r['tp'])} FN={len(r['fn'])} FP={len(r['fp'])}")
        if r["fn"]:
            for f in r["fn"]:
                print(f"         漏报: {f}")
        if r["fp"]:
            for f in r["fp"]:
                print(f"         误报: {f}")

    print(f"\n{'=' * 60}")
    print(f"  结果: {passed}/{total} 通过")
    print(f"{'=' * 60}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
