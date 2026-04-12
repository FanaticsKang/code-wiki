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

运行脚本：

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

创建骨架文件时，把占位符替换为步骤 1 中获取的真实值（项目名、一句话介绍、初步判断等）。日期用 `date +%Y-%m-%d` 获取。

### 校验

骨架创建完成后，运行 `scan.py plan` 确认文件清单符合预期：

```bash
python .code-wiki/scan.py plan
```

重点检查：
- 文件数量是否合理（和步骤 1 观察到的目录规模匹配）
- 使用了 `--folder` 时，确认只包含指定目录下的文件
- 没有意外包含 `wiki/`、`.code-wiki/`、`node_modules/` 等应排除的目录

## 步骤 4：展示扫描计划

向用户展示扫描计划：

```bash
python .code-wiki/scan.py plan --limit 30
```

`--limit 30` 限制只显示前 30 个文件，避免文件太多刷屏。

把输出展示给用户，告诉他：

- 你打算按这个顺序扫（浅层优先，由 `scan.py` 的排序策略决定）
- 输出中带 `[LARGE]` 标记的文件超过 800 行，会分批读（详情参见`scan.py`）
- 每扫完一个文件你会做什么（更新 files/modules/concepts/architecture/refactor）
- 是要你一口气扫到底，还是每 N 个停一次汇报

**得到确认后**，进入扫描循环（见 `workflow-scan.md`）。**如果是被 scan 流程自动触发到此的，确认后直接返回 scan 主循环继续执行。**

## 常见陷阱

- **别在用户没确认范围之前就开扫**。多问一句不会死。
- **别把根目录的 `README.md`, `CLAUDE.md`这样的文件写进 `files/`**——那是项目自己的文档，不是你要总结的源码。
- **别在 architecture.md 里瞎猜后就不管了**——它是在扫描过程中持续更新的，不是一次性写死的。
