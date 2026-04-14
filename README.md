# code-wiki

为任意代码仓库增量构建中文 wiki 的 Claude Code skill 分发包。

通过 `/code-wiki` 命令在目标项目中启动，自动扫描源码并生成结构化的中文文档，帮助理解和重构代码。

## 安装

```bash
./install.sh /path/to/target/project
```

安装完成后，在目标项目中使用 Claude Code 执行 `/code-wiki init` 即可开始。

## 使用

在已安装的目标项目中，通过 Claude Code 调用：

| 命令 | 说明 |
|---|---|
| `/code-wiki init` | 初始化 wiki 目录结构 |
| `/code-wiki scan` | 增量扫描源码，生成/更新 wiki 页面 |
| `/code-wiki query` | 查询 wiki 内容 |
| `/code-wiki lint` | 检查 wiki 一致性 |

## 生成的 wiki 结构

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
├── skill/
│   ├── SKILL.md              # Skill 主定义
│   ├── references/           # 各子命令工作流指南
│   └── scripts/scan.py       # 增量扫描器（纯 Python，无第三方依赖）
└── agents/                   # 按语言拆分的 sub-agent（Python/C++/Generic）
```
