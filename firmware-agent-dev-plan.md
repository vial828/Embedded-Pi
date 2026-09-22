# 嵌入式固件全自主开发 Agent — 开发计划书

> 版本: v0.1  
> 日期: 2026-07-09  
> 状态: 规划阶段

---

## 一、产品定义

### 1.1 一句话

**给定 PRD、电路图、寄存器手册、BSP、编码规范，Agent 100% 自主完成嵌入式固件开发，输出可编译、可验证、可追溯的完整工程。**

### 1.2 核心定位

```
不是: "一个会写 STM32 代码的 AI"
而是: "一个通用的嵌入式固件开发上下文引擎"

MCU 知识是外部数据（放在标准路径下），不是代码。
换 MCU = 换文件 + 改 config.yaml。Agent 代码零修改。
```

### 1.3 产品的精髓

> **上下文精准控制。**
>
> 任意时刻，给 LLM 组装**最小够用**的上下文。
> 完成一个子任务后，**清空大部分上下文**，为下一个子任务组装全新上下文。
> 以此严控上下文体量，避免注意力稀释。
>
> 模型的角色不是"记住一切的专家"，是"知道去哪查的工程师"。
> 给它一个图书馆（tools）+ 一张便签（working state）+ 三条家规（constitution）。

### 1.4 目标用户

- 嵌入式固件开发团队（中小公司为主）
- 有明确 PRD 和硬件设计，需要快速产出固件的项目
- 希望标准化开发流程、减少重复性编码工作的团队

### 1.5 差异化

| 通用 Coding Agent (Cursor/Copilot/Cline) | 本产品                         |
| ---------------------------------------- | ------------------------------ |
| Web/App 思维                             | 嵌入式领域深度                 |
| 对话累积，context 膨胀                   | 每步 fresh context，严格控量   |
| 无验证闭环                               | 编译→仿真→(HIL) 自动验证       |
| 无领域知识                               | 寄存器表、编码规范、流程规范   |
| 输出代码片段                             | 输出完整工程 + 文档 + 追溯矩阵 |
| 人驱动                                   | 自主状态机驱动                 |

---

## 二、整体架构

### 2.1 系统架构图

```
┌─────────────────────────────────────────────────────────────────┐
│                        用户输入（标准路径）                       │
│                                                                 │
│  /project/                                                      │
│  ├── config.yaml              ← 项目配置（MCU、工具链、路径）     │
│  ├── prd/requirements.md      ← 需求文档                         │
│  ├── hardware/                                                  │
│  │   ├── schematic/           ← 原理图                           │
│  │   ├── datasheet/           ← MCU 数据手册                     │
│  │   ├── registers/           ← 寄存器表（结构化 JSON）           │
│  │   └── pin_map.json         ← 引脚分配                         │
│  ├── bsp/                     ← 厂商 BSP/HAL 源码                │
│  ├── standards/               ← 编码规范、流程规范                │
│  └── toolchain/build.yaml     ← 编译配置                         │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Agent 引擎（核心）                          │
│                                                                 │
│  ┌───────────────┐    ┌──────────────────┐    ┌─────────────┐   │
│  │  Task Planner │──▶│  State Machine   │───▶│  Context    │   │
│  │  PRD→子任务列表│    │  任务流转/重试/   │    │  Assembler  │   │
│  │               │    │  回滚            │    │  (核心 IP)   │   │
│  └───────────────┘    └────────┬─────────┘    └──────┬──────┘   │
│                                │                      │         │
│                                ▼                      ▼         │
│  ┌───────────────┐    ┌──────────────────────────────────────┐  │
│  │  Knowledge    │◄───│         LLM Client                   │  │
│  │  Base         │    │  (本地 Qwen / 云端 Claude / GPT)      │  │
│  │  寄存器查询    │    │                                      │  │
│  │  规范查询      │    └──────────────────┬───────────────────┘  │
│  │  BSP 索引      │                       │                      │
│  └───────────────┘                       ▼                      │
│                                ┌──────────────────┐             │
│                                │  Action Executor │             │
│                                │  写文件/跑命令/   │             │
│                                │  调工具           │             │
│                                └────────┬─────────┘             │
│                                         │                       │
│                                         ▼                       │
│  ┌───────────────┐    ┌──────────────────────────────────────┐  │
│  │  Decision     │◄───│         Verifier                     │  │
│  │  Log          │    │  编译 → 静态分析 → 仿真 → (HIL)      │  │
│  │  决策记录     │    │  + Error Classifier                  │  │
│  └───────────────┘    └──────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                        输出（工程交付物）                         │
│                                                                 │
│  /output/                                                       │
│  ├── firmware/                ← 完整可编译工程                   │
│  ├── docs/                                                      │
│  │   ├── design_decisions.md  ← 关键决策及理由                   │
│  │   ├── traceability.md      ← 需求追溯矩阵                     │
│  │   └── assumptions.md       ← 假设与限制                       │
│  ├── test/                                                      │
│  │   ├── test_report.md       ← 测试报告                         │
│  │   └── cases/               ← 测试用例                         │
│  └── build/                   ← 编译产物 (.elf/.bin/.hex)        │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 核心设计原则

```
1. 通用性: Agent 不内置任何 MCU 知识。所有领域信息通过标准路径注入。
2. 上下文精准: 每步组装最小够用上下文，任务间清空重建。
3. 验证驱动: 不信任 LLM 输出。编译/仿真/断言是硬卡点。
4. 流程可配置: 开发流程由 process_spec.yaml 定义，客户可定制。
5. 可追溯: 每个决策有记录，每个需求有对应的代码和测试。
6. 模型无关: LLM 是可替换组件。本地/云端/不同厂商，接口不变。
```

---

## 三、标准输入接口

### 3.1 目录结构

```
/project/
├── config.yaml                 ← 唯一入口
├── prd/
│   └── requirements.md         ← 需求文档（Markdown）
├── hardware/
│   ├── schematic/              ← 原理图 (PDF / KiCad / Altium 导出)
│   ├── datasheet/              ← MCU Datasheet (PDF)
│   ├── registers/              ← 寄存器表（结构化，每外设一个 JSON）
│   │   ├── rcc.json
│   │   ├── gpio.json
│   │   ├── uart.json
│   │   ├── spi.json
│   │   ├── i2c.json
│   │   ├── tim.json
│   │   ├── dma.json
│   │   └── ...
│   └── pin_map.json            ← 引脚分配
├── bsp/                        ← 厂商 BSP/HAL 源码
│   ├── hal/
│   ├── cmsis/
│   ├── startup/
│   └── Makefile (或 CMakeLists.txt)
├── standards/
│   ├── coding_standard.md      ← 编码规范
│   └── process_spec.yaml       ← 开发流程定义
└── toolchain/
    └── build.yaml              ← 编译器、flags、链接脚本
```

### 3.2 config.yaml（核心配置）

```yaml
project:
  name: "sensor-node-v1"
  description: "环境传感器采集节点"

mcu:
  part: "STM32F407VGT6"        # 换 MCU 改这里
  core: "cortex-m4"
  flash_size: "1MB"
  ram_size: "192KB"
  clock:
    hse: "8MHz"
    sysclk: "168MHz"
    ahb: "168MHz"
    apb1: "42MHz"
    apb2: "168MHz"

toolchain:
  compiler: "arm-none-eabi-gcc"
  cpu_flags: "-mcpu=cortex-m4 -mthumb"
  build_cmd: "make -C {bsp} TARGET={target}"
  link_script: "{bsp}/ld/stm32f407xx.ld"

paths:
  registers: "./hardware/registers/"
  bsp: "./bsp/"
  schematic: "./hardware/schematic/"
  coding_standard: "./standards/coding_standard.md"
  process_spec: "./standards/process_spec.yaml"

verification:
  compile: true
  static_analysis:
    enabled: true
    tools: ["cppcheck", "clang-tidy"]
  simulate:
    enabled: true
    backend: "qemu"             # "qemu" | "hil" | "none"
    qemu_args: "-M virt -cpu cortex-m4 -serial stdio"
    timeout_sec: 30
  # hil:                        # v2 启用
  #   probe: "stlink"
  #   serial_port: "/dev/ttyUSB0"
  #   baud: 115200

llm:
  provider: "openai_compatible"   # "openai_compatible" | "anthropic" | "openai"
  base_url: "http://localhost:8080/v1"
  model: "Qwen3.8-27B"
  max_tokens: 8192
  temperature: 0.1

context:
  max_tokens: 3000              # 每步 context 上限
  constitution_file: "./standards/constitution.md"
```

### 3.3 寄存器表格式（registers/uart.json 示例）

```json
{
  "peripheral": "UART1",
  "base_address": "0x40011000",
  "clock": "APB2",
  "registers": {
    "UART_CR1": {
      "offset": "0x00",
      "address": "0x40011000",
      "description": "Control register 1",
      "bits": {
        "UE":    {"pos": 0,  "width": 1, "reset": 0, "desc": "UART enable"},
        "RE":    {"pos": 2,  "width": 1, "reset": 0, "desc": "Receiver enable"},
        "TE":    {"pos": 3,  "width": 1, "reset": 0, "desc": "Transmitter enable"},
        "M":     {"pos": 12, "width": 1, "reset": 0, "desc": "Word length: 0=8bit, 1=9bit"},
        "OVER8": {"pos": 13, "width": 1, "reset": 0, "desc": "Oversampling mode"},
        "UEIX":  {"pos": 8,  "width": 1, "reset": 0, "desc": "UART exit idle mode"}
      }
    },
    "UART_BRR": {
      "offset": "0x04",
      "address": "0x40011004",
      "description": "Baud rate register",
      "bits": {
        "mantissa": {"pos": 0,  "width": 12, "reset": 0, "desc": "BRR mantissa"},
        "fraction": {"pos": 16, "width": 4,  "reset": 0, "desc": "BRR fraction"}
      }
    },
    "UART_SR": {
      "offset": "0x10",
      "address": "0x40011010",
      "description": "Status register",
      "bits": {
        "RXNE": {"pos": 5, "width": 1, "reset": 0, "desc": "Read data register not empty"},
        "TXE":  {"pos": 7, "width": 1, "reset": 0, "desc": "Transmit data register empty"},
        "ORE":  {"pos": 3, "width": 1, "reset": 0, "desc": "Overrun error"},
        "NE":   {"pos": 5, "width": 1, "reset": 0, "desc": "Noise error"}
      }
    }
  },
  "interrupts": {
    "IRQn": "USART1_IRQn",
    "IRQ_number": 37
  },
  "dma_channels": {
    "rx": {"dma": "DMA2", "channel": 5, "request": 5},
    "tx": {"dma": "DMA2", "channel": 7, "request": 7}
  }
}
```

### 3.4 pin_map.json 格式

```json
{
  "UART1": {
    "TX": {"pin": "PA9",  "port": "A", "pin_num": 9,  "af": "AF7"},
    "RX": {"pin": "PA10", "port": "A", "pin_num": 10, "af": "AF7"}
  },
  "I2C1": {
    "SCL": {"pin": "PB6", "port": "B", "pin_num": 6, "af": "AF4"},
    "SDA": {"pin": "PB7", "port": "B", "pin_num": 7, "af": "AF4"}
  },
  "LED_STATUS": {
    "pin": "PD12", "port": "D", "pin_num": 12, "af": null, "active_level": "low"
  },
  "POWER": {
    "vcc": "3.3V",
    "hse_crystal": "8MHz"
  }
}
```

### 3.5 process_spec.yaml（流程定义，客户可定制）

```yaml
phases:
  - name: requirements_review
    description: "需求解析与完整性检查"
    entry_criteria: "prd/ 目录非空"
    exit_criteria: "所有需求项有唯一 ID，无歧义，无缺失关键参数"
    actions:
      - parse_prd
      - assign_requirement_ids
      - check_completeness

  - name: architecture
    description: "系统架构设计"
    entry_criteria: "requirements_review 完成"
    exit_criteria: "外设列表确定，时钟树确定，内存分配确定，中断优先级确定"
    actions:
      - extract_peripheral_list
      - design_clock_tree
      - allocate_memory
      - assign_interrupt_priorities
      - generate_architecture_doc

  - name: implementation
    description: "代码实现"
    entry_criteria: "architecture 完成"
    exit_criteria: "所有模块代码生成，编译通过，零 warning"
    subtask_order: "按依赖: startup → system_clock → gpio → drivers → app"
    actions:
      - generate_peripheral_init
      - generate_drivers
      - generate_app_logic
      - generate_main

  - name: verification
    description: "验证"
    entry_criteria: "implementation 完成"
    exit_criteria: "编译通过 + 静态分析通过 + 仿真/测试通过"
    actions:
      - compile
      - static_analysis
      - simulate
      - run_unit_tests
      # - hil_test          # v2

  - name: documentation
    description: "文档生成"
    entry_criteria: "verification 完成"
    exit_criteria: "追溯矩阵完整，设计决策文档生成"
    actions:
      - generate_traceability_matrix
      - generate_design_decisions
      - generate_test_report
      - generate_assumptions
```

---

## 四、上下文引擎（核心 IP）

### 4.1 分层模型

```
┌─────────────────────────────────────────────────────────┐
│  Layer 0: Constitution (始终在 context, < 300 tokens)    │
│  不可违反的硬规则，极短，像宪法                            │
├─────────────────────────────────────────────────────────┤
│  Layer 1: Working State (始终在 context, < 500 tokens)   │
│  当前任务状态快照（不是历史！）                            │
├─────────────────────────────────────────────────────────┤
│  Layer 2: Task Context (每步注入, 500~2000 tokens)       │
│  当前子任务相关的寄存器、代码片段、接口定义、错误信息       │
├─────────────────────────────────────────────────────────┤
│  Layer 3: Knowledge (按需检索, 不占固定 context)          │
│  完整寄存器手册、编码规范细则、协议规范                    │
│  → 通过 tool call 获取，用完即弃                         │
└─────────────────────────────────────────────────────────┘

总 context 目标: < 3000 tokens
```

### 4.2 Constitution 示例

```markdown
## Hard Rules
- 所有寄存器操作必须通过 lookup_register 确认地址，禁止凭记忆
- ISR 中禁止: malloc, printf, HAL_Delay, 任何阻塞调用
- 共享变量必须 volatile + 关中断保护
- 每个 .c 文件必须有对应 .h，函数必须有 doxygen 注释
- 外设初始化顺序: 使能时钟 → 配 GPIO → 配外设 → 使能外设 → 开 NVIC
- 不确定时，输出 [NEED_CLARIFICATION: 具体问题] 而非猜测
- 代码必须能编译通过，不确定的 API 先查 BSP 头文件
```

### 4.3 记忆分层（两层）

> 原则：激进刷新上下文，但不丢关键记忆。  
> 方式：短记忆 + 长记忆。模型不“记住”，系统“持久化”。

#### 4.3.1 短记忆（Working Memory）

```python
class WorkingMemory:
    """短记忆：当前任务快照。每步刷新，不累积对话历史。"""

    mcu: str
    phase: str
    current_task: str
    files_done: list[str]
    file_in_progress: str
    dependencies: str
    last_error: str
    retry_count: int

    def snapshot(self) -> str:
        """< 500 tokens，用于每步固定注入"""
```

#### 4.3.2 长记忆（Long Memory）

```python
class LongMemory:
    """长记忆：跨任务/跨阶段不可丢信息。结构化存储，按需召回。"""

    decisions: list[dict]      # 决策：id/content/rationale/source/scope
    constraints: list[dict]    # 约束：id/rule/severity/source
    traceability: list[dict]   # 追溯：req_id -> module/function/test

    def retrieve(self, task) -> str:
        """按任务相关性召回最小记忆包，不全量注入。"""
```

#### 4.3.3 持久化数据结构（落盘）

```
Docs/ai-generation/memory/
├── working_memory.json      # 短记忆快照（每步覆盖更新）
├── long_memory.json         # 长记忆（decisions/constraints/traceability）
├── candidate_memory.json    # LLM 提名候选（结构化）
└── memory_delta.log         # 记忆增量日志（新增/更新/冲突）

Docs/ai-generation/knowledge/
├── rules.json               # 标准/规范提取的规则（含 source_id）
├── requirements_index.json  # 需求索引（含 source_id）
├── register_index.json      # 寄存器索引（含 source_id）
└── artifact_graph.json      # req/module/file/test 关系图
```

### 4.4 记忆晋升与召回规则

```
晋升到长记忆（满足任一）:
1) 跨模块影响
2) 高失败代价（编译/运行时风险）
3) 来源权威（PRD/寄存器表/标准/验证结果）
4) 后续高复用频率

重要约束:
- LLM 只能“提名候选记忆”，不能直接晋升
- 最终晋升由规则引擎判定（deterministic）

召回规则:
- 每步仅召回与当前 task 相关的决策/约束/追溯片段
- 召回预算纳入 context token 控制
- 冲突时输出 NEED_CLARIFICATION，禁止静默覆盖
```

#### 4.4.1 规则引擎判定（替代语义猜测）

```
判定输入:
- candidate_memory.json (LLM 结构化提名)
- rules.json (由 standards/prd 等文档标准化生成)
- artifact_graph.json (req/module/file/test 关系图)

关键机制:
1) 来源权威不靠语义判断，而靠 source_id 白名单验证
   - candidate 必须引用 source_id
   - source_id 必须存在于 rules.json / requirement index / register index

2) 跨模块影响不靠文本标签，而靠图计算
   - 统计 candidate 关联的 artifact 节点集合
   - 影响节点数 >= 阈值（如 2）判定为跨模块

3) 高失败代价不靠描述，而靠验证系统信号
   - compile/link/runtime/static/hil 错误类型映射风险等级

4) 高复用频率由运行统计给出
   - 最近 N 步召回次数 / 被依赖次数
```

#### 4.4.2 知识标准化（Ingestion）

```
输入文档不直接用于晋升判定，先标准化:
- Docs/standards/*.md -> Docs/ai-generation/knowledge/rules.json
- Docs/prd/*.md -> Docs/ai-generation/knowledge/requirements_index.json
- Docs/hardware/registers/*.json -> Docs/ai-generation/knowledge/register_index.json
- traceability/build graph -> Docs/ai-generation/knowledge/artifact_graph.json

原则:
- 先标准化，再判定
- 无 source_id，不晋升
```

### 4.5 上下文生命周期（核心流程）

```
┌─────────────────────┐
│ TASK: 配置时钟树     │
│ context =            │
│   constitution       │  ← 固定 ~200 tokens
│   state_snapshot     │  ← 固定 ~300 tokens
│   RCC registers      │  ← 只读 RCC 相关
│   PRD 时钟段落       │  ← 只读相关需求
│   = ~1500 tokens     │
└────────┬────────────┘
         │ 完成 → 生成 system_clock.c
         ▼
┌─────────────────────┐
│ CLEAR                │  ← 丢掉 RCC registers, PRD 时钟段落
│ 保留:                │
│   constitution       │
│   state_snapshot     │  ← 更新: "时钟配置完成, SysClk=168MHz"
└────────┬────────────┘
         ▼
┌─────────────────────┐
│ TASK: 配置 UART1     │
│ context =            │
│   constitution       │  ← 同样的 200 tokens
│   state_snapshot     │  ← 更新后的 300 tokens
│   UART registers     │  ← 只读 UART
│   GPIO registers     │  ← 只读 GPIO (配 PA9/PA10)
│   pin_map: UART1     │  ← 只读 UART1 引脚
│   PRD: UART 段落     │  ← 只读相关需求
│   = ~1800 tokens     │
└────────┬────────────┘
         │ 完成 → 生成 uart_driver.c / uart_driver.h
         ▼
┌─────────────────────┐
│ CLEAR                │
│ state 更新: "UART1 驱动完成"
└────────┬────────────┘
         ▼
┌─────────────────────┐
│ TASK: 编译验证       │
│ context =            │
│   constitution       │
│   state_snapshot     │
│   编译错误信息        │  ← 如果有
│   报错文件片段        │  ← 只读报错涉及的函数
│   = ~1200 tokens     │
└─────────────────────┘
```

**关键：上一步的寄存器表不会泄漏到下一步。每步都是独立组装的。**

### 4.6 ContextAssembler 核心代码

```python
class ContextAssembler:
    """核心 IP。给定当前任务，组装最小够用上下文。"""
    
    def __init__(self, project_root: str):
        self.config = load_yaml(f"{project_root}/config.yaml")
        self.constitution = self._load_constitution()
        self.max_tokens = self.config["context"]["max_tokens"]
    
    def assemble(self, task: Task, wm: WorkingMemory, lm: LongMemory) -> str:
        parts = []
        
        # Layer 0: 固定
        parts.append(self.constitution)
        
        # Layer 1a: 短记忆快照
        parts.append(wm.snapshot())

        # Layer 1b: 长记忆相关片段（按任务召回，不全量）
        parts.append(lm.retrieve(task))
        
        # Layer 2: 按任务类型动态组装
        parts.append(self._task_context(task, wm))
        
        # 组装并控量
        context = "\n\n".join(parts)
        return self._enforce_limit(context)
    
    def _task_context(self, task: Task, state: WorkingState) -> str:
        parts = []
        
        if task.type == TaskType.PERIPHERAL_CONFIG:
            # 只读这个外设的寄存器
            parts.append(self._load_registers(task.peripheral))
            # 需要 GPIO 时读 GPIO
            if task.needs_gpio:
                parts.append(self._load_registers("gpio"))
                parts.append(self._load_pin_map(task.peripheral))
            # 只读 PRD 相关段落
            parts.append(self._load_prd_section(task.requirement_id))
            # 时钟依赖
            if task.needs_clock:
                parts.append(self._load_clock_tree())
        
        elif task.type == TaskType.DRIVER_IMPL:
            parts.append(self._load_file(task.header_file))
            parts.append(self._load_coding_standard(topic=task.topic))
            parts.append(self._load_registers(task.peripheral))
        
        elif task.type == TaskType.FIX_ERROR:
            parts.append(task.error_output)
            parts.append(self._load_file_snippet(
                task.error_file, task.error_line, context_lines=15
            ))
            # 根据错误类型加载不同内容
            parts.append(self._error_context(task.error_type))
        
        elif task.type == TaskType.INTEGRATION:
            parts.append(self._load_all_headers())  # 所有 .h 文件
            parts.append(self._load_main_c())
        
        return "\n\n".join(parts)
    
    def _load_registers(self, peripheral: str) -> str:
        """从标准路径读，不硬编码任何 MCU 知识"""
        path = f"{self.config['paths']['registers']}/{peripheral.lower()}.json"
        data = json.load(open(path))
        return format_register_table(data)  # 格式化为紧凑文本
    
    def _enforce_limit(self, context: str) -> str:
        """硬控 token 上限。超了就砍 Layer 2 中优先级最低的部分"""
        if estimate_tokens(context) <= self.max_tokens:
            return context
        # 裁剪策略: 先砍寄存器表中的非关键位域，再砍 PRD 段落
        return truncate_by_priority(context, self.max_tokens)
```

---

## 五、状态机与任务流

### 5.1 状态定义

```python
class Phase(Enum):
    REQUIREMENTS_REVIEW = "requirements_review"
    ARCHITECTURE = "architecture"
    IMPLEMENTATION = "implementation"
    VERIFICATION = "verification"
    DOCUMENTATION = "documentation"
    DONE = "done"
    FAILED = "failed"

class TaskType(Enum):
    PARSE_PRD = "parse_prd"
    CLOCK_CONFIG = "clock_config"
    PERIPHERAL_CONFIG = "peripheral_config"
    DRIVER_IMPL = "driver_impl"
    APP_IMPL = "app_impl"
    INTEGRATION = "integration"
    COMPILE = "compile"
    FIX_ERROR = "fix_error"
    SIMULATE = "simulate"
    DOCUMENT = "document"
```

### 5.2 主循环

```python
class FirmwareAgent:
    def __init__(self, project_root: str):
        self.config = load_config(project_root)
        self.planner = TaskPlanner(self.config)
        self.assembler = ContextAssembler(project_root)
        self.llm = LLMClient(self.config["llm"])
        self.verifier = Verifier(self.config["verification"])
        self.executor = ActionExecutor(project_root)
        self.decision_log = DecisionLog()
        self.state = WorkingState()
    
    def run(self):
        # 1. 任务规划: PRD → 有序子任务列表
        tasks = self.planner.plan(self.config)
        # tasks = [
        #   Task(PARSE_PRD),
        #   Task(CLOCK_CONFIG),
        #   Task(PERIPHERAL_CONFIG, "UART1"),
        #   Task(PERIPHERAL_CONFIG, "I2C1"),
        #   Task(DRIVER_IMPL, "UART1"),
        #   Task(DRIVER_IMPL, "I2C1"),
        #   Task(APP_IMPL),
        #   Task(INTEGRATION),
        #   Task(COMPILE),
        #   Task(SIMULATE),
        #   Task(DOCUMENT),
        # ]
        
        for task in tasks:
            self.state.current_task = task.description
            max_retries = 5
            
            for attempt in range(max_retries):
                # 2. 组装 fresh context（每步独立，不累积）
                context = self.assembler.assemble(task, self.state)
                
                # 3. 调 LLM
                response = self.llm.generate(
                    system=self.state.constitution,
                    context=context,
                    tools=self._tools_for(task)
                )
                
                # 4. 执行动作（写文件、调工具）
                self.executor.execute(response.actions)
                
                # 5. 记录决策
                if response.decisions:
                    self.decision_log.record(task, response.decisions)
                
                # 6. 验证（如果该任务需要）
                if task.needs_verification:
                    result = self.verifier.verify(task, self.state)
                    if result.passed:
                        break
                    # 失败: 分类错误，更新 state，重试
                    error = self.verifier.classify_error(result)
                    self.state.last_error = error.message
                    self.state.retry_count = attempt + 1
                    task.error_type = error.type
                    task.error_output = error.raw
                    continue
                
                # 7. 更新状态（压缩，不是追加）
                self.state.advance(task, response)
                self.state.last_error = ""  # 清空，下一步是全新的
        
        # 8. 生成最终交付物
        if self.state.phase == Phase.DONE:
            self._generate_deliverables()
```

### 5.3 错误分类与恢复策略

```python
class ErrorType(Enum):
    COMPILE_ERROR = "compile_error"        # 语法/类型错误
    LINK_ERROR = "link_error"              # undefined reference
    STATIC_ANALYSIS = "static_analysis"    # cppcheck/clang-tidy warning
    RUNTIME_CRASH = "runtime_crash"        # Hard Fault, assertion
    BEHAVIOR_ERROR = "behavior_error"      # 编译通过但逻辑错
    TIMEOUT = "timeout"                    # 仿真超时

class ErrorClassifier:
    """不同错误需要不同的 context 和恢复策略"""
    
    def classify(self, result: VerifyResult) -> Error:
        if result.compile_failed:
            if "undefined reference" in result.output:
                return Error(ErrorType.LINK_ERROR, result.output)
            return Error(ErrorType.COMPILE_ERROR, result.output)
        
        if result.sim_crashed:
            return Error(ErrorType.RUNTIME_CRASH, result.output)
        
        if result.sim_timeout:
            return Error(ErrorType.TIMEOUT, result.output)
        
        if not result.assertions_passed:
            return Error(ErrorType.BEHAVIOR_ERROR, result.output)
        
        return None

# 不同错误 → 不同的 context 组装策略
ERROR_CONTEXT_STRATEGY = {
    ErrorType.COMPILE_ERROR: [
        "error_output",           # 编译错误信息
        "error_file_snippet",     # 报错文件的相关函数
        "related_headers",        # 相关头文件
    ],
    ErrorType.LINK_ERROR: [
        "error_output",
        "all_source_files_list",  # 所有已生成的 .c 文件列表
        "link_script",            # 链接脚本
        "makefile",               # 构建文件
    ],
    ErrorType.RUNTIME_CRASH: [
        "error_output",
        "startup_file",           # 启动文件
        "vector_table",           # 中断向量表
        "stack_config",           # 栈大小配置
        "clock_init",             # 时钟初始化代码
    ],
    ErrorType.BEHAVIOR_ERROR: [
        "error_output",           # 期望 vs 实际
        "prd_section",            # PRD 对应段落
        "implementation_code",    # 实现代码
        "register_values",        # 相关寄存器配置值
    ],
    ErrorType.TIMEOUT: [
        "error_output",
        "main_loop_code",         # 主循环（可能在死等）
        "interrupt_handlers",     # 中断处理（可能没清标志）
    ],
}
```

---

## 六、验证闭环

### 6.1 验证层级

```
Level 1: 编译
  arm-none-eabi-gcc → 零 error, 零 warning
  最快，覆盖语法/类型/链接错误

Level 2: 静态分析
  cppcheck + clang-tidy + 自定义规则
  覆盖: 未初始化变量、内存泄漏、MISRA 违规

Level 3: 仿真 (QEMU)
  qemu-system-arm → 跑固件 → 读串口输出 → 断言
  覆盖: 运行时崩溃、基本逻辑、外设配置

Level 4: 单元测试
  Unity + Ceedling + 硬件 mock
  覆盖: 函数级逻辑、边界条件

Level 5: HIL (v2)
  pyocd 烧录 → 真实硬件跑 → 串口/GPIO 验证
  覆盖: 时序、真实外设行为、功耗
```

### 6.2 验证器代码

```python
class Verifier:
    def __init__(self, config: dict):
        self.config = config
        self.classifier = ErrorClassifier()
    
    def verify(self, task: Task, state: WorkingState) -> VerifyResult:
        result = VerifyResult()
        
        # Level 1: 编译
        if self.config.get("compile", True):
            result.compile_ok, result.compile_output = self._compile(state)
            if not result.compile_ok:
                return result
        
        # Level 2: 静态分析
        if self.config.get("static_analysis", {}).get("enabled"):
            result.static_ok, result.static_output = self._static_analysis(state)
        
        # Level 3: 仿真
        if self.config.get("simulate", {}).get("enabled"):
            result.sim_ok, result.sim_output = self._simulate(state)
            if result.sim_ok:
                result.assertions_passed = self._check_assertions(result.sim_output)
        
        return result
    
    def _compile(self, state: WorkingState) -> tuple:
        cmd = self.config["toolchain"]["build_cmd"].format(
            bsp=self.config["paths"]["bsp"],
            target=state.project_dir
        )
        output = run_command(cmd, timeout=60)
        return (output.returncode == 0, output.stderr)
    
    def _simulate(self, state: WorkingState) -> tuple:
        qemu_args = self.config["simulate"]["qemu_args"]
        timeout = self.config["simulate"]["timeout_sec"]
        elf = f"{state.project_dir}/build/firmware.elf"
        
        cmd = f"timeout {timeout} qemu-system-arm {qemu_args} -kernel {elf} -serial stdio 2>&1"
        output = run_command(cmd, timeout=timeout + 5)
        
        crashed = "HardFault" in output or "segmentation" in output
        timed_out = output.returncode == 124  # timeout 命令的退出码
        return (not crashed and not timed_out, output.stdout)
    
    def _check_assertions(self, sim_output: str) -> bool:
        """检查仿真输出中的测试断言"""
        # 约定: 固件测试输出 "TEST <ID> PASS" 或 "TEST <ID> FAIL: reason"
        import re
        failures = re.findall(r"TEST \S+ FAIL", sim_output)
        return len(failures) == 0
```

### 6.3 HIL 验证（v2）

```python
class HILVerifier:
    """硬件在环验证。需要物理板子 + 调试器。"""
    
    def __init__(self, config: dict):
        self.probe = config["probe"]           # "stlink" / "jlink"
        self.serial_port = config["serial_port"]
        self.baud = config["baud"]
    
    def flash(self, elf_path: str):
        subprocess.run(
            ["pyocd", "flash", "-t", self.probe, elf_path],
            check=True, timeout=30
        )
    
    def reset_and_run(self):
        subprocess.run(
            ["pyocd", "rtos", "-t", self.probe, "reset"],
            check=True, timeout=10
        )
    
    def capture_serial(self, duration: float = 5.0) -> str:
        import serial
        ser = serial.Serial(self.serial_port, self.baud, timeout=duration)
        data = ser.read_all().decode("utf-8", errors="replace")
        ser.close()
        return data
```

---

## 七、LLM 集成

### 7.1 模型无关接口

```python
class LLMClient:
    """统一接口，底层可换任何模型"""
    
    def __init__(self, config: dict):
        self.provider = config["provider"]
        self.model = config["model"]
        self.max_tokens = config.get("max_tokens", 8192)
        self.temperature = config.get("temperature", 0.1)
        
        if self.provider == "openai_compatible":
            # 本地 Qwen / vLLM / Ollama / llama.cpp
            from openai import OpenAI
            self.client = OpenAI(
                base_url=config["base_url"],
                api_key=config.get("api_key", "unused")
            )
        elif self.provider == "anthropic":
            import anthropic
            self.client = anthropic.Anthropic()
        elif self.provider == "openai":
            from openai import OpenAI
            self.client = OpenAI()
    
    def generate(self, system: str, context: str, tools: list = None) -> LLMResponse:
        if self.provider == "openai_compatible" or self.provider == "openai":
            return self._generate_openai(system, context, tools)
        elif self.provider == "anthropic":
            return self._generate_anthropic(system, context, tools)
    
    def _generate_openai(self, system, context, tools) -> LLMResponse:
        kwargs = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": context},
            ]
        }
        if tools:
            kwargs["tools"] = tools
        
        resp = self.client.chat.completions.create(**kwargs)
        return parse_openai_response(resp)
    
    def _generate_anthropic(self, system, context, tools) -> LLMResponse:
        kwargs = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": context}],
        }
        if tools:
            kwargs["tools"] = tools
        
        resp = self.client.messages.create(**kwargs)
        return parse_anthropic_response(resp)
```

### 7.2 领域 Tools

```python
def build_tools(config: dict) -> list:
    """Agent 可调用的工具。模型不需要"记住"，需要时"查"。"""
    
    return [
        {
            "type": "function",
            "function": {
                "name": "lookup_register",
                "description": "查询 MCU 寄存器的地址、位域定义",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "peripheral": {"type": "string", "description": "外设名，如 UART1, GPIOA, TIM2"},
                        "register": {"type": "string", "description": "寄存器名，如 CR1, BRR, SR"},
                    },
                    "required": ["peripheral"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "lookup_pin",
                "description": "查询引脚分配和复用功能",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "peripheral": {"type": "string"},
                        "signal": {"type": "string", "description": "如 TX, RX, SCL, MOSI"},
                    }
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "read_bsp_header",
                "description": "读取 BSP/HAL 头文件中的函数原型和宏定义",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "file": {"type": "string", "description": "头文件路径，如 stm32f4xx_hal_uart.h"},
                        "keyword": {"type": "string", "description": "搜索的函数名或宏名"},
                    }
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "check_coding_standard",
                "description": "查询编码规范中关于特定主题的规则",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "topic": {"type": "string", "description": "如 isr, naming, error_handling, dma"},
                    }
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "读取项目中的文件",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "start_line": {"type": "integer"},
                        "end_line": {"type": "integer"},
                    },
                    "required": ["path"]
                }
            }
        },
    ]
```

### 7.3 驱动模板（结构骨架，不是完整驱动）

```python
# templates/uart_driver_template.md
# 这是给 LLM 的结构指导，不是直接输出的代码

DRIVER_TEMPLATE = """
## {peripheral} Driver Structure

### Initialization Order (MUST follow):
1. Enable {peripheral} clock (RCC)
2. Configure GPIO pins: {pin_list} (AF{af}, speed, pull)
3. Configure {peripheral} registers:
   - {key_registers_with_descriptions}
4. Enable {peripheral}
5. Configure NVIC: {irqn}, priority {priority}

### ISR Structure (MUST follow):
```c
void {irqn}_Handler(void) {{
    // 1. Check and clear interrupt flag
    // 2. Read data
    // 3. Process (write to ring buffer / callback)
    // 4. NO blocking calls, NO malloc, NO printf
}}
```

### Values to fill from context:
- Clock source and frequency: {clock_info}
- Pin assignments: {pin_map}
- Register addresses: use lookup_register tool
- Baud rate / clock division: calculate from {clock_info}
"""
```

**模板管结构和顺序，LLM 管填值和适配。输出可预测、可验证。**

---

## 八、输出：工程交付物

### 8.1 输出目录

```
/output/
├── firmware/
│   ├── src/
│   │   ├── main.c
│   │   ├── system_clock.c
│   │   ├── gpio_config.c
│   │   ├── uart_driver.c
│   │   ├── i2c_driver.c
│   │   └── app_logic.c
│   ├── inc/
│   │   ├── main.h
│   │   ├── uart_driver.h
│   │   ├── i2c_driver.h
│   │   └── app_logic.h
│   ├── Makefile
│   └── ld/firmware.ld
│
├── docs/
│   ├── design_decisions.md
│   ├── traceability.md
│   └── assumptions.md
│
├── test/
│   ├── test_report.md
│   └── cases/
│       ├── test_uart.c
│       └── test_i2c.c
│
└── build/
    ├── firmware.elf
    ├── firmware.bin
    └── firmware.hex
```

### 8.2 design_decisions.md（自动生成）

```markdown
# Design Decisions

## D-001: UART 使用中断而非 DMA
- **决策**: UART1 RX 使用中断 + ring buffer，不使用 DMA
- **理由**: PRD §3.2 要求波特率 115200，数据率 < 14KB/s，
  中断开销可接受。DMA 增加配置复杂度，无性能收益。
- **来源**: PRD §3.2, coding_standard.md §4.3
- **否决方案**: DMA 模式（复杂度不值得）

## D-002: I2C 时钟配置为 400kHz
- **决策**: I2C1 SCL 频率设为 400kHz
- **理由**: 传感器 (BME280) datasheet 最大 400kHz，
  留 0% 余量。若后续换传感器需重新评估。
- **来源**: hardware/datasheet/BME280.pdf §3.1, PRD §3.3

## D-003: 看门狗使用 IWDG 而非 WWDG
- **决策**: 独立看门狗 (IWDG)，超时 30s
- **理由**: PRD §3.5 要求 30s 超时。IWDG 由 LSI 时钟驱动，
  不受主时钟故障影响。WWDG 依赖 APB1 时钟，主时钟挂掉时失效。
- **来源**: PRD §3.5
```

### 8.3 traceability.md（自动生成）

```markdown
# Requirements Traceability Matrix

| Req ID   | Description              | Implementation         | Function/Module      | Test Case   | Status   |
| -------- | ------------------------ | ---------------------- | -------------------- | ----------- | -------- |
| R-001    | UART1 115200 8N1         | uart_driver.c          | uart_init()          | TC-001      | PASS     |
| R-002    | UART RX interrupt        | uart_driver.c          | UART1_IRQHandler()   | TC-002      | PASS     |
| R-003    | I2C1 BME280 读取         | i2c_driver.c           | bme280_read()        | TC-003      | PASS     |
| R-004    | LED 状态指示             | app_logic.c            | led_update()         | TC-004      | PASS     |
| R-005    | 看门狗 30s               | main.c                 | iwdg_init()          | TC-005      | PASS     |
| R-006    | 低功耗模式               | -                      | -                    | -           | N/A      |
|          | (PRD 未要求，未实现)     |                        |                      |             |          |
```

---

## 九、技术选型

### 9.1 语言

```
主力: Python 3.11+
  理由:
  - Agent 瓶颈是 LLM API (5~30s) 和编译 (1~10s)，不是 CPU 计算
  - 开发速度 >> 运行速度（在这个场景下）
  - AI/LLM 生态 Python 第一
  - C/C++ 开发者 1~2 周可上手

辅助: C/C++（仅用于性能敏感的验证工具，如自定义仿真器）
后期: TypeScript（仅用于 Web UI，如果做产品界面）
```

### 9.2 框架

```
不用: LangChain, CrewAI, AutoGen, LangGraph
  理由: 对话模型 ≠ 状态机模型。需要完全控制 context 组装。

用: 裸 LLM API + 自己写状态机
  核心循环 ~200 行 Python
  完全控制每步注入什么、验证什么、怎么重试
```

### 9.3 依赖

```
核心:
  - openai (或 anthropic)    LLM API 客户端
  - pydantic                 结构化数据验证
  - pyyaml                   配置解析
  - rich                     CLI 输出格式化

验证:
  - arm-none-eabi-gcc        交叉编译 (系统安装)
  - qemu-system-arm          仿真 (系统安装)
  - cppcheck                 静态分析 (系统安装)
  - unity/ceedling           C 单元测试 (系统安装)

数据:
  - sqlite3 (Python 内置)    寄存器表查询
  - pdfplumber               PDF 解析 (一次性数据工程)

可选 (v2):
  - pyocd                    HIL 烧录/调试
  - pyserial                 HIL 串口通信
```

### 9.4 项目结构

```
firmware-agent/
├── pyproject.toml
├── src/
│   └── firmware_agent/
│       ├── __init__.py
│       ├── main.py              # CLI 入口
│       ├── agent.py             # FirmwareAgent 主循环
│       ├── state.py             # WorkingState, Phase, Task
│       ├── planner.py           # TaskPlanner: PRD → 任务列表
│       ├── context/
│       │   ├── assembler.py     # ContextAssembler (核心 IP)
│       │   ├── constitution.py  # Constitution 加载和管理
│       │   └── token_counter.py # Token 估算和裁剪
│       ├── llm/
│       │   ├── client.py        # LLMClient (模型无关)
│       │   ├── tools.py         # 领域 tools 定义和执行
│       │   └── parser.py        # LLM 输出解析
│       ├── knowledge/
│       │   ├── registers.py     # 寄存器表查询
│       │   ├── pin_map.py       # 引脚映射查询
│       │   ├── bsp_index.py     # BSP 头文件索引
│       │   └── standards.py     # 编码规范查询
│       ├── verifier/
│       │   ├── base.py          # Verifier 基类
│       │   ├── compiler.py      # 编译验证
│       │   ├── static.py        # 静态分析
│       │   ├── simulator.py     # QEMU 仿真
│       │   ├── hil.py           # HIL (v2)
│       │   └── classifier.py    # ErrorClassifier
│       ├── executor/
│       │   ├── actions.py       # 执行 LLM 返回的动作
│       │   └── file_ops.py      # 文件读写
│       ├── templates/
│       │   ├── driver_template.py   # 驱动结构模板
│       │   └── project_skeleton.py  # 工程骨架生成
│       ├── docs/
│       │   ├── traceability.py      # 追溯矩阵生成
│       │   ├── decisions.py         # 设计决策文档生成
│       │   └── test_report.py       # 测试报告生成
│       └── config.py            # config.yaml 加载和验证
├── data/
│   └── schemas/
│       ├── register_schema.json     # 寄存器表 JSON Schema
│       ├── pin_map_schema.json      # 引脚映射 JSON Schema
│       └── config_schema.json       # config.yaml Schema
├── tests/
│   ├── test_context_assembler.py
│   ├── test_state_machine.py
│   ├── test_verifier.py
│   └── fixtures/
│       └── sample_project/          # 测试用示例项目
├── examples/
│   └── stm32f407_uart_i2c/         # 完整示例项目
│       ├── config.yaml
│       ├── prd/
│       ├── hardware/
│       ├── bsp/
│       └── standards/
└── scripts/
    └── build_register_db.py         # PDF → JSON 寄存器表 (一次性)
```

### 9.5 跨平台策略（Win 优先，Linux 可平滑接入）

```
结论:
  v0.x 先做 Windows 首发没有问题，但从第一天按“Linux-ready”编码。
  目标是后续 Linux 增量接入，而不是重写。

工程约束（必须执行）:
1) 路径统一使用 pathlib
   - 禁止手拼 "C:\\..." 或 "/..." 字符串路径
   - 所有文件操作走 Path 对象

2) 命令执行统一走 CommandRunner 抽象
   - 业务层禁止直接写 shell 细节
   - Windows 与 Linux 的差异在 runner 层适配

3) 避免 shell 专属命令进入核心流程
   - 禁止在核心逻辑硬编码 timeout/grep/sed 等
   - 优先使用 Python 标准库实现等价功能

4) 工具链路径与参数全部配置化
   - gcc/qemu/cppcheck/pyocd 路径放 config.yaml
   - 不在代码中硬编码可执行文件绝对路径

5) HIL 与串口接口抽象
   - 串口名通过配置提供（Windows: COMx, Linux: /dev/ttyUSBx）
   - 上层调用同一接口，不感知平台差异

6) CI 从早期就采用双平台矩阵
   - windows-latest: 完整 smoke
   - ubuntu-latest: 至少跑核心单测 + dry-run
```

---

## 十、前端界面

### 10.1 策略：CLI 先行，GUI 后续

```
v0.1~v0.5:  CLI (Python, 零额外依赖)
  工程师日常使用，跑 agent、看进度、review 结果
  开发成本最低，反馈最快

v1.0+:  Web GUI (本地服务)
  项目设置向导、实时进度看板、代码浏览、追溯矩阵
  给非开发者（项目经理、硬件工程师）用
```

### 10.2 CLI 前端（v0.1 起）

#### 技术选型

```
  typer        CLI 框架（命令、子命令、参数解析）
  rich         终端美化（表格、语法高亮、进度条、面板）
  不用: Click（typer 更直观）、Curses（太底层）
```

#### 命令设计

```bash
# 项目初始化
fa init ./my-project --mcu STM32F407VGT6
# → 生成标准目录结构 + 空 config.yaml + 模板文件

# 运行 agent
fa run ./my-project
# → 启动自主开发流程，实时显示进度

fa run ./my-project --phase implementation   # 从指定阶段开始
fa run ./my-project --task "UART1 driver"    # 只跑单个任务
fa run ./my-project --dry-run                # 只显示计划，不执行

# 查看状态
fa status ./my-project
# → 当前阶段、已完成任务、进行中任务、错误

# 查看结果
fa report ./my-project
# → 测试报告、追溯矩阵、设计决策

fa code ./my-project --file uart_driver.c    # 查看生成的代码（语法高亮）
fa code ./my-project --diff                  # 查看最近一次修改的 diff

# 查看决策日志
fa decisions ./my-project
# → 所有设计决策及理由

# 配置管理
fa config ./my-project --show                # 显示当前配置
fa config ./my-project --set llm.model gpt-4o  # 修改配置

# 验证（独立运行，不重新生成代码）
fa verify ./my-project
# → 编译 + 静态分析 + 仿真，显示结果

fa verify ./my-project --level compile       # 只编译
fa verify ./my-project --level hil           # 包含 HIL (v2)

# 日志
fa log ./my-project --tail 50                # 最近 50 条日志
fa log ./my-project --task "UART1"           # 某任务的完整日志
```

#### 运行时的终端输出效果

```python
# 用 rich 实现的运行界面（示意）

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.progress import Progress
from rich.syntax import Syntax
from rich.live import Live

console = Console()

def display_run_progress(agent_state):
    """实时显示 agent 运行状态"""
    
    # 顶部: 项目信息 + 当前阶段
    header = Panel(
        f"[bold]{agent_state.project_name}[/bold]  "
        f"[dim]{agent_state.mcu}[/dim]  "
        f"[cyan]Phase: {agent_state.phase.value}[/cyan]",
        title="Firmware Agent",
        border_style="blue"
    )
    
    # 中间: 任务列表（带状态）
    table = Table(title="Tasks")
    table.add_column("#", style="dim")
    table.add_column("Task")
    table.add_column("Status", width=10)
    table.add_column("Duration", width=8)
    
    status_icons = {
        "done": "[green]✓[/green]",
        "running": "[yellow]●[/yellow]",
        "pending": "[dim]○[/dim]",
        "error": "[red]✗[/red]",
        "retry": "[magenta]↻[/magenta]",
    }
    
    for i, task in enumerate(agent_state.tasks):
        table.add_row(
            str(i+1),
            task.description,
            status_icons[task.status],
            task.duration_str
        )
    
    # 底部: 当前 LLM 输出（实时流）
    llm_output = Panel(
        agent_state.current_llm_output[-500:],  # 最近 500 字符
        title="LLM Output",
        border_style="dim"
    )
    
    # 验证状态
    if agent_state.last_verification:
        v = agent_state.last_verification
        verify_panel = Panel(
            f"Compile: {'[green]PASS[/green]' if v.compile_ok else '[red]FAIL[/red]'}\n"
            f"Simulate: {'[green]PASS[/green]' if v.sim_ok else '[red]FAIL[/red]'}\n"
            f"Errors: {v.error_count}",
            title="Verification",
            border_style="green" if v.all_passed else "red"
        )
    
    return [header, table, llm_output, verify_panel]


# 主循环: 用 rich.live 实时刷新
with Live(display_elements, refresh_per_second=2) as live:
    for event in agent.run():
        update_state(event)
        live.update(display_run_progress(state))
```

终端效果示意：

```
┌─────────────────────────────────────────────────────────────────────┐
│ Firmware Agent                                                      │
│ sensor-node-v1  STM32F407VGT6  Phase: implementation                │
├─────────────────────────────────────────────────────────────────────┤
│ Tasks                                                               │
│ ┌───┬────────────────────────────────────┬──────────┬────────┐     │
│ │ # │ Task                               │ Status   │ Time   │     │
│ ├───┼────────────────────────────────────┼──────────┼────────┤     │
│ │ 1 │ Parse PRD, assign requirement IDs  │ ✓        │ 3.2s   │     │
│ │ 2 │ Design clock tree                  │ ✓        │ 5.1s   │     │
│ │ 3 │ Configure GPIO                     │ ✓        │ 4.8s   │     │
│ │ 4 │ Implement UART1 driver             │ ●        │ 12.3s  │     │
│ │ 5 │ Implement I2C1 driver              │ ○        │        │     │
│ │ 6 │ Implement app logic                │ ○        │        │     │
│ │ 7 │ Integration & main                 │ ○        │        │     │
│ │ 8 │ Compile & verify                   │ ○        │        │     │
│ │ 9 │ Generate documentation             │ ○        │        │     │
│ └───┴────────────────────────────────────┴──────────┴────────┘     │
├─────────────────────────────────────────────────────────────────────┤
│ LLM Output                                                          │
│ ...HAL_UART_Init(&uart_handle);                                     │
│   if (HAL_UART_Receive_IT(&uart_handle, ...) != HAL_OK) {           │
├─────────────────────────────────────────────────────────────────────┤
│ Verification                                                        │
│ Compile: PASS                                                       │
│ Simulate: PASS                                                      │
│ Errors: 0                                                           │
└─────────────────────────────────────────────────────────────────────┘
```

#### CLI 代码结构

```python
# src/firmware_agent/cli.py
import typer
from rich.console import Console
from rich.table import Table
from rich.syntax import Syntax
from rich.live import Live

app = typer.Typer(name="fa", help="Firmware Agent - Autonomous embedded firmware development")
console = Console()

@app.command()
def init(
    project_dir: str = typer.Argument(...),
    mcu: str = typer.Option(..., help="MCU part number"),
    bsp_path: str = typer.Option(None, help="Path to existing BSP"),
):
    """Initialize a new firmware project with standard structure."""
    # 创建标准目录结构
    # 生成 config.yaml 模板
    # 生成空的 prd/requirements.md 模板
    # 生成 standards/ 模板
    ...

@app.command()
def run(
    project_dir: str = typer.Argument(...),
    phase: str = typer.Option(None, help="Start from specific phase"),
    task: str = typer.Option(None, help="Run single task only"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    verbose: bool = typer.Option(False, "-v"),
):
    """Run the autonomous firmware development agent."""
    config = load_config(project_dir)
    agent = FirmwareAgent(project_dir)
    
    if dry_run:
        display_plan(agent.planner.plan(config))
        return
    
    # 实时显示进度
    run_with_live_display(agent, phase=phase, task=task, verbose=verbose)

@app.command()
def status(project_dir: str = typer.Argument(...)):
    """Show current project status."""
    state = load_state(project_dir)
    display_status_table(state)

@app.command()
def report(project_dir: str = typer.Argument(...)):
    """Display test report and traceability matrix."""
    ...n
@app.command()
def code(
    project_dir: str = typer.Argument(...),
    file: str = typer.Option(None, "--file", "-f"),
    diff: bool = typer.Option(False, "--diff"),
):
    """View generated code with syntax highlighting."""
    if diff:
        # 显示最近修改的 diff
        ...n    elif file:
        content = read_file(f"{project_dir}/output/firmware/{file}")
        console.print(Syntax(content, "c", line_numbers=True))
    else:
        # 列出所有生成的文件
        ...

@app.command()
def verify(
    project_dir: str = typer.Argument(...),
    level: str = typer.Option("all", help="compile|static|simulate|hil|all"),
):
    """Run verification without regenerating code."""
    ...

@app.command()
def log(
    project_dir: str = typer.Argument(...),
    tail: int = typer.Option(50, help="Number of lines"),
    task: str = typer.Option(None, help="Filter by task"),
):
    """View agent execution log."""
    ...

@app.command()
def decisions(project_dir: str = typer.Argument(...)):
    """View design decision log."""
    ...


if __name__ == "__main__":
    app()
```

### 10.3 Web GUI（v1.0+）

#### 技术选型

```
后端:  FastAPI (Python, 跟 agent 同进程或子进程)
  - REST API + WebSocket (实时进度推送)
  - 复用 agent 的所有模块，不重复造轮子

前端:  二选一
  方案 A: React + TypeScript + TailwindCSS
    生态大，组件多，但重
  方案 B: Svelte + TypeScript
    轻量，开发快，适合工具类应用
  
  推荐方案 B（工具类应用不需要 React 那套生态）

部署:  本地 localhost
  fa serve --port 8080
  浏览器打开 http://localhost:8080
  不需要云端，代码不出内网
```

#### 页面设计

```
┌─────────────────────────────────────────────────────────────────────────┐
│  Firmware Agent                    [Project: sensor-node-v1]  [Settings]│
├────────┬────────────────────────────────────────────────────────────────┤
│        │                                                                │
│  SIDEBAR│  MAIN AREA                                                    │
│        │                                                                │
│  📁 Project│  ┌─────────────────────────────────────────────────────┐  │
│   config  │  │  PROGRESS DASHBOARD                                  │  │
│   prd     │  │                                                     │  │
│   hardware│  │  [██████████░░░░░░░░░░░░] 50% - Implementation      │  │
│   bsp     │  │                                                     │  │
│   output  │  │  Phase: implementation                              │  │
│        │  │  Current: Implement UART1 driver (attempt 2/5)         │  │
│  📊 Status│  └─────────────────────────────────────────────────────┘  │
│   phase   │                                                                │
│   tasks   │  ┌────────────────────┬─────────────────────────────────┐  │
│   errors  │  │  CODE VIEWER       │  VERIFICATION                   │  │
│        │  │  uart_driver.c       │                                 │  │
│  📄 Output│  │  ┌───────────────┐ │  ✅ Compile    (1.2s)           │  │
│   code    │  │  │ 42  void     │ │  ✅ Static     (0.8s)           │  │
│   docs    │  │  │     UART_Init│ │  ● Simulate   (running...)      │  │
│   trace   │  │  │ 43  {        │ │  ○ Unit Test                    │  │
│   report  │  │  │ 44    HAL_   │ │  ○ HIL                          │  │
│        │  │  └───────────────┘ │                                 │  │
│  📋 Log  │  └────────────────────┴─────────────────────────────────┘  │
│   llm     │                                                                │
│   decisions│ ┌─────────────────────────────────────────────────────────┐  │
│   errors  │  │  LLM OUTPUT (live stream)                               │  │
│        │  │  ...                                                        │  │
└────────┴────────────────────────────────────────────────────────────────┘
```

#### 核心页面

| 页面              | 功能                                                     | 对应数据源                      |
| ----------------- | -------------------------------------------------------- | ------------------------------- |
| **Dashboard**     | 项目总览：阶段进度、当前任务、验证状态、token 用量       | agent state                     |
| **Tasks**         | 任务列表：每个任务的状态、耗时、重试次数、错误           | task history                    |
| **Code Viewer**   | 浏览生成的代码，语法高亮，点击行号看对应的 PRD 需求      | output/firmware/ + traceability |
| **Verification**  | 验证结果：编译输出、仿真日志、测试用例 pass/fail         | verifier results                |
| **Traceability**  | 需求追溯矩阵：PRD 需求 → 代码 → 测试，可交互筛选         | traceability.md                 |
| **Decisions**     | 设计决策日志：每个决策、理由、来源、否决方案             | decision_log                    |
| **Config Editor** | 可视化编辑 config.yaml，表单化，带验证                   | config.yaml                     |
| **Log Viewer**    | 完整执行日志，可按任务/时间/级别过滤                     | execution log                   |
| **Project Setup** | 新项目向导：选 MCU → 指定 BSP 路径 → 上传 PRD → 配置验证 | init flow                       |

#### 后端 API 设计

```python
# src/firmware_agent/server.py
from fastapi import FastAPI, WebSocket
from fastapi.staticfiles import StaticFiles

app = FastAPI(title="Firmware Agent API")

# === 项目 ===
@app.get("/api/projects")
def list_projects():
    """列出所有项目"""
    ...

@app.post("/api/projects")
def create_project(config: ProjectConfig):
    """创建新项目（初始化标准目录结构）"""
    ...

@app.get("/api/projects/{name}/config")
def get_config(name: str):
    """获取项目配置"""
    ...

@app.put("/api/projects/{name}/config")
def update_config(name: str, config: ProjectConfig):
    """更新项目配置"""
    ...

# === 运行控制 ===
@app.post("/api/projects/{name}/run")
def start_run(name: str, options: RunOptions = None):
    """启动 agent 运行"""
    ...

@app.post("/api/projects/{name}/stop")
def stop_run(name: str):
    """停止当前运行"""
    ...

@app.get("/api/projects/{name}/status")
def get_status(name: str):
    """获取当前状态（阶段、任务、进度）"""
    ...

# === 实时进度 (WebSocket) ===
@app.websocket("/ws/projects/{name}/stream")
async def progress_stream(websocket: WebSocket, name: str):
    """实时推送: LLM 输出、任务状态变更、验证结果"""
    await websocket.accept()
    async for event in agent_event_bus.subscribe(name):
        await websocket.send_json(event)
    
    # event 类型:
    # {"type": "task_start", "task": "UART1 driver", "timestamp": ...}
    # {"type": "llm_token", "text": "void UART_"}
    # {"type": "llm_done", "tokens_used": 1234}
    # {"type": "verify_start", "level": "compile"}
    # {"type": "verify_result", "level": "compile", "passed": true}
    # {"type": "task_done", "task": "UART1 driver", "duration": 12.3}
    # {"type": "error", "task": "UART1 driver", "error_type": "compile", "message": ...}
    # {"type": "retry", "task": "UART1 driver", "attempt": 2}

# === 输出 ===
@app.get("/api/projects/{name}/code/{filepath}")
def get_code(name: str, filepath: str):
    """获取生成的代码文件"""
    ...

@app.get("/api/projects/{name}/code/{filepath}/trace")
def get_code_trace(name: str, filepath: str):
    """获取代码行的需求追溯信息"""
    ...

@app.get("/api/projects/{name}/report")
def get_report(name: str):
    """获取测试报告"""
    ...

@app.get("/api/projects/{name}/traceability")
def get_traceability(name: str):
    """获取需求追溯矩阵"""
    ...

@app.get("/api/projects/{name}/decisions")
def get_decisions(name: str):
    """获取设计决策日志"""
    ...

@app.get("/api/projects/{name}/log")
def get_log(name: str, task: str = None, level: str = None, limit: int = 100):
    """获取执行日志"""
    ...

# === 验证 ===
@app.post("/api/projects/{name}/verify")
def run_verification(name: str, level: str = "all"):
    """独立运行验证（不重新生成代码）"""
    ...


# 启动
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8080)
```

#### CLI 与 GUI 的关系

```
┌─────────────────────────────────────────────────────────┐
│  CLI (typer)              Web GUI (FastAPI + Svelte)     │
│  fa run                   fa serve                       │
│  fa status                Dashboard                      │
│  fa code -f xxx.c         Code Viewer                    │
│  fa report                Traceability + Report          │
│  fa verify                Verification                   │
│  fa log                   Log Viewer                     │
│  fa decisions             Decisions                      │
├─────────────────────────────────────────────────────────┤
│  共用同一个核心:                                          │
│  FirmwareAgent / ContextAssembler / Verifier / State     │
│                                                         │
│  CLI 直接调用 Python 函数                                 │
│  GUI 通过 REST API + WebSocket 调用同一套函数             │
│                                                         │
│  不是两套系统，是一个引擎两个壳                            │
└─────────────────────────────────────────────────────────┘
```

### 10.4 前端开发节奏

```
Phase 0~1 (第 1~6 周):
  只有 CLI。rich 输出够用。
  不要分心做 GUI。

Phase 2 (第 7~12 周):
  CLI 完善（fa report, fa code, fa verify 等子命令齐全）
  开始搭 FastAPI 后端（把 agent 状态暴露为 API）
  不写前端，用 curl / httpie 测试 API

Phase 3 (第 3~4 月):
  前端开发（Svelte + TypeScript）
  先做 Dashboard + Code Viewer + Verification 三个核心页面
  其他页面按需加

Phase 4 (第 5~6 月):
  完善: Project Setup 向导、Config Editor、Traceability 交互
  性能优化、错误处理、边缘情况
  打包: 单二进制 (PyInstaller) 或 Docker
```

### 10.5 前端技术栈总结

| 层       | 技术                             | 理由                                        |
| -------- | -------------------------------- | ------------------------------------------- |
| CLI 框架 | typer                            | Python 原生，类型提示，自动 help            |
| CLI 显示 | rich                             | 表格/高亮/进度条/Live 更新，一个库全搞定    |
| Web 后端 | FastAPI                          | 异步、自动 OpenAPI 文档、WebSocket 原生支持 |
| Web 前端 | Svelte + TypeScript              | 轻量、快、适合工具类应用                    |
| 前端样式 | TailwindCSS                      | 快速布局，不用写 CSS                        |
| 代码高亮 | Shiki (前端) / rich.syntax (CLI) | C 语言高亮                                  |
| 实时通信 | WebSocket                        | LLM 输出流、任务状态变更                    |
| 部署     | 本地 localhost                   | 代码不出内网，嵌入式客户刚需                |

---

## 十一、开发路线图

### Phase 0: 验证核心假设（第 1~2 周）

```
目标: 一个 Python 脚本，LLM 生成 UART 驱动，gcc 编译通过

Day 1-2: 环境搭建
  - Python 3.11+, pip install openai pyyaml rich
  - arm-none-eabi-gcc 安装
  - 最小 STM32 工程骨架（startup, system_clock, HAL, 链接脚本）
  - 本地 LLM 确认能调通 (Qwen3.8-27B via vLLM/Ollama)
  - 定义跨平台基线：路径用 pathlib、命令统一经 CommandRunner
  - 明确 v0 首发平台为 Windows，并保留 Linux smoke 运行能力

Day 3-4: 最小 agent 循环
  - 一个 prompt → LLM 生成 uart_driver.c/h
  - 写文件 → 跑 gcc → 看结果
  - 编译失败 → 把 error 喂回去 → 重试 (最多 3 次)

Day 5-7: 评估
  - 3 次重试内编译通过率多少？
  - 生成的代码质量如何？（能看吗？结构对吗？）
  - 哪里最丑？→ 这就是 v0.1 要解决的

交付: agent_v0.py (~100 行) + 示例工程
```

### Phase 1: 核心引擎（第 3~6 周）

```
目标: 状态机 + ContextAssembler + 验证闭环

Week 3:
  - WorkingState 实现
  - ContextAssembler 实现（分层、按任务类型组装）
  - Constitution 定义
  - 寄存器表 JSON 格式定稿 + 查询模块
  - pin_map.json 格式定稿

Week 4:
  - TaskPlanner: PRD → 有序任务列表
  - 状态机主循环
  - 错误分类器
  - 编译 + QEMU 仿真验证

Week 5:
  - 驱动模板（结构骨架）
  - 领域 tools (lookup_register, read_bsp_header, ...)
  - 决策日志

Week 6:
  - 集成测试: 完整跑一个 UART + I2C + LED 项目
  - 输出工程交付物（不只是 .c，还有 Makefile、文档）
  - 边界情况处理

交付: firmware-agent v0.1，能自主完成简单项目
```

### Phase 2: 工程化（第 7~12 周）

```
目标: 可靠、可配置、可交付

Week 7-8:
  - process_spec.yaml 驱动流程（客户可定制流程）
  - 编码规范引擎（从 standards/ 加载规则，验证时检查）
  - 知识标准化管线（standards/prd/registers -> rules/index JSON）
  - artifact graph 构建（req/module/file/test 关系）
  - 需求追溯矩阵自动生成
  - design_decisions.md 自动生成
  - 测试报告生成

Week 9-10:
  - 多外设支持（SPI, CAN, ADC, DAC, TIM...）
  - 中断优先级自动分配
  - 内存分配检查（RAM/Flash 不超）
  - 静态分析集成 (cppcheck + 自定义规则)

Week 11-12:
  - 错误恢复策略完善（每类错误的 context 组装）
  - 重试策略（不是简单重试，是换策略重试）
  - 记忆晋升规则引擎（LLM 提名 + 程序判定）
  - source_id 白名单校验与冲突检测
  - 日志和调试工具
  - 跨平台适配收口：CommandRunner、ToolchainResolver、SerialAdapter
  - CI 双平台矩阵（Windows + Linux）与回归基线
  - 文档

交付: firmware-agent v0.5，能处理中等复杂度项目
```

### Phase 3: 产品化（第 3~6 月）

```
目标: 给第一个客户用

  - HIL 验证（pyocd + 串口 + GPIO 检查）
  - KiCad netlist 导入（自动生成 pin_map.json）
  - 多 MCU 家族验证（STM32, GD32, ESP32）
  - CLI 工具完善（项目初始化、进度查看、结果导出）
  - 第一个真实客户项目
  - 根据客户反馈迭代

交付: firmware-agent v1.0
```

---

## 十二、关键风险与应对

| 风险                            | 影响                     | 应对                                                        |
| ------------------------------- | ------------------------ | ----------------------------------------------------------- |
| LLM 生成代码质量不稳定          | 编译通过率低，重试次数多 | 驱动模板约束结构；Constitution 硬规则；足够重试次数         |
| 本地模型 (Qwen3.8-27B) 能力不够 | 复杂任务完成率低         | 关键步骤用云端强模型；简单填值用本地模型；混合策略          |
| 寄存器表数据质量                | 错误地址 → 代码全错      | JSON Schema 验证；交叉校验（多个来源）；编译时检查          |
| QEMU 仿真覆盖有限               | 仿真通过但硬件不工作     | v2 加 HIL；仿真只作为必要非充分条件                         |
| 客户 PRD 质量参差               | 需求不完整 → 实现偏差    | requirements_review 阶段强制检查；[NEED_CLARIFICATION] 机制 |
| 上下文裁剪丢失关键信息          | LLM 缺少必要信息 → 错误  | token 预算监控；裁剪时优先保留寄存器地址和接口定义          |
| 范围蔓延                        | 想支持所有 MCU 所有外设  | 先做 1 个 MCU 家族 + 5 个常见外设，跑通再扩                 |
| 平台耦合（只在 Windows 跑通）   | Linux 适配成本激增        | Day1 起执行跨平台约束（pathlib/runner 抽象/配置化命令）+ CI 矩阵 |
| 语义判定不稳定（晋升靠感觉）     | 长记忆污染，错误固化       | LLM 仅提名；规则引擎按 source_id + artifact_graph + 验证信号判定 |

---

## 十三、精神内核（设计哲学）

### 12.1 上下文即产品

> 这个产品的核心不是"让 LLM 写代码"，是**在正确的时间给 LLM 正确的信息，且只给这些**。
>
> ContextAssembler 是核心 IP。状态机是骨架。验证闭环是安全网。LLM 是可替换的零件。
>
> 换模型不用改架构。换 MCU 不用改代码。换流程不用改引擎。

### 12.2 不信任，只验证

> LLM 会说"我写好了"。你不信。
> 编译过了吗？仿真跑通了吗？断言通过了吗？
> 没通过就是没通过。喂回错误，重试。
>
> 这不是对 LLM 的不尊重，是对工程的尊重。

### 12.3 状态是快照，不是历史

> 不要"记住我们之前做了什么"。
> 要"知道现在在哪里"。
>
> WorkingMemory 是 400 token 的快照，不是 40000 token 的对话历史。
> 长记忆也不是聊天记录，而是 decisions/constraints/traceability 的结构化数据。
> 上一步的寄存器表跟这一步无关？那就别放在 context 里。

### 12.4 领域知识是数据，不是代码

> Agent 不知道 STM32F407 的 UART1 基地址是 0x40011000。
> 它知道去 `/project/hardware/registers/uart.json` 查。
>
> 你的嵌入式经验体现在：
> - 寄存器表的格式设计
> - 驱动模板的结构和顺序
> - 错误分类和恢复策略
> - Constitution 里的硬规则
> - 验证断言的设计
>
> 这些是数据和方法论，不是硬编码在 agent 里的 if-else。

### 12.5 先丑后美

> 第一周的代码一定是丑的。
> 一个 100 行的脚本，硬编码的 prompt，简单的正则解析。
> 它能跑就行。
>
> 不要第一周就设计微服务。
> 不要第一周就支持 10 种 MCU。
> 不要第一周就做 Web UI。
>
> 先让一个 UART 驱动编译通过。然后加一个 I2C。然后加验证。然后加文档。
> 每一步都是可运行的。

### 12.6 速度在外部

> Agent 的瓶颈是 LLM 响应 (20s) 和编译 (5s)，不是你的 Python 代码 (0.001s)。
> 优化 context 长度比优化代码语言重要 1000 倍。
> 选更快的模型比选更快的编程语言重要 100 倍。
> 减少不必要的重试比优化重试逻辑重要 10 倍。

---

## 附录 A: 最小可运行示例（Phase 0）

```python
#!/usr/bin/env python3
"""
agent_v0.py - 最小固件生成 agent
目标: LLM 生成 UART 驱动 → 写文件 → 编译 → 失败则重试
"""

import os
import re
import subprocess
import sys

try:
    from openai import OpenAI
except ImportError:
    print("pip install openai")
    sys.exit(1)

# === 配置 ===
LLM_CONFIG = {
    "base_url": os.environ.get("LLM_BASE_URL", "http://localhost:8080/v1"),
    "api_key": os.environ.get("LLM_API_KEY", "unused"),
    "model": os.environ.get("LLM_MODEL", "Qwen3.8-27B"),
}

WORK_DIR = "./firmware_output"
COMPILER = "arm-none-eabi-gcc"
CPU_FLAGS = "-mcpu=cortex-m4 -mthumb"
MAX_RETRIES = 3

SYSTEM_PROMPT = """\
You are an embedded firmware engineer specializing in ARM Cortex-M MCUs.
You write complete, compilable C code using the STM32 HAL library.

Rules:
- Always include necessary #include directives
- Use HAL library API (HAL_UART_Init, HAL_UART_Receive_IT, etc.)
- ISR: no blocking calls, no malloc, no printf
- Shared variables: volatile
- Initialization order: clock → GPIO → peripheral → enable → NVIC

Output format: Mark each file with:
// ===== FILE: relative/path =====
<code>
// ===== END =====
"""

USER_PROMPT = """\
Write a UART1 driver for STM32F407VGT6.

Requirements:
- UART1, 115200 baud, 8N1
- PA9 (TX), PA10 (RX), AF7
- RX interrupt with ring buffer (size 256)
- System clock: 168MHz from 8MHz HSE via PLL
- APB2 clock: 168MHz

Files to generate:
1. uart_driver.h - public interface
2. uart_driver.c - implementation including ISR

Assume HAL is already initialized (HAL_Init, system clock configured).
"""


def extract_files(text: str) -> dict:
    """从 LLM 输出中提取文件"""
    files = {}
    pattern = r'// ===== FILE: (\S+) =====\n(.*?)(?:// ===== END =====|$)'
    for match in re.finditer(pattern, text, re.DOTALL):
        files[match.group(1)] = match.group(2).strip() + "\n"
    
    # 回退: 尝试 ```c 代码块
    if not files:
        pattern2 = r'```c\s*\n(.*?)(?:\n```|$)'
        matches = re.findall(pattern2, text, re.DOTALL)
        if matches:
            files["uart_driver.c"] = matches[0].strip() + "\n"
    
    return files


def write_files(files: dict):
    os.makedirs(WORK_DIR, exist_ok=True)
    for name, content in files.items():
        path = os.path.join(WORK_DIR, name)
        os.makedirs(os.path.dirname(path), exist_ok=True) if '/' in name else None
        with open(path, 'w') as f:
            f.write(content)
        print(f"  wrote: {name} ({len(content)} bytes)")


def compile_firmware() -> tuple:
    """编译所有 .c 文件，返回 (success, error_output)"""
    c_files = []
    for f in os.listdir(WORK_DIR):
        if f.endswith('.c'):
            c_files.append(os.path.join(WORK_DIR, f))
    
    if not c_files:
        return False, "No .c files found"
    
    cmd = (
        f"{COMPILER} {CPU_FLAGS} "
        f"-I{WORK_DIR} "
        f"-I./bsp/include "          # HAL 头文件路径（按实际调整）
        f"-DSTM32F407xx "
        f"-DUSE_HAL_DRIVER "
        f"-c {' '.join(c_files)} "
        f"-o /dev/null "
        f"2>&1"
    )
    
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return result.returncode == 0, result.stderr


def main():
    client = OpenAI(
        base_url=LLM_CONFIG["base_url"],
        api_key=LLM_CONFIG["api_key"],
    )
    
    messages = [{"role": "user", "content": USER_PROMPT}]
    
    for attempt in range(1, MAX_RETRIES + 1):
        print(f"\n{'='*60}")
        print(f"  Attempt {attempt}/{MAX_RETRIES}")
        print(f"{'='*60}")
        
        # 1. 调 LLM
        print("  Calling LLM...")
        response = client.chat.completions.create(
            model=LLM_CONFIG["model"],
            max_tokens=8000,
            temperature=0.1,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                *messages
            ]
        )
        code = response.choices[0].message.content
        print(f"  LLM responded: {len(code)} chars")
        
        # 2. 提取并写文件
        files = extract_files(code)
        if not files:
            print("  WARNING: Could not extract files, trying fallback...")
            files = {"uart_driver.c": code}
        
        write_files(files)
        
        # 3. 编译
        print("  Compiling...")
        ok, errors = compile_firmware()
        
        if ok:
            print(f"\n  ✅ COMPILE SUCCESS (attempt {attempt})")
            print(f"  Output in: {WORK_DIR}/")
            return 0
        
        # 4. 失败，准备重试
        print(f"  ❌ COMPILE FAILED:")
        print(f"  {errors[:500]}")
        
        if attempt < MAX_RETRIES:
            messages.append({"role": "assistant", "content": code})
            messages.append({
                "role": "user",
                "content": (
                    f"Compilation failed:\n{errors}\n\n"
                    "Fix the code. Output the complete corrected files "
                    "with // ===== FILE: ... ===== markers."
                )
            })
    
    print(f"\n❌ FAILED after {MAX_RETRIES} attempts")
    return 1


if __name__ == "__main__":
    sys.exit(main())
```

```bash
# 运行
export LLM_BASE_URL="http://localhost:8080/v1"
export LLM_MODEL="Qwen3.8-27B"
python agent_v0.py
```

---

## 附录 B: 寄存器表 JSON Schema

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "MCU Peripheral Register Map",
  "type": "object",
  "required": ["peripheral", "base_address", "registers"],
  "properties": {
    "peripheral": {
      "type": "string",
      "description": "外设名称，如 UART1, GPIOA, TIM2"
    },
    "base_address": {
      "type": "string",
      "pattern": "^0x[0-9A-Fa-f]+$",
      "description": "外设基地址"
    },
    "clock": {
      "type": "string",
      "enum": ["AHB1", "AHB2", "AHB3", "APB1", "APB2", "ADC", "LSE", "HSE"],
      "description": "所属时钟总线"
    },
    "registers": {
      "type": "object",
      "additionalProperties": {
        "type": "object",
        "required": ["offset", "description"],
        "properties": {
          "offset": {
            "type": "string",
            "pattern": "^0x[0-9A-Fa-f]+$"
          },
          "address": {
            "type": "string"
          },
          "description": {
            "type": "string"
          },
          "access": {
            "type": "string",
            "enum": ["RW", "RO", "WO", "RC", "SC"]
          },
          "reset_value": {
            "type": "string"
          },
          "bits": {
            "type": "object",
            "additionalProperties": {
              "type": "object",
              "required": ["pos", "width", "desc"],
              "properties": {
                "pos": {"type": "integer", "minimum": 0},
                "width": {"type": "integer", "minimum": 1},
                "reset": {"type": "integer"},
                "desc": {"type": "string"},
                "values": {
                  "type": "object",
                  "description": "枚举值，如 {\"0\": \"8-bit\", \"1\": \"9-bit\"}"
                }
              }
            }
          }
        }
      }
    },
    "interrupts": {
      "type": "object",
      "properties": {
        "IRQn": {"type": "string"},
        "IRQ_number": {"type": "integer"}
      }
    },
    "dma_channels": {
      "type": "object",
      "properties": {
        "rx": {
          "type": "object",
          "properties": {
            "dma": {"type": "string"},
            "channel": {"type": "integer"},
            "request": {"type": "integer"}
          }
        },
        "tx": {
          "type": "object",
          "properties": {
            "dma": {"type": "string"},
            "channel": {"type": "integer"},
            "request": {"type": "integer"}
          }
        }
      }
    },
    "errata": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "id": {"type": "string"},
          "description": {"type": "string"},
          "workaround": {"type": "string"}
        }
      },
      "description": "芯片勘误及 workaround"
    }
  }
}
```

---

## 附录 C: 与通用 Coding Agent 的对比

| 维度     | 通用 Agent (Cursor/Cline/pi)   | 本产品                         |
| -------- | ------------------------------ | ------------------------------ |
| 驱动模型 | 用户对话驱动                   | 状态机自主驱动                 |
| Context  | 对话历史累积                   | 每步 fresh 组装，< 3000 tokens |
| 领域知识 | 无（靠 LLM 训练数据）          | 外部数据（寄存器表、规范）     |
| 验证     | 无 / 用户手动                  | 自动编译→仿真→断言             |
| 错误恢复 | "你再试试"                     | 分类→策略→重试                 |
| 输出     | 代码片段                       | 完整工程 + 文档 + 追溯         |
| 换 MCU   | 改 prompt 祈祷                 | 换 JSON 文件 + config.yaml     |
| 流程     | 无                             | process_spec.yaml 可配置       |
| 可追溯   | 无                             | 需求→代码→测试 全链路          |
| 模型     | 绑定特定 LLM                   | 模型无关，可热切换             |

---

*End of Document*
