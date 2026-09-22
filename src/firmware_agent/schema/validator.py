from __future__ import annotations

import re

REQUIRED_SECTIONS = [
    "SCHEMA",
    "AI_USAGE_CONSTRAINTS",
    "PROJECT_META",
    "LAYER_ARCHITECTURE_GRAPH",
    "MODULE_DESIGN_TABLE",
    "TASK_TABLE",
    "INTERFACE_TABLE",
    "REGISTER_INIT_TABLE",
    "CLOCK_CONFIG_TABLE",
    "INTERRUPT_TABLE",
    "WATCHDOG_TABLE",
    "DEV_ENVIRONMENT",
    "TRACEABILITY_LINKS",
    "VALIDATION_STATUS",
]

EXPECTED_HEADERS = {
    "MODULE_DESIGN_TABLE": ["module_id", "layer", "name", "responsibility", "input_if", "output_if", "depends_on", "req_ids"],
    "TASK_TABLE": ["task_id", "name", "period_ms", "priority", "stack_bytes", "core_affinity", "entry_fn", "req_ids"],
    "INTERFACE_TABLE": ["if_id", "provider", "consumer", "type", "name", "direction", "payload", "timing", "req_ids"],
    "REGISTER_INIT_TABLE": ["item_id", "domain", "peripheral", "register", "field", "value", "access", "init_order", "source_req", "note"],
    "CLOCK_CONFIG_TABLE": ["clock_id", "source", "target", "value", "tolerance", "source_req", "note"],
    "INTERRUPT_TABLE": ["irq_id", "irqn", "preempt_priority", "sub_priority", "handler", "trigger", "source_req", "note"],
    "WATCHDOG_TABLE": ["wdg_id", "type", "timeout_ms", "feed_point", "reset_action", "source_req", "note"],
    "DEV_ENVIRONMENT": ["env_id", "component", "version", "install_method", "verify_cmd", "note"],
    "TRACEABILITY_LINKS": ["link_id", "req_id", "artifact_type", "artifact_ref", "status"],
    "VALIDATION_STATUS": ["check_id", "check_name", "status", "details"],
}

LAYER_ENUM = {"driver", "middleware", "os", "task", "module"}
REQ_RE = re.compile(r"^R-\d+$")


def validate_parsed(parsed: dict) -> list[str]:
    errors: list[str] = []

    present = set(parsed.get("sections", []))
    for section in REQUIRED_SECTIONS:
        if section not in present:
            errors.append(f"missing section: {section}")

    if not parsed.get("LAYER_ARCHITECTURE_GRAPH", {}).get("mermaid"):
        errors.append("LAYER_ARCHITECTURE_GRAPH mermaid block missing")

    for sec, headers in EXPECTED_HEADERS.items():
        got = parsed.get(sec, {}).get("headers", [])
        if got != headers:
            errors.append(f"{sec} headers mismatch: expected {headers}, got {got}")

    for row in parsed.get("MODULE_DESIGN_TABLE", {}).get("rows", []):
        layer = row.get("layer", "")
        if layer != "N/A" and layer not in LAYER_ENUM:
            errors.append(f"MODULE_DESIGN_TABLE invalid layer: {layer}")

    for sec in ["MODULE_DESIGN_TABLE", "TASK_TABLE", "INTERFACE_TABLE", "REGISTER_INIT_TABLE", "CLOCK_CONFIG_TABLE", "INTERRUPT_TABLE", "WATCHDOG_TABLE"]:
        req_key = "req_ids" if sec in {"MODULE_DESIGN_TABLE", "TASK_TABLE", "INTERFACE_TABLE"} else "source_req"
        for row in parsed.get(sec, {}).get("rows", []):
            val = row.get(req_key, "N/A")
            if val == "N/A":
                continue
            parts = [p.strip() for p in val.split(",")]
            for p in parts:
                if not REQ_RE.match(p):
                    errors.append(f"{sec} invalid requirement id: {p}")

    return errors
