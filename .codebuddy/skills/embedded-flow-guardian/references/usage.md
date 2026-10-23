# 工作台用法与约束

> 本文件是 `SKILL.md` 的详细展开。按需加载：只在真正要跑构建/串口/分析时读。
> 触发词速查见 `SKILL.md`；工具清单见 `registry.md`。

## 1. 三个工作台模块

| 模块 | 能力 | 必须保留的实战约束（踩过坑） |
|------|------|---------------------------|
| `ef_build.py` | 工程自动发现（递归 `.uvprojx`，排除 vendor/参考树）、TargetName 自动解析、UV4 定位、构建期**版本头注入**（`git describe` 派生）、日志解析 | ① **烧录不能加 `-j0`**（隐藏 GUI 会取消下载 → "Target DLL has been cancelled"）② **cwd 必须设为工程目录**（否则相对路径落到 UV4 安装目录 → "error 56: cannot open file"）③ **UV4 的 stdout 常为空**，日志只在 `-o` 文件里 |
| `ef_serial.py` | 串口枚举（pyserial 优先，缺失则回退 Windows 注册表）、自动探测、只读监听、CSV 采集（**旁车元数据** + **断线重连**） | ① **默认只读**——不发送任何命令；`send` 必须显式 `--yes` ② 不实现电机/舵机驱动（属业务专项且涉及安全）③ 保持 CSV 格式与既有管线完全兼容（元数据写 `*.csv.meta.json`，不污染 CSV） |
| `ef_analyze.py` | 统计（均值/σ/峰峰/分位）、按列分箱、**FFT 频谱**（Hann 窗 + 峰提取）、**异常段检测**（>kσ 连续段）、PNG 出图 | ① **时间戳质量必须诊断**（见第 3 节）② **均值正常 ≠ 没问题**——间歇性问题只有分段/σ 倍数才显形 |

## 2. 零依赖说明

目标环境可能**没有 pyserial / numpy / matplotlib**，因此全部自实现：

- **串口 I/O**：Windows 走 `ctypes` 调 Win32 API（`CreateFileW` / `GetCommState` / `SetCommState` / `ReadFile` / `WriteFile`）；POSIX 走 `os.open` + `termios`
- **FFT**：迭代式基-2 Cooley-Tukey + Hann 窗
- **PNG 编码**：`zlib` + `struct` 手写编码器（扁平 bytearray 画布）

→ **开箱即用，不需要先装环境。**

### ctypes 陷阱（必须显式声明函数原型）

⚠️ ctypes 默认把返回值当 **32 位 int**，而 Windows `HANDLE` 在 x64 上是 **64 位**。
不声明 `restype` 会导致句柄被截断：`CreateFileW` 看似成功，后续
`GetCommState` / `ReadFile` 却全部失败（表现为 "GetCommState 失败"）。
`ef_serial._load_k32()` 已为每个 API 显式声明 `argtypes` / `restype`，**勿删**。

## 3. 实测案例：时间戳量化会骗过采样率估计

对某高频陀螺采集文件（11955 行 / 23.877 s）的分析暴露出真实数据问题：

```
时间戳量化严重（50% 相邻间隔为 0，中位间隔 1.00e-06s），已改用平均速率 500.7 Hz 估计采样率
重复时间戳 5981 个 (50.0%) | 中位法 1000000.0 Hz vs 平均法 500.7 Hz
```

按中位间隔 1 µs 计算会得到 **1 MHz** 的荒谬采样率，频谱随之全是混叠伪峰。
修正后主峰为 9.41 / 13.69 / 48.28 Hz，符合机身与电机振动的物理量级。

> **教训**：PC 侧时间戳分辨率不足以反映真实采样间隔时，**中位法失效**。
> 工具会自动诊断并回退到平均速率，同时显式告警——**不要静默给出错误频谱**。
> 另注：该文件实际平均速率 **500.7 Hz**，而记录器标称 1 kHz，这本身值得排查。

**排查清单（当频谱看起来不对时）**
1. 看报告里的时间戳质量告警（是否有大量重复时间戳）
2. 若自动估计可疑，用 `--fs <Hz>` 显式指定采样率
3. 检查峰值是否超过 Nyquist（fs/2）——超过必然是错的
4. 与物理常识对照：机身/桨叶振动通常在几十到几百 Hz 量级

## 4. 与工程内既有脚本的关系

工程内往往已有大量业务脚本（构建、采集、分析、激励）。**本 SKILL 只提供通用原子能力**，
业务专项脚本保留在工程内，两者互补而非替换。用注册表统一查看与调用（见 `registry.md`）：

```bash
python scripts/ef_dev.py registry list                     # 通用 + 项目专项一览
python scripts/ef_dev.py registry list --nonportable       # 只看不可移植的专项工具
python scripts/ef_dev.py registry run <tool-id> -- <args>  # 统一调用（含安全提示）
```

**改动既有脚本前先跑一次 `registry list`**，确认是否已有覆盖该需求的能力。

## 5. 已知陷阱（实测修正，勿回退）

| # | 陷阱 | 表现 | 修正方式 |
|---|------|------|---------|
| 1 | **概念提及 ≠ 产物存在** | 一份「讨论 RTM/ICD 的分析报告」被误判为「项目已具备该交付物」 | 证据分级：文件名（强）> 标题行（中）；**正文提及不采信**；排除「分析类」文档 |
| 2 | **参考代码树污染** | 第三方参考固件的 `gtest.cmake`、41 处 malloc 被计入自研结果 | 识别 `-master`/`-main` 等归档后缀与已知第三方固件名；支持 `excludePaths` |
| 3 | **基础设施检测沿用代码层排除口径** | `MDK-ARM/` 被当 vendor 排除，导致「构建系统 = 无」的漏报 | 基础设施检测走独立排除集，**放行 IDE 工程目录** |
| 4 | **文件名令牌派生过松** | `project.yml`→`project` 误命中 `05b_project_report.json`（错报 Ceedling） | 令牌改词边界匹配 + 通用词黑名单；**检测结果附证据路径** |
| 5 | **时间戳量化骗过采样率估计** | 50% 相邻间隔为 0 → 中位法推出 1 MHz，频谱全是混叠伪峰 | 量化严重时**回退平均速率**并显式告警；提供 `--fs` 覆盖 |
| 6 | **静默给出错误结论** | 绘图/解析失败被吞掉，报告里看不出问题 | 失败原因写入 `png_error` 等字段并在报告中呈现，不静默降级 |
| 7 | **ctypes 句柄截断** | 未声明 `restype` → 64 位 HANDLE 被截成 32 位，串口打不开 | 显式声明全部 Win32 函数原型 |
| 8 | **通用代码硬编码项目值** | 把某项目的目录名/串口号写进通用脚本 → 换项目即错 | 项目值一律进 `.ef-guardian.json`，代码只读配置（见 `registry.md`） |

## 6. 推荐工作流

1. **盘点**：`ef_dev.py registry list` —— 先搞清工程里已有什么，避免重复造轮子
2. **审计**：`ef_scan.py --path .` —— 拿到流程缺口清单
3. **构建**：`ef_dev.py build --inject-version version.h` —— 让固件自带可追溯版本
4. **烧录**：`ef_dev.py flash`
5. **验证**：`ef_dev.py watch` —— 只读确认固件输出正常（字段数由配置决定）
6. **采集**：`ef_dev.py capture --out data/run1.csv --firmware <版本>` —— 带元数据留痕
7. **分析**：`ef_dev.py analyze data/run1.csv --bin <油门列>` —— 统计 + 频谱 + 异常段
8. **归档**：把 CSV + 元数据 + 分析结论一并归档（对应 `change_log.csv` / `compat_matrix.csv`）
