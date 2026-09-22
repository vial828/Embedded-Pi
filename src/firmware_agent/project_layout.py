from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


DOCS_ROOT = "Docs"
SYSTEM_DESIGN_REL_PATH = f"{DOCS_ROOT}/ai-generation/fw-architecture/system-design/system-design.md"

REQUIRED_DIRS = [
    f"{DOCS_ROOT}/prd",
    f"{DOCS_ROOT}/hardware/schematic",
    f"{DOCS_ROOT}/hardware/datasheet",
    f"{DOCS_ROOT}/hardware/registers",
    f"{DOCS_ROOT}/bsp",
    f"{DOCS_ROOT}/standards",
    f"{DOCS_ROOT}/toolchain",
    f"{DOCS_ROOT}/ai-generation",
    f"{DOCS_ROOT}/ai-generation/fw-architecture",
    f"{DOCS_ROOT}/ai-generation/fw-architecture/architecture",
    f"{DOCS_ROOT}/ai-generation/fw-architecture/system-design",
    f"{DOCS_ROOT}/ai-generation/fw-architecture/module-design",
    f"{DOCS_ROOT}/ai-generation/register-init",
    f"{DOCS_ROOT}/ai-generation/dev-environment",
    f"{DOCS_ROOT}/ai-generation/todo",
    f"{DOCS_ROOT}/ai-generation/knowledge",
    f"{DOCS_ROOT}/ai-generation/memory",
]

SYSTEM_DESIGN_TEMPLATE = """# Embedded-Pi System Design Schema

## SCHEMA
- schema_id: EPI-SD-1.0
- schema_version: 1.0.0
- generated_at_utc: N/A
- generator: N/A

## AI_USAGE_CONSTRAINTS
- parser_mode: strict
- semantic_inference: forbidden
- source_of_truth: table_and_key_value_only
- unknown_value_policy: use_N/A
- parse_error_policy: stop_and_report
- driver_init_location: Docs/ai-generation/register-init/register_init_table.json
- driver_init_policy: excluded_from_fw_architecture

## PROJECT_META
- project_name: N/A
- mcu_part: N/A
- toolchain: gcc-arm-none-eabi
- os: none

## LAYER_ARCHITECTURE_GRAPH
![layer-architecture-fallback](../architecture/architecture.svg)

> Graph source: `layer-architecture.mmd` (kept out of Markdown to avoid unstable preview rendering).

## MODULE_DESIGN_TABLE
| module_id | layer | name | responsibility | input_if | output_if | depends_on | req_ids |
|---|---|---|---|---|---|---|---|
| MOD-001 | module | N/A | N/A | N/A | N/A | N/A | R-001 |

## TASK_TABLE
| task_id | name | period_ms | priority | stack_bytes | core_affinity | entry_fn | req_ids |
|---|---|---:|---:|---:|---|---|---|
| TASK-001 | N/A | 10 | 5 | 1024 | N/A | task_main | R-001 |

## INTERFACE_TABLE
| if_id | provider | consumer | type | name | direction | payload | timing | req_ids |
|---|---|---|---|---|---|---|---|---|
| IF-001 | MOD-001 | TASK-001 | queue | sensor_q | in | N/A | 10ms | R-001 |

## REGISTER_INIT_TABLE
| item_id | domain | peripheral | register | field | value | access | init_order | source_req | note |
|---|---|---|---|---|---|---|---:|---|---|
| REG-001 | clock | RCC | N/A | N/A | N/A | RW | 1 | R-001 | N/A |

## CLOCK_CONFIG_TABLE
| clock_id | source | target | value | tolerance | source_req | note |
|---|---|---|---|---|---|---|
| CLK-001 | HSE | SYSCLK | 168MHz | ±1% | R-001 | N/A |

## INTERRUPT_TABLE
| irq_id | irqn | preempt_priority | sub_priority | handler | trigger | source_req | note |
|---|---|---:|---:|---|---|---|---|
| IRQ-001 | USART1_IRQn | 5 | 0 | USART1_IRQHandler | RXNE | R-001 | N/A |

## WATCHDOG_TABLE
| wdg_id | type | timeout_ms | feed_point | reset_action | source_req | note |
|---|---|---:|---|---|---|---|
| WDG-001 | IWDG | 30000 | main_loop | system_reset | R-001 | N/A |

## DEV_ENVIRONMENT
| env_id | component | version | install_method | verify_cmd | note |
|---|---|---|---|---|---|
| ENV-001 | vscode | N/A | manual | code --version | N/A |
| ENV-002 | arm-none-eabi-gcc | N/A | package | arm-none-eabi-gcc --version | N/A |

## TRACEABILITY_LINKS
| link_id | req_id | artifact_type | artifact_ref | status |
|---|---|---|---|---|
| TR-001 | R-001 | module | MOD-001 | planned |

## VALIDATION_STATUS
| check_id | check_name | status | details |
|---|---|---|---|
| VAL-001 | schema_structure | pending | N/A |
"""

REQUIRED_FILES = {
    f"{DOCS_ROOT}/config.yaml": """project:\n  name: \"demo-project\"\n  description: \"\"\n\nmcu:\n  part: \"STM32F407VGT6\"\n\ntoolchain:\n  compiler: \"arm-none-eabi-gcc\"\n\npaths:\n  registers: \"./hardware/registers/\"\n  bsp: \"./bsp/\"\n  schematic: \"./hardware/schematic/\"\n  coding_standard: \"./standards/coding_standard.md\"\n  process_spec: \"./standards/process_spec.yaml\"\n\ncontext:\n  max_tokens: 3000\n  constitution_file: \"./standards/constitution.md\"\n\nllm:\n  provider: \"openai_compatible\"\n  model: \"Qwen3.8-27B\"\n  max_tokens: 8192\n  temperature: 0.1\n""",
    f"{DOCS_ROOT}/prd/requirements.md": "# Requirements\n",
    f"{DOCS_ROOT}/hardware/pin_map.json": "{}\n",
    f"{DOCS_ROOT}/standards/coding_standard.md": "# Coding Standard\n",
    f"{DOCS_ROOT}/standards/process_spec.yaml": "phases: []\n",
    f"{DOCS_ROOT}/standards/constitution.md": "## Hard Rules\n- Verify generated code before claiming success.\n",
    f"{DOCS_ROOT}/toolchain/build.yaml": "compiler: arm-none-eabi-gcc\n",
    SYSTEM_DESIGN_REL_PATH: SYSTEM_DESIGN_TEMPLATE,
    f"{DOCS_ROOT}/ai-generation/fw-architecture/system-design/layer-architecture.mmd": "flowchart TB\n  subgraph driver\n    D1[GPIO/UART/I2C/SPI]\n  end\n  subgraph middleware\n    M1[Protocol/Service]\n  end\n  subgraph os\n    O1[Kernel/None]\n  end\n  subgraph task\n    T1[Task Sensor]\n    T2[Task Comms]\n  end\n  subgraph module\n    MD1[App Modules]\n  end\n\n  D1 --> M1 --> O1 --> T1\n  O1 --> T2\n  T1 --> MD1\n  T2 --> MD1\n",
    f"{DOCS_ROOT}/ai-generation/system-design.compiled.json": "{}\n",
    f"{DOCS_ROOT}/ai-generation/memory/candidate_memory.json": "{\n  \"version\": \"0.1\",\n  \"candidates\": []\n}\n",
    f"{DOCS_ROOT}/ai-generation/fw-architecture/README.md": "# FW Architecture Outputs\n\nGenerated artifacts from system-design.md parsing/compilation.\n",
    f"{DOCS_ROOT}/ai-generation/fw-architecture/architecture/architecture.mmd": """flowchart TB\n  subgraph driver\n    D1[Driver APIs (no init table data)]\n  end\n  subgraph middleware\n    M1[Protocol/Service]\n  end\n  subgraph os\n    O1[Kernel/None]\n  end\n  subgraph task\n    T1[Task Sensor]\n    T2[Task Comms]\n  end\n  subgraph module\n    MD1[App Modules]\n  end\n\n  D1 --> M1 --> O1 --> T1\n  O1 --> T2\n  T1 --> MD1\n  T2 --> MD1\n""",
    f"{DOCS_ROOT}/ai-generation/fw-architecture/architecture/architecture.svg": """<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"1000\" height=\"620\" viewBox=\"0 0 1000 620\"><rect x=\"0\" y=\"0\" width=\"1000\" height=\"620\" fill=\"#ffffff\"/><text x=\"30\" y=\"40\" font-size=\"22\" font-family=\"Segoe UI, Arial\" fill=\"#1f2a44\">FW Architecture (Driver init excluded; see register-init table)</text><rect x=\"70\" y=\"100\" width=\"300\" height=\"70\" fill=\"#eef3ff\" stroke=\"#4a5fa3\" stroke-width=\"2\"/><text x=\"115\" y=\"145\" font-size=\"20\" font-family=\"Segoe UI, Arial\" fill=\"#1f2a44\">GPIO / UART / I2C / SPI</text></svg>\n""",
    f"{DOCS_ROOT}/ai-generation/fw-architecture/module-design/module-design.md": """# Module Design\n\n| module_id | layer | name | responsibility | input_if | output_if | depends_on | req_ids |\n|---|---|---|---|---|---|---|---|\n| MOD-001 | module | N/A | N/A | N/A | N/A | N/A | R-001 |\n\n> Driver initialization is excluded here and must be defined in register-init artifacts.\n""",
    f"{DOCS_ROOT}/ai-generation/register-init/README.md": "# Register Init Outputs\n\nGenerated register initialization artifacts (single source for driver init values).\n",
    f"{DOCS_ROOT}/ai-generation/dev-environment/README.md": "# Dev Environment Outputs\n\nGenerated toolchain/environment artifacts.\n",
    f"{DOCS_ROOT}/ai-generation/knowledge/rules.json": "{\n  \"version\": \"0.1\",\n  \"rules\": []\n}\n",
    f"{DOCS_ROOT}/ai-generation/knowledge/requirements_index.json": "{\n  \"version\": \"0.1\",\n  \"requirements\": []\n}\n",
    f"{DOCS_ROOT}/ai-generation/knowledge/register_index.json": "{\n  \"version\": \"0.1\",\n  \"register_items\": []\n}\n",
    f"{DOCS_ROOT}/ai-generation/knowledge/artifact_graph.json": "{\n  \"version\": \"0.1\",\n  \"nodes\": [],\n  \"edges\": []\n}\n",
    f"{DOCS_ROOT}/ai-generation/todo/pending.md": "# Pending Items\n\n- [ ] Add additional compile-time checks\n",
}


class FilePolicy(str, Enum):
    CREATE_ONLY = "create_only"
    SYNC_MANAGED = "sync_managed"


# User-authored artifacts should never be overwritten during regular epi runs.
USER_AUTHORED_FILE_POLICIES: dict[str, FilePolicy] = {
    f"{DOCS_ROOT}/config.yaml": FilePolicy.CREATE_ONLY,
    f"{DOCS_ROOT}/prd/requirements.md": FilePolicy.CREATE_ONLY,
    f"{DOCS_ROOT}/hardware/pin_map.json": FilePolicy.CREATE_ONLY,
    f"{DOCS_ROOT}/standards/coding_standard.md": FilePolicy.CREATE_ONLY,
    f"{DOCS_ROOT}/standards/process_spec.yaml": FilePolicy.CREATE_ONLY,
    f"{DOCS_ROOT}/standards/constitution.md": FilePolicy.CREATE_ONLY,
    f"{DOCS_ROOT}/toolchain/build.yaml": FilePolicy.CREATE_ONLY,
    SYSTEM_DESIGN_REL_PATH: FilePolicy.CREATE_ONLY,
}


def _resolve_file_policy(rel: str) -> FilePolicy:
    """All ai-generation scaffolds are managed and always synced, except authored schema source."""
    if rel in USER_AUTHORED_FILE_POLICIES:
        return FilePolicy.CREATE_ONLY

    if rel.startswith(f"{DOCS_ROOT}/ai-generation/"):
        return FilePolicy.SYNC_MANAGED

    return FilePolicy.CREATE_ONLY

BSP_MARKER_ALTERNATIVES = [f"{DOCS_ROOT}/bsp/Makefile", f"{DOCS_ROOT}/bsp/CMakeLists.txt"]


@dataclass
class LayoutReport:
    created_dirs: list[str] = field(default_factory=list)
    created_files: list[str] = field(default_factory=list)
    updated_files: list[str] = field(default_factory=list)
    existing: list[str] = field(default_factory=list)


@dataclass
class LayoutRequirement:
    key: str
    kind: str
    exists: bool
    detail: str = ""


def inspect_project_layout(project_dir: Path) -> list[LayoutRequirement]:
    items: list[LayoutRequirement] = []

    for rel in REQUIRED_DIRS:
        items.append(LayoutRequirement(key=rel, kind="dir", exists=(project_dir / rel).exists()))

    for rel in REQUIRED_FILES:
        items.append(LayoutRequirement(key=rel, kind="file", exists=(project_dir / rel).exists()))

    found_bsp = [rel for rel in BSP_MARKER_ALTERNATIVES if (project_dir / rel).exists()]
    items.append(
        LayoutRequirement(
            key=f"{DOCS_ROOT}/bsp/{{Makefile|CMakeLists.txt}} (optional)",
            kind="file(any)",
            exists=True,
            detail=", ".join(found_bsp) if found_bsp else "not required",
        )
    )

    return items


def ensure_project_layout(project_dir: Path) -> LayoutReport:
    report = LayoutReport()
    project_dir.mkdir(parents=True, exist_ok=True)

    for rel in REQUIRED_DIRS:
        p = project_dir / rel
        if p.exists():
            report.existing.append(rel)
        else:
            p.mkdir(parents=True, exist_ok=True)
            report.created_dirs.append(rel)

    for rel, content in REQUIRED_FILES.items():
        p = project_dir / rel
        policy = _resolve_file_policy(rel)
        if p.exists():
            if policy == FilePolicy.SYNC_MANAGED:
                current = p.read_text(encoding="utf-8")
                if current != content:
                    p.write_text(content, encoding="utf-8")
                    report.updated_files.append(rel)
                else:
                    report.existing.append(rel)
            else:
                report.existing.append(rel)
        else:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            report.created_files.append(rel)

    # BSP 子结构不做强约束：不同芯片厂商/SDK 目录形态差异很大。
    return report


def reset_system_design_template(project_dir: Path) -> Path:
    """Force-regenerate the canonical schema template file."""
    target = project_dir / SYSTEM_DESIGN_REL_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(SYSTEM_DESIGN_TEMPLATE, encoding="utf-8")
    return target
