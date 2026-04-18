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

用户如果只说"跑单元测试"、"生成单元测试"而没有指定阶段，默认 `auto`。

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

## 核心原则

### 使命定位

**本技能的核心使命是通过测试发现源码中的潜在问题，而不是让测试"看起来都通过"。**
测试失败揭示源码 bug 是技能产出的核心价值之一——发现一个边界未处理的真实 bug，
比一百个全绿的无效测试更有价值。

基于这一使命，下列强约束和行为准则不可动摇。

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
2. **按语言检查工具可用性**：具体的检查命令和缺失时的降级行为，见对应语言
   参考文档的「覆盖率收集」和「Dead Code 检测」章节。
3. **写入工具状态**：将检查结果存入 `test_cases.json` 的 `tool_status` 字段，
   供后续步骤读取。
4. **降级策略**：工具不可用时跳过对应功能，报告注明跳过原因，不影响测试执行。

### `init` 命令

1. **解析参数**：`--mode`（默认 incremental）、`--source`（默认全仓库）。
2. **检查基线**：读取 `test/generated_unit/test_cases.json`。
   - 不存在或解析失败 → 提示"未检测到基线，自动退化为全量模式"，切换 `full`。
3. **扫描源码**：
   - 应用排除规则 + `--source` 限定范围。排除规则见
     [`references/scanning.md`](references/scanning.md)。
   - 自动识别语言和测试框架（同上）。
   - 解析每个源文件的函数/方法签名和行为。各语言的扫描规则和过滤条件见
     `references/` 下的语言参考文档。
4. **计算哈希**：对每个文件和每个函数分别计算 MD5。
5. **对比基线**（增量模式）：
   - 文件 MD5 相同 → 跳过整个文件。
   - 文件 MD5 变化但函数 MD5 未变 → 跳过该函数。
   - 函数 MD5 变化或新增 → 标记为需要重新生成。
   - 基线中存在但扫描未发现的函数 → 标记为删除。
6. **分析函数行为**：对需要重新生成的函数做特征分析，判定适用的测试维度。
   维度定义见 [`references/dimensions.md`](references/dimensions.md)，
   各语言的特征检测规则见 `references/` 下的语言参考文档。
7. **写入基线文件**：
   - scanner 的标准输出是 JSON，必须保存到两个位置：
     - `test/generated_unit/scan_result.json`（scanner 原始输出）
     - `test/generated_unit/test_cases.json`（基线文件）
   - 增量模式下，merge 变更到现有 `test_cases.json`。
   - **确保 `test_cases.json` 始终存在**：如果 run 或 generate 阶段找不到
     `test_cases.json`，应先检查 `scan_result.json` 并自动提升为基线。
   - 只存元数据（签名、MD5、维度、测试 case 描述），不存测试代码。
     基线文件结构见 [`references/test-cases-schema.md`](references/test-cases-schema.md)。

大仓库策略：如果扫描到超过 30 个源文件，考虑按文件分批处理（Claude 自行决定
是否拆分），避免单次分析过载。

### `generate` 命令

1. **读取 `test_cases.json`**（如果不存在，自动从 `scan_result.json` 提升）。
2. **生成共享工具文件**（如果不存在或技能版本升级）。各语言的辅助文件
   （Python 的 `_helpers.py`、C++ 的 `_helpers.hpp`）见对应语言参考文档。
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
   - 生成前先读取对应语言的参考文档获取数据构造策略和测试模板。

### `run` 命令

1. **执行测试框架**：增量模式下只跑受影响的测试文件。各语言的执行命令见
   对应语言参考文档。
2. **收集覆盖率数据**：读取 `tool_status` 确认工具可用性，按语言执行覆盖率收集，
   与阈值对比标记未达标。详细规则见
   [`references/coverage.md`](references/coverage.md)，具体命令见对应语言参考文档。
3. **Dead code 检测**：读取 `tool_status` 确认工具可用性，按语言执行静态分析，
   与覆盖率 0% 的函数交叉验证。详细规则见
   [`references/coverage.md`](references/coverage.md)。
4. **失败处理**：
   - 生成代码问题（断言写错、mock 不对）→ 修正测试代码，重跑。
   - 疑似源码 bug → 不修改源码，记入报告。
   - **skip 用例视为测试代码问题**：所有 skip 必须修复（构造真实输入替换 skip）。
   - 最多重试 5 轮，仍失败则报告。
5. **写入 `report.md`**，包含测试结果、覆盖率报告、dead code 检测结果、skip
   数量和原因。报告模板见 [`references/report-format.md`](references/report-format.md)。

### `auto` 命令

串联 `init → generate → run`。中间任一步失败则停止并报告错误位置。

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

**命名规则**：源码 `src/<path>/<n>.<ext>` → 测试 `test/generated_unit/<path>/test_<n>.<ext>`。
每个测试文件顶部加注释：

```
AUTO-GENERATED by unit-test-gen skill. DO NOT EDIT.
Source: src/core/parser.py
Regenerate with: /unit-test-gen auto
```

---

## 辅助脚本

`scripts/` 下的脚本是 Claude 的工具，使用前应先阅读其代码并按需调整：

- **`scan_repo.py`** — 扫描仓库，输出函数列表和 MD5。支持多种语言。
  用法：`python scripts/scan_repo.py <repo_root> [--source core,utils] [--language python|cpp]`

- **`analyze_function.py`** — 对单个函数做特征分析，输出适用维度。
  用法：`python scripts/analyze_function.py <source_file> --function <n> [--language python|cpp]`

- **`batch_generate.py`** — 批量生成测试代码。支持多种语言。
  用法：`python scripts/batch_generate.py --test-cases test_cases.json [--language python|cpp]`

- **`run_and_report.py`** — 执行测试并生成 markdown 报告。支持多种测试框架。
  用法：`python scripts/run_and_report.py --output report.md [--language python|cpp]`

---

## 参考文档索引

| 文档 | 内容 |
|------|------|
| [`references/language-python.md`](references/language-python.md) | Python 扫描规则、pytest 模板、mock 实现、覆盖率、dead code |
| [`references/language-cpp.md`](references/language-cpp.md) | C++ 扫描规则、gtest 模板、mock 实现、覆盖率、dead code |
| [`references/dimensions.md`](references/dimensions.md) | 六个测试维度的定义、触发条件、通用测试策略 |
| [`references/coverage.md`](references/coverage.md) | 覆盖率配置、三种指标、阈值判定、dead code 通用策略 |
| [`references/scanning.md`](references/scanning.md) | 语言识别规则、扫描排除路径 |
| [`references/test-cases-schema.md`](references/test-cases-schema.md) | `test_cases.json` 字段结构和设计约束 |
| [`references/report-format.md`](references/report-format.md) | `report.md` 模板和字段说明 |
