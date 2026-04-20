# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目简介

code-wiki 是一个 Claude Code skills + agents 分发包，包含以下 skill：

核心（默认安装）：
- **code-wiki**：为任意代码仓库增量构建和维护中文 wiki
- **module-test-gen**：半自动化的模块级测试生成工具
- **unit-test-gen**：单元测试生成工具，支持 Python（pytest）和 C++（Google Test）
- **unit-test-gen-init**：单测生成流水线的初始化阶段，扫描代码仓库并生成/更新 `test_cases.json` 基线文件

可选（`install.sh --full` 安装）：
- **paper-code-deepdive**：论文-代码深度对比分析工具（四阶段流水线：定位创新点 → 分析论文材料 → 定位代码实现 → 深度对比出报告）

本仓库本身**不是**最终运行的项目，而是一个安装源：通过 `install.sh`（核心）或 `install.sh --full`（全部）将 skills 和 agents 安装到目标项目的 `.claude/` 目录下。

## 常用命令

```bash
# 将所有 skills + agents 安装到目标项目
./install.sh /path/to/target/project

# 从已安装的目标项目反向同步修改回本仓库
./sync_from_project.sh /path/to/project_with_code_wiki
```

### code-wiki 命令（在目标项目中运行）

```bash
python .code-wiki/scan.py init
python .code-wiki/scan.py status
python .code-wiki/scan.py plan
python .code-wiki/scan.py next
python .code-wiki/scan.py mark-done <file>
```

### module-test-gen 命令（在目标项目中运行）

```bash
python .claude/skills/module-test-gen/scripts/scan_repo.py <仓库根目录>
python .claude/skills/module-test-gen/scripts/generate_tests.py <config.yml> --output-dir tests/
python .claude/skills/module-test-gen/scripts/run_and_report.py <测试目录> --report-path <输出路径.md>
```

本仓库无构建、测试、lint 流程。

## 架构

```
code-wiki/                        ← 安装源仓库（本仓库）
├── install.sh                    ← 安装脚本 → 目标项目/.claude/
├── sync_from_project.sh          ← 反向同步脚本
├── skills/                       ← 所有 skill 的容器
│   ├── code-wiki/                ← 中文 wiki 构建技能
│   │   ├── SKILL.md              ← 命令解析 + 四层 wiki 架构 + 提炼原则
│   │   ├── references/           ← 各子命令的详细工作流指南
│   │   │   ├── workflow-init.md  ← init 子命令流程
│   │   │   ├── workflow-scan.md  ← scan 子命令流程
│   │   │   ├── workflow-query-lint.md ← query/lint 子命令流程
│   │   │   ├── page-templates.md ← wiki 页面模板
│   │   │   ├── refactor-guide.md ← 提炼与重构建议指南
│   │   │   ├── hypothesis-guide.md ← hypothesis 机制指南
│   │   │   ├── reflection-checklist.md ← 反思检查清单
│   │   │   └── init-skeletons.md ← init 骨架模板
│   │   └── scripts/
│   │       └── scan.py           ← 增量扫描器（纯 Python，无第三方依赖）
│   └── module-test-gen/          ← 模块测试生成技能
│       ├── SKILL.md              ← init/generate/run 三命令工作流
│       ├── references/
│       │   └── language-python.md ← Python 扫描和生成的详细规则
│       ├── scripts/
│       │   ├── scan_repo.py      ← 仓库扫描（发现模块和功能）
│       │   ├── generate_tests.py ← 从配置生成 pytest 文件
│       │   └── run_and_report.py ← 执行测试并生成 markdown 报告
│       └── templates/
│           ├── index-template.yml          ← index.yml 参考模板
│           └── module-config-template.yml  ← 模块配置参考模板
│   └── paper-code-deepdive/       ← 论文-代码深度对比分析技能
│       ├── SKILL.md               ← 四阶段流水线（定位创新→分析材料→定位代码→对比报告）
│       ├── references/
│       │   ├── innovation_signals.md          ← 创新点识别启发式
│       │   ├── figure_analysis_protocol.md    ← 三源交叉验证协议
│       │   ├── figure_schemas.md              ← 5 种图类型结构化 schema
│       │   ├── hidden_details_checklist.md    ← 12 类"论文不写但代码里有"的清单
│       │   └── report_template.md             ← 最终报告模板
│       ├── scripts/
│       │   ├── extract_innovations.py   ← Stage 1: 从 PDF 抽取高信号区域
│       │   ├── analyze_figures.py       ← Stage 2c: 图渲染 + 三源提取
│       │   ├── locate_implementation.py ← Stage 3: 代码仓库定向 grep
│       │   └── deep_compare.py          ← Stage 4: 组装对比报告骨架
│       └── examples/
│           └── flamingo_gated_xattn.md  ← Flamingo Gated Xattn 完整示例
└── agents/                       ← 按语言拆分的 sub-agent（code-wiki 专用）
    ├── code-wiki-python-scanner.md   ← Python 文件扫描
    ├── code-wiki-cpp-scanner.md      ← C/C++ 文件扫描
    └── code-wiki-generic-scanner.md  ← 其他语言文件扫描
```

安装后在目标项目中的运行时结构：

```
<目标项目>/
├── .claude/skills/                ← 所有 skill 文件
│   ├── code-wiki/                 ← wiki 构建技能
│   └── module-test-gen/           ← 测试生成技能
├── .claude/agents/                ← agent 文件
├── .code-wiki/                    ← code-wiki 运行时状态
│   ├── scan.py
│   ├── state.json
│   └── config.json
├── wiki/                          ← code-wiki 产物
│   ├── README.md, index.md, log.json, architecture.md, refactor.md
│   ├── files/       ← 每个源文件一页
│   ├── modules/     ← 每个模块一页
│   ├── concepts/    ← 静态结构
│   └── algorithm/   ← 动态过程
└── test-config/                   ← module-test-gen 产物
    ├── index.yml                  ← 模块索引
    ├── modules/                   ← 各模块配置 YAML
    ├── reports/                   ← 测试报告
    └── templates/                 ← 参考模板
```

## 关键设计决策

### code-wiki
- **增量扫描**：`scan.py` 通过 SHA-1 哈希比对检测文件变更，已处理文件不会重复扫描
- **子命令驱动**：SKILL.md 解析用户输入映射到 init/scan/query/lint 四个子命令
- **并行扫描**：主 agent 通过 Agent 工具派发三个 sub-agent（Python/C++/Generic）并行处理不同语言的文件
- **扫描顺序**：按路径深度排序，浅层文件（通常是入口和配置）优先处理
- **wiki 页面分类**：concepts/ 放静态结构，algorithm/ 放动态过程；两者重叠时主体写 algorithm/，concepts/ 只留短指针

### module-test-gen
- **source 标记机制**：每个配置项（feature、related_code、test_target）都有 `source: manual` 或 `source: auto` 标签，工程师始终知道哪些是自己写的
- **init → generate → run 工作流分离**：三步独立执行，每步之间工程师必须有机会审查
- **增量更新**：`init` 对已有配置做增量更新，不删除 manual 条目，对消失的 auto 条目标记 STALE
- **报告按模块生成**：每个模块独立的测试报告，index.yml 指向各报告

### paper-code-deepdive
- **四阶段流水线**：Stage 1 定位创新点 → Stage 2 分析论文材料（文本+公式+图表三源交叉验证）→ Stage 3 定位代码实现 → Stage 4 深度对比出报告
- **脚本做机械工作，判断留给 LLM**：四个脚本负责 PDF 解析、文件遍历、grep 等确定性工作，识别创新点、填充 schema、写对比报告由 Claude 完成
- **Stage 1 后必须停下确认**：避免分析错误的"创新点"浪费后续工作
- **hidden_details_checklist**：12 大类（初始化、归一化、激活、注意力细节、dropout、数值稳定、训练/推理分支、loss 细节、优化器、数据、精度、显式差异），是复现失败原因的系统性清单
- **脚本依赖**：`pdfplumber` 或 `pypdf`（Stage 1/2c），`pymupdf`（Stage 2c 图渲染），Stage 3/4 仅标准库

## 修改注意事项

- `skills/*/references/` 下的文件是 skill 的执行指令，修改时保持"LLM 可直接遵循"的风格
- `agents/*.md` 是独立的 agent prompt，每个 agent 必须自包含（不依赖外部上下文）
- code-wiki 的 `scan.py` 是无第三方依赖的纯 Python 脚本，保持兼容 Python 3.9+
- module-test-gen 的脚本（`scan_repo.py`、`generate_tests.py`、`run_and_report.py`）依赖 `pyyaml`
- 所有 wiki 产出内容使用中文，代码标识符保留原样
