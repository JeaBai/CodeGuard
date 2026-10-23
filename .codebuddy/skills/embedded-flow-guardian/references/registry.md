# 工具管理规范（注册表）

> 本文件规定一件事：**什么能力该放进 Skill，什么不该；不放进去的怎么统一调用。**
> 这是防止 Skill 随项目膨胀、防止 token 被无意义占用的核心纪律。

## 1. 两类工具，两种命运

| | 通用能力 | 项目专项工具 |
|---|---|---|
| **判定** | 换项目即用，源码中无任何项目特定值 | 依赖特定机型/板卡/试验场景/路径/端口 |
| **存放** | Skill 的 `scripts/`（随版本分发） | **工程内单独管理**（不进 Skill） |
| **登记** | `BUILTIN` 清单（版本化） | 注册表自动扫描登记 |
| **调用** | 直接调用 | **经注册表统一调用** |
| **典型** | 编译烧录、串口采集、数据分析、流程审计 | 某机型的倾斜符号验证、电机映射、PID 调参对比 |

**为什么项目专项工具不能塞进 Skill**

1. **污染通用性**：项目目录名/串口号一旦进通用代码，换项目就是错
2. **抬高维护成本**：每次 Skill 升级都要处理这些一次性脚本
3. **抬高 token 成本**：清单越长，模型选错工具的概率越高
4. **造成口径分裂**：同一能力在 Skill 与工程内各有一份实现

**为什么也不能放任散落**

- 会重复造轮子（新会话不知道已有工具）
- 会口径分裂（同一个"静置分析"出现三种算法）
- **激励类脚本分散且无安全标记，是真实风险**（驱动电机/舵机）

→ 注册表同时解决这两端。

## 2. 三层数据来源（后者覆盖前者）

```
① BUILTIN            Skill 自带通用工具（随版本发布，必须可移植）
        ↓ 合并
② 自动扫描            扫描工程内脚本 → 判定可移植性 → 自动登记
        ↓ 覆盖
③ .ef-registry.json   项目级策展（改名/加说明/纠正判定/排除误报）
```

策展文件（写入项目根）结构：

```json
{
  "project_tools": [ /* 由 scan 生成，只读参考 */ ],
  "overrides": [
    { "id": "proj.sim.analyze_tilt_sign",
      "summary": "卸桨倾斜方向验证（本项目专用）",
      "superseded_by": null,
      "tags": ["analysis", "bench"] }
  ],
  "exclude": ["proj.tmp.scratch"]
}
```

## 3. 可移植性判定：找证据，不猜

判定不做臆测，而是**在源码里找"不可移植"的证据**：

| 证据类型 | 检测方式 | 示例 |
|---|---|---|
| 硬编码绝对路径 | 正则匹配盘符路径 | `r"D:\...\<工程>.uvprojx"` |
| 硬编码串口 | 匹配 `COM\d+` | `serial.Serial("<COMx>")` |
| 硬编码芯片型号 | 匹配已知 MCU 前缀 | `STM32F407` / `ESP32` / `nRF52` |
| 硬编码板卡版本 | 匹配 `Rev A` / `rev-3.0` | `if BOARD_REV == "RevB"` |
| 硬编码工程目录名 | 匹配常见工程目录词 | `<固件目录>/`、`<工具目录>/` |
| 硬编码工程名 | 工程根目录名出现在源码中 | `<工程名>` |

命中任一即判为**不可移植**，并**回传具体原因**——检测结果是可审计的，不是黑箱标签。

## 4. 安全分级（调用前必看）

| 级别 | 含义 | 标记 |
|---|---|---|
| `read` | 只读（分析、验证、体检、可视化） | `R` |
| `write` | 会改文件或构建产物（编译、烧录、采集落盘） | `W` |
| `actuate` | **会驱动执行机构**（电机、舵机、SBUS 注入） | `!!` |

`actuate` 类工具调用前必须确认：**桨叶已取下（或等效隔离）· 机体固定 · 无人靠近 · 明确中止手段**。
`registry show` 与 `registry run` 都会主动打印该提醒。

## 5. 统一调用

```bash
# 一览（默认紧凑表格，token 友好）
python scripts/ef_dev.py registry list
python scripts/ef_dev.py registry list --type skill
python scripts/ef_dev.py registry list --type project
python scripts/ef_dev.py registry list --nonportable
python scripts/ef_dev.py registry list --tag analysis

# 详情（含可移植性原因、安全提示、调用命令）
python scripts/ef_dev.py registry show <tool-id>

# 统一调用（附加参数用 -- 分隔）
python scripts/ef_dev.py registry run <tool-id> -- --help

# 重建登记 / 校验
python scripts/ef_dev.py registry scan
python scripts/ef_dev.py registry verify
```

## 6. 维护纪律（四条）

1. **项目特定值只出现在 `.ef-guardian.json`**：目录名、串口号、字段数、参考树路径一律配置化。
   通用代码里出现项目值，视为缺陷（对应 `usage.md` 陷阱 #8）。
2. **新增工具先问归哪类**：能跨项目复用 → 进 Skill；不能 → 留工程内并跑一次 `registry scan`。
3. **`registry verify` 纳入例行检查**：注册项路径失效会让"统一调用"变成空头承诺。
4. **Skill 的 `scripts/` 只增不减要警惕**：每次新增前先确认现有能力是否已覆盖
   （`registry list` 会显示每类对应的通用能力，含"无通用实现"的项）。

## 7. token 成本纪律

| 项 | 规则 |
|---|---|
| `SKILL.md` | 只做**路由**：定位、边界、快速开始、路由表。详细内容一律放 references |
| `description` | 保留触发关键词即可，不写实现细节（单行，勿用 YAML 折叠标量 `>`，校验器会误判） |
| `references/` | 按需加载。**不要在一次会话里全读**；每个文件顶部说明"何时加载" |
| `scripts/` | 不进上下文（被执行而非阅读）。可以长，但要能被 `--help` 自解释 |
| 注册表输出 | `list` 默认紧凑表格；需要机器可读时才用 `--json` |
