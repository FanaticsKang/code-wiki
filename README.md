# code-wiki

Claude Code skills + agents 分发包，包含两个 skill：

- **code-wiki**：为任意代码仓库增量构建中文 wiki，帮助理解和重构代码
- **module-test-gen**：半自动化的模块级测试生成工具，扫描代码仓库、生成配置、运行测试

## 安装

```bash
./install.sh /path/to/target/project
```

安装完成后，目标项目的 `.claude/skills/` 下会包含两个 skill，通过 Claude Code 调用对应命令即可启动。

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

## 反向同步

如果在目标项目中修改了 skill/agent 文件，可以同步回本仓库：

```bash
./sync_from_project.sh /path/to/project_with_code_wiki
```

## 目录结构

```
code-wiki/
├── install.sh                # 安装脚本
├── sync_from_project.sh      # 反向同步脚本
├── skills/
│   ├── code-wiki/            # 中文 wiki 构建技能
│   │   ├── SKILL.md
│   │   ├── references/       # 各子命令工作流指南
│   │   └── scripts/scan.py   # 增量扫描器（纯 Python，无第三方依赖）
│   └── module-test-gen/      # 模块测试生成技能
│       ├── SKILL.md
│       ├── references/       # 语言特定的扫描和生成规则
│       ├── scripts/          # 扫描、生成、运行脚本（依赖 pyyaml）
│       └── templates/        # 配置文件模板
└── agents/                   # 按语言拆分的 sub-agent（code-wiki 专用）
```
