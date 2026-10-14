# EPI Agent Design Hub

该目录用于集中管理 **EPI 本体开发设计**（不是 demo-project 产物）。

## 内容

- `epi-dev-plan-and-log.md`：**当前执行计划 + 工作日志（唯一进度入口，先看这个）**
- `firmware-agent-dev-plan.md`：主开发计划书（已同步副本，目标态；与执行计划的差异以执行计划为准）
- `epi-dev-slices-overview.md`：全量开发切片 + 总体架构大图 + 依赖关系
- `epi-risk-register.md`：按切片风险登记与缓解策略
- `epi-llm-workflow-standard.md`：LLM 使用标准流（作用域 / 用前用中用后 / 字源唯一货币）
- `worklog-2026-10-13.md`：单日工作笔记（后续日志并入 `epi-dev-plan-and-log.md` §7）

## 约定

1. 本目录只放“EPI 开发设计文档”，不放 demo 输出。
2. 所有切片以 `Sxx` 编号统一管理。
3. 风险以 `R-Sxx-xx` 编号，需可追踪到切片。
4. 结构变更先改本目录文档，再落代码。

## Mermaid 渲染规范（开发文档）

1. **大图拆分规则**：单张 Mermaid 图节点数 > 20 时，拆成 2~3 张子图（建议按“主流程 / 子系统”拆分）。
2. **统一高对比样式**：每张图建议使用 `%%{init: {'theme':'base', ...}}%%`，并统一 `linkStyle default stroke:#2563EB,stroke-width:2.2px`。
