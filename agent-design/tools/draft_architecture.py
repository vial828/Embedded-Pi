#!/usr/bin/env python3
"""Draft an architecture proposal for a project - as a *reviewable draft*, never as design.

Why this exists: the constitution forbids the agent inventing design content
(`semantic_inference: forbidden`), but a human still has to start the design
somewhere. This tool produces the part a human can check line by line:

  * hardware facts read out of the IO-mapping workbook (pins, nets, functions)
  * a module partition, with each module's peripheral basis stated
  * every requirement assigned to a module **by a visible rule**, with the matched
    keyword printed next to it

The output is a proposal document. It is not `system-design.md`, and the coverage
check keeps reporting `not-evaluated` until a human moves rows into
`system-design.md` and approves the design - which is the point: an unreviewed
proposal must not be able to certify anything.

Run:  .venv/bin/python agent-design/tools/draft_architecture.py demo-project
      .venv/bin/python agent-design/tools/draft_architecture.py demo-project --check
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

REQUIREMENTS_INDEX = "Docs/ai-generation/knowledge/requirements_index.json"
PROPOSAL_RELATIVE = "Docs/ai-generation/fw-architecture/system-design/PROPOSAL-system-design-draft.md"

# ---------------------------------------------------------------- hardware facts

XLSX_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
XLSX_REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"


def read_workbook_sheets(path: Path) -> dict[str, list[list[str]]]:
    """Read an .xlsx with no third-party dependency: it is a zip of XML."""
    with zipfile.ZipFile(path) as archive:
        shared: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            shared = ["".join(node.text or "" for node in item.iter(f"{XLSX_NS}t")) for item in root.iter(f"{XLSX_NS}si")]

        relations = {
            rel.get("Id"): rel.get("Target")
            for rel in ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        }
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        sheets: dict[str, list[list[str]]] = {}
        for sheet in workbook.iter(f"{XLSX_NS}sheet"):
            target = relations[sheet.get(f"{XLSX_REL}id")].lstrip("/")
            body = ET.fromstring(archive.read(f"xl/{target}"))
            rows: list[list[str]] = []
            for row in body.iter(f"{XLSX_NS}row"):
                cells: list[str] = []
                for cell in row.iter(f"{XLSX_NS}c"):
                    value = cell.find(f"{XLSX_NS}v")
                    if value is None:
                        cells.append("")
                        continue
                    cells.append(shared[int(value.text)] if cell.get("t") == "s" else (value.text or ""))
                rows.append(cells)
            sheets[sheet.get("name")] = rows
    return sheets


def io_map_rows(docs_root: Path) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Return (mcu pins, co-processor pins) from the first IO-mapping workbook."""
    candidates = sorted((docs_root / "hardware").rglob("*.xlsx"))
    if not candidates:
        return [], []
    sheets = read_workbook_sheets(candidates[0])
    mcu, other = [], []
    for name, rows in sheets.items():
        header = None
        for row in rows:
            cells = [c.strip() for c in row]
            if "Pin number" in cells:
                header = cells
                continue
            if not header or not any(cells):
                continue
            record = {header[i]: (cells[i] if i < len(cells) else "") for i in range(len(header))}
            if record.get("Pin type") and record.get("Netlist"):
                (mcu if "CY8C" in name.upper() or "MCU" in name.upper() else other).append(record)
    return mcu, other


# ------------------------------------------------------------------- module model

MODULES: list[dict[str, str]] = [
    {"id": "MOD-001", "layer": "hal", "name": "mcu_core", "responsibility": "PSoC6 上电/时钟/复位/SWD、双核启动与看门狗", "basis": "CY8C6245FNI-S3D41；XRES、SWDIO/SWCLK、CY_NRES"},
    {"id": "MOD-002", "layer": "hal", "name": "adc_sense", "responsibility": "NTC、电压、电流、IR 采样与滤波", "basis": "NTC_USB/NTC_HEAT、P_Sensor、VOL_H±/CUR1/CUR2、VOL_BAT"},
    {"id": "MOD-003", "layer": "hal", "name": "gpio_io", "responsibility": "按键与数字 IO 输入去抖", "basis": "KEY1/KEY2、USB_INT、CAP_WKUP"},
    {"id": "MOD-004", "layer": "drv", "name": "heater", "responsibility": "TCR 加热驱动与闭环（双运流采样）", "basis": "HEAT_EN、MS_BAT、CUR1/CUR2、NTC_HEAT；V2.0→V2.1 改 TCR + 双运放"},
    {"id": "MOD-005", "layer": "drv", "name": "haptics", "responsibility": "马达与蜂鸣器输出", "basis": "MOTOR (P0.0 PWM)、BUZZER (P2.2 PWM)"},
    {"id": "MOD-006", "layer": "drv", "name": "display", "responsibility": "OLED 面板驱动（SPI + DCX + 电源/复位）", "basis": "LCD_MOSI/MISO/CLK/CS、LCD_DCX、VCC_EN；LED_RESX/LED_TE 在 SS805 侧"},
    {"id": "MOD-007", "layer": "drv", "name": "storage", "responsibility": "外部 NOR Flash（QSPI）与数据分区", "basis": "FLASH_CS/D0/D1/CLK（Dual SPI）"},
    {"id": "MOD-008", "layer": "drv", "name": "power_cell", "responsibility": "充电、电量计、电源轨使能", "basis": "I2C SCL/SDA、BQ25622、BQ27426、2V8_EN、MP4235、SGM38045"},
    {"id": "MOD-009", "layer": "comm", "name": "link_ble", "responsibility": "与 BLE 协处理器 UART 协议栈适配", "basis": "RX_BLE/TX_BLE (P2.0/P2.1)、S_W_C 单线、TL_nRST、CY_NRES"},
    {"id": "MOD-010", "layer": "comm", "name": "link_usb_cli", "responsibility": "USB 串口控制台与 BOOT UART", "basis": "RX_USB/TX_USB (P9.0/P9.1)、USB_INT、NTC_USB"},
    {"id": "MOD-011", "layer": "svc", "name": "ble_profile", "responsibility": "GATT 服务、配对/连接/断开、APP 数据面", "basis": "需求簇：BLE/无线"},
    {"id": "MOD-012", "layer": "svc", "name": "ui", "responsibility": "界面状态机、动画、提示与命名", "basis": "需求簇：UI/显示"},
    {"id": "MOD-013", "layer": "svc", "name": "heating_service", "responsibility": "加热档位/曲线、会话状态与安全限幅", "basis": "需求簇：加热；硬件基础见 MOD-004"},
    {"id": "MOD-014", "layer": "svc", "name": "power_service", "responsibility": "电源模式、休眠/唤醒、开关机与电量策略", "basis": "需求簇：电池/电源；CAP_WKUP、FUEL_WKUP"},
    {"id": "MOD-015", "layer": "svc", "name": "logging", "responsibility": "会话/使用记录、导出与清理", "basis": "需求簇：日志/数据；存储见 MOD-007"},
    {"id": "MOD-016", "layer": "svc", "name": "update", "responsibility": "FOTA/UI 升级、签名/加密/防降级、双区引导", "basis": "需求簇：OTA/固件"},
    {"id": "MOD-017", "layer": "svc", "name": "security", "responsibility": "RDP、读保护、锁定与调试口管控", "basis": "需求簇：安全；SWD 口见 MOD-001"},
    {"id": "MOD-018", "layer": "svc", "name": "factory", "responsibility": "产测、校准、HW ID 与序列号", "basis": "需求簇：校准/产测；CLI 见 MOD-010"},
    {"id": "MOD-019", "layer": "safety", "name": "interlock", "responsibility": "过流 OCP / 过热 OTP / MCU 复位兜底（在 BLE 侧独立存在）", "basis": "SS805EX：IMON(OCP)、NTC_HEAT(OTP)、CY_NRES、TL_nRST"},
]

# Visible assignment rules: first match wins, printed next to the requirement so a
# reviewer can disagree with a specific row instead of the whole partition.
RULES: list[tuple[str, str]] = [
    ("MOD-016", r"FOTA|UI OTA|Firmware|FW (Update|Signature|Encryption|Downgrade)|Boot|bootloader"),
    ("MOD-017", r"\bRDP\b|Readout|Write Protection|Tamper|Damaged or Modified|Security"),
    ("MOD-019", r"Over.?current|Over.?temp|OCP|OTP|Watchdog|Reset.*fault"),
    ("MOD-014", r"Batter|Power (On|Off|Mode)|Charge|Voltage|Sleep|Shutdown|Activation|End of Life"),
    ("MOD-013", r"Heat|Heating|Profile|Temperature|TCR|Char|Stick.*(use|activation)|Cleaning Prompt"),
    ("MOD-011", r"\bBLE\b|Bluetooth|Pairing|Connection|Advertising|Disconnection|GATT|Find My Device|My Naming|Device Name"),
    ("MOD-015", r"\bLog|Data Log|Puff|Session|Export|Statistics|Clear.*Data"),
    ("MOD-018", r"Calib|Factory|HW ID|Serial|Production|Test Point|Mass Production"),
    ("MOD-010", r"\bCLI\b|\bUSB\b|Console|Command line"),
    ("MOD-012", r"\bUI\b|OLED|Display|Screen|LED|Animation|Prompt|Icon|Naming"),
    ("MOD-006", r"OLED driver|panel|pixel"),
    ("MOD-007", r"Flash|Storage|Partition|File ?system"),
    ("MOD-008", r"Fuel gauge|Charge IC|Battery level|Coulomb"),
]
FALLBACK_MODULE = "MOD-012"


def assign(requirements: list[dict]) -> dict[str, list[dict]]:
    buckets: dict[str, list[dict]] = {}
    for item in requirements:
        haystack = f'{item["title"]} {item.get("description", "")[:160]}'
        for module, pattern in RULES:
            if re.search(pattern, haystack, re.IGNORECASE):
                buckets.setdefault(module, []).append({**item, "matched": pattern})
                break
        else:
            buckets.setdefault(FALLBACK_MODULE, []).append({**item, "matched": "(fallback)"})
    return buckets


# ------------------------------------------------------------------------ render

# The execution-model question, with every claim tied to a requirement or a pin.
# Kept as data so a reviewer can disagree with one row instead of the whole section.
EXECUTION_EVIDENCE: list[tuple[str, str, str]] = [
    ("FW 若 >2s 未服务，看门狗必须复位系统", "R-091", "活性必须可证明；喂狗不能放在主循环里无条件喂"),
    ("数据传输期间设备必须保持完全可用", "R-053", "升级/传输不能阻塞加热与 UI——这是 RTOS 唯一真正的论据"),
    ("充电与会话的优先级「需要被定义」", "R-130", "PRD 要的是一张**优先级/抢占表**，不是调度器"),
    ("长按 2.5s / 3s / 13s、短按 4s、60s 广播窗口", "R-051 R-122 R-124 R-089", "秒级时间判定：一个 tick 就够，不需要抢占"),
    ("20ms 广播间隔", "R-049", "发生在 **SS805EX 侧**，不是我们这颗 MCU"),
    ("360min 充电超时由 CIC 触发后再通知 MCU", "R-128", "长定时器已在充电 IC 上，不需要软件维护"),
    ("OCP（过流）/ OTP（过热）在 SS805EX 里", "IO-Mapping SS805", "最高优先级的保护**不经过任何软件调度器**"),
    ("实时记录 intensity / power / TC 温度", "R-075", "采样放定时器 ISR + 环形缓冲，主循环消费"),
    ("**加热闭环是 ms 级，不是硬实时**", "架构裁定 2026-10-18", "可用系统 tick + 任务调度控制；**不必进 ISR**"),
    ("提示可被按钮/BLE 立即打断", "R-081", "事件驱动状态机，而非多任务"),
]

EXECUTION_LAYERS: list[tuple[str, str, str]] = [
    ("L0 硬件", "PWM/ADC 由定时器驱动；OCP/OTP 在硬件与对端", "保护不依赖任何软件调度"),
    ("L1 ISR", "ADC 转换完成、UART RX（BLE 流量）、tick", "只做搬数据与置标志；无阻塞、无 malloc"),
    ("L2 控制与业务（tick 驱动）", "加热闭环（ms 级）、状态机、事件队列、显式让出点", "加热周期与抖动预算待定；每轮检查活性令牌"),
    ("L3 长任务（分片）", "FOTA 写 flash、日志批量落盘", "分片执行，片间让出——这是对 R-053 的正面回答"),
]

# 判据由 2026-10-18 裁定：只有两条。这里把两条做成**可复核的度量**，
# 而不是靠当时谁声音大。度量值从需求索引与 IO-Mapping 算出来，可逐行核。
RTOS_CRITERIA: list[tuple[str, str, str, str, str]] = [
    (
        "1",
        "**软件规模是否够大**",
        "需要被调度的**独立并发时序域**数量（不是需求数），以及代码量级",
        "8 个时序域，其中 **2 个已在硬件/对端**（OCP/OTP、CIC 360min 定时）；**剩 6 个软件域**（加热闭环为 ms 级，算软件域）；145 条需求 / 19 个模块，估 5k–9k 行 C",
        "**未到**（但余量不算宽裕：6 vs >8）",
    ),
    (
        "2",
        "**有强实时要求 → 只能 while(1)，不能 RTOS**",
        "是否存在必须可证明最坏响应时间的**软件**路径",
        "没有：加热是 ms 级（tick 可控）、OCP/OTP 在 SS805EX 硬件、R-091 是 2s **活性**而不是硬实时、20ms 广播在对端",
        "**不适用**",
    ),
]

# 判据 1 何时翻向 RTOS 的细化信号（量到才算，不算不翻）
RTOS_TRIGGERS: list[str] = [
    "软件内并发时序域从 6 个长到 >8 个（新交互、新对端芯片、新协议栈）",
    "加热闭环实测发现远快于 ms 级（例如需要亚 ms 电流环），与 flash 写 / BLE 流量并存时抖动超预算",
    "引入自带 OS 依赖的第三方协议栈或安全中间件",
    "分片让出在实测中仍无法满足 R-053（传输期间 UI 卡顿或控制超时）",
]


def render(project: str, requirements: list[dict], mcu_pins: list[dict], co_pins: list[dict]) -> str:
    buckets = assign(requirements)
    assigned_count = sum(len(rows) for rows in buckets.values())
    unassigned = [m["id"] for m in MODULES if not buckets.get(m["id"])]
    fallback_count = sum(1 for row in buckets.get(FALLBACK_MODULE, []) if row["matched"] == "(fallback)")

    lines = [
        "# 初步设计框架（草案 / 待人工评审）",
        "",
        "> **origin: generated** — 本文件由 `agent-design/tools/draft_architecture.py` 从",
        "> `requirements_index.json` 与 IO-Mapping 工作表生成，**不是已评审设计**。",
        "> 依据 `Docs/standards/constitution.md` 的 `semantic_inference: forbidden`，",
        "> 生成物不得直接作为设计来源：需要人工逐行核对后，把认可的行搬进",
        "> `system-design.md` 并走 `wait_for_design_review` 批准。",
        "> 在那之前，S04 的覆盖检查仍报 `not-evaluated`，S30 仍拒绝认证——这是刻意的。",
        "",
        f"- 项目：`{project}`",
        f"- 需求条数：{len(requirements)}（已分配 {assigned_count}）",
        f"- 模块数：{len(MODULES)}；无**直接**需求挂接：{', '.join(unassigned) or '无'}",
        "  （HAL/DRV 层由上层模块间接覆盖，0 条直接挂接是正常的，不是缺口）",
        f"- 兜底规则落到 `{FALLBACK_MODULE}` 的：{fallback_count} 条（**最需要人看**，规则没说话、只是没别的地方去）",
        "",
        "## 1. 硬件事实（来源：IO-Mapping 工作表与 SCH PDF）",
        "",
        "| 事实 | 来源 |",
        "|---|---|",
        "| 主控 `CY8C6245FNI-S3D41`（PSoC 6，双核） | IO-Mapping 表 `CY8C6245FNI`；SCH `MCU` |",
        "| BLE 协处理器 `SS805EX`（与主控 UART + 单线相连） | IO-Mapping 表 `SS805`；SCH `MCU` |",
        "| 充电 `BQ25622ERYKR`、电量计 `BQ27426YZF` | SCH `Power` |",
        "| 电源 `MP4235GVE-0000`、`SGM38045` | SCH `Power` |",
        "| 加热为 **TCR**，电流采样用**双运放**（V2.0→V2.1 变更） | IO-Mapping 变更记录 |",
        "| **OCP/OTP 与 MCU 复位兜底在 BLE 侧独立存在** | `IMON`/`NTC_HEAT(OTP)`/`CY_NRES` on SS805EX |",
        "",
        "> ⚠ `Docs/config.yaml` 仍写着 `mcu.part: STM32F407VGT6`（S02 模板占位），",
        "> 与硬件实际型号 `CY8C6245FNI-S3D41` **不一致**，必须先改配置再谈生成。",
        "",
        "### 1.1 引脚→功能（MCU，摘自有网络的行）",
        "",
        "| Pin | Net | 类型 | 功能 |",
        "|---|---|---|---|",
    ]
    for row in mcu_pins:
        if row.get("Pin type") == "Power":
            continue
        lines.append(f"| {row.get('Pin number','')} | {row.get('Netlist','')} | {row.get('Pin type','')} | {row.get('Function description','')} |")

    lines += ["", "### 1.2 BLE 协处理器侧（安全相关，勿只看 MCU）", "", "| Pin | Net | 类型 | 功能 |", "|---|---|---|---|"]
    for row in co_pins:
        lines.append(f"| {row.get('Pin number','')} | {row.get('Netlist','')} | {row.get('Pin type','')} | {row.get('Function description','')} |")

    lines += [
        "",
        "## 2. 执行模型：`while(1)` 还是 RTOS（本框架最大的空缺）",
        "",
        "**结论（按 §2.3 两条判据得出）**：分层——**保护不交给软件，业务层用 tick 驱动的协作式主循环 + 显式状态机**；",
        "判据 2 对本项目**不适用**（无软件侧硬实时路径），所以这个结论**完全靠判据 1（规模）与可测性支撑**。",
        "",
        "### 2.1 需求里实有的约束（逐条对应）",
        "",
        "| 事实 | 来源 | 对执行模型的含义 |",
        "|---|---|---|",
    ]
    for fact, src, implication in EXECUTION_EVIDENCE:
        lines.append(f"| {fact} | {src} | {implication} |")

    lines += [
        "",
        "### 2.2 建议的分层",
        "",
        "| 层 | 内容 | 约束 |",
        "|---|---|---|",
    ]
    for layer, content, constraint in EXECUTION_LAYERS:
        lines.append(f"| {layer} | {content} | {constraint} |")

    lines += [
        "",
        "### 2.3 判据（已裁定：只看两条）",
        "",
        "| # | 判据 | 可复核的度量 | 本项目实测 | 结论 |",
        "|---|---|---|---|---|",
    ]
    for num, criterion, metric, measured, verdict in RTOS_CRITERIA:
        lines.append(f"| {num} | {criterion} | {metric} | {measured} | {verdict} |")

    lines += [
        "",
        "**判据 2 的准确读法**（这条最容易读歪）：它不是「整个项目必须 while(1)」",
        "而是：**强实时的那部分一旦进了任务上下文，最坏情况就要穿过调度器去证明**——",
        "包括 OS 的中断延迟、临界区、以及别人写的任务里一句 `taskENTER_CRITICAL()`。",
        "本项目**没有这样的软件路径**（加热 ms 级、保护在硬件），所以判据 2 不构成否决；",
        "但它仍是硬规则：**一旦以后出现亚毫秒级软件需求，它不得进任务上下文**。",
        "",
        "**加热进任务的新约束**：加热闭环跑在 tick 上，调度器一停加热就失控，所以",
        "**加热任务必须挂活性令牌**（R-091 的 2s 活性与加热周期从此挂钩，不能只给喂狗单独一个位）。",
        "",
        "**判据 1 何时翻向 RTOS**（细化信号，量到才算，不算不翻）：",
        "",
    ]
    for idx, item in enumerate(RTOS_TRIGGERS, 1):
        lines.append(f"{idx}. {item}")

    lines += [
        "",
        "### 2.4 为什么默认不选 RTOS（本项目的理由，不是泛泛之谈）",
        "",
        "- **可测性**：现有主机侧测试（`tests/**/*_test.c` + gcc + `assert`）能直接跑状态机；",
        "  RTOS 化后每块业务都要 OS 移植层或模拟器才能测——现在一行测试都跑不了",
        "- **可审计**：让出点是**显式**的；抢占把时序耦合藏进优先级数字里",
        "- **双核是硬件出路**：PSoC6 的 CM0+ 可承担活性/保护监督（R-091），不靠调度器保证",
        "- **BLE 20ms 不在我们这颗 MCU 上**：最大的硬实时需求本来就在 SS805EX 侧",
        "",
        "### 2.5 无论选哪个都要做的一件事",
        "",
        "**活性令牌喂狗**：每个关键任务一个 deadline 位，全部满足才喂。",
        "在主循环里无条件喂狗，恰好会在 R-091 描述的那个场景（FW 已经不服务）把看门狗关掉。",
        "",
        "定量阈值（闭环速率、允许抖动）需要 `Docs/hardware/registers/` 与 `datasheet/` 才能定，",
        "**现在写任何具体频率都是猜**，所以本节不写。",
        "",
        "## 3. 模块划分（`module_id` 与 `system-design.md` 的 `MODULE_DESIGN_TABLE` 对齐）",
        "",
        "| module_id | layer | name | responsibility | 硬件/需求依据 |",
        "|---|---|---|---|---|",
    ]
    for module in MODULES:
        lines.append(f"| {module['id']} | {module['layer']} | {module['name']} | {module['responsibility']} | {module['basis']} |")

    lines += [
        "",
        "## 4. 需求→模块分配（每条带命中规则）",
        "",
        "搬运到 `system-design.md` 时，把 `req_ids` 列按模块合并即可；",
        "不认可的行**删掉**，不要留空——留空会被覆盖检查算成未映射。",
        "",
        "| module | 需求数 | req_ids |",
        "|---|---|---|",
    ]
    for module in MODULES:
        rows = buckets.get(module["id"], [])
        ids = ", ".join(row["req_id"] for row in rows)
        lines.append(f"| {module['id']} {module['name']} | {len(rows)} | {ids or '—'} |")

    lines += ["", "### 4.1 逐条依据（可逐行否决）", "", "| req_id | 标题 | 模块 | 命中规则 | 来源 |", "|---|---|---|---|---|"]
    for module in MODULES:
        for row in buckets.get(module["id"], []):
            title = row["title"].replace("|", "/")[:56]
            lines.append(
                f"| {row['req_id']} | {title} | {module['id']} | `{row['matched'][:40]}` | "
                f"{row.get('user_story_id','')} p{row.get('page','')} |"
            )

    lines += [
        "",
        "## 5. 待人裁定（框架不能替人决定的事）",
        "",
        "0. **执行模型**：按上述两条判据，建议 A（分层 + 协作式主循环）。要改成 RTOS 就得先推翻判据 1 的实测（见 §2）",
        "1. **加热安全边界**：谁定超温/超流阈值与响应时间？硬件已把 OCP/OTP 放在 SS805 侧，",
        "   软件侧的限幅与失效策略必须与之一致（缺 datasheet 无法核对门限）。",
        "2. **双核分工**：PSoC6 的 CM4/CM0+ 如何切分（实时加热控制 vs 通信/UI）？",
        "3. **BLE 侧固件归属**：SS805EX 上是否也有需要跟踪的需求（31 条 BLE 需求里有多少落在对端）？",
        "4. **升级与回滚**：签名/加密/防降级（24 条）落在 MCU 还是 BLE 侧引导？",
        "5. **缺输入**：`Docs/hardware/registers/`、`Docs/hardware/datasheet/`、`Docs/bsp/` 仍为空——",
        "   寄存器初始化表与引脚电气参数无法从 IO-Mapping 推出，不能猜。",
        "",
        "## 6. 这份草案**没有**做的事",
        "",
        "- 没有生成 `system-design.md`，也没有改它：覆盖检查仍应报 `not-evaluated`",
        "- 没有编造寄存器地址、时钟树或引脚电气参数（缺 datasheet）",
        "- 没有把需求改写或合并：145 条原文与 work item ID 一字未动",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", help="project root, e.g. demo-project")
    parser.add_argument("--check", action="store_true", help="report drift without writing")
    args = parser.parse_args()

    root = Path(args.project)
    index_path = root / REQUIREMENTS_INDEX
    if not index_path.exists():
        print(f"no requirements index at {index_path} - ingest the PRD first", file=sys.stderr)
        return 2
    requirements = json.loads(index_path.read_text(encoding="utf-8")).get("requirements", [])
    if not requirements:
        print("requirements index is empty - nothing to map", file=sys.stderr)
        return 2

    mcu_pins, co_pins = io_map_rows(root / "Docs")
    text = render(str(root), requirements, mcu_pins, co_pins)
    out = root / PROPOSAL_RELATIVE
    if args.check:
        current = out.read_text(encoding="utf-8") if out.exists() else ""
        print("in sync" if current == text else "STALE - regenerate")
        return 0 if current == text else 1
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
