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
| 2026-10-18 | **P0-9 完成**：S30 质量门。只读报告不重算事实；有桩参与 → `rejected`；`rejected` = 不予认证而非阻断流程。见 §7 |
| 2026-10-18 | **P0-8 完成**：S29 测试报告（md+json）。追溯靠声明 `/* requires: R-001 */`，不靠推导；`not-evaluated` ≠ `complete`。见 §7 |
| 2026-10-18 | **工作流接真**：`generate`/`test` 两个假阶段改掉 —— 跑真校验器、真失败就停、报告顶部列桩清单。见 §7 |
| 2026-10-18 | **P0-7 完成**：S24 主机侧测试真跑（host gcc 编 + 跑 + 超时；无用例不算过）。新增 `toolchain.host_compiler`（可选但有用例时必需）。见 §7 |
| 2026-10-18 | **P0-6 完成**：S22 真编译器（空 `src/` 不算过、缺编译器不算过、一个坏文件就整体 `passed=False`）；S23/S24 桩改为 `stub=True, passed=False`，`VerifyResult` 禁止桩报成功。见 §7 |
| 2026-10-18 | **P0-4 完成**：S20 真 LLM 客户端（`temperature=0` 钉死、审计包先写后返、桩与断网只能报错）。旧 `--run` 路径不再能打 `[stub]` 文字。见 §7 |
| 2026-10-18 | **P0-5 完成**：S21 执行器落地（默认拒写 + 策略先于 IO + 全量审计）。**P0-3 方问待裁定**：需求→模块无人写声明源与 `semantic_inference: forbidden` 相冲，需选模块清单来源 A/B/C。见 §7 |
| 2026-10-18 | **P0-2 完成**：S03 配置加载落地 —— 必需项不得默用默认、模板来源记为事实（`template: true`）、门禁开关入配置。见 §7 |
| 2026-10-18 | **P0-1 完成**：门禁改为显式豁免 `--allow-missing`，豁免记录进 `state.json`、逐次失效不继承；回退不再静默。见 §7 |
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
| `wait_for_external_files` | ✅ 真（可显式豁免） | 门禁见 §2.3；`--allow-missing` 逐次豁免或 `gate.allow_missing_inputs` 持久豁免，`state.json` 记 `waived_by` |
| `ingest` | ✅ 真 | S09 正则，116 条需求 |
| `wait_for_design_review` | ⚠️ 半 | 人工 approve 流程真，但**没有代码从需求生成架构**，审的是空模板（等 P0-3） |
| `generate` | ✅ 真（但只做这些） | 跑 S07 把设计编成 JSON，失败停在本阶段；**明确声明不生成代码**，不再声称“Generated” |
| `test` | ✅ 真（S23 无证据） | 跑 S22 编译 + S24 主机测试，任一真失败就停在本阶段可 `retry`；报告顶部列出桩清单 |
| `done` | ✅ 真 | — |

### 2.2 切片实现度（切片代码 2972 行，`slices/**/*.py` 不含 `__init__.py`）

| 状态 | 切片 |
|---|---|
| ✅ 有实现 | S02 布局(260) S09 PRD(330) S03 配置(357) S21 执行器(276) S20 LLM 客户端(236) S22 编译器校验(165) S24 主机测试运行(153) S29 测试报告(254) S30 质量门(145) S05 解析(122) S15 晋升(75) S13 长记忆(96) S06 校验(71) S16 召回(48) S07 编译(46) S11 图(43) |
| 🟡 桩（已标 `stub=True`，不会报成功） | S23 静态分析 S25 分类（关键词）S26 重试（集合判断）S12 S14 S17 S18 S19 |
| ❌ **零代码，只有 README** | **S04 系统架构生成** **S27 追溯输出** **S28 决策日志** **S29 测试报告** **S30 质量门** **S31 CI 矩阵** |

**工作流缺口 = S04 + S20 + S21 + S22 + S24 + S29 + S30。** 其余属于质量打磨。

### 2.3 门禁为什么卡死（P0 必修 → **已解**：P0-1 显式豁免 + P0-2 provenance）

`workflow.py:_has_min_content()` 三条判据，任一不满足即视为"缺文件"：① < 20 字符；② 含 `template`/`todo`/`placeholder`/**`n/a`**；③ `Docs/prd` 下还须含 `User Story`/`Acceptance Criteria`/`Description`。

两个后果：

- **自产模板永远过不了自己的门**（模板里全是 `N/A`）
- `_pin_to_external_gate_if_needed()` 在**每轮循环开头**执行，任一必需目录不合格就把状态强推回 `wait_for_external_files` 并**清掉 `approved_design`** —— demo 项目 4 个目录只有空模板（`Docs/hardware/{schematic,registers,datasheet}`、`Docs/bsp`），因此永远到不了 `ingest`

---

## 3. 工作流跑通最短路径（P0 序列，按依赖排序）

| # | 工作项 | 目标 | 验收 | 依赖 |
|---|---|---|---|---|
| **P0-1** ✅ | 门禁改为**显式可跳过 + 报告** | 缺输入时打印缺什么，允许 `--allow-missing` 继续；不再静默回退状态 | demo 项目能走到 `ingest` 并产出 116 条 | — |
| **P0-2** ✅ | S03 配置加载（最小） | 读 `config/*.yaml`，暴露 toolchain 路径、provider、门禁开关 | 配置缺失时明确报错，不默用默认 | — |
| **P0-3** | **S04 需求→架构（最小）** | 从 `requirements_index.json` 填 `MODULE_DESIGN_TABLE` / `TASK_TABLE` 的 `req_ids`（当前全 `N/A`） | 每条需求至少挂到一个 module；未挂的进 `unassigned` 并告警 | P0-1 |
| **P0-4** ✅ | **S20 真 LLM 客户端** | 单一 provider、可关、`temperature=0`、请求/响应全量落盘 | 同输入同输出；断网时报错而非返回 `[stub]` | P0-2 |
| **P0-5** ✅ | **S21 执行器扩展** | `write_text` + `run_command(cwd, timeout)`，动作全量追加日志 | 能写 `src/` 并跑一条命令 | P0-2 |
| **P0-6** ✅ | **S22 真编译器** | 调 `arm-none-eabi-gcc` 或 host `gcc`，命令与退出码落盘 | 故意写坏一个文件必须 `passed=False` | P0-5 |
| **P0-7** ✅ | **S24 主机侧测试运行** | host gcc 编 unit test 并跑，收集结果 | 一个真实失败的用例必须让阶段失败 | P0-6 |
| **P0-8** ✅ | **S29 测试报告** | 汇总 P0-6/P0-7 成 md + json，含需求→用例追溯 | 报告里每条能回指需求 ID | ~~P0-3~~ P0-7（追溯改成声明式，见 §7） |
| **P0-9** ✅ | **S30 质量门** | 集中判定：无桩参与、覆盖率、追溯完整度 | 任一 verifier 是桩 → 整体 `rejected` | P0-6..P0-8 |

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

现状（2026-10-18 更新）：**S22 已换成真编译器**（跑 `toolchain.compiler`，命令与退出码落审计）。S23/S24 仍是桩，但已按规则 1 改成 `passed=False, stub=True`；`VerifyResult.__post_init__` 把规则 2 变成**运行时强制**：`stub=True 且 passed=True` 直接 `ValueError`，不再靠人自觉。

历史：S22/S23/S24 曾返回 `passed=True`，TEST 阶段写死一行字。这类桩比缺失更危险。

**规则**：

1. 桩不得返回成功：要么 `raise NotImplementedError`，要么 `passed=False, stub=True`
2. `stub=True` 的结果不得进入 `passed=True` 分支（§4.3 红线）
3. S30 质量门必须统计本次运行参与结果的 `stub` 计数，非零则整体 `rejected`
4. 报告页顶部必须显示桩清单（哪些环节是桩、什么时候换）
5. 新增桩必须同时在本文件登记，不得静默添加

**当前桩清单**（S30 就按这份拒 —— 已实现为 `no-stub-participation` 规则）：S23 静态分析、S25 分类（关键词）、S26 重试（集合判断）、S12/S14/S17/S18/S19 记忆与上下文机器。

---

## 7. 工作日志（只追加，最新在上）

### 2026-10-18 · 状态页要能看见证据

- P0-8/P0-9 把结论存进了 `state.json`，但状态页不显示就等于没存。现在 `_show_status()` 多一个 **Evidence** 块：逐阶段结论 + 认证结论
- 三条渲染规则：**没记录就渲染成“没记录”**（绝不渲染成一切正常）；`no_evidence` 有自己的颜色和字（桩不能长得跟 pass 一样）；`rejected` 写 **NOT CERTIFIED** 而不是“已失败”
- 新增 4 条测试（`_evidence_lines()` 不依赖控制台，直接断言行）；全套 **157 passed**

### 2026-10-18 · P0-9 S30 质量门

- S30 只**读 S29 的报告字典**：不跑工具、不读文件、不看时钟。理由：门自己重算事实就会跟旁边的报告不一致，而审计的人无从判断哪一份在骗人
- 四条规则：`no-stub-participation`（有桩参与即拒，本项目头号规则）、`no-failed-stage`、`traceability-complete`（**`not-evaluated` 也算拒**）、`requirement-coverage`（仅当 `gate.min_requirement_coverage` 配了才判）
- **`rejected` = 不予认证，不是停下流程**。今天 S23 是桩，所以每次都被拒；如果拒绝同时阻断工作流，唯一的出路就是拆掉这个门 —— 正好是把门变成装饰的那股压力。所以只记结论（`state.json` + `quality_gate.json`），让 CI（S31）去失败
- **判不了的规则不算满足**：`min_requirement_coverage` 默认不配。不配既不当 0（白送）也不当 1（我们替客户定验收线），而是落进 `not_judged` 并写明原因 —— 判不了却读成通过，跟桩报成功是同一种错
- 模板里以注释列出 `min_requirement_coverage`；实测：真编译 + 真用例全过 → 阶段推进，但 `Quality gate: REJECTED - this run is not certified`，原因 `no-stub-participation: static-analysis`
- 新增 `tests/test_quality_gate.py` 13 条 + 工作流集成 1 条；全套 **153 passed**

### 2026-10-18 · P0-8 S29 测试报告（需求→用例追溯）

- **决定：追溯链靠声明，不靠推导。** 用例文件里写 `/* requires: R-001, R-004 */`，报告只做查表。理由：`semantic_inference: forbidden` 在报告这一层最致命 —— 猜出来的链接在报告里长得跟事实一模一样
- **以这二条拆开了 P0-8 对 P0-3 的依赖**：需求→**用例** 由写用例的人声明（不依赖模块清单）；需求→**模块** 才是 P0-3 要裁定的事。所以 P0-8 不再等 P0-3
- 四种追溯状态分得很开：`complete` / `broken`（ malformed 或未知 ID）/ `not-evaluated`（索引缺失、解析不了、或 `requirements: []`）。**`not-evaluated` 不等于 `complete`** —— S02 模板就带一个空索引，“文件在”不等于“PRD 已录入”，把零条需求报成“全覆盖”是空真
- **坏链接绝不默默丢掉**：`R-1` 这种写法进 `malformed_links` 并把追溯标成 broken；丢掉它就等于把断链变成一份干净的报告
- **阶段结论不挂需求 ID**：`compile`/`host-tests` 这类全工程门在需求列里写 `n/a (whole-project gate)` —— 整体编译过了不是某一条需求的证据
- 总结论的话术不粉饰：失败时 `1 stage(s) failed: compile`（而不是把桩当标题），过了但有桩才写 `passed with unverified stages: ...`
- md 与 json 由**同一个字典**渲染，两者不可能不一致；**不带墙钟时间戳**，同输入同字节（已测）
- 实测端到端：真 gcc 编译 + 真跑用例 → `R-001 covered by tests/crc_test.c`、`R-002 untested`、`static-analysis NO_EVIDENCE (stub)`，阶段才推进
- `VerifyResult` 新增 `cases`（只有真跑了用例的阶段填），S29 只读不写；新增 `tests/test_test_report.py` 12 条，全套 **139 passed**

### 2026-10-18 · 工作流最后两个假阶段接真

- `test` 阶段不再写死一行字：跑 S22 编译 + S24 主机测试 + S23（桩）。**真失败就停在本阶段**，可 `retry`；`state.json` 记 `test_verdicts`
- `generate` 阶段不再说“Generated”：只跑 S07 编设计，并**明说没写任何 `src/` 代码**。设计编译失败也停在本阶段
- **桩不算过也不算败**：S23 没出证据，所以不能拿它的 `passed=False` 把工作流锁死；但报告**顶部**就写 `No evidence (stub): static-analysis`，所以下游不能把“0 个失败”读成“全部验过”（§6 规则 4）
- 报告现在含总结论 / 失败项 / 桩清单 / 每个阶段的工具版本、耗时、命令与输出
- 实测（新项目 + 豁免门禁）：`compile: FAIL`（`no .c sources under src/`）、`host-tests: FAIL`（`collected nothing`）、`static-analysis: no evidence (stub)` —— 以前这里是一句 `MVP workflow reached test stage.`
- 副作用：没生成代码的项目现在**到不了 `done`**。这是真的红而不是门禁死锁：修它的办法就是 P0-3/P0-6 要做的事
- 新增 `tests/test_workflow_phases.py` 5 条（含“报告顶部必须有桩清单”、“真失败用例必须不推进阶段”）；全套 **126 passed**

### 2026-10-18 · P0-7 S24 主机侧测试真跑

- `SimulatorVerifier` 从桩变成真跑：收 `tests/**/*_test.c` → 用 **host 编译器** 连同 `src/**/*.c` 编成可执行 → 跑起来 → **退出码 0 是唯一的过**；编与跑都走 S21 执行器，命令与退出码进审计流水
- **测试约定定在标准库上**：`#include <assert.h>` + `main()` + 返 0。不自造 harness、不生成测试框架（生成框架就是本项目在自己造内容）；**绝不传 `-DNDEBUG`** —— 那会把所有 `assert` 默化成空，整条测试链变成假通过
- **新增 `toolchain.host_compiler`（可选）**：交叉编译器造不出本机能跑的二进制，所以主机测试必须自己的编译器；有用例又没配 → `passed=False` 并点名这个配置项（不默用 `gcc`）。模板里以注释形式列出
- 四种情必须不过：没用例（收 0 条不能算过）、没 host 编译器、编不过（`BUILD FAILED` + 编译器原话，不是 skip）、跑挂死（超时后 `timed_out`）
- S21 新增 `allow_executable()`：先编后跑的调用方需要把刚编出来的二进制加进允许清单，走方法而不是让调用方拿 set 的引用偷偷改
- 踩到的坑（已被测试拓住）：`_binary_path` 用 `relative_to(project_root)` 把 `tests/` 带进了输出路径（`build/tests/tests/...`）；`ActionExecutor` 对 `allowed_executables` 做副本，调用方改自己那个 set 并不生效
- `tests/test_host_tests.py` 8 条（含真失败用例、编不过、挂死超时）；全套 **121 passed**

### 2026-10-18 · P0-6 S22 真编译器（+ 桩纪律上锁）

- `CompilerVerifier` 跑真编译器：从 S03 配置取 `toolchain.compiler`（不默认），`src/**/*.c` 排序后逐个 `-c` 到 `build/objects/`，每次调用走 S21 执行器 → **argv 与退出码自动落审计流水**（验收项「命令与退出码落盘」）
- **四种情况必须不过**：`src/` 空（没干活不能叫干净）、没配 project_root（不能凭空气出结论）、编译器二进制不存在（报告里说清找了哪个名字）、多个文件里有一个坏（整体 `passed=False` 并带编译器自己的诊断）
- **`VerifyResult.__post_init__` 禁止 `stub=True 且 passed=True`** —— §6 规则 2 从「人记住」变成运行时报错
- S23/S24 两个桩从 `passed=True` 改成 `passed=False, stub=True`：桩只能说自己没干，不能发通行证；否则 S30 质门根本无从拒绝
- §6 新增**当前桩清单**，S30 直接按这份拒
- `tests/test_compiler_verifier.py` 8 条（真 gcc 跑不了的机器会明确 skip，但空目录/未配置/桩锁这三条任何机器都跑）；全套 **112 passed**
- 未做（P1）：目标芯片 flag（`-mcpu`/`-mthumb`/链接脚本）与多文件链接 —— 那是配置层的决定，不放进校验器

### 2026-10-18 · P0-4 S20 真 LLM 客户端

- `LLMClient` 替掉返回 `[stub] ...` 的桩：单一 provider（`openai_compatible`）、`temperature=0` + `seed=0` **钉在请求里**、请求前先写 `task.json` + `input.numbered.txt`，返回前先写 `output.raw` + `response.json`
- **审计包先写后返**：没留下审计的调用等于没发生过；`task_id` 重用直接 `AuditConflict`（重试必须另开 attempt，而不是覆写证据）。失败的 attempt 不写 `output.raw`，所以同一 id 允许重试
- **`temperature` 从配置里拿掉选择权**：模板改为 `0.0`，非 0 在**加载期**报错（而不是客户端默默发 0）。一个能悄悄改变可复现性的旋钮与 P0-2 要拆的默用默认同罪
- **密钥只从环境读** `EPI_LLM_API_KEY`，绝不进 `Docs/config.yaml`（那是要进 git 的）；测试直接断言密钥不出现在审计包任何文件里
- 桩纪律：`provider: stub` **报错且不写审计包**（一个看起来像调用的桩比没调用更坑）；`EPI_LLM_ENABLED=0` 也报错而不是默默跳过
- 旧 `--run` 路径（`agent.py`）接上真客户端：以前 `_ = self.llm.generate(context)` 把结果丢掉，现在无 provider 就 `ProviderUnavailable`。新增 smoke 测试钉住「不许编文字」
- 测试 14 条：假 transport 验确定性与审计内容，真 `HTTPServer` 验 urllib 真路径，端口 1 验**拒连时报错而非返文字**；全套 **104 passed**
- 附带整理：`tests/fixtures/sample_project/` 下曾有**两份** config（根目录 + `Docs/`），只有一份是有效的；现只留 `Docs/config.yaml` 一份（与 S02 布局契约一致），删掉根目录那份避免再漂移

### 2026-10-18 · P0-5 S21 执行器（+ P0-3 方向问题）

- `ActionExecutor` 从 12 行桩变成完整实现：`write_text` / `read_text` / `run_command(argv, cwd, timeout)`，返回 `CommandResult(exit_code, stdout, stderr, duration_ms, timed_out)`
- **`CommandResult` 故意没有 `passed` 字段** —— 「算不算过」是 S22–S24 与 S30 的职责，执行器只能报告事实，不能下结论（§6 防假通过）
- **默认拒写**：只允许 `src/` `include/` `tests/` `Docs/ai-generation/generated/`，且必须在项目内。`Docs/prd`、`Docs/standards`、`workflow/state.json`、**自己的审计流水** 全部拒绝
- **策略先于 IO**：这条是测试逼出来的 —— 第一版把可写性检查放在 `_record()` 里，于是**先写后查**，9 条越界路径全被真写了。测试断言「被拒就必须没落盘」直接抦住
- **全量审计**：`Docs/ai-generation/audit/<task-id>/actions.jsonl`（沿用 `epi-llm-workflow-standard.md` §5 的审计包位置）。成功/失败/被拒全记；seq 跨进程续号，两个执行器不能都声称自己是第 1 条
- **覆盖写必记 predecessor**：每条写带 `previous_sha256` —— 「生成物被反复清空」那起事故下次是一条查询，不是一次考古
- **不开 shell**：argv 直接执行 + 项内 cwd + 超时；可执行文件不存在是**返回结果**不是抛异常（「编译器没装」必须是校验器能报告的事，不是一段 traceback）
- `allowed_executables` 是给「输入来自模型」的调用方的控制面（只放配置里的工具链）；`None` = 不限，只有受信调用方能这么用
- `tests/test_executor.py` 22 条；全套 **89 passed**。实测：写 `src/main.c` + `gcc -c` 真编译通过（122ms），两条流水带哈希
- **P0-3 待裁定（方向层，已问用户）**：`semantic_inference: forbidden` 使「需求→模块」无法自动，而模块清单本质是人的架构决定；且现在 `module-design/module_design_table.json` 是 S07 从 `system-design.md` **派生**的，方问要反过来。选项：A `module-design.md` 改为人写源、`system-design.md` 降为生成物（推荐）；B `system-design.md` 保持唯一人写源、S04 只做覆盖率检查；C 新增 `config/architecture.yaml` 模块清单

### 2026-10-18 · P0-2 S03 配置加载

**规范冲突与解法**（P0-2 要求「缺失明确报错、不默用默认」，但 `Docs/config.yaml` 是 S02 自产模板，占位值看起来像真值）：

- 只校「字段在不在」= 假严格；校「值真不真」= 新项目直接卡死（就是 P0-1 刚解掉的死结）
- 解法：**把「还是模板吗」变成记录的事实**，S02 生成时写 `template: true`，S03 读这个标记 → `is_template`。不是内容猜测，与 §2.3 那套关键字嗅探划清界线
- 结果：严格校验与脚手架共存 —— 报告「结构合法但尚未配置」，而不是假装占位值是用户的选择

**必需项清单**（`REQUIRED_KEYS`，每项带「为什么不能默认」的理由，报错时一并打印）：`project.name`、`mcu.part`、`toolchain.compiler`、`llm.provider`、`llm.model`。其余（token 预算、paths、gate）允许默认，因为它们改变的是成本，不是「产出什么」

- `extra="forbid"` + 必需项前置校验：拼错的键会被点名（`llm.provder looks like a typo for llm.provider`）；pydantic 原生的「应该是字典」消息在整节为空时不可用，所以自己走一遍必需项
- **`llm.provider` 白名单**：未知 provider 在加载期失败。静默回退等于把项目源码发给没人选的模型
- **paths 必须项目相对**：两台机器（Windows/Linux）编辑同一项目，绝对路径只在其中一台能用
- **`objcopy` 由编译器派生**（同目录同前缀），非 gcc 形态则要求显式配置并报错 —— 派生不出来的东西不能瞎猜
- **门禁开关入配置**：`gate.allow_missing_inputs`（默认 `false`，门禁不可能默认敞开）。与 P0-1 的 `--allow-missing` 区别是**权威来源**：配置里的豁免是提交进版本库的项目决定（持久），命令行是临时绕过（逐次失效）。`state.json` 新增 `waived_by: cli|config` 记录是谁豁免的
- 结构：实现在 `slices/S03_Config_Loading_and_Validation/config.py`，顶层 `config.py` 退化为 `import *` 转发（沿用 S02 的切片约定），`agent.py`/S17 的旧导入不变
- 模板新增注释掉的 `gate:` 块（安全开关要能被看见），并提示「改完删掉 `template: true`」
- `tests/test_config.py` 15 条 + 工作流门禁 7 条，全套 **67 passed**；实测消息：`toolchain.compiler: required value missing - a default compiles with a toolchain nobody selected`
- **待确认（方向层）**：计划里写的是读 `config/*.yaml`（目录式多文件），实际布局契约是单一 `Docs/config.yaml`。我按后者实现并把 `config.yaml` 作为兼容位置；若真要拆成 `config/toolchain.yaml` 等，那是 S02 布局契约变更，需同步 constitution 与切片大图
- 遗留风险：`agent.py`（旧 `--run` 路径）现在也会因缺必需项而报错。它不在 P0 序列里，但严格化的代价就是旧路径同样严格 —— 这是刻意的

### 2026-10-18 · P0-1 门禁显式豁免

- `--allow-missing` 把外部门禁从"必须满足"改成"显式豁免"：缺什么逐条打印，`waived_missing` 落进 `state.json`，`notes` 标注 —— 被豁免的跑与通过门禁的跑，从状态文件上就能分辨
- **豁免逐次失效**：不带 flag 的下一次运行自动清空豁免。否则一次 `--allow-missing` 就把门禁永久解除，正是这个门禁要防的静默回退
- 豁免**按路径精确生效**：只放行清单内的项；新出现的缺失项照样阻塞
- 修掉静默回退：`_pin_to_external_gate_if_needed()` 把状态打回 `wait_for_external_files` 时现在必须打印是哪几条输入卡的
- `tests/test_workflow_gate.py` 7 条：模板目录不算就绪、豁免需显式请求且持久化、逐次失效、按路径精确、回退必须报告、豁免后不再被拉回门禁、CLI 层 flag 真的存在（用 `typer.testing.CliRunner` 走真实参数解析）
- 端到端实测：新建项目 + 4 条 markdown 需求 → 不带 flag 卡在门禁；带 flag 走到 `ingest`，产出 `requirements_index.json` 4 条，阶段 `wait_for_design_review`
- **验收打折处说明**：「产出 116 条」需要真实 ADO PDF，而 `demo-project/` 在 `.gitignore` 里，只存在于 Windows 那台。Linux 侧用 4 条 md 需求验证了同一门禁路径
- 顺带：Linux 机器没有可用的 Python 环境（PEP 668 外部管理），已建 `.venv` 并 `pip install -e .[dev]`，`epi` 可用；测试 52 passed

### 2026-10-16 · 切片大图语义重构 + 图工具链

### 2026-10-16 · 交互图：聚焦语义与排布

### 2026-10-16 · 交互图：标签落位、端点贴框、拖拽防选中

- **标签压线的根因是线束**：跨列长边全挤在同一根竖线上。改为**逐列通道布线**（每个列间隙按穿越数切等分通道、按高度排序），再让标签沿自己的折线找位置 —— 压到别人的边=禁止，没压到自己的边=罚，压节点/叠标签=不可行。当前 74 个标签：互相重叠 0、压到别边 0、2 个找不到自己边上的干净段
- **橙/紫边"两端错位"**：反向边原先挂在节点顶边外 6px，同列边退化成竖线。现在反向边源左出、目标右入走列间通道，同列边从右侧绕出；**所有端点贴节点框**，并由测试断言
- 拖拽会选中整页文字：全站禁选，`.panel` 内恢复（说明框文字要能复制）
- 标签放置一度把测试套件拖到 **74 秒**；缓存线段包围盒 + 找到零冲突即早停 → **1.5 秒**，输出不变
- 新增 2 条不变量（端点贴框、标签只压本边），各配一个变异验证；全套 45 passed / 4 秒
- **遗留**：`S20`(LLM) 与 `S21`(执行器) 在数据流上无前驱，被排到 L0，它们的橙/紫边因此横跨半张图。补 `S03 →S20/S21 配置` 数据边即可归位 —— 这是图内容缺边，不是渲染问题

- **聚焦 bug 根因不是"兄弟边"，是可达性爆炸**：本图有一个 15 节点强连通回路，按"任意边可达"定义下游时，`S26 →重试反馈→ S19` 会把整个记忆子系统算成 S22 的下游，聚焦一个节点点亮大半张图
- 改为 **ego 网络**：只沿主关系（数据流）传递 N 跳；工作流/待定边不参与传递，只在 ego 网络内部或与聚焦节点直连时显示。聚焦 S22 从"大半张图"收敛到 20 条边 / 9 个节点
- **排布**：长边拆成逐列虚节点（Sugiyama），排序用中位数扫描 + 相邻交换，层内交叉 75；边标签在生成期做避让，**重叠数 0 并由测试钉住**
- 节点说明框补**功能描述**（来源 WBS「目标产物」列，规则里声明 `description_column`），验收标准另起一行；线型含义移出说明框，常驻右下角大图说明
- 模板外置 `tools/graph_template.html`；纯逻辑用 `/*LOGIC-START*/` 标记，**node 直接跑真实生成数据做回归测试**（方向、深度、类别过滤四条不变量），不再依赖浏览器
- 新增 `tests/test_slices_graph.py` 7 条；4 种变异（关范围裁剪 / 关标签避让 / 描述列失效 / 改图不重生成）逐一验证会被抓到

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
