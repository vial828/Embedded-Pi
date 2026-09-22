# EPI 切片风险登记表（Risk Register）

## 风险等级说明

- 影响（Impact）：H / M / L
- 概率（Likelihood）：H / M / L
- 优先级（Priority）：P1 > P2 > P3

## 风险清单（按切片）

| Risk ID | Slice | 风险描述 | Impact | Likelihood | Priority | 触发信号 | 缓解措施 |
|---|---|---|---|---|---|---|---|
| R-S05-01 | S05 parser | Markdown 方言差异导致解析失败 | M | H | P1 | 同模板不同环境结果不一致 | 严格固定模板；解析器只支持白名单语法 |
| R-S06-01 | S06 validator | 规则过严导致可用性下降 | M | M | P2 | 频繁误报 fail | 区分 error/warn 两级；错误信息可定位到节/列 |
| R-S07-01 | S07 compiler | 输出 JSON 非确定性 | H | M | P1 | 相同输入多次输出 diff | 排序稳定化；统一格式化；移除时间噪声字段 |
| R-S08-01 | S08 ingestion | 标准文档抽取 source_id 不完整 | H | M | P1 | 候选记忆无法通过白名单校验 | 先定义 source_id 生成规范；抽取失败回退人工确认 |
| R-S11-01 | S11 graph | artifact_graph 不完整导致“跨模块”误判 | H | M | P1 | 晋升判断与人工结论偏差大 | 最小图先做 file/module 级，再迭代 function/test 级 |
| R-S12-01 | S12 short memory | 短记忆膨胀，挤占上下文预算 | M | M | P2 | token 超限、信息截断 | 强制字段上限 + 摘要策略 |
| R-S13-01 | S13 long memory | 长记忆污染（错误决策固化） | H | M | P1 | 后续多任务重复出现同类错误 | 加入冲突检测与撤销机制 |
| R-S15-01 | S15 promotion | 晋升规则误判（错收/漏收） | H | M | P1 | recall 质量显著下降 | 加灰区队列 + 人工审批开关 |
| R-S17-01 | S17 assembler | 上下文召回不足导致任务失败 | H | M | P1 | 任务重试率升高 | 失败后扩大召回窗口重试 |
| R-S19-01 | S19 state machine | 状态转移死循环 | H | L | P2 | 重试次数异常、无法推进 phase | 最大重试上限 + 熔断状态 |
| R-S22-01 | S22 compiler verify | 编译环境差异导致假失败 | M | M | P2 | 本地过 CI 不过 | 工具链版本锁定与环境快照 |
| R-S24-01 | S24 simulator | 仿真覆盖不足导致假通过 | H | M | P1 | 上板失败但仿真通过 | 提升断言密度；引入 HIL 阶段 |
| R-S30-01 | S30 quality gates | 门禁定义过宽无法拦截低质输出 | H | M | P1 | 缺陷逃逸率高 | 门禁指标量化（编译、覆盖、追溯） |
| R-S31-01 | S31 CI matrix | Win/Linux 行为不一致 | M | M | P2 | 单平台通过双平台失败 | 平台抽象层 + matrix 回归基线 |

---

## 高优先级行动（P1）

1. 优先完成 S08/S11/S15（知识标准化 + 图 + 晋升判定）。
2. 在 S17 前完成基础 long-memory 质量保护（冲突检测）。
3. 在 S30 定义硬门禁阈值并接入 CI（S31）。

---

## 每周风险复盘模板

```markdown
### Week X Risk Review
- 新增风险：
- 已关闭风险：
- P1 风险状态：
- 触发信号统计：
- 下周缓解动作：
```
