# Embedded-Pi System Design Schema

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
