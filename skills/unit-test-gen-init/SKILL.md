··---
name: unit-test-gen-init
description: 单测生成流水线的初始化阶段:为 Python / C++ 项目扫描代码仓库并生成或增量更新 `test_cases.json` 基线文件。
---

# unit-test-gen-init

扫描代码仓库(Python 和/或 C++),生成 `test_cases.json` 基线文件 —— 记录每个可测试函数的 MD5、源码位置、签名、适用的测试维度和建议的 mock。同时统计文件和函数的扫描完整性覆盖率。

## 扫描器的工作原理

初始化分为两个阶段,由两个独立脚本完成:

1. **`scan_repo.py`**(纯扫描器):遍历仓库源码,用 AST 提取函数信息,输出原始扫描结果(含 `features` 字段)到 `.test/scan_result.json`
2. **`build_baseline.py`**(基线生成器):读取原始扫描结果,移除 `features`,与已有基线 merge,统计覆盖率,写入 `test_cases.json`

`scan_repo.py` 只负责扫描,`build_baseline.py` 只负责基线生成和 merge —— 职责清晰,原始扫描结果始终保留在 `.test/` 下供审计。

## 标准工作流

**这是 99% 的情况下应该走的流程**。不要预先询问用户任何参数 —— 按下面的决策树直接跑。

### 步骤 1:扫描仓库

```bash
python scripts/scan_repo.py <repo_root> --output .test/scan_result.json
```

### 步骤 2:生成基线

#### 2a:首次生成(基线不存在)

```bash
python scripts/build_baseline.py --scan .test/scan_result.json --output test/generated_unit/test_cases.json --mode full
```

#### 2b:增量生成(基线已存在)

```bash
python scripts/build_baseline.py --scan .test/scan_result.json --output test/generated_unit/test_cases.json
```

`build_baseline.py` 会自动与已有 `test_cases.json` merge,保留用户编辑的 `coverage_config`、`tool_status`、未变函数的 `cases`。

### 步骤 3:报告结果

读取两个脚本的 stderr 摘要,向用户报告:

1. **扫描覆盖率**:文件扫描率、函数提取率
2. **语言和维度分布**:Python/C++,functional/boundary/exception 等
3. **增量诊断**(如有):变更文件数、新增/删除函数
4. **重点**:如果函数因 MD5 改变导致 `cases` 被清空,明确列出这些函数名

## 故障排查出口:检视模式

如果扫描结果看起来异常,可以检查原始扫描结果:

```bash
cat .test/scan_result.json | python3 -m json.tool | head -50
```

原始扫描结果包含比基线更多的信息(`features`、`decorators`、`has_float_type`、`total_funcs_found` 等),供诊断使用。

## 调试产物

所有调试产物保存在 `.test/` 目录下:

- `.test/scan_result.json`:原始扫描结果(含 `features` 等完整 AST 特征)

## 依赖

- Python 3.9+(使用了 `ast.unparse`、`|` 类型联合)
- C++ 扫描需要:`pip install tree-sitter tree-sitter-cpp`
  - 如果仓库里有 C++ 文件但这个依赖没装,扫描器会在 stderr 打印警告并跳过 C++ 文件

## 输出格式

基线 `test_cases.json` 长这样:

```json
{
  "version": "1.0",
  "generated_at": "2026-04-20T12:34:56+09:00",
  "languages": ["python"],
  "test_frameworks": {"python": "pytest"},
  "source_dirs": ["."],
  "mode_last_run": "full",
  "summary": {
    "total_files": 104,
    "total_functions": 805,
    "total_cases": 0,
    "total_source_files": 120,
    "scanned_files": 104,
    "file_scan_rate": 86.7,
    "total_functions_found": 850,
    "extracted_functions": 805,
    "function_scan_rate": 94.7
  },
  "coverage_config": { "...": "用户可编辑,扫描时保留" },
  "files": {
    "core/parser.py": {
      "file_md5": "...",
      "test_path": "test/generated_unit/core/test_parser.py",
      "functions": {
        "parse_header": {
          "func_md5": "...",
          "line_range": [12, 45],
          "signature": "parse_header(data: bytes, strict: bool = False) -> Header",
          "is_async": false,
          "class_name": null,
          "dimensions": ["functional", "boundary", "exception"],
          "mocks_needed": [],
          "cases": []
        }
      }
    }
  }
}
```

`features` 字段仅存在于 `.test/scan_result.json`(原始扫描结果),不进入基线。

完整字段说明:见 `references/baseline-schema.md`。
维度判定规则:见 `references/dimensions.md`。

## 字段保留规则

基线生成时 `coverage_config`、`tool_status`、未变函数的 `cases` 都会保留;`func_md5` 变化会清空该函数的 `cases`,这是下游需要重新生成测试的信号。

## 默认跳过的内容

- **目录**:`__pycache__`、`.git`、`.venv`、`node_modules`、`test`/`tests`、  `docs`、`scripts`、`third_party`、`vendor`,以及任何以 `.` 开头或 `.egg-info`结尾的目录
- **Python 文件**:以 `_` 开头(除 `__init__.py`)、以 `_generated.py` 结尾
- **函数**:桩函数、property setter、`@overload`、C++ `main`、析构、纯虚、`= default`、`= delete`

若用户报告"我的函数被漏了",优先怀疑是否匹配上述任一规则;其次检查解析错误(Python 版本过新、文件截断、编码异常)。
