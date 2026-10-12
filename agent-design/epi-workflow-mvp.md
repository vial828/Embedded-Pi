# EPI Workflow MVP Architecture

This diagram shows how the interactive `pi`/`epi` CLI cooperates with the resumable workflow engine.

```mermaid
flowchart LR
  subgraph Left[Current runtime architecture]
    direction TB
    U[User]
    P[pi / epi CLI\nInteractive frontend\nMVP: single entry\nauto resume\nready / approve / revise]
    W[WorkflowRunner\nState machine backend]
    S[(Docs/ai-generation/workflow/state.json)]
    U -->|cmds| P -->|run| W -->|state| S
    W -->|status| P -->|step| U
  end

  subgraph Middle[Inputs / outputs]
    direction TB
    X[External documents\nDocs/prd, Docs/standards, Docs/hardware, Docs/bsp]
    J[(normalized JSON\nrequirements_index.json)]
    L[(Docs/ai-generation/knowledge/*)]
    D[(Docs/ai-generation/fw-architecture/*)]
    C[(coding)]
    G[(debug)]
    T[(test)]
    B[(bug report / bug fix)]
    R[(Docs/ai-generation/reports/*)]
    X -->|docs| W -->|json| J
    J -->|knowledge| L
    J -->|design| D
    L -->|fw arch| D
    D -->|code| C
    D -->|debug| G
    D -->|test| T
    D -->|bugs| B
    C -->|run| G -->|run| T -->|report| R
    R -->|find issues| B
    B -->|fix| C
  end

  subgraph Right[Future evolution path]
    direction TB
    F1[split engine]
    F2[optional UI / TUI / service]
    F3[keep state + artifacts]
    F1 --> F2 --> F3
  end

  W -.->|future| F1
  F1 -.->|replace| P
```

## Responsibilities

- **pi / epi CLI**: renders prompts, shows status, accepts user input.
- **WorkflowRunner**: owns the phase machine, validates readiness, and advances only in order.
- **state.json**: shared resume point between runs.
- **Artifacts**: normalized knowledge, design outputs, and reports.

## Gate points

1. **External documents ready**: user types `ready`.
2. **Design approved**: user types `approve`.
3. **Design needs revision**: user types `revise` and workflow pauses.
