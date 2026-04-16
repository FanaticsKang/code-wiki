# code-wiki

Claude Code skills + agents 分发包。

## Skills 概览

### 核心 Skills（默认安装）

- **code-wiki**：为任意代码仓库增量构建中文 wiki，帮助理解和重构代码
- **module-test-gen**：半自动化的模块级测试生成工具，扫描代码仓库、生成配置、运行测试

### 可选 Skills（`--full` 安装）

- **unit-test-gen**：单元测试生成工具，支持 Python（pytest）和 C++（Google Test）
- **paper-code-deepdive**：论文-代码深度对比分析工具，四阶段流水线定位论文创新点并与代码实现逐项对比

## 安装

```bash
# 安装核心 skills（code-wiki、module-test-gen）
./install.sh /path/to/target/project

# 安装全部 skills（含可选 skill）
./install.sh --full /path/to/target/project
```

安装完成后，目标项目的 `.claude/skills/` 下会包含对应 skill，通过 Claude Code 调用命令即可启动。

## 使用

### code-wiki

在已安装的目标项目中，通过 Claude Code 调用：

| 命令 | 说明 |
|---|---|
| `/code-wiki init` | 初始化 wiki 目录结构 |
| `/code-wiki scan` | 增量扫描源码，生成/更新 wiki 页面 |
| `/code-wiki query` | 查询 wiki 内容 |
| `/code-wiki lint` | 检查 wiki 一致性 |

生成的 wiki 结构：

```
wiki/
├── README.md           # wiki 入口
├── index.md            # 文件索引
├── architecture.md     # 架构概览
├── files/              # 每个源文件一页
├── modules/            # 每个模块一页
├── concepts/           # 静态结构（数据结构、术语、设计模式）
└── algorithm/          # 动态过程（核心算法、数据流水线）
```

### module-test-gen

在已安装的目标项目中，通过 Claude Code 调用：

| 命令 | 说明 |
|---|---|
| `/module-test-gen init` | 扫描仓库，生成测试配置（index.yml + 各模块 YAML） |
| `/module-test-gen generate` | 补充自动发现的相关代码和测试目标 |
| `/module-test-gen run` | 根据配置生成测试代码并执行，输出报告 |

工作流：

```
init → （工程师审查配置）→ generate → （工程师审查配置）→ run
```

每个配置项标记 `source: manual`（工程师指定）或 `source: auto`（Claude 生成），工程师始终能区分来源。

生成的测试配置结构：

```
test-config/
├── index.yml           # 模块索引
├── modules/            # 各模块配置 YAML
└── reports/            # 测试报告（markdown）
```

### paper-code-deepdive（可选）

配对论文与开源代码进行深度对比分析。四阶段流水线：

1. **Stage 1**：从论文 PDF 定位核心创新点（使用 `extract_innovations.py`）
2. **Stage 2**：分析论文材料——文本、公式、图表三源交叉验证（使用 `analyze_figures.py`）
3. **Stage 3**：在代码仓库中定位实现（使用 `locate_implementation.py`）
4. **Stage 4**：深度对比出报告，揭示论文未提及的实现细节（使用 `deep_compare.py`）

适用场景：想复现某篇论文、怀疑代码与论文不一致、或想深入了解"代码实际做了什么"。

## 反向同步

如果在目标项目中修改了 skill/agent 文件，可以同步回本仓库：

```bash
./sync_from_project.sh /path/to/project_with_code_wiki
```

## 目录结构

```
code-wiki/
├── install.sh                # 安装脚本（--full 安装可选 skills）
├── sync_from_project.sh      # 反向同步脚本
├── skills/
│   ├── code-wiki/            # 中文 wiki 构建技能 [核心]
│   │   ├── SKILL.md
│   │   ├── references/       # 各子命令工作流指南
│   │   └── scripts/scan.py   # 增量扫描器（纯 Python，无第三方依赖）
│   ├── module-test-gen/      # 模块测试生成技能 [核心]
│   │   ├── SKILL.md
│   │   ├── references/       # 语言特定的扫描和生成规则
│   │   ├── scripts/          # 扫描、生成、运行脚本（依赖 pyyaml）
│   │   └── templates/        # 配置文件模板
│   ├── unit-test-gen/        # 单元测试生成技能 [可选]
│   │   ├── SKILL.md
│   │   ├── references/
│   │   └── scripts/
│   └── paper-code-deepdive/  # 论文-代码深度对比 [可选]
│       ├── SKILL.md
│       ├── references/       # 创新点识别、图表分析、隐藏细节清单、报告模板
│       ├── scripts/          # 四阶段脚本（依赖 pdfplumber/pymupdf）
│       └── examples/         # Flamingo 完整示例
└── agents/                   # 按语言拆分的 sub-agent（code-wiki 专用）
```
