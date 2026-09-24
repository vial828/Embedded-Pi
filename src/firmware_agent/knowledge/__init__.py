from firmware_agent.slices.S08_Standards_Ingestion.standards_ingestion import ingest_standards
from firmware_agent.slices.S09_PRD_Ingestion.prd_ingestion import ingest_prd
from firmware_agent.slices.S10_REGS_Ingestion.regs_ingestion import ingest_registers
from firmware_agent.slices.S11_Artifact_Graph.artifact_graph import build_artifact_graph

__all__ = [
    "ingest_standards",
    "ingest_prd",
    "ingest_registers",
    "build_artifact_graph",
]
