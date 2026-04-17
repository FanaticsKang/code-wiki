---
name: module-test-gen
description: >
  半自动模块测试/集成测试生成。扫描仓库 → 生成测试配置 → 补充代码引用和测试目标 → 工程师审查 → 生成并运行 pytest/googletest。
  触发词：模块测试、集成测试、测试配置、扫描模块、生成测试目标、module test、integration test、test config。
  提及 test-config/ 目录或模块测试 YAML 文件时也应触发。
  命令：init, generate, run。
---

# 模块测试生成器

半自动化的模块级测试生成技能。扫描代码仓库，构建描述功能、相关代码和测试目标的配置文件，
然后生成并运行测试。

配置中的每一项都标记了 `source: manual`（工程师指定）或 `source: auto`（Claude 生成），
工程师始终能分辨哪些是自己写的、哪些是 Claude 补充的。

## 流程概览

工作流包含三个按顺序执行的命令：

```
init → generate → （工程师审查）→ run
```

1. **init** — 扫描仓库，生成配置文件（index.yml + 各模块 YAML）
2. **generate** — 补充自动发现的相关代码和测试目标
3. *（工程师审查并编辑配置文件）*
4. **run** — 根据最终配置生成测试代码并执行

---

## 重要原则

1. **永远不删除 manual 条目。** 工程师指定的内容是神圣的。只增不删。

2. **始终标记来源。** 每个 feature、related_code 条目和 test_target 都必须有
   `source: manual` 或 `source: auto`。工程师写的标记为 `manual`，Claude 添加的
   标记为 `auto`。

3. **工程师在 run 之前审查。** init 和 generate 可连续执行，工程师在 run 之前
   集中审查最终配置（模块划分、功能列表、代码引用、测试目标）。

4. **测试应该有意义。** 不要为了增加数量而生成无意义的测试。每个测试都应验证其
   test_target 描述的具体行为。

5. **报告按模块生成。** 每个模块有自己的报告文件。index.yml 指向各个报告。

6. **配置文件持久保存。** test-config/ 目录存在于项目仓库中。需要更新时，
   重新运行 `init`（会提示确认删除旧配置）再 `generate`。

---

## 命令详情

### 命令 1：`init`

**触发条件**：用户说"init"、"初始化测试配置"、"扫描项目"或类似表述。

**行为：**

1. **检查 index.yml 是否已存在。** 若存在，使用 AskUserQuestion 询问用户：
   > 检测到已有 test-config/index.yml，init 会删除并重新全量扫描。是否继续？

   用户确认后删除整个 `test-config/` 目录再继续；用户拒绝则终止。

2. 扫描整个代码仓库以发现模块。使用以下启发式规则：
   - Python：包含 `__init__.py` 的目录，或 `src/` 下的顶级包
   - C++：拥有独立头文件的目录，或 CMakeLists.txt 划分的子目录
   - 通用：逻辑上相关的功能分组（如 `auth/`、`payment/`、`api/`）

3. 对每个发现的模块，通过以下方式识别功能：
   - 公共类及其方法
   - 导出的函数
   - API 端点或路由处理器
   - 关键数据结构及其转换逻辑

4. 对每个功能，通过以下方式查找相关代码文件：
   - import/include 依赖链
   - 类型依赖
   - 模块边界内的调用图

5. 生成目录结构：
   ```
   test-config/
       index.yml
       modules/
           <模块名>.yml
           ...
       reports/
   ```

6. 所有条目标记为 `source: auto`，因为此时没有工程师输入。

**输出**：告知工程师创建了什么内容，接下来可运行 `generate` 补充详细配置。

---

### 命令 2：`generate`

**触发条件**：用户说"generate"、"生成测试配置"、"补充配置"或类似表述。

**前置条件**：index.yml 必须存在。若不存在，告知用户需要先运行 `init` 并终止。

**全 auto 检查**：读取所有模块配置文件，若所有 feature、related_code、test_target
的 source 均为 `auto`（无任何 manual 条目），使用 AskUserQuestion 提醒用户：
> 当前配置全部由自动扫描生成，尚未经过人工审查。建议先检查 index.yml 和各模块
> 配置文件中的模块划分与功能列表是否合理。是否继续？
用户确认则继续，拒绝则终止。

对每个模块配置文件：

1. 读取当前配置。
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
**环境**：Python 3.11 / macOS 14 / pytest 8.1
**扫描范围**：src/（42 文件，3 模块）
**总耗时**：12.3s

## 汇总

| 指标   | 值       |
|--------|----------|
| 总测试 | 30       |
| 通过   | 26 (87%) |
| 失败   | 3        |
| 跳过   | 1        |
| 错误   | 0        |

## 模块总览

| 模块 | 测试数 | 通过 | 失败 | 跳过 | 耗时 |
|------|--------|------|------|------|------|
| auth | 12     | 11   | 1    | 0    | 3.2s |
| api  | 10     | 8    | 2    | 0    | 5.1s |
| core | 8      | 7    | 0    | 1    | 4.0s |

## 功能：<功能名>

| # | 测试目标 | 来源 | 结果 | 耗时 |
|---|----------|------|------|------|
| 1 | 描述     | manual | 通过 | 0.1s |
| 2 | 描述     | auto   | 通过 | 0.2s |

## 失败详情

### <测试文件>::<测试函数>

- **断言**：`assert result == expected`
- **Expected**：`200`
- **Actual**：`404`
- **位置**：`tests/module_auth/test_login.py:45`
- **失败原因**：登录接口返回 404，可能路由未注册

## 跳过用例

| 测试函数 | 跳过原因 |
|----------|----------|
| test_redis_connection | 缺少 redis 依赖 |

## 文件覆盖映射

| 源文件 | 测试文件 |
|--------|----------|
| src/auth/login.py | tests/module_auth/test_login.py |
| src/api/router.py | tests/module_api/test_router.py |
| src/core/parser.py | tests/module_core/test_parser.py |
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
