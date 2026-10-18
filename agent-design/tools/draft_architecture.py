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
        "## 2. 模块划分（`module_id` 与 `system-design.md` 的 `MODULE_DESIGN_TABLE` 对齐）",
        "",
        "| module_id | layer | name | responsibility | 硬件/需求依据 |",
        "|---|---|---|---|---|",
    ]
    for module in MODULES:
        lines.append(f"| {module['id']} | {module['layer']} | {module['name']} | {module['responsibility']} | {module['basis']} |")

    lines += [
        "",
        "## 3. 需求→模块分配（每条带命中规则）",
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

    lines += ["", "### 3.1 逐条依据（可逐行否决）", "", "| req_id | 标题 | 模块 | 命中规则 | 来源 |", "|---|---|---|---|---|"]
    for module in MODULES:
        for row in buckets.get(module["id"], []):
            title = row["title"].replace("|", "/")[:56]
            lines.append(
                f"| {row['req_id']} | {title} | {module['id']} | `{row['matched'][:40]}` | "
                f"{row.get('user_story_id','')} p{row.get('page','')} |"
            )

    lines += [
        "",
        "## 4. 待人裁定（框架不能替人决定的事）",
        "",
        "1. **加热安全边界**：谁定超温/超流阈值与响应时间？硬件已把 OCP/OTP 放在 SS805 侧，",
        "   软件侧的限幅与失效策略必须与之一致（缺 datasheet 无法核对门限）。",
        "2. **双核分工**：PSoC6 的 CM4/CM0+ 如何切分（实时加热控制 vs 通信/UI）？",
        "3. **BLE 侧固件归属**：SS805EX 上是否也有需要跟踪的需求（31 条 BLE 需求里有多少落在对端）？",
        "4. **升级与回滚**：签名/加密/防降级（24 条）落在 MCU 还是 BLE 侧引导？",
        "5. **缺输入**：`Docs/hardware/registers/`、`Docs/hardware/datasheet/`、`Docs/bsp/` 仍为空——",
        "   寄存器初始化表与引脚电气参数无法从 IO-Mapping 推出，不能猜。",
        "",
        "## 5. 这份草案**没有**做的事",
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
