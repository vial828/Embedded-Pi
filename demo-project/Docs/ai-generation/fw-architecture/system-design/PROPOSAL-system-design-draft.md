# 初步设计框架（草案 / 待人工评审）

> **origin: generated** — 本文件由 `agent-design/tools/draft_architecture.py` 从
> `requirements_index.json` 与 IO-Mapping 工作表生成，**不是已评审设计**。
> 依据 `Docs/standards/constitution.md` 的 `semantic_inference: forbidden`，
> 生成物不得直接作为设计来源：需要人工逐行核对后，把认可的行搬进
> `system-design.md` 并走 `wait_for_design_review` 批准。
> 在那之前，S04 的覆盖检查仍报 `not-evaluated`，S30 仍拒绝认证——这是刻意的。

- 项目：`demo-project`
- 需求条数：145（已分配 145）
- 模块数：19；无**直接**需求挂接：MOD-001, MOD-002, MOD-003, MOD-004, MOD-005, MOD-006, MOD-008, MOD-009
  （HAL/DRV 层由上层模块间接覆盖，0 条直接挂接是正常的，不是缺口）
- 兜底规则落到 `MOD-012` 的：16 条（**最需要人看**，规则没说话、只是没别的地方去）

## 1. 硬件事实（来源：IO-Mapping 工作表与 SCH PDF）

| 事实 | 来源 |
|---|---|
| 主控 `CY8C6245FNI-S3D41`（PSoC 6，双核） | IO-Mapping 表 `CY8C6245FNI`；SCH `MCU` |
| BLE 协处理器 `SS805EX`（与主控 UART + 单线相连） | IO-Mapping 表 `SS805`；SCH `MCU` |
| 充电 `BQ25622ERYKR`、电量计 `BQ27426YZF` | SCH `Power` |
| 电源 `MP4235GVE-0000`、`SGM38045` | SCH `Power` |
| 加热为 **TCR**，电流采样用**双运放**（V2.0→V2.1 变更） | IO-Mapping 变更记录 |
| **OCP/OTP 与 MCU 复位兜底在 BLE 侧独立存在** | `IMON`/`NTC_HEAT(OTP)`/`CY_NRES` on SS805EX |

> ⚠ `Docs/config.yaml` 仍写着 `mcu.part: STM32F407VGT6`（S02 模板占位），
> 与硬件实际型号 `CY8C6245FNI-S3D41` **不一致**，必须先改配置再谈生成。

### 1.1 引脚→功能（MCU，摘自有网络的行）

| Pin | Net | 类型 | 功能 |
|---|---|---|---|
| E9 | MOTOR | PWM | Motor pwm |
| D10 | HEAT_EN | GPIO | Heating NMOS enable |
| H10 | RX_BLE | UART | BLE UART |
| F8 | TX_BLE | UART | BLE UART |
| H8 | BUZZER | PWM | Buzzer pwm |
| G9 | USB_INT | INT | USB detection |
| J11 | KEY1 | INT | Switch |
| J9 | KEY2 | INT | Switch |
| J5 | CAP_WKUP | INT | Stick activation wake-up |
| G7 | LCD_DCX | GPIO | Screen date/command |
| J3 | MS_BAT | GPIO | Heating DCDC enable |
| H4 | 2V8_EN | GPIO | 2.8V voltage enable |
| G5 | SCL | IIC | IIC |
| J11 | SDA | IIC | IIC |
| H2 | SWDIO | Program | Program |
| G3 | SWCLK | Program | Program |
| F6 | LCD_MOSI | SPI | Screen SPI |
| F4 | LCD_MISO | SPI | Screen SPI |
| F2 | LCD_CLK | SPI | Screen SPI |
| E3 | LCD_CS | SPI | Screen SPI |
| D2 | RX_USB | UART | BOOT UART |
| E5 | TX_USB | UART | BOOT UART |
| E7 | NTC_USB | ADC | USB temperature |
| C1 | P_Sensor | ADC | IR detection |
| D4 | VOL_H+ | ADC | Heating voltage detection |
| A5 | VOL_H- | ADC | Heating voltage detection |
| B4 | CUR1 | ADC | Heating current (first-stage amplifier) detection |
| A3 | CUR2 | ADC | Heating current (second-stage amplifier) detection |
| C5 | NTC_HEAT | ADC | Heater pads temperature detection |
| D6 | VOL_BAT | ADC | Battery voltage detection |
| C7 | FLASH_CS | SPI | FLASH Dual SPI |
| A7 | VCC_EN | GPIO | Screen power enable |
| D8 | S_W_C | GPIO | SS805 single wire |
| B8 | FLASH_D1 | SPI | FLASH Dual SPI |
| C9 | FLASH_D0 | SPI | FLASH Dual SPI |
| B10 | FLASH_CLK | SPI | FLASH Dual SPI |

### 1.2 BLE 协处理器侧（安全相关，勿只看 MCU）

| Pin | Net | 类型 | 功能 |
|---|---|---|---|
| 1 | DCDC_EN | GPIO | DCDC enable |
| 2 | TL_nRST | GPIO | BLE IC RST |
| 3 | FUEL_WKUP | GPIO | Fuel gauge wakeup IO |
| 6 | NA | Power |  |
| 7 | 2.8V | Power | POWER |
| 8 | 2.8V | Power | POWER |
| 9 | S_W_C | GPIO | single wire |
| 10 | CY_NRES | GPIO | MCU Reset pin |
| 11 | IMON | ADC | OCP |
| 12 | NA | GPIO |  |
| 13 | LED_TE | GPIO | Horizontal synchronizing signal |
| 14 | NTC_HEAT | ADC | OTP |
| 15 | NA | GPIO |  |
| 16 | LED_RESX | GPIO | Screen Reset pin |
| Thermal pad | GND | GND |  |

## 2. 执行模型：`while(1)` 还是 RTOS（本框架最大的空缺）

**建议（待裁，不代裁）**：分层——**控制层不交给 OS，业务层用协作式主循环 + 显式状态机**；
RTOS 只在下面四个可证伪条件任一成立时引入。

### 2.1 需求里实有的约束（逐条对应）

| 事实 | 来源 | 对执行模型的含义 |
|---|---|---|
| FW 若 >2s 未服务，看门狗必须复位系统 | R-091 | 活性必须可证明；喂狗不能放在主循环里无条件喂 |
| 数据传输期间设备必须保持完全可用 | R-053 | 升级/传输不能阻塞加热与 UI——这是 RTOS 唯一真正的论据 |
| 充电与会话的优先级「需要被定义」 | R-130 | PRD 要的是一张**优先级/抢占表**，不是调度器 |
| 长按 2.5s / 3s / 13s、短按 4s、60s 广播窗口 | R-051 R-122 R-124 R-089 | 秒级时间判定：一个 tick 就够，不需要抢占 |
| 20ms 广播间隔 | R-049 | 发生在 **SS805EX 侧**，不是我们这颗 MCU |
| 360min 充电超时由 CIC 触发后再通知 MCU | R-128 | 长定时器已在充电 IC 上，不需要软件维护 |
| OCP（过流）/ OTP（过热）在 SS805EX 里 | IO-Mapping SS805 | 最高优先级的保护**不经过任何软件调度器** |
| 实时记录 intensity / power / TC 温度 | R-075 | 采样放定时器 ISR + 环形缓冲，主循环消费 |
| 提示可被按钮/BLE 立即打断 | R-081 | 事件驱动状态机，而非多任务 |

### 2.2 建议的分层

| 层 | 内容 | 约束 |
|---|---|---|
| L0 硬件 | ADC 序列由定时器触发 + DMA；OCP/OTP 在硬件与对端 | 确定性不依赖任何软件调度 |
| L1 控制（ISR） | 加热闭环、采样滤波、保护判定 | 预算 <100µs；无阻塞、无 OS 调用、无 malloc |
| L2 业务（协作式主循环） | 显式状态机 + 事件队列 + 显式让出点 | 每轮检查活性令牌，满足才喂狗 |
| L3 长任务（分片） | FOTA 写 flash、日志批量落盘 | 分片执行，片间让出——这是对 R-053 的正面回答 |

### 2.3 什么时候该换 RTOS（可证伪触发条件）

1. 加热闭环需要 >1kHz 且与 flash 写 / BLE 流量并存，实测抖动超预算
2. 引入自带 OS 依赖的第三方协议栈或安全中间件
3. 分片让出在实测中仍无法满足 R-053（传输期间 UI 卡顿或控制超时）
4. 并发状态机数量多到让出点的正确性无法评审（经验阈值：>8 个）

### 2.4 为什么默认不选 RTOS（本项目的理由，不是泛泛之谈）

- **可测性**：现有主机侧测试（`tests/**/*_test.c` + gcc + `assert`）能直接跑状态机；
  RTOS 化后每块业务都要 OS 移植层或模拟器才能测——现在一行测试都跑不了
- **可审计**：让出点是**显式**的；抢占把时序耦合藏进优先级数字里
- **双核是硬件出路**：PSoC6 的 CM0+ 可承担活性/保护监督（R-091），不靠调度器保证
- **BLE 20ms 不在我们这颗 MCU 上**：最大的硬实时需求本来就在 SS805EX 侧

### 2.5 无论选哪个都要做的一件事

**活性令牌喂狗**：每个关键任务一个 deadline 位，全部满足才喂。
在主循环里无条件喂狗，恰好会在 R-091 描述的那个场景（FW 已经不服务）把看门狗关掉。

定量阈值（闭环速率、允许抖动）需要 `Docs/hardware/registers/` 与 `datasheet/` 才能定，
**现在写任何具体频率都是猜**，所以本节不写。

## 3. 模块划分（`module_id` 与 `system-design.md` 的 `MODULE_DESIGN_TABLE` 对齐）

| module_id | layer | name | responsibility | 硬件/需求依据 |
|---|---|---|---|---|
| MOD-001 | hal | mcu_core | PSoC6 上电/时钟/复位/SWD、双核启动与看门狗 | CY8C6245FNI-S3D41；XRES、SWDIO/SWCLK、CY_NRES |
| MOD-002 | hal | adc_sense | NTC、电压、电流、IR 采样与滤波 | NTC_USB/NTC_HEAT、P_Sensor、VOL_H±/CUR1/CUR2、VOL_BAT |
| MOD-003 | hal | gpio_io | 按键与数字 IO 输入去抖 | KEY1/KEY2、USB_INT、CAP_WKUP |
| MOD-004 | drv | heater | TCR 加热驱动与闭环（双运流采样） | HEAT_EN、MS_BAT、CUR1/CUR2、NTC_HEAT；V2.0→V2.1 改 TCR + 双运放 |
| MOD-005 | drv | haptics | 马达与蜂鸣器输出 | MOTOR (P0.0 PWM)、BUZZER (P2.2 PWM) |
| MOD-006 | drv | display | OLED 面板驱动（SPI + DCX + 电源/复位） | LCD_MOSI/MISO/CLK/CS、LCD_DCX、VCC_EN；LED_RESX/LED_TE 在 SS805 侧 |
| MOD-007 | drv | storage | 外部 NOR Flash（QSPI）与数据分区 | FLASH_CS/D0/D1/CLK（Dual SPI） |
| MOD-008 | drv | power_cell | 充电、电量计、电源轨使能 | I2C SCL/SDA、BQ25622、BQ27426、2V8_EN、MP4235、SGM38045 |
| MOD-009 | comm | link_ble | 与 BLE 协处理器 UART 协议栈适配 | RX_BLE/TX_BLE (P2.0/P2.1)、S_W_C 单线、TL_nRST、CY_NRES |
| MOD-010 | comm | link_usb_cli | USB 串口控制台与 BOOT UART | RX_USB/TX_USB (P9.0/P9.1)、USB_INT、NTC_USB |
| MOD-011 | svc | ble_profile | GATT 服务、配对/连接/断开、APP 数据面 | 需求簇：BLE/无线 |
| MOD-012 | svc | ui | 界面状态机、动画、提示与命名 | 需求簇：UI/显示 |
| MOD-013 | svc | heating_service | 加热档位/曲线、会话状态与安全限幅 | 需求簇：加热；硬件基础见 MOD-004 |
| MOD-014 | svc | power_service | 电源模式、休眠/唤醒、开关机与电量策略 | 需求簇：电池/电源；CAP_WKUP、FUEL_WKUP |
| MOD-015 | svc | logging | 会话/使用记录、导出与清理 | 需求簇：日志/数据；存储见 MOD-007 |
| MOD-016 | svc | update | FOTA/UI 升级、签名/加密/防降级、双区引导 | 需求簇：OTA/固件 |
| MOD-017 | svc | security | RDP、读保护、锁定与调试口管控 | 需求簇：安全；SWD 口见 MOD-001 |
| MOD-018 | svc | factory | 产测、校准、HW ID 与序列号 | 需求簇：校准/产测；CLI 见 MOD-010 |
| MOD-019 | safety | interlock | 过流 OCP / 过热 OTP / MCU 复位兜底（在 BLE 侧独立存在） | SS805EX：IMON(OCP)、NTC_HEAT(OTP)、CY_NRES、TL_nRST |

## 4. 需求→模块分配（每条带命中规则）

搬运到 `system-design.md` 时，把 `req_ids` 列按模块合并即可；
不认可的行**删掉**，不要留空——留空会被覆盖检查算成未映射。

| module | 需求数 | req_ids |
|---|---|---|
| MOD-001 mcu_core | 0 | — |
| MOD-002 adc_sense | 0 | — |
| MOD-003 gpio_io | 0 | — |
| MOD-004 heater | 0 | — |
| MOD-005 haptics | 0 | — |
| MOD-006 display | 0 | — |
| MOD-007 storage | 1 | R-010 |
| MOD-008 power_cell | 0 | — |
| MOD-009 link_ble | 0 | — |
| MOD-010 link_usb_cli | 4 | R-017, R-036, R-038, R-123 |
| MOD-011 ble_profile | 27 | R-003, R-004, R-009, R-047, R-048, R-050, R-051, R-052, R-053, R-054, R-058, R-062, R-063, R-064, R-065, R-071, R-095, R-096, R-097, R-098, R-099, R-100, R-104, R-109, R-110, R-111, R-112 |
| MOD-012 ui | 22 | R-001, R-015, R-016, R-018, R-029, R-034, R-045, R-046, R-060, R-070, R-089, R-090, R-092, R-093, R-094, R-101, R-103, R-107, R-108, R-120, R-121, R-133 |
| MOD-013 heating_service | 23 | R-020, R-030, R-031, R-033, R-037, R-056, R-066, R-067, R-069, R-072, R-075, R-105, R-106, R-116, R-119, R-122, R-128, R-130, R-132, R-135, R-136, R-138, R-144 |
| MOD-014 power_service | 22 | R-006, R-014, R-022, R-032, R-035, R-049, R-057, R-059, R-077, R-079, R-081, R-082, R-102, R-124, R-125, R-126, R-127, R-129, R-131, R-137, R-139, R-143 |
| MOD-015 logging | 12 | R-002, R-005, R-011, R-013, R-021, R-023, R-024, R-025, R-026, R-117, R-118, R-134 |
| MOD-016 update | 21 | R-019, R-028, R-039, R-040, R-041, R-044, R-055, R-061, R-068, R-074, R-076, R-080, R-083, R-086, R-087, R-088, R-113, R-114, R-115, R-141, R-142 |
| MOD-017 security | 7 | R-007, R-008, R-042, R-043, R-084, R-085, R-145 |
| MOD-018 factory | 4 | R-012, R-073, R-078, R-140 |
| MOD-019 interlock | 2 | R-027, R-091 |

### 4.1 逐条依据（可逐行否决）

| req_id | 标题 | 模块 | 命中规则 | 来源 |
|---|---|---|---|---|
| R-010 | Dump MCU Memory (RAM/Flash) | MOD-007 | `Flash|Storage|Partition|File ?system` | US-2276704 p8 |
| R-017 | Get/Send Challenge (unlock) | MOD-010 | `\bCLI\b|\bUSB\b|Console|Command line` | US-2258073 p10 |
| R-036 | Command Line Communication to Device | MOD-010 | `\bCLI\b|\bUSB\b|Console|Command line` | US-2258106 p14 |
| R-038 | CLI Authentication - GUI | MOD-010 | `\bCLI\b|\bUSB\b|Console|Command line` | US-2258108 p15 |
| R-123 | CLI Authentication | MOD-010 | `\bCLI\b|\bUSB\b|Console|Command line` | US-2325484 p26 |
| R-003 | BLE Connectivity Operation | MOD-011 | `\bBLE\b|Bluetooth|Pairing|Connection|Adv` | US-2285155 p1 |
| R-004 | Start BLE Pairing Process | MOD-011 | `\bBLE\b|Bluetooth|Pairing|Connection|Adv` | US-2285140 p1 |
| R-009 | Clear Bluetooth Pairing | MOD-011 | `\bBLE\b|Bluetooth|Pairing|Connection|Adv` | US-2276715 p8 |
| R-047 | BLE Connection/Pairing Fail Error | MOD-011 | `\bBLE\b|Bluetooth|Pairing|Connection|Adv` | US-2292636 p17 |
| R-048 | BLE Clear Data Log | MOD-011 | `\bBLE\b|Bluetooth|Pairing|Connection|Adv` | US-2300500 p18 |
| R-050 | BLE Pairing Success Feedback (Not Reconnection) | MOD-011 | `\bBLE\b|Bluetooth|Pairing|Connection|Adv` | US-2258130 p18 |
| R-051 | BLE Pairing Process | MOD-011 | `\bBLE\b|Bluetooth|Pairing|Connection|Adv` | US-2258159 p19 |
| R-052 | [2P] BLE Pairing - UI | MOD-011 | `\bBLE\b|Bluetooth|Pairing|Connection|Adv` | US-2258149 p19 |
| R-053 | BLE Connection (Re-connection) | MOD-011 | `\bBLE\b|Bluetooth|Pairing|Connection|Adv` | US-2258131 p20 |
| R-054 | BLE Disconnection | MOD-011 | `\bBLE\b|Bluetooth|Pairing|Connection|Adv` | US-2258132 p21 |
| R-058 | Device Name | MOD-011 | `\bBLE\b|Bluetooth|Pairing|Connection|Adv` | US-2258122 p22 |
| R-062 | Find My Device | MOD-011 | `\bBLE\b|Bluetooth|Pairing|Connection|Adv` | US-2258133 p24 |
| R-063 | [2P] Find My Device-UI | MOD-011 | `\bBLE\b|Bluetooth|Pairing|Connection|Adv` | US-2258144 p25 |
| R-064 | My Naming | MOD-011 | `\bBLE\b|Bluetooth|Pairing|Connection|Adv` | US-2258142 p26 |
| R-065 | [2P] My Naming - UI | MOD-011 | `\bBLE\b|Bluetooth|Pairing|Connection|Adv` | US-2258146 p27 |
| R-071 | Debug Information Feature | MOD-011 | `\bBLE\b|Bluetooth|Pairing|Connection|Adv` | US-2258154 p32 |
| R-095 | BLE Connection (Re-connection) | MOD-011 | `\bBLE\b|Bluetooth|Pairing|Connection|Adv` | US-2325531 p11 |
| R-096 | BLE Disconnection | MOD-011 | `\bBLE\b|Bluetooth|Pairing|Connection|Adv` | US-2325532 p11 |
| R-097 | BLE Connection/Pairing Fail Error | MOD-011 | `\bBLE\b|Bluetooth|Pairing|Connection|Adv` | US-2325538 p11 |
| R-098 | BLE Pairing | MOD-011 | `\bBLE\b|Bluetooth|Pairing|Connection|Adv` | US-2325530 p11 |
| R-099 | BLE Pairing - UI | MOD-011 | `\bBLE\b|Bluetooth|Pairing|Connection|Adv` | US-2289558 p12 |
| R-100 | BLE Advertising Interval | MOD-011 | `\bBLE\b|Bluetooth|Pairing|Connection|Adv` | US-2325534 p13 |
| R-104 | BLE Clear Data Log | MOD-011 | `\bBLE\b|Bluetooth|Pairing|Connection|Adv` | US-2325540 p13 |
| R-109 | My Naming | MOD-011 | `\bBLE\b|Bluetooth|Pairing|Connection|Adv` | US-2325546 p16 |
| R-110 | My Naming - UI | MOD-011 | `\bBLE\b|Bluetooth|Pairing|Connection|Adv` | US-2300992 p17 |
| R-111 | Find My Device | MOD-011 | `\bBLE\b|Bluetooth|Pairing|Connection|Adv` | US-2325522 p17 |
| R-112 | Find My Device - UI | MOD-011 | `\bBLE\b|Bluetooth|Pairing|Connection|Adv` | US-2252251 p18 |
| R-001 | Update Configuration Parameters | MOD-012 | `\bUI\b|OLED|Display|Screen|LED|Animation` | US-2289550 p1 |
| R-015 | Get/Set Device Time -GUI | MOD-012 | `(fallback)` | US-2276584 p9 |
| R-016 | FW Supports Commands in ASCII Format | MOD-012 | `(fallback)` | US-2265261 p9 |
| R-018 | Device Info Check | MOD-012 | `\bUI\b|OLED|Display|Screen|LED|Animation` | US-2258075 p10 |
| R-029 | Button Simulation | MOD-012 | `(fallback)` | US-2258090 p13 |
| R-034 | Disarm Non-recoverable Error Alarm | MOD-012 | `(fallback)` | US-2258099 p14 |
| R-045 | RLE Implementation | MOD-012 | `(fallback)` | US-2329118 p17 |
| R-046 | Authentication Command Handling | MOD-012 | `(fallback)` | US-2300551 p17 |
| R-060 | Buzzer Definition (will waiver this topic as only one bu | MOD-012 | `(fallback)` | US-2258139 p23 |
| R-070 | [2P] Lock & Unlock Status Switch - UI | MOD-012 | `\bUI\b|OLED|Display|Screen|LED|Animation` | US-2258152 p30 |
| R-089 | HW Reset | MOD-012 | `(fallback)` | US-2324999 p5 |
| R-090 | HW Reset - UI | MOD-012 | `\bUI\b|OLED|Display|Screen|LED|Animation` | US-2240681 p6 |
| R-092 | Error Codes | MOD-012 | `(fallback)` | US-2240708 p7 |
| R-093 | Error Codes - UI | MOD-012 | `\bUI\b|OLED|Display|Screen|LED|Animation` | US-2240716 p8 |
| R-094 | RLE Implementation | MOD-012 | `(fallback)` | US-2329141 p11 |
| R-101 | Device Information Feature | MOD-012 | `(fallback)` | US-2325533 p13 |
| R-103 | Debug Information Feature | MOD-012 | `(fallback)` | US-2325542 p13 |
| R-107 | Lock & Unlock Status Switch | MOD-012 | `(fallback)` | US-2325518 p15 |
| R-108 | Lock & Unlock Status Switch - UI | MOD-012 | `\bUI\b|OLED|Display|Screen|LED|Animation` | US-2325486 p16 |
| R-120 | Haptic Definition | MOD-012 | `(fallback)` | US-2325543 p23 |
| R-121 | Reset | MOD-012 | `(fallback)` | US-2325526 p25 |
| R-133 | Devices Modes | MOD-012 | `(fallback)` | US-2325173 p32 |
| R-020 | Live Data Printing | MOD-013 | `Heat|Heating|Profile|Temperature|TCR|Cha` | US-2258077 p11 |
| R-030 | Heating Profile Editing | MOD-013 | `Heat|Heating|Profile|Temperature|TCR|Cha` | US-2258092 p13 |
| R-031 | Visualized Heating Curve | MOD-013 | `Heat|Heating|Profile|Temperature|TCR|Cha` | US-2258094 p13 |
| R-033 | CIC Register Display | MOD-013 | `Heat|Heating|Profile|Temperature|TCR|Cha` | US-2258097 p14 |
| R-037 | Usage History | MOD-013 | `Heat|Heating|Profile|Temperature|TCR|Cha` | US-2258107 p15 |
| R-056 | Heating Profile Switch (duplicate) | MOD-013 | `Heat|Heating|Profile|Temperature|TCR|Cha` | US-2258135 p22 |
| R-066 | Mode Customization - Heating Profile | MOD-013 | `Heat|Heating|Profile|Temperature|TCR|Cha` | US-2258147 p27 |
| R-067 | [2P] Mode Customization - Heating Profile - UI | MOD-013 | `Heat|Heating|Profile|Temperature|TCR|Cha` | US-2258148 p28 |
| R-069 | Lock & Unlock Status Switch | MOD-013 | `Heat|Heating|Profile|Temperature|TCR|Cha` | US-2258151 p30 |
| R-072 | Heating Profile Switch-UI (duplicate) | MOD-013 | `Heat|Heating|Profile|Temperature|TCR|Cha` | US-2258160 p32 |
| R-075 | Logging - Advanced Session( for Stick Charring ) | MOD-013 | `Heat|Heating|Profile|Temperature|TCR|Cha` | US-2329029 p34 |
| R-105 | Mode Customization - Heating Profile | MOD-013 | `Heat|Heating|Profile|Temperature|TCR|Cha` | US-2325521 p14 |
| R-106 | Mode Customization - Heating Profile - UI | MOD-013 | `Heat|Heating|Profile|Temperature|TCR|Cha` | US-2325520 p14 |
| R-116 | Logging - Advanced Session( for Stick Charring ) | MOD-013 | `Heat|Heating|Profile|Temperature|TCR|Cha` | US-2329025 p20 |
| R-119 | Logging - Session Data | MOD-013 | `Heat|Heating|Profile|Temperature|TCR|Cha` | US-2325482 p23 |
| R-122 | Exit Shipping Mode - UI | MOD-013 | `Heat|Heating|Profile|Temperature|TCR|Cha` | US-2300169 p25 |
| R-128 | Charging - Time Out | MOD-013 | `Heat|Heating|Profile|Temperature|TCR|Cha` | US-2324685 p29 |
| R-130 | Charging - During Session | MOD-013 | `Heat|Heating|Profile|Temperature|TCR|Cha` | US-2324677 p30 |
| R-132 | Charging - UI | MOD-013 | `Heat|Heating|Profile|Temperature|TCR|Cha` | US-2324672 p31 |
| R-135 | Heating - Start and Stop | MOD-013 | `Heat|Heating|Profile|Temperature|TCR|Cha` | US-2323241 p34 |
| R-136 | Heating - UI | MOD-013 | `Heat|Heating|Profile|Temperature|TCR|Cha` | US-2325485 p34 |
| R-138 | Heating - Back To Back Sessions | MOD-013 | `Heat|Heating|Profile|Temperature|TCR|Cha` | US-2240688 p35 |
| R-144 | Cleaning Prompt -UI | MOD-013 | `Heat|Heating|Profile|Temperature|TCR|Cha` | US-2505907 p38 |
| R-006 | Power On/Off | MOD-014 | `Batter|Power (On|Off|Mode)|Charge|Voltag` | US-2285114 p6 |
| R-014 | Configure the Charging SOC Maximum(80% or 100% ) | MOD-014 | `Batter|Power (On|Off|Mode)|Charge|Voltag` | US-2276640 p9 |
| R-022 | Output Discharge Data Log | MOD-014 | `Batter|Power (On|Off|Mode)|Charge|Voltag` | US-2258079 p11 |
| R-032 | Charge Enable/Disable | MOD-014 | `Batter|Power (On|Off|Mode)|Charge|Voltag` | US-2258095 p14 |
| R-035 | Faulty Condition Simulation | MOD-014 | `Batter|Power (On|Off|Mode)|Charge|Voltag` | US-2258105 p14 |
| R-049 | BLE Advertising Interval | MOD-014 | `Batter|Power (On|Off|Mode)|Charge|Voltag` | US-2290520 p18 |
| R-057 | Battery Level of Device | MOD-014 | `Batter|Power (On|Off|Mode)|Charge|Voltag` | US-2258136 p22 |
| R-059 | Device On Charge BLE Notification (duplicate) | MOD-014 | `Batter|Power (On|Off|Mode)|Charge|Voltag` | US-2258137 p23 |
| R-077 | Auto Activation | MOD-014 | `Batter|Power (On|Off|Mode)|Charge|Voltag` | US-2266447 p34 |
| R-079 | Battery Replaces | MOD-014 | `Batter|Power (On|Off|Mode)|Charge|Voltag` | US-2314846 p35 |
| R-081 | Battery End of Life | MOD-014 | `Batter|Power (On|Off|Mode)|Charge|Voltag` | US-2505801 p37 |
| R-082 | Cleaning Prompt | MOD-014 | `Batter|Power (On|Off|Mode)|Charge|Voltag` | US-2505884 p37 |
| R-102 | Battery Level of Device | MOD-014 | `Batter|Power (On|Off|Mode)|Charge|Voltag` | US-2325545 p13 |
| R-124 | Battery Level Check | MOD-014 | `Batter|Power (On|Off|Mode)|Charge|Voltag` | US-2240678 p27 |
| R-125 | Battery Level Check - UI | MOD-014 | `Batter|Power (On|Off|Mode)|Charge|Voltag` | US-2325030 p28 |
| R-126 | Battery Replaces | MOD-014 | `Batter|Power (On|Off|Mode)|Charge|Voltag` | US-2325516 p28 |
| R-127 | Charging - Number of Session in One Fully Charge | MOD-014 | `Batter|Power (On|Off|Mode)|Charge|Voltag` | US-2324687 p29 |
| R-129 | Charging - Charge Time | MOD-014 | `Batter|Power (On|Off|Mode)|Charge|Voltag` | US-2324679 p29 |
| R-131 | Charging | MOD-014 | `Batter|Power (On|Off|Mode)|Charge|Voltag` | US-2240672 p30 |
| R-137 | Heating -Too Low To Start Session | MOD-014 | `Batter|Power (On|Off|Mode)|Charge|Voltag` | US-2240707 p35 |
| R-139 | Auto Activation | MOD-014 | `Batter|Power (On|Off|Mode)|Charge|Voltag` | US-2325514 p36 |
| R-143 | Battery End of Life - UI | MOD-014 | `Batter|Power (On|Off|Mode)|Charge|Voltag` | US-2505872 p37 |
| R-002 | CLI Generate Historical Test Puff Data | MOD-015 | `\bLog|Data Log|Puff|Session|Export|Stati` | US-2285204 p1 |
| R-005 | Clear/Delete Puff Data | MOD-015 | `\bLog|Data Log|Puff|Session|Export|Stati` | US-2285130 p6 |
| R-011 | Output Statistics | MOD-015 | `\bLog|Data Log|Puff|Session|Export|Stati` | US-2276681 p8 |
| R-013 | Reset Statistics | MOD-015 | `\bLog|Data Log|Puff|Session|Export|Stati` | US-2276655 p9 |
| R-021 | Output Session Data Log | MOD-015 | `\bLog|Data Log|Puff|Session|Export|Stati` | US-2258078 p11 |
| R-023 | Output Lifecycle Data - GUI | MOD-015 | `\bLog|Data Log|Puff|Session|Export|Stati` | US-2258080 p12 |
| R-024 | Output Event Data Log - GUI | MOD-015 | `\bLog|Data Log|Puff|Session|Export|Stati` | US-2258081 p12 |
| R-025 | Output Error Statistics - GUI | MOD-015 | `\bLog|Data Log|Puff|Session|Export|Stati` | US-2258082 p12 |
| R-026 | Log Erase | MOD-015 | `\bLog|Data Log|Puff|Session|Export|Stati` | US-2258083 p12 |
| R-117 | Logging - Event Data | MOD-015 | `\bLog|Data Log|Puff|Session|Export|Stati` | US-2325481 p20 |
| R-118 | Logging - Lifecycle Data | MOD-015 | `\bLog|Data Log|Puff|Session|Export|Stati` | US-2325483 p22 |
| R-134 | Mode Selection - UI | MOD-015 | `\bLog|Data Log|Puff|Session|Export|Stati` | US-2325157 p32 |
| R-019 | FW Update - GUI | MOD-016 | `FOTA|UI OTA|Firmware|FW (Update|Signatur` | US-2258076 p10 |
| R-028 | Reboot Device | MOD-016 | `FOTA|UI OTA|Firmware|FW (Update|Signatur` | US-2258089 p13 |
| R-039 | FW Signature | MOD-016 | `FOTA|UI OTA|Firmware|FW (Update|Signatur` | US-2258110 p15 |
| R-040 | FW Encryption | MOD-016 | `FOTA|UI OTA|Firmware|FW (Update|Signatur` | US-2258111 p16 |
| R-041 | FW Downgrade Prevention | MOD-016 | `FOTA|UI OTA|Firmware|FW (Update|Signatur` | US-2258112 p16 |
| R-044 | Legitimate FW Update | MOD-016 | `FOTA|UI OTA|Firmware|FW (Update|Signatur` | US-2258116 p16 |
| R-055 | Device Information Feature | MOD-016 | `FOTA|UI OTA|Firmware|FW (Update|Signatur` | US-2258134 p21 |
| R-061 | FOTA | MOD-016 | `FOTA|UI OTA|Firmware|FW (Update|Signatur` | US-2258143 p23 |
| R-068 | [2P] FOTA - UI | MOD-016 | `FOTA|UI OTA|Firmware|FW (Update|Signatur` | US-2258150 p29 |
| R-074 | UI OTA | MOD-016 | `FOTA|UI OTA|Firmware|FW (Update|Signatur` | US-2263684 p33 |
| R-076 | Use BAT boot | MOD-016 | `FOTA|UI OTA|Firmware|FW (Update|Signatur` | US-2250368 p34 |
| R-080 | FW Update | MOD-016 | `FOTA|UI OTA|Firmware|FW (Update|Signatur` | US-2243999 p35 |
| R-083 | Legitimate FW Update | MOD-016 | `FOTA|UI OTA|Firmware|FW (Update|Signatur` | US-2325510 p38 |
| R-086 | FW Downgrade Prevention | MOD-016 | `FOTA|UI OTA|Firmware|FW (Update|Signatur` | US-2325506 p38 |
| R-087 | FW Encryption | MOD-016 | `FOTA|UI OTA|Firmware|FW (Update|Signatur` | US-2325504 p38 |
| R-088 | FW Signature | MOD-016 | `FOTA|UI OTA|Firmware|FW (Update|Signatur` | US-2325503 p5 |
| R-113 | FOTA | MOD-016 | `FOTA|UI OTA|Firmware|FW (Update|Signatur` | US-2325524 p19 |
| R-114 | FOTA - UI | MOD-016 | `FOTA|UI OTA|Firmware|FW (Update|Signatur` | US-2325529 p19 |
| R-115 | UI OTA | MOD-016 | `FOTA|UI OTA|Firmware|FW (Update|Signatur` | US-2325525 p20 |
| R-141 | Use BAT boot | MOD-016 | `FOTA|UI OTA|Firmware|FW (Update|Signatur` | US-2325513 p36 |
| R-142 | FW Update | MOD-016 | `FOTA|UI OTA|Firmware|FW (Update|Signatur` | US-2325512 p36 |
| R-007 | RDP on Set | MOD-017 | `\bRDP\b|Readout|Write Protection|Tamper|` | US-2285096 p7 |
| R-008 | Update PC Command Authentication Key | MOD-017 | `\bRDP\b|Readout|Write Protection|Tamper|` | US-2276730 p7 |
| R-042 | Damaged or Modified FW | MOD-017 | `\bRDP\b|Readout|Write Protection|Tamper|` | US-2258114 p16 |
| R-043 | Readout/Write Protection | MOD-017 | `\bRDP\b|Readout|Write Protection|Tamper|` | US-2258115 p16 |
| R-084 | Readout/Write Protection | MOD-017 | `\bRDP\b|Readout|Write Protection|Tamper|` | US-2325508 p38 |
| R-085 | Damaged or Modified FW | MOD-017 | `\bRDP\b|Readout|Write Protection|Tamper|` | US-2325507 p38 |
| R-145 | RDP on Set | MOD-017 | `\bRDP\b|Readout|Write Protection|Tamper|` | US-2522146 p38 |
| R-012 | Device Serial Number | MOD-018 | `Calib|Factory|HW ID|Serial|Production|Te` | US-2276673 p9 |
| R-073 | Reset | MOD-018 | `Calib|Factory|HW ID|Serial|Production|Te` | US-2258161 p32 |
| R-078 | HW ID | MOD-018 | `Calib|Factory|HW ID|Serial|Production|Te` | US-2313935 p35 |
| R-140 | HW ID | MOD-018 | `Calib|Factory|HW ID|Serial|Production|Te` | US-2325515 p36 |
| R-027 | Factory Reset - GUI | MOD-019 | `Over.?current|Over.?temp|OCP|OTP|Watchdo` | US-2258085 p13 |
| R-091 | Watchdog | MOD-019 | `Over.?current|Over.?temp|OCP|OTP|Watchdo` | US-2240715 p6 |

## 5. 待人裁定（框架不能替人决定的事）

0. **执行模型**：承受建议 A（分层 + 协作式主循环）还是直接上 RTOS？（见 §2）
1. **加热安全边界**：谁定超温/超流阈值与响应时间？硬件已把 OCP/OTP 放在 SS805 侧，
   软件侧的限幅与失效策略必须与之一致（缺 datasheet 无法核对门限）。
2. **双核分工**：PSoC6 的 CM4/CM0+ 如何切分（实时加热控制 vs 通信/UI）？
3. **BLE 侧固件归属**：SS805EX 上是否也有需要跟踪的需求（31 条 BLE 需求里有多少落在对端）？
4. **升级与回滚**：签名/加密/防降级（24 条）落在 MCU 还是 BLE 侧引导？
5. **缺输入**：`Docs/hardware/registers/`、`Docs/hardware/datasheet/`、`Docs/bsp/` 仍为空——
   寄存器初始化表与引脚电气参数无法从 IO-Mapping 推出，不能猜。

## 6. 这份草案**没有**做的事

- 没有生成 `system-design.md`，也没有改它：覆盖检查仍应报 `not-evaluated`
- 没有编造寄存器地址、时钟树或引脚电气参数（缺 datasheet）
- 没有把需求改写或合并：145 条原文与 work item ID 一字未动
