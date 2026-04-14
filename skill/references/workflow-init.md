# 初始化流程（workflow-init）

当用户首次让你为一个代码仓库建 wiki 时，按这个流程走。**不要跳步**，尤其不要跳过和用户的确认——在错误的方向上扫 100 个文件比多聊两分钟贵得多。

## 步骤 1：浅层概览

只读这些东西，**不读具体代码**：

- 仓库根目录的 `ls` 结果（`ls -la` 或 `view` 根目录）
- 根目录的 `README*`、`CHANGELOG*`、`CONTRIBUTING*`
- 构建/依赖文件：`package.json`、`pyproject.toml`、`requirements.txt`、`Cargo.toml`、`go.mod`、`pom.xml`、`build.gradle`、`Makefile`、`Dockerfile`、`docker-compose*`
- 配置入口：`.env.example`、`config/`、`settings.*`
- 顶层的目录结构（不展开到叶子，看一两层即可）

基于这些，回答给用户这几件事：

1. 这是个什么项目？（语言、框架、大致用途）
2. 主要目录在哪？看起来哪几个是核心，哪几个是辅助（测试、脚本、文档、示例、配置）？
3. 入口文件可能是哪个？
4. 有没有已有的架构文档？

### DL 仓库检测（步骤 1：内存计算）

在浅层概览中额外计算是否为深度学习训练仓库。检测规则见 SKILL.md（两级信号：必要信号 + 辅助信号），**执行时遵循"浅层概览"原则**：

1. **必要信号检查**（浅层）：
   - 检查依赖文件（`requirements.txt` / `pyproject.toml` / `setup.py` / `setup.cfg`）是否包含 DL 框架（torch / tensorflow / jax / transformers / accelerate 等）
   - **如果依赖文件未提供明确信号**，可快速 grep 源码文件的前 10 行查找 import 语句（避免深入阅读代码）
2. **辅助信号检查**（浅层）：
   - 训练入口文件：存在 `train*.py` / `run*.py` / `pretrain*.py` / `finetune*.py` / `trainer*.py`（仅检查文件名，不读内容）
   - 模型定义目录：存在 `model/` / `models/` / `network/` / `nets/` / `backbone/` / `arch/`（仅检查目录名，不读内部文件）
   - 数据集模块：存在 `dataset*.py` / `datamodule*.py` / `dataloader*.py` / `data.py` / `collator*.py`（仅检查文件名）
   - HuggingFace 生态：存在 `transformers` 等 import（通过 grep 前几行）

**判定**：必要信号未命中 → `dl_repo = false`。必要信号命中 + 任意一条辅助信号命中 → `dl_repo = true`。

**此时不写入文件**，将 `dl_repo` 布尔值保留在内存中，供步骤 3 使用。

如果后续发现检测有误，用户可直接修改 `wiki/README.md` 的 `dl_repo` 字段，无需重新 init。

## 步骤 2：和用户确认扫描计划

**如果用户已通过 `--folder`/`--file` 指定了范围**，跳过本步骤，直接用用户指定的范围。

**否则，用 `AskUserQuestion` 工具让用户选择要扫描的目录**（multiSelect: true，允许全选）。根据步骤 1 看到的目录结构，列出主要目录作为选项。例如：

```
AskUserQuestion:
  question: "要扫描哪些目录？"
  multiSelect: true
  options:
    - label: "src/"
    - label: "tests/"
    - label: "scripts/"
    - label: "examples/"
```

根据用户选择的结果拼接 `--folder` 参数传给 `scan.py init`。如果用户全选或选了大部分，不传 `--folder`（即扫描全部）。

## 步骤 3：搭建 wiki 骨架

先部署扫描脚本到工作目录：

```bash
mkdir -p .code-wiki && cp .claude/skills/code-wiki/scripts/scan.py .code-wiki/scan.py
```

然后运行初始化：

```bash
python .code-wiki/scan.py init
```

这会：
- 创建 `wiki/`、`wiki/files/`、`wiki/modules/`、`wiki/concepts/`、`wiki/algorithm/`
- 创建 `.code-wiki/state.json`
- 扫描仓库，列出所有源码文件

如果用户在步骤 2 中确认了特定范围（如只要 `src/core/`），加 `--folder` 参数限定：

```bash
python .code-wiki/scan.py init --folder=src/core/
```

`--folder` 和 `--file` 决定了 state.json 中注册哪些文件，即 wiki 的**扫描范围**。后续 scan 流程只处理这些已注册的文件。

然后**你手动**（用 `Write` 工具）创建骨架文件。需要创建的文件和初始内容见 `references/init-skeletons.md`。需要创建的文件清单：

- `wiki/README.md` — 入口页
- `wiki/index.md` — 内容目录
- `wiki/log.json` — 处理日志
- `wiki/architecture.md` — 架构总览（先写初步猜测，扫描过程中持续更新）
- `wiki/refactor.md` — 重构清单（初始为空骨架）
- `wiki/hypothesis.md` — 工作假设 v1（**必须创建**，模板见 references/hypothesis-guide.md）

创建骨架文件时，把占位符替换为步骤 1 中获取的真实值（项目名、一句话介绍、初步判断等）。日期用 `date +%Y-%m-%d` 获取。

**DL 仓库处理**：根据步骤 1 计算的内存 `dl_repo` 值：
- 如果 `dl_repo` 为 `true`：
  - `architecture.md` 使用增强版骨架（含模型拓扑、训练阶段、扩展点、复现命令的占位段落）
  - `README.md` 的 frontmatter 中设置 `dl_repo: true`
- 如果 `dl_repo` 为 `false`：
  - `README.md` 的 frontmatter 中设置 `dl_repo: false`（非 DL 仓库标记）

**这是首次将 `dl_repo` 写入磁盘**。后续所有 DL 分支逻辑都读这个 frontmatter 标志。

### 校验

骨架创建完成后，运行 `scan.py plan` 确认文件清单符合预期：

```bash
python .code-wiki/scan.py plan
```

重点检查：
- 文件数量是否合理（和步骤 1 观察到的目录规模匹配）
- 使用了 `--folder` 时，确认只包含指定目录下的文件
- 没有意外包含 `wiki/`、`.code-wiki/`、`node_modules/` 等应排除的目录

## 步骤 3.5：产出 hypothesis v1

基于步骤 1 的浅层概览，产出第一版工作假设。模板和规则见 `references/hypothesis-guide.md`。

**关键**：此时你还没读过任何源码细节，hypothesis v1 应该是"粗糙但全局"的——不要假装你已经知道答案。置信度填 "low"，大部分核心抽象和数据流都标为猜测。

重要："我还不确定的"和"我预期会看到但还没看到的"这两节要认真填——它们会决定第一批扫描读什么。

如果 DL 检测为 true，hypothesis v1 的"我还不确定的"中追加 DL 特有问题：
- 模型的主干架构是什么？
- 训练分几个阶段，每个阶段的损失函数是什么？
- 数据从原始格式到模型输入经过哪些变换？
- 有哪些预训练权重，如何加载？

产出 v1 后，展示给用户看，问一句："我目前是这样理解这个项目的，有没有明显误解？"

**用户反馈的处理**：

- 如果用户没有纠正 → hypothesis.md 保持 v1
- 如果用户有少量纠正 → 直接在 v1 基础上修订，仍叫 v1（不 bump version，因为还没做过反思）
- 如果用户大幅纠正（例如"你理解错了，这不是 DAG 执行器，这是个 RPC 框架"）→ 整段重写 hypothesis.md，但仍叫 v1（同上）

hypothesis version 的递增只发生在**扫描后的反思步骤**，用户反馈不触发版本递增。

**产出完成的标志**：hypothesis.md 的内容已根据用户反馈修订，用户认可了当前版本。然后进入步骤 4，基于这份修订后的 v1 产出首批阅读计划。

## 步骤 4：展示首批阅读计划（不是整体扫描计划）

不再展示 `scan.py plan` 的全部文件列表（那是文件系统视角）。改为展示**基于 hypothesis v1 的首批阅读计划**：

- 首批要读的 3-8 个文件（入口 + 最核心的抽象定义）
- 每个文件要回答 hypothesis 里的哪个问题
- 预计读完首批后，hypothesis 的置信度能提到哪种程度

剩余文件仍然通过 `scan.py plan` 可查，但**不承诺阅读顺序**——顺序由 hypothesis 演化决定。

得到用户确认后，init 流程结束。提醒用户可以执行 `/code-wiki scan` 开始扫描。

## 常见陷阱

- **别在用户没确认范围之前就开扫**。多问一句不会死。
- **别把根目录的 `README.md`, `CLAUDE.md`这样的文件写进 `files/`**——那是项目自己的文档，不是你要总结的源码。
- **别在 architecture.md 里瞎猜后就不管了**——它是在扫描过程中持续更新的，不是一次性写死的。
