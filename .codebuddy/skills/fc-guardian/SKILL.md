---
name: fc-guardian
description: "飞控守护 Skill（v3.0.0）—— 飞控硬件领域检测，对标大疆 / ArduPilot / PX4 项目管理能力。 独立于 CodeGuard，专注飞控硬件层静态检测：引脚冲突/复用（.ioc）、串口波特率/DMA/中断一致性、 控制循环刷新率/阻塞延迟、arming/failsafe 状态机完整性、看门狗/电机解锁/传感器校准安全。 当用户请求检测 STM32 飞控项目、.ioc 引脚配置、电机控制 PWM、传感器状态机、 或提及飞控安全/看门狗/失控保护/刷新率时应触发。 纯 Python 标准库实现，复用 CodeGuard IssueCollector 门禁体系。 MCP 协议兼容：`scripts/mcp_server.py` 复用 shared/_mcp_base.py，暴露 fc_scan 工具（JSON-RPC 2.0 over stdio），可作为 MCP Server 被 Claude Code / Cursor / VS Code 等客户端调用。"
agent_created: true
---
# fc-guardian — 飞控守护（v3.0.0）

## 定位与隔离

fc-guardian 是**独立于 CodeGuard 的第五个 SKILL**，专注飞控硬件领域静态检测。
与 CodeGuard 的嵌入式 C 代码质量检测形成分层互补，**不修改 CodeGuard 任何文件**：

```
CodeGuard（现有，零修改）
├── 纯软语言（Python/JS/Java/Go/C#/Rust）— 完全隔离
└── C 方言分流
    ├── generic C —— 通用代码质量
    └── embedded C —— MISRA/ISR/volatile/栈（嵌入式代码规范层）

fc-guardian（本 SKILL，独立）
├── 飞控硬件领域 —— 引脚/串口/刷新率/状态机/飞控安全（飞控领域层）
└── 嵌入式管理层 —— 复用 CodeGuard quality_embedded 9 项检测（代码规范层）
```

## 检测能力（5 硬件模块 + 嵌入式管理 9 项）

### 飞控硬件层（fc_* 前缀）

| 模块 | 检测项 | 对标 |
|------|--------|------|
| `pin_checker.py` | .ioc 引脚冲突/复用/悬空 | STM32CubeMX 校验 |
| `uart_checker.py` | 串口波特率/DMA/中断一致性 | 大厂驱动规范 |
| `refresh_checker.py` | 控制循环刷新率/delay 阻塞 | PX4 调度规范 |
| `state_machine_checker.py` | arming/failsafe 状态机完整性 | ArduPilot failsafe |
| `flight_safety.py` | 看门狗/电机解锁/传感器校准 | 大疆安全标准 |

### 嵌入式管理层（embedded_* 前缀，复用 CodeGuard）

对飞控项目 `.c/.cpp` 全量执行 CodeGuard `quality_embedded` 9 项检测（只读 import，零改写）：

| 规则 | category | 严重度 | 说明 |
|------|----------|:------:|------|
| 动态内存分配 | embedded_memory | block | MISRA Dir 21，malloc/free/new/delete 禁用 |
| 递归调用 | embedded_recursion | block | MISRA 17.2，栈溢出风险 |
| goto 使用 | embedded_goto | warn | MISRA 15.x，限制使用 |
| ISR 安全 | embedded_isr | block/warn | ISR 内阻塞调用 + ISR 过长 |
| volatile 寄存器 | embedded_volatile | warn | 内存映射寄存器指针必须 volatile |
| 局部大数组 | embedded_stack | warn | 栈深度风险 |
| ISR 优先级 | embedded_isr_priority | warn | NVIC 优先级配置 |
| 看门狗 | embedded_watchdog | block | 启用看门狗但未喂狗 |
| 电源管理 | embedded_power_mgmt | info | 低功耗无唤醒源 |

## 可扩展基脚（检测器调度表）

`fc_scan.py` 采用 `_DETECTORS` 检测器调度表，硬件层与嵌入式层统一调度。
未来接入软件/数据大屏/图像算法/端到端等业务只需在调度表追加一条 `(layer, detector_fn)`，
无需修改调度逻辑，最大化功能复用、避免规则冗余。

## 快速开始

```bash
# 扫描飞控项目
python fc_scan.py --path /path/to/fc-project --format text

# JSON 输出（CI 集成）
python fc_scan.py --path /path/to/fc-project --format json

# 退出码: 0=PASS / 1=WARN / 2=BLOCK
```

### MCP Server（跨客户端调用）

```bash
python scripts/mcp_server.py --project-root /path/to/fc-project
```

- 复用 `shared/_mcp_base.py`（与 CodeGuard / governance-hub / iac-guardian 同一协议层，协议版本由基类统一提供）
- 暴露工具：**`fc_scan`**（入参 `path` / `format`，出参 `exit_code` + `verdict` + `summary` + 分类计数）
- 暴露资源：`fcguardian://detectors`（检测器清单，由 `fc_scan._DETECTORS` 调度表实时导出）
- **零修改边界**：仅只读 import `fc_scan`（其内部再只读复用 CodeGuard 的 `quality_embedded`），
  不反向修改 CodeGuard 任何文件
- MCP 与 CLI 两条入口共用同一个 `scan_project()`，保证判定结果一致

## 触发条件

- 项目含 `.ioc` 文件（STM32CubeMX 工程）
- 提及飞控/无人机/电机控制/PWM/姿态解算/传感器融合
- 提及看门狗/失控保护/failsafe/arming/校准

## 与 CodeGuard 的关系

- 复用 `quality_core.IssueCollector` 门禁体系 + `quality_embedded` 嵌入式管理 9 项检测（只读 import，非改写）
- 检测粒度：飞控领域规则 ID（fc-pin-* / fc-uart-* / fc-refresh-* / fc-state-* / fc-safety-*）+ 嵌入式规范（embedded_*）
- 降级兼容：独立部署（无 CodeGuard）时嵌入式层静默跳过，硬件层不受影响
- 可选启用：仅飞控项目显式引用，纯软/通用嵌入式项目不加载

## Roadmap

- [ ] PWM 电机输出频率/死区时间检测
- [ ] 传感器融合（IMU/GPS/磁力计）数据流完整性
- [ ] RTOS 任务优先级反转检测
- [ ] 遥测链路（MavLink/CRSF）协议完整性
