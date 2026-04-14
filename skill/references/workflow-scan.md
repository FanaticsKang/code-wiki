# 扫描流程（workflow-scan）

这是 skill 的主循环。初始化完成后，主 agent 负责调度 sub-agent 扫描文件，并汇总跨文件发现。

## 流程概述

扫描流程的目标是**逐文件处理整个仓库**，为每个源码文件生成 wiki 页面，同时提炼出跨文件的架构、概念和算法。

三方分工：

- **scan.py**：管理文件状态（哈希比对、待处理清单），不读代码。它告诉你"下一个该处理谁"以及"这个文件处理完了没"。
- **主 agent（你）**：调度 sub-agent、处理汇报、更新跨文件页面（modules/concepts/algorithm/architecture/refactor）、维护 log.json 和 index.md。
- **sub-agent**：读源码、生成 files 页、返回 JSON 汇报。按语言分为 Python/C++/Generic 三种。

## 初始化检测

进入主循环前，先检查仓库是否已完成初始化：

1. 检查 `.code-wiki/state.json` 是否存在
   - **不存在** → 仓库尚未初始化。提示用户先执行 `/code-wiki init` 完成初始化，然后重新执行 scan。
   - **存在** → 直接进入主循环。

## 主循环一览

```
repeat:
    0. 确认 hypothesis.md 存在且是最新版，主 agent 上下文里已载入
    1. 基于 hypothesis.md 决定本批读哪些文件（不再用 scan.py next-folder 机械排序）
       - 首批：入口 + 核心抽象定义
       - 后续批：能最大压缩 hypothesis 不确定性的文件
       - 末期：填充细节的文件
       - 最后：胶水/边角料（可以大批量、浅扫）
    2. 按扩展名分组，选择对应 sub-agent
    3. 派发 sub-agent，每个 prompt 中注入：
       - 文件路径、仓库根目录、输出目录（同现有设计）
       - ★ 当前 hypothesis.md 完整内容（新增）
       - ★ 该文件已知的直接依赖/被依赖（从 import 提取，新增）
       - ★ 邻居文件的一句话摘要（如果已扫过，新增）
    4. 等待当前批次所有 sub-agent 返回汇报
    5. 收集汇报，统一处理：
       a. 验证 files 页已创建
       b. 批量写入 log.json
       c. 按汇报更新跨文件页面（modules/concepts/algorithm/architecture/refactor）
       d. 更新 index.md
       e. scan.py mark-done
    6. ★ 走完整的反思步骤（见 references/reflection-checklist.md）（新增，不可跳过）
       - 处理 hypothesis_feedback.contradicts
       - 更新 hypothesis.md（必要时整段重写核心抽象/数据流）
       - 检查老页面一致性（必要时整段重写）
       - 决定下一批读什么
    7. 文件夹级汇报（简短，让用户知道进展）
until hypothesis 已收敛且 pending 文件只剩边角料（pending 文件全部为 test/config/doc/script 目录下的文件，或剩余 pending 数 < 5）或 用户打断
```

## 批次选择策略：两阶段

主循环的步骤 1 "决定本批读哪些文件"分两阶段，由 hypothesis 的 confidence 决定：

**阶段 A：假设驱动阶段**（hypothesis.md 的 confidence 为 low 或 medium）

主 agent **自由选文件**，忽略 scan.py next-folder 的顺序。选择标准：
- 优先读 hypothesis.md "本轮将重点验证" 列出的文件
- 其次读入口、核心抽象的定义、被 contradicts 频繁指向的模块
- 一批 3-8 个文件，跨目录没关系，重要的是"能最大压缩 hypothesis 不确定性"

这一阶段**不走 scan.py next-folder**，直接读 state.json 里的 pending 列表，按 hypothesis 选。选完后 `mark-done` 留到该批所有 sub-agent 返回并完成反思后统一执行。

**阶段 B：系统性填充阶段**（hypothesis.md 的 confidence 为 high 且连续 2 批扫描没触发实质修改）

hypothesis 已收敛，剩下的多是胶水代码和边角料。此时回落到 `scan.py next-folder` 的文件夹级派发，走原有的按文件夹并行批次，只是每个 sub-agent 拿到的 hypothesis 仍然是完整的（它们读起来会很快，因为大多数文件只是填充）。

**阶段切换的判断**：每次反思步骤的步骤 8 写 log 时，记一条 `stage: A` 或 `stage: B`。如果连续 2 次反思都认为 hypothesis 已收敛，下一批切到 B。

**阶段 B 回退**：如果在阶段 B 中某批扫描的反思发现了 contradicts（与 hypothesis 冲突），立即回退到阶段 A（假设驱动阶段）。回退原因记录在反思 log 中。连续 2 次反思无 contradicts 后再尝试切回 B。

**阶段性汇报**：阶段 A（跨目录批次）每批完成后做一次简短汇报，不按文件夹汇报。阶段 B（按文件夹）每完成一个文件夹的所有文件后做一次简短汇报。汇报内容：新建了哪些模块/概念页，architecture 有什么新认识，refactor 新增了几条。用户随时可以打断调整方向。

## Sub-agent 调度规则

### 扩展名 → agent 映射

| 扩展名 | sub-agent |
|--------|-----------|
| `.py`, `.pyi` | `code-wiki-python-scanner` |
| `.c`, `.h`, `.cc`, `.cpp`, `.cxx`, `.hpp`, `.hh`, `.hxx`, `.m`, `.mm` | `code-wiki-cpp-scanner` |
| 其他所有 `scan.py` 列出的扩展名 | `code-wiki-generic-scanner` |

### 并行派发策略

**按文件夹为单元派发**：`scan.py next-folder` 返回当前最浅文件夹下所有待处理文件。主 agent 按扩展名分组后，将文件分配给对应 sub-agent 并行派发。

**批次大小**：默认每批 3 个 sub-agent 并行。可在 `.code-wiki/config.json` 的 `batch_size` 字段覆盖。如果文件夹文件数超过 batch_size，分多批处理，每批完成后再发下一批。

**文件夹间串行**：一个文件夹的所有批次完成后，做文件夹级汇报，然后调用 `scan.py next-folder` 获取下一个文件夹。

### 派发时必须注入的 preamble

派发任何 sub-agent 前，主 agent 必须在 prompt 中嵌入以下 preamble（在任务说明之前）。**所有 `<...>` 占位符必须替换为实际值，不允许透传字面量**：

```
## 项目整体认知（来自 wiki/hypothesis.md v<N>）

<完整粘贴 hypothesis.md 当前内容>

## 本文件的已知上下文

* 所属模块：<从路径推断>
* 直接依赖（import/include）：<从源文件头部提取，给出路径>
* 被本项目其他文件依赖：<如有，从已扫过的文件汇报里反查>
* 邻居文件摘要（同目录已扫过的文件）：
    * <file1>：<一句话>
    * <file2>：<一句话>

## 阅读期望

根据 hypothesis，本文件预期在项目中扮演的角色：<主 agent 的猜测，1-2 句>
请在汇报的 hypothesis_feedback 字段里明确回应：这个猜测对不对。
```

sub-agent 收到这份 preamble 后，带着全局视角去读单个文件，而不是冷启动。

每个 sub-agent 的 prompt 必须包含：
1. 文件路径（相对仓库根目录）
2. 仓库根目录的绝对路径
3. 输出目录的绝对路径

派发示例（以 Python 文件为例）：

```
请扫描以下文件并生成 wiki 页面：
- 文件路径: path/to/target/file
- 仓库根目录: /Users/example/project
- 输出目录: /Users/example/project/wiki/files/
```

### sub-agent 完成后的验证

sub-agent 完成后，主 agent **必须验证** files 页已创建：
```bash
for f in <expected_files>; do test -f "wiki/files/$f" || echo "MISSING: $f"; done
```

如果发现 MISSING 文件，按以下两级策略逐级恢复：

**第 1 级：重新派发 sub-agent（最多重试 3 次）**
- 用相同参数重新派发对应类型的 sub-agent
- prompt 中追加："上次扫描未能创建 files 页 `wiki/files/<映射>.md`，请重新扫描源文件并确保创建该页面"
- 每次重试后重新验证，3 次均失败则进入第 2 级
- 重试成功 → 正常 mark-done

**第 2 级：主 agent 补建占位 files 页**
- 3 次重试均失败后，主 agent 尝试读取源文件：
  - **可读取**：创建含 frontmatter + 一句话定位的极简版
  - **不可读取**（编码/权限/损坏等）：创建仅含 frontmatter 和失败原因的占位页
- frontmatter 中加 `incomplete: true` 标志，表示此文件未被 sub-agent 正式扫描
- 后续可通过 `grep -rl "incomplete: true" wiki/files/` 找出所有未正式处理的文件
- 然后 `mark-done --note "主 agent 补建占位页，未正式处理"`

## 处理 sub-agent 汇报

sub-agent 完成后会返回一份 JSON 汇报，格式如下：

```json
{
  "date": "<YYYY-MM-DD>",
  "action": "scan",
  "file": "<相对路径>",
  "files_page": "<输出目录相对于仓库根的路径>/<映射名>.md",
  "status": "created",
  "cross_file_updates": {
    "modules": ["<模块名>: <原因>", "..."] 或 null,
    "concepts": ["<概念名>: <原因>", "..."] 或 null,
    "algorithms": ["<算法名>: <原因>", "..."] 或 null,
    "architecture": "<描述> 或 null",
    "refactor": ["<条数及概述>", "..."] 或 null
  },
  "hypothesis_feedback": {
    "confirms": ["<证实了 hypothesis 的哪些点>"],
    "contradicts": ["<和 hypothesis 冲突的点>"],
    "new_observations": ["<hypothesis 没提到但本文件暴露出来的东西>"]
  },
  "members": [ ... ]
}
```

主 agent 收集完当前批次所有汇报后，统一处理：

1. **验证** files 页确实存在（sub-agent 可能误报）
2. **批量写入 log.json**：从每个汇报中提取完整 JSON 对象，一次性追加到 `wiki/log.json`
3. **读取**每个汇报的 `cross_file_updates`，找出值为非 null 的字段
4. **按下方"判断跨文件页面更新"规则**，决定是否采纳并更新对应页面
5. **更新 index.md**，登记新创建的页面
6. **执行** `scan.py mark-done <path>`（逐个执行）

### 批量写入 log.json 的方法

```bash
python3 -c "
import json, pathlib
p = pathlib.Path('wiki/log.json')
data = json.loads(p.read_text()) if p.exists() else []
# 将当前批次所有 sub-agent 汇报的 JSON 依次追加
for record in [<record1>, <record2>, ...]:
    data.append(record)
p.write_text(json.dumps(data, ensure_ascii=False, indent=2))
"
```

## 判断跨文件页面更新

sub-agent 会在汇报中建议更新哪些跨文件页面。主 agent 需要根据以下规则判断是否采纳，以及如何更新。

### modules 页（大多数文件需要）

满足以下任一条即需要更新对应 modules 页：
- 文件属于某个模块目录（如 `core/dag/` → `modules/core__dag.md`）
- 文件定义了对外提供的服务、接口或工具
- 文件包含业务逻辑

modules 页重点是**"这个模块对外承担什么职责"**——对外接口、内部结构、和其他模块的关系、数据流入流出。

### concepts 页（只在引入新概念时）

满足以下任一条：
- 引入了一个跨多文件出现的领域实体或术语（例如"订单"、"权限规则"）
- 定义了会被多处使用的核心数据结构
- 体现了一个贯穿项目的设计模式（例如仓储模式、观察者、状态持有者）

concepts 页重点是**"这是什么"**——定义、字段、关系、和其他概念的区别。

### algorithm 页（只在发现算法/流水线时）

只要文件承载下列任一类内容，就要建或更新对应的 algorithm 页：

- **通用算法或其变体**：排序、查找、图、解析器、编码/解码、哈希、压缩、加解密、近似算法
- **业务核心算法**：推荐打分、风控规则、匹配、调度策略、价格/计费计算、搜索排序、路由决策、状态机转移规则
- **数据处理流水线**：ETL、特征工程、数据清洗、聚合、批处理、流式处理的多步变换
- **关键计算逻辑**：有非平凡复杂度的计算、需要注意边界条件的处理、有性能敏感点的代码

algorithm 页重点是**"怎么一步步从输入变成输出"**——输入输出、步骤、复杂度、关键不变量、边界条件、为什么这么设计、可疑点。

**和 concepts 页的边界**：如果一个东西既是概念又是算法，主体写到 algorithm/，concepts/ 里只留 1-3 行的指针。不要两边都写详细版。

**什么时候不要硬建 algorithm 页**：如果一个文件只是简单的 CRUD、字段映射、薄封装，**即使它是"业务核心"也不要建 algorithm 页**——因为没有算法可写。硬写出来的只会是对代码的复述，既稀释真正有算法的页面的价值，也浪费用户的注意力。**宁缺毋滥**。

### algorithm DL 页（DL 仓库专属）

DL 仓库（`wiki/README.md` frontmatter 中 `dl_repo: true`）在扫描模型和数据文件时，额外触发以下页面创建：

| 条件 | 创建页面 |
|------|---------|
| 扫描了 `model/` 目录下的文件，且 `algorithm/模型拓扑.md` 尚未存在 | 创建 `algorithm/模型拓扑.md` |
| 扫描了 `datasets/` / `datamodules/` / `transforms/` 目录下的文件，且 `algorithm/数据集.md` 尚未存在 | 创建 `algorithm/数据集.md` |
| 上述两者都已创建，且 `algorithm/数据流.md` 尚未存在 | 创建 `algorithm/数据流.md` |
| 扫描的模型文件中发现可独立描述的组件（如 Encoder、Decoder、Loss 类） | 创建 `<组件名>.md`，`category` 标为 `模型组件` |

模板见 `page-templates.md` 的 DL 专属模板。DL 页面创建后同步更新 index.md 的 algorithm 区段。

### architecture.md（只在架构级发现时）

满足以下任一条：
- 这是系统的入口（main、web 路由注册、CLI 入口）
- 这里定义了模块间的组织方式（依赖注入容器、插件注册表）
- 这里展示了重要的外部依赖（数据库连接、消息队列、外部 API 客户端）
- 这里揭示了一条完整的数据流

### refactor.md（只在发现问题时）

满足以下任一条：
- 明显的 bug 或竞争条件
- 死代码 / 未使用的导出
- 注释声明的意图和实现不符
- 循环依赖
- God class、God function（单个类/函数承担过多职责）
- 神秘的魔法值、硬编码
- 错误处理吞异常
- TODO / FIXME / XXX 注释

每一条 refactor 条目必须注明来源文件和大致行号。

## 每处理完一批 sub-agent 的检查清单

**阶段 1：验证 sub-agent 产出**
- [ ] 所有 sub-agent 的 `wiki/files/<映射>.md` 已存在（`ls` 验证）
- [ ] 所有汇报 JSON 已收集完整，`hypothesis_feedback` 字段齐全
- [ ] 缺失文件已通过两级恢复策略处理

**阶段 2：记录和状态更新（可以失败重来，不影响数据）**
- [ ] 批量写入 log.json（sub-agent 汇报 JSON 作为记录）
- [ ] 按汇报更新 modules/concepts/algorithm/architecture/refactor 页面
- [ ] 更新 index.md
- [ ] **执行 scan.py mark-done（逐个执行，此时本批文件的处理状态固化）**

**阶段 3：反思（必须完整走，见 reflection-checklist.md）**
- [ ] 步骤 1：收集 contradicts 信号
- [ ] 步骤 2：收集 new_observations
- [ ] 步骤 3：更新 hypothesis.md（含可能的整段重写）
- [ ] 步骤 4：检查老页面一致性（含可能的整段重写）
- [ ] 步骤 5：检查"预期但还没看到"
- [ ] 步骤 6：更新 refactor.md（含老条目复查）
- [ ] 步骤 7：决定下一批读什么（写入 hypothesis.md 的"本轮将重点验证"）
- [ ] 步骤 8：log.json 写入反思记录（含 stage: A/B 标记）

**关键：阶段 3 不能跳**。如果阶段 3 发现某个文件被 sub-agent 严重误读需要重扫，执行 `scan.py mark-pending <path>` 把它标回 pending，下一批重新派发。

