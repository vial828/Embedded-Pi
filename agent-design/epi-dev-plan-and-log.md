# EPI 开发计划（兼工作日志）

> 唯一进度入口。§0–§6 是计划与契约（改动需说明理由），§7 是工作日志（只追加，最新在上）。

## 术语（统一用词，禁用同义词）

| 术语 | 英文 | 指代 | 禁用同义词 |
|---|---|---|---|
| **架构** | architecture | 模块 / 任务 / 寄存器初始化的结构，产物是 `system-design.md` 里的架构表 | 设计（指架构时）、design doc、体系结构 |
| **工作流** | workflow | `init → wait_for_external_files → ingest → wait_for_design_review → generate → test → done` 的端到端执行 | **全栈、骨架、walking skeleton、链路、pipeline、端到端链路** |

**两条例外**：

1. **文件名与代码标识符不改**：`system-design.md`、`S04_System_Design_Generation`、`wait_for_design_review`、`compile_system_design()` 一律保留原样，中文行文里称「架构」。
2. **`firmware-agent-dev-plan.md` / `epi-dev-slices-overview.md` 里的「工程骨架」「结构骨架」「状态机是骨架」是另一个概念**（project / driver skeleton），不在禁用范围内，也不做批量替换。

「LLM 使用标准流」（`epi-llm-workflow-standard.md`）指**治理规范**，不是本文件说的「工作流」，两者不要混用。


## 0. 变更记录

| 日期 | 变更 |
|---|---|
| 2026-10-13 | **计划变更：工作流优先**。PRD 解析冻结在"宪法合规的最小归一化"；优先打通 PRD→架构→生成→编译→测试。昨天定稿的深度解析方案降级为 §5 **伏笔**，是否采用取决于届时讨论 |
| 2026-10-13 | 生成物被反复清空已修（`9c0dd11`）；PRD 解析质量已修（`5d94bc6`，176→116 条） |
| 2026-10-12 | LLM 使用标准流定稿（`epi-llm-workflow-standard.md`）。其 §9 实施顺序**整体后置**到骨架跑通之后 |

---

## 1. 计划变更

**决策**：优先把工作流跑通（workflow）。真实项目跑一遍暴露的问题，比现在打磨 PRD 解析更有信息量。

**理由**：GENERATE / TEST 目前是桩。整条工作流的失败模式、反馈质量、上下文够不够用，**在桩存在的情况下无法被评估**。

**边界**：

- PRD 解析只做宪法合规的最小归一化（§5.4），不做 LLM 归一化、不做字源映射审计
- 输入允许"最小可用"（手写寄存器表 / BSP 桩都行），但**必须是真内容，不能是模板**
- **允许架构粗糙，不允许假通过**（§6）

**最重要的一条推论**：三个 verifier 现在硬编码 `passed=True`。工作流打通期最大的风险不是跑不通，而是**跑"通"了但没人知道它是空的**。

---

## 2. 现状真值表

### 2.1 工作流阶段

| 阶段 | 实现 | 说明 |
|---|---|---|
| `init` | ✅ 真 | 状态机落盘 |
| `wait_for_external_files` | ✅ 真（**且卡死**） | 门禁见 §2.3 |
| `ingest` | ✅ 真 | S09 正则，116 条需求 |
| `wait_for_design_review` | ⚠️ 半 | 人工 approve 流程真，但**没有代码从需求生成架构**，审的是空模板 |
| `generate` | ❌ **假** | 只调 `compile_system_design()`（S07，46 行，md 表格→json），不生成任何代码 |
| `test` | ❌ **假** | 写死一行 `"MVP workflow reached test stage."` |
| `done` | ✅ 真 | — |

### 2.2 切片实现度（31 个切片共 1516 行）

| 状态 | 切片 |
|---|---|
| ✅ 有实现 | S02 布局(260) S09 PRD(330) S05 解析(122) S15 晋升(75) S13 长记忆(96) S06 校验(71) S16 召回(48) S07 编译(46) S11 图(43) |
| 🟡 桩 | S20 LLM 客户端（返回 `[stub]`）S21 执行器（只有 `write_text`）S22/S23/S24 校验器（**`passed=True` 硬编码**）S25 分类（关键词）S26 重试（集合判断）S12 S14 S17 S18 S19 |
| ❌ **零代码，只有 README** | **S03 配置** **S04 系统架构生成** **S27 追溯输出** **S28 决策日志** **S29 测试报告** **S30 质量门** **S31 CI 矩阵** |

**工作流缺口 = S04 + S20 + S21 + S22 + S24 + S29 + S30。** 其余属于质量打磨。

### 2.3 门禁为什么卡死（P0 必修）

`workflow.py:_has_min_content()` 三条判据，任一不满足即视为"缺文件"：① < 20 字符；② 含 `template`/`todo`/`placeholder`/**`n/a`**；③ `Docs/prd` 下还须含 `User Story`/`Acceptance Criteria`/`Description`。

两个后果：

- **自产模板永远过不了自己的门**（模板里全是 `N/A`）
- `_pin_to_external_gate_if_needed()` 在**每轮循环开头**执行，任一必需目录不合格就把状态强推回 `wait_for_external_files` 并**清掉 `approved_design`** —— demo 项目 4 个目录只有空模板（`Docs/hardware/{schematic,registers,datasheet}`、`Docs/bsp`），因此永远到不了 `ingest`

---

## 3. 工作流跑通最短路径（P0 序列，按依赖排序）

| # | 工作项 | 目标 | 验收 | 依赖 |
|---|---|---|---|---|
| **P0-1** | 门禁改为**显式可跳过 + 报告** | 缺输入时打印缺什么，允许 `--allow-missing` 继续；不再静默回退状态 | demo 项目能走到 `ingest` 并产出 116 条 | — |
| **P0-2** | S03 配置加载（最小） | 读 `config/*.yaml`，暴露 toolchain 路径、provider、门禁开关 | 配置缺失时明确报错，不默用默认 | — |
| **P0-3** | **S04 需求→架构（最小）** | 从 `requirements_index.json` 填 `MODULE_DESIGN_TABLE` / `TASK_TABLE` 的 `req_ids`（当前全 `N/A`） | 每条需求至少挂到一个 module；未挂的进 `unassigned` 并告警 | P0-1 |
| **P0-4** | **S20 真 LLM 客户端** | 单一 provider、可关、`temperature=0`、请求/响应全量落盘 | 同输入同输出；断网时报错而非返回 `[stub]` | P0-2 |
| **P0-5** | **S21 执行器扩展** | `write_text` + `run_command(cwd, timeout)`，动作全量追加日志 | 能写 `src/` 并跑一条命令 | P0-2 |
| **P0-6** | **S22 真编译器** | 调 `arm-none-eabi-gcc` 或 host `gcc`，命令与退出码落盘 | 故意写坏一个文件必须 `passed=False` | P0-5 |
| **P0-7** | **S24 主机侧测试运行** | host gcc 编 unit test 并跑，收集结果 | 一个真实失败的用例必须让阶段失败 | P0-6 |
| **P0-8** | **S29 测试报告** | 汇总 P0-6/P0-7 成 md + json，含需求→用例追溯 | 报告里每条能回指需求 ID | P0-3, P0-7 |
| **P0-9** | **S30 质量门** | 集中判定：无桩参与、覆盖率、追溯完整度 | 任一 verifier 是桩 → 整体 `rejected` | P0-6..P0-8 |

**明确不在 P0**：S23 静态分析（P1，先靠编译器）、S25/S26 重试闭环（P1，先让人看到失败）、S28 决策日志（P1）、S31 CI（P1）、记忆系统 S12–S17（P2）。

---

## 4. 接口预留（契约先冻结，实现可替换）

> 规则：**签名先定，实现可换**。桩必须遵守 §6，不得返回成功。

### 4.1 S04 架构生成

```python
# slices/S04_System_Design_Generation/design_generator.py
class DesignGenerator:
    def generate(self, requirements: RequirementsIndex,
                 template: Path, out: Path) -> DesignDraft: ...

@dataclass
class DesignDraft:
    path: Path
    assigned: dict[str, list[str]]   # module_id -> [requirement_id]
    unassigned: list[str]            # 未挂上任何 module 的需求，非空即告警
    conflicts: list[str]             # 需求矛盾对（P1 再填，P0 恒为空）
```

- **调用时机**：进入 `wait_for_design_review` **之前**（当前该阶段审的是空模板，是错的）
- **红线**：不得生成需求内容，只做**映射与填充**；需求文本一律从 `requirements_index.json` 引用

### 4.2 S20 LLM 客户端

```python
# slices/S20_LLMClient_and_Tools/client.py
@dataclass(frozen=True)
class LLMRequest:
    task_id: str           # 审计包目录名，见 epi-llm-workflow-standard.md §5
    action: str            # carry | elaborate | judge —— 一次调用只能一类
    prompt_sha: str
    context: str
    expect: str = "text"   # text | json | std_format

@dataclass(frozen=True)
class LLMResponse:
    text: str
    raw_path: Path         # 原始响应落盘，不可改
    model: str
    prompt_sha: str

class LLMClient:
    def generate(self, req: LLMRequest) -> LLMResponse: ...
    # P0 允许抛 ProviderUnavailable；绝不返回 "[stub]"
```

- **预留**：`action` 字段工作流打通期用不上（代码生成不区分），但它是后续所有审计分级的入口，**必须现在占位**
- **首个真用户**：代码生成（P0-6 前置）；S04 不用 LLM，纯映射

### 4.3 S21–S24 执行与校验

```python
@dataclass(frozen=True)
class VerifyResult:
    passed: bool
    output: str = ""
    stub: bool = False     # 新增：桩参与则质量门直接 reject
    tool: str = ""         # "gcc-12" / "arm-none-eabi-gcc-12.2"
    duration_ms: int = 0

class ActionExecutor:
    def write_text(self, rel: str, content: str) -> Path: ...
    def run_command(self, argv: list[str], cwd: str = ".",
                    timeout: int = 300) -> CommandResult: ...

class CompilerVerifier:
    def verify(self, task_name: str) -> VerifyResult: ...
```

- **兼容性**：`VerifyResult` 新增字段全带默认值，现有调用方不破
- **红线**：`stub=True` 的结果**不得**进入 `passed=True` 分支

### 4.4 S30 质量门

```python
# slices/S30_Quality_Gates/quality_gates.py
class QualityGate:
    def evaluate(self, run: RunRecord) -> GateVerdict: ...
    # 必查：参与结果里 stub 计数 == 0；追溯断裂数 == 0
```

### 4.5 PRD 伏笔预留（只占位，不实现）

| 预留位置 | 签名 | 用途 |
|---|---|---|
| `prd_ingestion.ingest_prd(docs_root, *, annotator=None)` | `annotator: Annotator \| None` | 非空时走深度解析（§5），为空走现有正则 |
| `prd_ingestion.ReqSource` | `kind: Literal["regex","annotated"]` | 产物里记录来源，下游可区分可信度 |
| `knowledge/annotation.json` | 文件不存在即未启用 | 字源映射产物，见 §5.2 |
| `knowledge/verification.json` | 同上 | 覆盖率 / 守恒报告 |

**约束**：四个占位不得改变现有正则路径的行为，不得引入新依赖。

---

## 5. 【伏笔】延后的 PRD 深度解析方案

> **状态：不采用、不实现、不否决。** 完整推导见 `epi-llm-workflow-standard.md` 与 2026-10-13 工作日志。
> 工作流跑通后拿真实痛点对着 §5.5 的触发信号讨一次，再定做不做、做多少。

### 5.1 八步方案（原方案）

| 步骤 | 内容 | 性质 |
|---|---|---|
| 1 抽取 | PDF → 纯文本 + 字符偏移编号 | 确定性，可立即做 |
| 2 标注 | LLM **只交字符区间 + 标签**，不写正文 | 需 LLM |
| 3 拼装 | 代码用区间切原文，**改写不可能发生** | 确定性 |
| 4 覆盖率对账 | 原文每个非空白字符必须被恰好一个区间覆盖 | 确定性，防漏 |
| 5 数字守恒 | 原文数字+单位 token 多重集 == 产物 token 多重集 | 确定性，零误判 |
| 6 情态/否定守恒 | `必须/不得/禁止/仅/应` 与 `不、未、无、禁` 计数对账 | 确定性，防反转 |
| 7 多轮一致性 | 同输入跑 3 次，区间不一致 → 人工 | 高成本，**已降级为可选** |
| 8 客户确认 | 逐条 ✓/✗/改，**需求完整性的唯一真值** | 组外流程 |

### 5.2 原子模型（为何不是“user story”）

“user story” 是 ADO/Jira 特有格式，客户 PRS 无 title/description/AC 结构。最小单位改为**原子**：一句可独立验证的陈述 + 源字符区间。

例：`需要有BLE功能能支持跟手机app连接实现app control、OTA升级等`

| 项 | 逐字内容 | 区间 |
|---|---|---|
| atom a | `BLE功能` | [1243,1248) |
| atom b | `跟手机app连接实现app control` | [1251,1272) |
| atom c | `OTA升级` | [1273,1278) |
| qualifier | `需要有` / `能支持` | [1240,1243) / [1248,1251) |
| **红旗** | `等` → `open_ended` | [1278,1279) |

`等` 是整套流程最值钱的产出：它证明**客户自己承认需求没写完**，正确动作是生成澄清项，不是让模型补全。

### 5.3 分层产物（不混文件）

| 文件 | 内容 | 权威性 |
|---|---|---|
| `requirements_index.json` | 逐字来自 PRD，零生成 | **唯一真值** |
| `requirements_proposals.json` | LLM 建议的验收标准，带 `origin:"generated"` + `basis` + `assumptions` + `invented_value` | 建议，需确认 |

### 5.4 宪法合规的最小归一化（**工作流打通期实际做的**）

- 保持现有正则路径，不引入 LLM
- 补上失败时的**显式报错**（不再静默写空 JSON）：解析结果为 0 条或标题重复率异常 → `PrdParseError`
- 产物带 `source` / `page`（已有），保证可回查
- 不承诺“不漏”，只承诺“格式错能发现”

### 5.5 采用触发信号（未来讨论用的判据）

出现下列**任一条**，说明最小归一化不够了，§5.1 该重新上桌：

| 信号 | 阈值 |
|---|---|
| 真实客户 PRD 格式不是 ADO 导出 | 首次发生即触发 |
| 因漏需求导致的返工 | 累计 ≥ 2 次，且根因在解析 |
| 客户争议“这条你没做到” | 首次发生即触发（可审计性变成硬需求） |
| 正则修改频率 | 每月 > 2 次 → 格式集不可维护 |
| 错误代价 | 进入安全相关需求（充电/加热/RDP）阶段 |

**反向信号**（继续不做的理由）：工作流未跑通；无真实客户 PRD 在手；LLM 调用与审计成本尚未评估。

### 5.6 已否决 / 已降级（避免重走）

- ❌ 格式 adapter 集作主路径 → 降为可选缓存优化（维护量 O(客户数×版本)）
- ❌ LLM 直接产 `requirements_index.json`
- ❌ LLM review 替代代码校验（只能叠加，不能替代）
- ⚠️ 多轮一致性 → 搬运类用一致率；补全类改用“共识度”（并集 + 频次）

---

## 6. 桩的纪律（防假通过）

现状：S22/S23/S24 返回 `passed=True`，TEST 阶段写死一行字。这类桩比缺失更危险。

**规则**：

1. 桩不得返回成功：要么 `raise NotImplementedError`，要么 `passed=False, stub=True`
2. `stub=True` 的结果不得进入 `passed=True` 分支（§4.3 红线）
3. S30 质量门必须统计本次运行参与结果的 `stub` 计数，非零则整体 `rejected`
4. 报告页顶部必须显示桩清单（哪些环节是桩、什么时候换）
5. 新增桩必须同时在本文件登记，不得静默添加

---

## 7. 工作日志（只追加，最新在上）

### 2026-10-16 · 切片大图语义重构 + 图工具链

- **问题**：原图把三种关系（开发顺序 / 数据流 / 控制流）塞进两种线型。13 对节点被迫画两条同义边；50 个 `linkStyle` 索引被重复赋值（后者覆盖前者），近半实线渲染成橙色；按"这条边搬内容还是搬决策"重划，28/82 条边归类错误
- **判据换成对单条边可判的一问**：内容=数据流(蓝实线)、决策=工作流(橙虚线)、双重身份=待定(紫虚线 + 标签 `？`)。重划后 74 条边 = 数据 57 / 工作 11 / 待定 6，删同义重复边 8 条
- **开发依赖不再手写，改为推导**：`开发顺序 = 数据流图缩点后的拓扑序`。工作流边必须排除 —— 混进去会让 15 节点反馈回路把 S12–S26 压成"必须同时开工"
- **数据流当前唯一环 = `S17→S18→S19`**（agent 回路：上下文→任务序列→状态机→当前 phase 回写）。已在测试中声明为唯一合法环，出现新环即失败 —— 这是可执行的架构约束，比配色约定值钱
- **工具链落 `agent-design/tools/`**：`mermaid_doc.py`（只认标准 Mermaid 元素）+ `graph-rules.json`（颜色↔类别↔是否参与排序，语义唯一来源）+ `apply_edge_style.py`（按箭头重生成配色，幂等）+ `gen_interactive_graph.py`（零依赖离线可交互 HTML）+ `derive_dev_order.py` + `sync_diagram_md.py`
- 图例改**声明式** `%% @legend Legend`，工具据此排除，不再硬编码 `LGS/LRS/LPU` 这类 id
- `tests/test_slices_overview.py` 11 条不变量；6 种破坏逐一变异验证（改箭头 / 去 `？` / 造环 / 未登记配色 / 只改 `.md` / 忘重生成 HTML）全部被抓，还原后全绿
- **待裁定**：6 条待定边见 overview §1.3
- **图有缺边**：`S20`(LLM) 与 `S21`(执行器) 在数据流上无前驱，说明缺 `S03→S20`、`S03→S21` 这类配置数据边；`S08/S09/S10 ← S02` 在文档「开发依赖」列里有、数据流里没有

### 2026-10-13

- 诊断“PRD JSON 丢失”：三个独立问题叠加 —— 代码在另一台机器、`ensure_project_layout()` 在 `run_workflow()` 之前把生成物回写成空模板、ADO 页脚噪声被当成 story 头
- 修 `9c0dd11`：6 个生成物钉成 `CREATE_ONLY`；替换掉那条断言“必须覆写”的测试
- 修 `5d94bc6`：页眉/页脚噪声过滤、`please refer to User Story N` 占位条目折并并带走 work-item ID（含 `Pease` 拼写错误变体）、新增 `source`/`page`。真实 PDF 176→116 条，重复 0、噪声 0、work-item ID 30 条归位
- 实测确认：裸跑 `epi` 会**不可逆**清空需求（状态机已过 INGEST，不会重解）；修复后重复跑不再丢数据
- `tests/test_prd_ingestion.py` 曾被**另一个并发 pi 会话**追加同名 `_STUBS` fixture，后定义覆盖前定义导致 4 条测试跑错数据 —— 已重写。**同一工作树同时只跑一个 agent**
- 定稿 `epi-llm-workflow-standard.md`（作用域矩阵 / 用前用中用后 / 字源唯一货币）
- **计划变更：工作流优先**。深度解析方案降为 §5 伏笔；盘点出工作流缺口 = S04+S20+S21+S22+S24+S29+S30（§2.2）
- 发现两个结构性问题：门禁自产模板永远满不了自己的标准（§2.3）；三个 verifier 硬编码 `passed=True`（§6）
- 待办未落盘：【质量门禁】`PrdParseError`/`ParseReport`（一次 edit 因响应超长被截断）；`annotation.py` 草稿在 `wip/s09-annotation-model` 分支
