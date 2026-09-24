# EPI Agent Design Hub

该目录用于集中管理 **EPI 本体开发设计**（不是 demo-project 产物）。

## 内容

- `firmware-agent-dev-plan.md`：主开发计划书（已同步副本）
- `epi-dev-slices-overview.md`：全量开发切片 + 总体架构大图 + 依赖关系
- `epi-risk-register.md`：按切片风险登记与缓解策略

## 约定

1. 本目录只放“EPI 开发设计文档”，不放 demo 输出。
2. 所有切片以 `Sxx` 编号统一管理。
3. 风险以 `R-Sxx-xx` 编号，需可追踪到切片。
4. 结构变更先改本目录文档，再落代码。

## Mermaid 渲染规范（开发文档）

1. **大图拆分规则**：单张 Mermaid 图节点数 > 20 时，拆成 2~3 张子图（建议按“主流程 / 子系统”拆分）。
2. **统一高对比样式**：每张图建议使用 `%%{init: {'theme':'base', ...}}%%`，并统一 `linkStyle default stroke:#2563EB,stroke-width:2.2px`。
