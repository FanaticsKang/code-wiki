# 扫描流程（workflow-scan）

这是 skill 的主循环。初始化完成后，主 agent 负责调度 sub-agent 扫描文件，并汇总跨文件发现。

## 流程概述

扫描流程的目标是**逐文件处理整个仓库**，为每个源码文件生成 wiki 页面，同时提炼出跨文件的架构、概念和算法。

三方分工：

- **scan.py**：管理文件状态（哈希比对、待处理清单），不读代码。它告诉你"下一个该处理谁"以及"这个文件处理完了没"。
- **主 agent（你）**：调度 sub-agent、处理汇报、更新跨文件页面（modules/concepts/algorithm/architecture/refactor）、维护 log.json 和 index.md。
- **sub-agent**：读源码、生成 files 页、返回 JSON 汇报。按语言分为 Python/C++/Generic 三种。

## 主循环一览

```
repeat:
    1. scan.py next-folder              → 拿到一个文件夹下所有待处理文件
    2. 按扩展名分组，选择对应 sub-agent
    3. 按批次并行派发 sub-agent（默认每批 3 个，用户可在 config.json 覆盖）
    4. 等待当前批次所有 sub-agent 返回汇报
    5. 收集所有汇报，统一处理：
       a. 验证 files 页已创建
       b. 从汇报中提取 log 记录，批量写入 log.json
       c. 按汇报建议更新跨文件页面
          - wiki/modules/<模块>.md         ← 多数情况需要
          - wiki/concepts/<概念>.md        ← 只在引入新概念时
          - wiki/algorithm/<算法>.md       ← 只在发现算法/流水线时
          - wiki/architecture.md           ← 只在架构级发现时
          - wiki/refactor.md               ← 只在发现问题时
       d. 更新 index.md
       e. scan.py mark-done <path>（逐个执行）
    6. 文件夹级汇报
until 无待处理 或 用户打断
```

**每完成一个文件夹的所有文件后，做一次简短汇报**（不暂停，继续扫描）：这个文件夹里新建了哪些模块/概念页，architecture 有什么新认识，refactor 新增了几条。用户随时可以打断调整方向。

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

## 定向扫描

上面的主循环默认按最浅文件夹优先处理所有待处理文件。如果只想分析特定目录或文件，可以在 `scan.py` 的子命令中加 `--folder` 或 `--file` 过滤：

```bash
# 只看 core/ 下的待处理文件
python .code-wiki/scan.py plan --folder=core/

# 只取 core/dag/ 下一个待处理文件
python .code-wiki/scan.py next --folder=core/dag

# 只处理特定文件
python .code-wiki/scan.py next --file=core/dag/executor.py

# 取 core/dag/ 文件夹下所有待处理文件
python .code-wiki/scan.py next-folder --folder=core/dag
```

使用定向扫描时，主循环中的 `scan.py next-folder` 替换为 `scan.py next-folder --folder=<target>`（或 `--file=<path>`），其余流程不变。

## 每处理完一批 sub-agent 的检查清单

**前置条件（不满足就不能 mark-done）：**
- [ ] `wiki/files/<映射>.md` 已存在（用 `ls` 验证）

**批次汇总检查：**
- [ ] log.json 已批量写入（从汇报 JSON 中提取完整记录，一次性追加）
- [ ] 汇报 `cross_file_updates.modules` 非 null 时，modules 页已更新
- [ ] 汇报 `cross_file_updates.concepts` 非 null 时，concepts 页已处理
- [ ] 汇报 `cross_file_updates.algorithms` 非 null 时，algorithm 页已更新
- [ ] architecture.md 已更新（如适用）
- [ ] refactor.md 已追加条目（如适用）
- [ ] `wiki/index.md` 已登记新页面
- [ ] `python .code-wiki/scan.py mark-done <path>` 已逐个执行

## scan.py 速查

`scan.py` 是本 skill 自带的扫描器，位于 `.code-wiki/scan.py`。它**不读代码**（那是 sub-agent 的工作），它做的是：遍历仓库按扩展名和 `.gitignore` 筛出源码文件、计算哈希对比上次状态、输出待处理清单、维护 `.code-wiki/state.json`。

所有子命令都支持 `--folder=<path>` 和 `--file=<path>` 过滤参数（定向扫描时使用）。

| 子命令 | 用途 |
|--------|------|
| `init` | 首次初始化：创建 wiki 骨架，扫描全仓库生成待处理清单 |
| `rescan` | 重新扫描仓库，和 state 对比，刷新清单 |
| `plan` | 查看当前待处理清单（默认列出前 50 个） |
| `next` | 拿下一个待处理文件 |
| `next-folder` | 拿当前最浅文件夹下所有待处理文件 |
| `mark-done <file>` | 标记一个文件处理完毕 |
| `status` | 查看整体进度 |

常用诊断命令：

```bash
python .code-wiki/scan.py status          # 查看整体进度
python .code-wiki/scan.py plan            # 查看待处理清单
grep -rn <pattern> <dir>                  # 全目录搜索，找引用关系
rg <pattern>                              # ripgrep，比 grep 快
```

脚本的完整用法见脚本本身的 `--help`。
