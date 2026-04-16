---
name: module-test-gen
description: >
  生成并运行模块级（集成）测试。当用户提到模块测试、集成测试、生成测试配置、扫描代码仓库的可测试模块、
  运行模块级测试套件时触发此技能。触发关键词包括："模块测试"、"集成测试"、"测试配置"、"扫描模块"、
  "生成测试目标"、"初始化测试配置"、"运行模块测试"、"module test"、"integration test"、
  "test config"、"init test config"、"run module tests"。当用户提及 test-config/ 目录、
  index.yml 或任何模块测试配置 YAML 文件时也应触发。此技能管理一个半自动化工作流：扫描代码仓库、
  生成配置文件（列出功能/代码/测试目标）、让工程师审查编辑、然后生成并运行 pytest（Python）或
  googletest（C++）测试。
---

# 模块测试生成器

半自动化的模块级测试生成技能。扫描代码仓库，构建描述功能、相关代码和测试目标的配置文件，
然后生成并运行测试。

配置中的每一项都标记了 `source: manual`（工程师指定）或 `source: auto`（Claude 生成），
工程师始终能分辨哪些是自己写的、哪些是 Claude 补充的。

## 流程概览

工作流包含四个按顺序执行的命令：

```
init → （工程师审查）→ generate → （工程师审查）→ run
```

1. **init** — 扫描仓库，生成配置文件（index.yml + 各模块 YAML）
2. **generate** — 补充自动发现的相关代码和测试目标
3. *（工程师审查并编辑配置文件）*
4. **run** — 根据最终配置生成测试代码并执行

步骤 1 和步骤 2 必须是独立的命令。每一步之间工程师都必须有机会审查。

---

## 命令详情

### 命令 1：`init`

**触发条件**：用户说"init"、"初始化测试配置"、"扫描项目"或类似表述。

**行为取决于 index.yml 是否存在：**

#### 情况 A：index.yml 不存在（首次运行）

1. 扫描整个代码仓库以发现模块。使用以下启发式规则：
   - Python：包含 `__init__.py` 的目录，或 `src/` 下的顶级包
   - C++：拥有独立头文件的目录，或 CMakeLists.txt 划分的子目录
   - 通用：逻辑上相关的功能分组（如 `auth/`、`payment/`、`api/`）

2. 对每个发现的模块，通过以下方式识别功能：
   - 公共类及其方法
   - 导出的函数
   - API 端点或路由处理器
   - 关键数据结构及其转换逻辑

3. 对每个功能，通过以下方式查找相关代码文件：
   - import/include 依赖链
   - 类型依赖
   - 模块边界内的调用图

4. 生成目录结构：
   ```
   test-config/
       index.yml
       modules/
           <模块名>.yml
           ...
       reports/
   ```

5. 所有条目标记为 `source: auto`，因为此时没有工程师输入。

#### 情况 B：index.yml 已存在（增量更新）

1. 读取现有的 index.yml 和所有模块配置文件。
2. 扫描整个代码仓库。
3. 发现不在现有配置中的新模块 → 添加到 index.yml 并标记 `source: auto`。
4. 在已有模块中发现未列出的新功能 → 添加并标记 `source: auto`。
5. 永远不修改或删除标记为 `source: manual` 的条目。
6. 之前标记为 `source: auto` 且仍然有效的条目保持不变。
   标记为 `source: auto` 但对应代码已不存在的条目，添加注释
   `# STALE: 代码已不存在`，由工程师决定是否删除。

**输出**：告知工程师创建/更新了什么内容，并提醒在运行 `generate` 之前先审查。

---

### 命令 2：`generate`

**触发条件**：用户说"generate"、"生成测试配置"、"补充配置"或类似表述。

**前置条件**：index.yml 必须存在（先运行 `init`）。

对每个模块配置文件：

1. 读取当前配置（工程师可能在 `init` 之后做了编辑）。
2. 对每个功能（无论 `manual` 还是 `auto`）：
   a. **补充 related_code**：从已列出的文件出发，追踪 import 链、调用图和类型依赖。
      发现新依赖则添加并标记 `source: auto`。不重复添加已有条目。
   b. **补充 test_targets**：分析代码以识别可测试行为：
      - 接口契约（输入/输出类型、返回值结构）
      - 错误处理路径（错误输入、缺少依赖时的行为）
      - 边界情况（空集合、空值、边界数值）
      - 状态转换（如果模块是有状态的）
      - 集成点（该功能如何调用其他功能/模块）
      添加新测试目标并标记 `source: auto`。不重复添加已有条目。

3. 将更新后的配置写回文件。

**输出**：告知工程师添加了什么内容，并提醒在运行 `run` 之前先审查。

---

### 命令 3：`run`

**触发条件**：用户说"run"、"运行测试"、"执行测试"或类似表述。

**前置条件**：配置文件必须已经过工程师审查。

对 index.yml 中列出的每个模块：

1. 读取模块配置文件。
2. 读取所有功能中 `related_code` 列出的文件。
3. 对每个 `test_target`，生成一个 pytest 测试函数（C++ 则生成 googletest），要求：
   - 有清晰的文档字符串，说明测试内容和所属功能
   - 用 pytest marker 标记来源为 `manual` 或 `auto`
   - 尽可能具体地测试描述中的行为
   - 对模块外部的依赖使用适当的 fixtures 和 mock

4. 将测试文件写入 `tests/module_<模块名>/`：
   - 每个功能一个测试文件：`test_<功能名_slug>.py`
   - 如需共享 fixtures 则生成 `conftest.py`

5. 运行 pytest：
   ```bash
   pytest tests/module_<模块名>/ -v --tb=short 2>&1
   ```

6. 在 `test-config/reports/<模块名>-report.md` 生成 markdown 报告，包含：
   - 摘要：总测试数、通过数、失败数、错误数
   - 按功能分组的详细结果，每个测试目标标注通过/失败
   - 每个测试目标标注来源（manual/auto）
   - 失败详情：断言信息、相关代码片段

7. 更新 index.yml，为每个模块写入报告路径。

**输出**：向工程师展示报告。

---

## 配置文件格式

### index.yml

```yaml
project: <项目名>

modules:
  - name: <模块名>
    config: test-config/modules/<模块名>.yml
    report: test-config/reports/<模块名>-report.md    # 由 run 命令写入
    language: python          # python | cpp
    test_framework: pytest    # pytest | googletest
    source: manual | auto
```

### 模块配置文件：`<模块名>.yml`

```yaml
module: <模块名>
language: python
test_framework: pytest

features:
  - name: "功能描述"
    source: manual | auto
    related_code:
      - path: "src/module/file.py"
        source: manual | auto
    test_targets:
      - description: "用自然语言描述要测试什么"
        source: manual | auto
```

### 报告格式：`<模块名>-report.md`

```markdown
# 模块测试报告：<模块名>

**日期**：YYYY-MM-DD HH:MM
**状态**：X 通过，Y 失败，Z 错误

## 功能：<功能名>

| # | 测试目标 | 来源 | 结果 | 详情 |
|---|----------|------|------|------|
| 1 | 描述     | manual | 通过 |      |
| 2 | 描述     | auto   | 失败 | 信息 |
```

---

## 语言相关行为

技能通过读取配置中的 `language` 和 `test_framework` 字段来决定如何扫描代码和生成测试。

### Python + pytest（当前支持）

- 扫描：解析 `import` 语句、`def`/`class` 定义、类型注解
- 测试生成：编写带有 `@pytest.mark.manual` 或 `@pytest.mark.auto` 标记的 pytest 函数
- 执行：`pytest tests/module_<n>/ -v --tb=short`
- Fixtures：使用 `conftest.py` 进行共享设置，使用 `monkeypatch` 或 `unittest.mock` 进行 mock

### C++ + googletest（未来支持）

- 扫描：解析 `#include` 指令、头文件中的函数声明、namespace 结构
- 测试生成：编写 TEST() 或 TEST_F() 宏
- 执行：用 CMake/Make 编译后运行测试二进制文件
- Mock：按需使用 Google Mock

当 `language` 未指定时，默认使用 `python` + `pytest`。

详细的 Python 扫描和生成规则请阅读 `references/language-python.md`。

---

## 重要原则

1. **永远不删除 manual 条目。** 工程师指定的内容是神圣的。只增不删。

2. **始终标记来源。** 每个 feature、related_code 条目和 test_target 都必须有
   `source: manual` 或 `source: auto`。工程师写的标记为 `manual`，Claude 添加的
   标记为 `auto`。

3. **init 和 generate 必须分开。** 永远不要合并执行。工程师必须有机会在 Claude
   开始添加详细的代码引用和测试目标之前，先审查结构性决策（哪些模块存在、哪些功能存在）。

4. **测试应该有意义。** 不要为了增加数量而生成无意义的测试。每个测试都应验证其
   test_target 描述的具体行为。

5. **报告按模块生成。** 每个模块有自己的报告文件。index.yml 指向各个报告。

6. **配置文件持久保存。** test-config/ 目录存在于项目仓库中。后续运行时，`init`
   执行增量更新，而非全量扫描。

---

## 辅助脚本

技能在 `scripts/` 中包含以下辅助脚本：

- **`scan_repo.py`** — 扫描仓库并输出已发现模块、功能和代码文件的 JSON 结构。
  由 `init` 命令使用来引导生成配置文件。
  用法：`python scripts/scan_repo.py <仓库根目录> [--language python|cpp]`

- **`generate_tests.py`** — 读取模块配置 YAML 并生成 pytest 测试文件。
  用法：`python scripts/generate_tests.py <config.yml> --output-dir tests/`

- **`run_and_report.py`** — 在测试目录上运行 pytest 并生成 markdown 报告。
  用法：`python scripts/run_and_report.py <测试目录> --report-path <输出路径.md>`

Claude 在使用这些脚本前应先阅读其代码，并可根据具体项目需要进行修改或扩展。
