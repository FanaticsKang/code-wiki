---
name: unit-test-gen
description: >
  全自动仓库级单元测试生成。扫描源码 → 分析函数 → 生成测试 → 执行并出报告，无需人工干预。
  支持全量/增量模式，当前支持 Python（pytest）和 C++（Google Test）。
  触发词：单元测试、生成测试、测试覆盖率、增量测试、回归测试、unit test、跑测试、给函数加测试、哪些函数没被测试。
  提及 test/generated_unit/ 或 test_cases.json 时也应触发。
  命令：init, generate, run, auto。
---

# 单元测试生成器

全自动的仓库级单元测试生成技能。扫描代码 → 分析函数行为 → 按六个维度生成
测试 → 执行并出报告。全程无需人工介入。

支持多语言，当前已实现 Python（pytest）和 C++（Google Test）。
各语言的扫描规则、测试代码模板、mock 实现等细节见 `references/` 下的语言参考文档。

## 命令

| 命令 | 作用 |
|------|------|
| `init` | 扫描源码、分析函数、生成/更新 `test_cases.json` 基线 |
| `generate` | 读取基线，生成测试代码到 `test/generated_unit/` |
| `run` | 执行测试，生成 markdown 报告 |
| `auto` | **一键模式**：自动串联 `init → generate → run` |

用户如果只说"跑单元测试"、"生成单元测试"而没有指定阶段，默认走 `auto`。

## 参数

所有参数都传给 `init` 阶段（因为只有扫描和基线需要参数）。`generate` 和 `run` 不接受参数。

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--mode` | `incremental` | `full`（全量）或 `incremental`（增量）。无基线时自动退化为 `full` |
| `--source` | 全仓库 | 限定扫描目录，逗号分隔，如 `core,utils` |

示例：
```
/unit-test-gen auto                              # 一键跑完，默认增量
/unit-test-gen auto --mode full                  # 一键跑完，全量重建
/unit-test-gen auto --source core,utils          # 限定扫描目录
/unit-test-gen init --mode full                  # 只跑第一步
/unit-test-gen run                               # 只跑测试并出报告
```

---

## 覆盖率配置

### 配置位置

覆盖率阈值配置存储在 `test_cases.json` 的 `coverage_config` 字段中。
用户可手动编辑该文件调整配置。首次运行时如果该字段不存在，使用默认值。

### 配置项

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `statement_threshold` | int | 70 | 语句覆盖率最低阈值（%） |
| `function_threshold` | int | 70 | 函数覆盖率最低阈值（%） |
| `branch_threshold` | int | 60 | 分支覆盖率最低阈值（%） |
| `exclude_dirs` | string[] | [] | 排除覆盖率统计的目录（如 `tools/data_sdk/`） |
| `dead_code_min_confidence` | int | 80 | dead code 检测的最低置信度（%） |

### 三种覆盖率指标

| 指标 | 含义 | Python 工具 | C++ 工具 |
|------|------|------------|---------|
| 语句覆盖率 | 被执行到的代码语句占比 | `pytest-cov`（`coverage.py`） | `gcov` + `lcov` |
| 函数覆盖率 | 被调用到的函数占比 | `pytest-cov` | `gcov` + `lcov` |
| 分支覆盖率 | if/else 等分支被走过的占比 | `pytest-cov --cov-branch` | `gcov` + `lcov` |

### 阈值判定规则

- 三种指标各自独立判定达标/未达标
- 未达标的文件和模块在报告中高亮标注
- 同时给出未达标原因分析（哪些函数/分支未被覆盖）

---

## Dead Code 检测

### 检测工具

| 语言 | 工具 | 安装方式 |
|------|------|---------|
| Python | `vulture` | `pip install vulture` |
| C++ | `cppcheck` / 编译器 `-Wunused-function` | 系统包管理器 |

### 检测策略

1. 在测试执行和覆盖率收集之后，对源码目录运行静态分析
2. Python：`vulture <source_dirs> --min-confidence <configured_value>`
   - 输出格式：`<file>:<line>: unused <type> '<name>' (<confidence>%)`
   - 过滤入口函数（`main`、CLI handler）等已知误报
3. C++：
   - 优先使用编译时 `-Wunused-function` 警告
   - 或运行 `cppcheck --enable=unusedFunction <source_dirs>`
4. 结果与覆盖率 0% 的函数列表交叉验证，提高准确性

### 局限性

- 静态分析存在误报（动态调用、反射、入口函数等）
- 报告中标注为「dead code 候选项」，建议用户复核

---

## 核心原则

### 强约束（不可违反）

#### 1. 不修改源码

**绝对禁止修改任何项目源代码。** 技能只在 `test/generated_unit/` 下操作。

- 不修改任何 `test/generated_unit/` 以外的文件
- 不覆盖用户在其他位置手写的测试
- 不修改配置文件、数据文件、构建脚本等任何项目文件
- 违反此约束等同于破坏用户代码

#### 2. 失败处理：分析原因，分类处理

测试失败时**不得篡改测试来掩盖失败**，也不得主观断言所有失败都是测试问题。
必须先从**测试用例的初衷**出发分析失败原因，再按类别处理：

| 失败原因 | 处理方式 |
|----------|----------|
| 测试代码问题（mock 不对、参数类型错误） | 修复 `test/generated_unit/` 下的测试文件 |
| 源码问题（bug、边界未处理、行为异常） | 不修改源码，在报告中标记为疑似源码问题 |
| 不确定原因 | 在报告中如实记录，不主观判断 |

**分析失败时的注意事项**：
- 边界测试传空值、零值、非法类型等是**正常的测试行为**，函数抛异常说明源码有边界处理
- 不要一看到运行时错误就判定为"测试问题" — 先看测试类型（functional 还是 boundary）
- 功能测试失败 → 可能是测试参数构造不对，也可能是源码确实有 bug
- 边界测试失败（异常没被捕获）→ 检查异常类型是否在捕获列表中

**严禁的掩盖行为**：删除断言、弱化边界值、skip 失败场景、hard-code 预期结果。

#### 3. 禁止使用 skip 机制

**凡是通过扫描过滤的函数，必须生成并执行完整测试，不得以任何理由跳过。**

- 不得用测试框架的 skip 机制（如 pytest.skip、GTEST_SKIP 等）
- 不得以"依赖复杂"、"需要真实环境"、"无法 mock"等理由跳过
- 不知道函数参数时，必须读源码分析后构造输入，而非 skip
- 唯一例外：测试环境缺少运行时依赖，必须在报告中注明

### 行为准则

#### 4. 全自动无交互

整个流程自动完成，不向用户询问任何问题。遇到编译错误、导入失败、断言失败等问题时，
自行分析原因、修复测试代码、重试。只有在所有自动修复手段穷尽后才在报告中记录问题。

#### 5. 客观反映源码真实行为

测试断言基于**源码实际输出**编写，不预设理想行为。如果源码行为与预期不符
（如返回类型不一致、边界返回意外值），以源码实际行为为准写断言，
同时在报告中标记为疑似问题。主动暴露以下源码问题：

- 源码与类型注解/文档不一致
- 边界输入导致崩溃（未捕获异常）
- 并发/竞态隐患
- 资源泄漏（未关闭的文件/连接/内存）

#### 6. 每个函数必须有实质性测试

每个被测函数必须生成功能性测试和边界测试的完整代码。禁止生成只有函数签名和
空实现的测试。每个测试函数体内必须有：具体的输入构造、被测函数调用、断言验证。

#### 7. Mock 外部边界，测试内部逻辑

| 依赖类型 | Mock 策略 |
|----------|-----------|
| 文件读取 | 使用临时文件或替换文件打开函数 |
| 配置加载 | 替换配置解析函数，返回固定配置 |
| 数据库/ORM | 用 mock 对象替代数据库客户端 |
| 网络请求 | 替换 HTTP 客户端，返回预设响应 |
| 类方法 | 用 mock 对象替代（保持接口一致） |
| 纯数据变换库 | 直接使用真实库（无副作用，不需要 mock） |
| 异步函数 | 用同步包装或异步测试支持 |
| 子进程调用 | 替换子进程执行函数，构造安全返回值 |

纯数据变换永远不需要 mock：数值操作、字符串处理等直接构造输入调用即可。

各语言具体的 mock 工具和实现方式见 `references/` 下的语言参考文档。

---

## 执行流程

### 环境预检（所有命令的前置步骤）

所有命令（`init`/`generate`/`run`/`auto`）执行前，必须先运行环境预检：

1. **读取语言信息**：从 `test_cases.json` 的 `languages` 字段判断仓库语言。
2. **按语言检查工具可用性**：

   | 语言 | 工具 | 检查命令 | 缺失时行为 |
   |------|------|---------|-----------|
   | Python | `pytest-cov` | `python -c "import pytest_cov"` | 尝试 `pip install pytest-cov -i https://pypi.org/simple/`；失败则跳过覆盖率收集 |
   | Python | `vulture` | `python -c "import vulture"` | 尝试 `pip install vulture -i https://pypi.org/simple/`；失败则跳过 dead code 检测 |
   | C++ | `gcov` | `which gcov` | 跳过 C++ 覆盖率收集 |
   | C++ | `lcov` | `which lcov` | 跳过 C++ 覆盖率报告 |
   | C++ | `cppcheck` | `which cppcheck` | 跳过 C++ dead code 检测 |

3. **写入工具状态**：将检查结果存入 `test_cases.json` 的 `tool_status` 字段，供后续步骤读取。
4. **降级策略**：工具不可用时跳过对应功能，报告注明跳过原因，不影响测试执行。

### `init` 命令

1. **解析参数**：`--mode`（默认 incremental）、`--source`（默认全仓库）。
2. **检查基线**：读取 `test/generated_unit/test_cases.json`。
   - 不存在或解析失败 → 提示"未检测到基线，自动退化为全量模式"，切换 `full`。
3. **扫描源码**：
   - 应用排除规则 + `--source` 限定范围。
   - 自动识别语言和测试框架。
   - 解析每个源文件的函数/方法签名和行为。
   - 过滤：跳过存根函数（仅有空实现）、主程序入口、setter、私有模块、纯重导出。
   - 各语言的具体扫描规则和过滤条件见 `references/` 下的语言参考文档。
4. **计算哈希**：对每个文件和每个函数分别计算 MD5。
5. **对比基线**（增量模式）：
   - 文件 MD5 相同 → 跳过整个文件。
   - 文件 MD5 变化但函数 MD5 未变 → 跳过该函数。
   - 函数 MD5 变化或新增 → 标记为需要重新生成。
   - 基线中存在但扫描未发现的函数 → 标记为删除。
6. **分析函数行为**：对需要重新生成的函数做特征分析，判定适用的测试维度。
   - 各语言的特征检测规则见 `references/` 下的语言参考文档。
7. **写入基线文件**：
   - scanner 的标准输出是 JSON，必须保存到两个位置：
     - `test/generated_unit/scan_result.json`（scanner 原始输出）
     - `test/generated_unit/test_cases.json`（基线文件，供后续 generate 和 run 使用）
   - 增量模式下，merge 变更到现有 `test_cases.json`（保留未变更函数的元数据）。
   - **确保 `test_cases.json` 始终存在**：如果 run 或 generate 阶段找不到
     `test_cases.json`，应先检查 `scan_result.json` 并自动提升为基线。
   - 只存元数据（签名、MD5、维度、测试 case 描述），不存测试代码。

大仓库策略：如果扫描到超过 30 个源文件，考虑按文件分批处理（Claude 自行决定
是否拆分），避免单次分析过载。

### `generate` 命令

1. **读取 `test_cases.json`**（如果不存在，自动从 `scan_result.json` 提升）。
2. **生成共享工具文件**（如果不存在或技能版本升级）。
   - 各语言有各自的辅助文件，如 Python 的 `_helpers.py`、C++ 的 `_helpers.hpp`。
3. **为每个文件生成测试**：
   - 计算输出路径（镜像源码目录结构）。
   - 按 `test_cases.json` 中的 case 描述，生成对应的测试函数。
   - 加上 AUTO-GENERATED 文件头注释。
4. **生成测试代码时的具体要求**：
   - 正确设置模块/include 搜索路径（视项目结构和语言而定）。
   - 每个测试函数有清晰的说明，描述测试目的。
   - 浮点断言用近似比较。
   - 边界测试用参数化方式批量运行。
   - **严禁使用框架的 skip 机制**：必须读取源码分析参数，构造真实输入或 mock。
   - **先读取源码再生成**：对每个函数，先读取其源码理解参数用途，再构造测试输入。
   - 生成前先读取对应语言的参考文档（`references/language-python.md` 或
     `references/language-cpp.md`）获取数据构造策略和测试模板。

### `run` 命令

1. **执行测试框架**：
   - 增量模式下只跑受影响的测试文件。
   - 各语言的执行命令见 `references/` 下的语言参考文档。
2. **收集覆盖率数据**（`run` 和 `auto` 都执行，依赖环境预检结果）：
   - 读取 `test_cases.json` 中的 `coverage_config` 配置（不存在则用默认值）。
   - 读取 `tool_status` 确认工具可用性，不可用时跳过并记录原因。
   - 按语言执行覆盖率收集（具体命令见 `references/` 下的语言参考文档）：
     - **Python**：`pytest --cov --cov-branch --cov-report=json:coverage.json`
       - `--cov` 收集语句覆盖率和函数覆盖率
       - `--cov-branch` 收集分支覆盖率
       - JSON 报告用于解析文件/函数/分支级别的详细数据
     - **C++**：编译时加 `--coverage` 标志，测试后执行 `gcov` + `lcov --summary`
   - 解析覆盖率输出，提取三种指标（语句/函数/分支）。
   - 与阈值对比，标记未达标的模块和文件。
3. **Dead code 检测**（依赖环境预检结果）：
   - 读取 `tool_status` 确认工具可用性，不可用时跳过并记录原因。
   - 按语言执行静态分析（具体命令见 `references/` 下的语言参考文档）：
     - **Python**：`vulture <source_dirs> --min-confidence <configured_value>`
     - **C++**：`cppcheck --enable=unusedFunction <source_dirs>` 或编译器 `-Wunused-function` 警告
   - 过滤已知误报（入口函数、动态调用等）。
   - 与覆盖率 0% 的函数列表交叉验证。
4. **失败处理**：
   - 生成代码问题（断言写错、mock 不对） → 修正测试代码，重跑。
   - 疑似源码 bug → 不修改源码，记入报告。
   - **skip 用例视为测试代码问题**：所有 skip 必须修复（构造真实输入替换 skip）。
   - 最多重试 5 轮，仍失败则报告。
5. **分析未达标原因**：
   - 对覆盖率未达标的模块/文件，分析具体哪些函数或分支未被覆盖。
   - 给出原因分析（如：依赖外部上下文、mock 难度高等）。
6. **写入 `report.md`**，包含测试结果、覆盖率报告、dead code 检测结果、skip 数量和原因。

### `auto` 命令

串联 `init → generate → run`。中间任一步失败则停止并报告错误位置。

---

## 语言与框架自动识别

不要求用户指定，技能自行检测：

| 语言 | 扩展名 | 默认框架 | 配置文件探测 |
|------|--------|----------|-------------|
| Python | `.py` | pytest | `pyproject.toml`、`setup.cfg`、`requirements.txt` |
| C++ | `.cpp` `.cc` `.cxx` `.h` `.hpp` | gtest | `CMakeLists.txt`、`Makefile`、`conanfile.txt` |

**识别流程**：

1. 遍历源码目录，按扩展名统计文件数量
2. 有 `.py` → 标记 `python`；有 `.cpp`/`.cc`/`.cxx` → 标记 `cpp`
3. 两种都有 → 标记为混合仓库，各语言各自独立扫描和生成
4. 检查配置文件进一步确认框架

检测结果写入 `test_cases.json` 的 `languages` 和 `test_frameworks` 字段。
各语言的扫描规则、测试代码生成规范和 mock 实现见 `references/` 下的语言参考文档。

---

## 扫描排除规则

以下路径自动排除，无需用户指定：

| 类型 | 排除模式 |
|------|----------|
| 测试目录 | `test/`, `tests/` |
| 虚拟环境 | `.venv/`, `venv/`, `env/`, `node_modules/` |
| 缓存 | `__pycache__/`, `.tox/`, `.pytest_cache/`, `.mypy_cache/` 等各语言缓存目录 |
| 构建产物 | `build/`, `dist/`, `*.egg-info/`, `cmake-build-*/` 等 |
| 已生成代码 | `test/generated_unit/`（自身）、`*_generated.*` |
| 文档 | `docs/` |
| 工具/配置 | `.claude/`, `.git/`, `.github/`, `scripts/` |
| 第三方 | `third_party/`, `vendor/` |

各语言可能有额外的排除规则，见语言参考文档。

---

## 六个测试维度

每个函数根据其代码特征生成不同维度的测试：

| 维度 | 触发条件 | 必选 |
|------|----------|------|
| 功能性（functional） | 所有函数 | 是 |
| 边界（boundary） | 所有函数 | 是 |
| 异常容错（exception） | 检测到错误处理、IO 操作、外部调用 | 否 |
| 数据完整性（data_integrity） | 检测到数值计算、浮点运算 | 否 |
| 性能（performance） | 检测到排序、递归、大规模集合构造、循环内字符串拼接等 | 否 |
| 安全（security） | 检测到子进程调用、动态代码执行、SQL 操作、不安全反序列化、缓冲区操作等 | 否 |

### 维度判定的特征分析

各语言的 AST 特征检测规则见 `references/` 下的语言参考文档。

### 各维度的测试策略

**功能性（必选）**：
- 正向路径：标准输入 → 预期输出
- 等价类划分：有效等价类和无效等价类各选一个代表值

**边界（必选）**：
- 根据参数类型查表取边界值
- 参数化批量测试所有边界值
- 各语言的边界值查表见语言参考文档

**异常容错（按需）**：
- 非法输入类型 → 预期抛出类型错误
- 越界值 → 预期抛出越界错误
- 模拟 IO 失败（文件不存在、权限不足）
- 模拟网络失败（超时、4xx/5xx）

**数据完整性（按需）**：
- 精度验证：浮点结果在容差范围内
- 确定性验证：同样输入调用多次，结果必须一致
- 往返验证：`decode(encode(x)) == x`

**性能（按需）**：
- 基本负载测试：大规模输入（可配置大小）下验证函数能完成执行
- 时间记录：不设硬性超时阈值，记录执行时间供报告分析
- 可扩展性测试：对比小输入和大输入的执行时间比，验证非指数增长
- 内存稳定性：验证大输入下不引发内存异常

**安全（按需）**：
- 命令注入测试：特殊字符输入不触发 shell 执行
- SQL 注入测试：SQL 片段输入不改变查询语义（验证参数化查询）
- 路径遍历测试：`../` 等路径不越界访问
- 动态代码执行测试：任意代码字符串不被执行
- 输入清洗验证：恶意输入在输出中被转义或移除
- 缓冲区溢出测试（适用于无内存安全语言）

各维度在具体语言/框架中的实现代码见对应的语言参考文档。

---

## 输出目录结构

所有生成物在 `test/generated_unit/` 下，镜像源码目录结构。

```
test/generated_unit/
├── test_cases.json              # 基线文件（元数据 + MD5，不含测试代码）
├── report.md                    # 测试报告
├── core/
│   ├── test_parser.py           # Python 测试（对应 Python 源码）
│   └── test_calculator.cpp      # C++ 测试（对应 C++ 源码）
├── utils/
│   └── test_format.py
└── api/
    └── test_handlers.py
```

混合语言仓库中，不同语言的测试文件共存于同一目录结构下。
各语言有自己的辅助文件（如 Python 的 `_helpers.py`、C++ 的 `_helpers.hpp`）。

**命名规则**：源码 `src/<path>/<name>.<ext>` → 测试 `test/generated_unit/<path>/test_<name>.<ext>`。
每个测试文件顶部加注释：

```
AUTO-GENERATED by unit-test-gen skill. DO NOT EDIT.
Source: src/core/parser.py
Regenerate with: /unit-test-gen auto
```

---

## `test_cases.json`

基线文件只存元数据和 MD5，不存测试代码。完整结构见 [`references/test-cases-schema.md`](references/test-cases-schema.md)。

---

## 报告格式

写入 `test/generated_unit/report.md`，包含头部元信息表、执行摘要表、增量信息、失败用例详情、文件变更列表。
完整模板和字段说明见 [`references/report-format.md`](references/report-format.md)。

---

## 辅助脚本

`scripts/` 下的脚本是 Claude 的工具，使用前应先阅读其代码并按需调整：

- **`scan_repo.py`** — 扫描仓库，输出函数列表和 MD5。支持多种语言。
  用法：`python scripts/scan_repo.py <repo_root> [--source core,utils] [--language python|cpp]`

- **`analyze_function.py`** — 对单个函数做特征分析，输出适用维度。
  用法：`python scripts/analyze_function.py <source_file> --function <name> [--language python|cpp]`

- **`batch_generate.py`** — 批量生成测试代码。支持多种语言。
  用法：`python scripts/batch_generate.py --test-cases test_cases.json [--language python|cpp]`

- **`run_and_report.py`** — 执行测试并生成 markdown 报告。支持多种测试框架。
  用法：`python scripts/run_and_report.py --output report.md [--language python|cpp]`

各语言的 CMake 集成、tree-sitter 解析等细节见对应的语言参考文档。
