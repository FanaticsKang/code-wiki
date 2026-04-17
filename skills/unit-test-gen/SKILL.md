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

## 核心原则

### 全自动无交互

整个流程自动完成，**不向用户询问任何问题**。遇到编译错误、导入失败、断言失败等问题时，
自行分析原因、修复测试代码、重试。只有在所有自动修复手段穷尽后才在报告中记录问题。

### 客观反映源码真实行为

测试必须忠实反映源码的实际行为，而非"应该怎样"。断言基于**源码实际输出**编写，
不预设理想行为。如果源码行为与预期不符（如返回类型不一致、边界返回意外值），
以源码实际行为为准写断言，同时在报告中标记为疑似问题。

### 主动暴露源码问题

测试的目标之一是发现源码缺陷。当测试揭示以下情况时，不回避、不掩盖，
在报告中明确标记：

- 源码与类型注解/文档不一致
- 边界输入导致崩溃（未捕获异常）
- 并发/竞态隐患
- 资源泄漏（未关闭的文件/连接）

### 失败就是失败，不要隐藏为跳过

测试失败时不得通过 `pytest.skip`、`@unittest.skip`、`GTEST_SKIP` 等机制将失败
伪装为跳过。每个失败用例必须在报告中完整记录：失败断言、实际 vs 预期、所在位置。
唯一允许跳过的场景是测试环境缺少必要的运行时依赖（如特定版本的库），且必须在
报告中注明跳过原因。

### 禁止跳过函数

**凡是通过扫描过滤的函数（非存根、非私有模块），必须生成测试。** 遇到外部依赖时
用 mock 隔离后测试内部逻辑，不得以下列理由跳过：

- "依赖复杂"
- "需要集成测试覆盖"
- "需要真实环境"
- "无法 mock"

报告中也不得出现"建议通过集成测试覆盖"、"依赖复杂跳过"等措辞。

### 禁止生成空框架

每个函数必须生成完整的测试用例，包含功能性测试和边界测试的具体代码。禁止生成
只有函数签名和 `pass`、`# TODO`、`NotImplementedError` 的空壳测试。每个测试
函数体内必须有：具体的输入构造、被测函数调用、断言验证。

### Mock 外部边界，测试内部逻辑

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
| 数据库操作 | 替换数据库连接，mock 查询执行 |

**纯数据变换永远不需要 mock**：数值操作、字符串处理等直接构造输入调用即可。

各语言参考文档中有具体的 mock 实现代码和工具。

### 不修改源码

技能只在 `test/generated_unit/` 下操作。不修改任何源码文件，不覆盖用户在其他位置
手写的测试。

---

## 执行流程

### `init` 命令

1. **解析参数**：`--mode`（默认 incremental）、`--source`（默认全仓库）。
2. **检查基线**：读取 `test/generated_unit/test_cases.json`。
   - 不存在或解析失败 → 提示"未检测到基线，自动退化为全量模式"，切换 `full`。
3. **扫描源码**：
   - 应用排除规则 + `--source` 限定范围。
   - 自动识别语言和测试框架。
   - 解析每个源文件的函数/方法签名和行为（含前缀函数、类方法、getter、异步函数）。
   - 过滤：跳过存根函数（仅有空实现）、主程序块内函数、setter、私有模块（文件名以下划线开头）、纯重导出。
4. **计算哈希**：对每个文件和每个函数分别计算 MD5。
5. **对比基线**（增量模式）：
   - 文件 MD5 相同 → 跳过整个文件。
   - 文件 MD5 变化但函数 MD5 未变 → 跳过该函数。
   - 函数 MD5 变化或新增 → 标记为需要重新生成。
   - 基线中存在但扫描未发现的函数 → 标记为删除。
6. **分析函数行为**：对需要重新生成的函数做特征分析，判定适用的测试维度。
7. **写入 `test_cases.json`**：只存元数据（签名、MD5、维度、测试 case 描述），
   不存测试代码。

大仓库策略：如果扫描到超过 30 个源文件，考虑按文件分批处理（Claude 自行决定
是否拆分），避免单次分析过载。

### `generate` 命令

1. **读取 `test_cases.json`**。
2. **生成共享工具文件**（如果不存在或技能版本升级）。
3. **为每个文件生成测试**：
   - 计算输出路径（镜像源码目录结构）。
   - 按 `test_cases.json` 中的 case 描述，生成对应的测试函数。
   - 加上 AUTO-GENERATED 文件头注释。
4. **生成测试代码时的具体要求**：
   - 正确设置模块搜索路径（视项目结构而定）。
   - 每个测试函数有清晰的说明，描述测试目的。
   - 异步函数用同步包装测试。
   - 浮点断言用近似比较。
   - 边界测试用参数化方式批量运行。

### `run` 命令

1. **执行测试框架**：
   - 增量模式下只跑受影响的测试文件。
2. **失败处理**：
   - 生成代码问题（断言写错、mock 不对） → 修正测试代码，重跑。
   - 疑似源码 bug → 不修改源码，记入报告。
   - 最多重试 3 轮，仍失败则报告。
3. **写入 `report.md`**。

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
3. 两种都有 → 标记为混合仓库，Python 和 C++ 各自独立扫描和生成
4. 检查配置文件进一步确认框架（如 `CMakeLists.txt` 中 `find_package(GTest)` → gtest）

检测结果写入 `test_cases.json` 的 `languages` 和 `test_frameworks` 字段。
各语言的扫描规则、测试代码生成规范和 mock 实现见 `references/` 下的语言参考文档（`language-python.md`、`language-cpp.md`）。

---

## 扫描排除规则

以下路径自动排除，无需用户指定：

| 类型 | 排除模式 |
|------|----------|
| 测试目录 | `test/`, `tests/` |
| 虚拟环境 | `.venv/`, `venv/`, `env/` |
| 缓存 | `__pycache__/`, `.tox/`, `.pytest_cache/`, `.mypy_cache/` |
| 构建产物 | `build/`, `dist/`, `*.egg-info/` |
| 已生成代码 | `test/generated_unit/`（自身）、`*_generated.*` |
| 文档 | `docs/` |
| 工具/配置 | `.claude/`, `.git/`, `.github/`, `scripts/` |
| 第三方 | `node_modules/`, `third_party/`, `vendor/` |

---

## 六个测试维度

每个函数根据其代码特征生成不同维度的测试：

| 维度 | 触发条件 | 必选 |
|------|----------|------|
| 功能性（functional） | 所有函数 | 是 |
| 边界（boundary） | 所有函数 | 是 |
| 异常容错（exception） | 检测到错误处理、IO 操作、外部调用 | 否 |
| 数据完整性（data_integrity） | 检测到数值计算、浮点运算 | 否 |
| 性能（performance） | 检测到排序、递归、大型推导式、循环内字符串拼接、大文件迭代 | 否 |
| 安全（security） | 检测到子进程调用、动态代码执行、SQL 操作、不安全反序列化 | 否 |

### 维度判定的特征分析

各维度的具体触发条件和 AST 检测规则见 `references/` 下的语言参考文档（如 `references/language-python.md`）。

### 各维度的测试策略

**功能性（必选）**：
- 正向路径：标准输入 → 预期输出
- 等价类划分：有效等价类和无效等价类各选一个代表值

**边界（必选）**：
- 根据参数类型查表取边界值（如整数取 0/极大/极小，字符串取空/超长/特殊字符等）
- 参数化批量测试所有边界值

**异常容错（按需）**：
- 非法输入类型 → 预期抛出 TypeError
- 越界值 → 预期抛出 ValueError
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
- 命令注入测试：特殊字符（`;`、`$()`、`` ` ``、`|`）输入不触发 shell 执行
- SQL 注入测试：SQL 片段输入不改变查询语义（验证参数化查询）
- 路径遍历测试：`../` 等路径不越界访问
- eval/exec 测试：任意代码字符串不被执行
- 输入清洗验证：XSS 向量在输出中被转义或移除

各维度在具体语言/框架中的实现代码见对应的语言参考文档（如 `references/language-python.md`）。

---

## 输出目录结构

所有生成物在 `test/generated_unit/` 下，镜像源码目录结构。

```
test/generated_unit/
├── test_cases.json              # 基线文件（元数据 + MD5，不含测试代码）
├── _helpers.py                  # Python 共享工具函数
├── _helpers.hpp                 # C++ 共享工具头文件
├── report.md                    # 测试报告
├── core/
│   ├── test_parser.py           # 对应 src/core/parser.py（Python）
│   └── test_calculator.cpp      # 对应 src/core/calculator.cpp（C++）
├── utils/
│   └── test_format.py           # 对应 src/utils/format.py
└── api/
    └── test_handlers.py         # 对应 src/api/handlers.py
```

混合语言仓库中，Python（`.py`）和 C++（`.cpp`）测试文件共存于同一目录结构下。
辅助文件按语言各自一份：`_helpers.py`（pytest 工具）和 `_helpers.hpp`（gtest 工具）。

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

- **`scan_repo.py`** — 扫描仓库，输出函数列表和 MD5。
  `python scripts/scan_repo.py <repo_root> [--source core,utils]`

- **`analyze_function.py`** — 对单个函数做特征分析，输出适用维度。
  `python scripts/analyze_function.py <file.py> --function <name>`

- **`run_and_report.py`** — 执行测试并生成 markdown 报告。
  `python scripts/run_and_report.py --output report.md`

C++ 的 CMake 集成、tree-sitter 解析、辅助头文件等细节见 [`references/language-cpp.md`](references/language-cpp.md)。
