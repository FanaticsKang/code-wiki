123123
# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目简介

code-wiki 是一个 Claude Code skill + agents 分发包，用于为任意代码仓库增量构建和维护中文 wiki。本仓库本身**不是**最终运行的项目，而是一个安装源：通过 `install.sh` 将 skill 和 agents 安装到目标项目的 `.claude/` 目录下，目标项目中使用 `/code-wiki` 命令启动。

## 常用命令

```bash
# 将 skill + agents 安装到目标项目
./install.sh /path/to/target/project

# 从已安装的目标项目反向同步修改回本仓库
./sync_from_project.sh /path/to/project_with_code_wiki

# 运行扫描器脚本（在目标项目中运行，不是本仓库）
python .code-wiki/scan.py init
python .code-wiki/scan.py status
python .code-wiki/scan.py plan
python .code-wiki/scan.py next
python .code-wiki/scan.py mark-done <file>
```

本仓库无构建、测试、lint 流程。

## 架构

```
code-wiki/                    ← 安装源仓库（本仓库）
├── install.sh                ← 安装脚本 → 目标项目/.claude/
├── sync_from_project.sh      ← 反向同步脚本
├── skill/
│   ├── SKILL.md              ← Skill 主定义（命令解析 + 四层 wiki 架构 + 提炼原则）
│   ├── references/           ← 各子命令的详细工作流指南
│   │   ├── workflow-init.md  ← init 子命令流程
│   │   ├── workflow-scan.md  ← scan 子命令流程
│   │   ├── workflow-query-lint.md ← query/lint 子命令流程
│   │   ├── page-templates.md ← wiki 页面模板
│   │   └── refactor-guide.md ← 提炼与重构建议指南
│   └── scripts/
│       └── scan.py           ← 增量扫描器（遍历文件、哈希比对、状态管理）
└── agents/                   ← 按语言拆分的 sub-agent
    ├── code-wiki-python-scanner.md   ← Python 文件扫描
    ├── code-wiki-cpp-scanner.md      ← C/C++ 文件扫描
    └── code-wiki-generic-scanner.md  ← 其他语言文件扫描
```

安装后在目标项目中的运行时结构：

```
<目标项目>/
├── .claude/skills/code-wiki/  ← skill 文件（install.sh 复制）
├── .claude/agents/            ← agent 文件（install.sh 复制）
├── .code-wiki/                ← 运行时状态（scan.py 创建）
│   ├── scan.py
│   ├── state.json             ← 文件哈希和处理状态
│   └── config.json            ← 可选配置（追加扩展名、排除项等）
└── wiki/                      ← wiki 产物（skill 维护）
    ├── README.md, index.md, log.json, architecture.md, refactor.md
    ├── files/       ← 每个源文件一页
    ├── modules/     ← 每个模块一页
    ├── concepts/    ← 静态结构（数据结构、术语、设计模式）
    └── algorithm/   ← 动态过程（核心算法、数据流水线）
```

## 关键设计决策

- **增量扫描**：`scan.py` 通过 SHA-1 哈希比对检测文件变更，已处理文件不会重复扫描
- **子命令驱动**：SKILL.md 解析用户输入映射到 init/scan/query/lint 四个子命令，每个子命令必须先读取对应的 reference 文件
- **并行扫描**：主 agent 通过 Agent 工具派发三个 sub-agent（Python/C++/Generic）并行处理不同语言的文件
- **扫描顺序**：按路径深度排序，浅层文件（通常是入口和配置）优先处理
- **wiki 页面分类**：concepts/ 放静态结构，algorithm/ 放动态过程；两者重叠时主体写 algorithm/，concepts/ 只留短指针

## 修改注意事项

- `skill/references/` 下的文件是 skill 的执行指令，修改时保持"LLM 可直接遵循"的风格
- `agents/*.md` 是独立的 agent prompt，每个 agent 必须自包含（不依赖外部上下文）
- `scan.py` 是无第三方依赖的纯 Python 脚本，保持兼容 Python 3.9+
- 所有 wiki 产出内容使用中文，代码标识符保留原样
