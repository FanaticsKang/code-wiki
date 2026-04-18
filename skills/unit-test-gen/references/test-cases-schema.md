# test_cases.json 结构说明

基线文件只存元数据和 MD5，**不存测试代码**（测试代码只在生成的测试文件里）。

## 完整结构

```json
{
  "version": "1.0",
  "generated_at": "2026-04-16T12:34:56+09:00",
  "languages": ["python", "cpp"],
  "test_frameworks": {"python": "pytest", "cpp": "gtest"},
  "source_dirs": ["src"],
  "mode_last_run": "incremental",
  "summary": {
    "total_files": 42,
    "total_functions": 187,
    "total_cases": 612
  },
  "coverage_config": {
    "statement_threshold": 70,
    "function_threshold": 70,
    "branch_threshold": 60,
    "exclude_dirs": [],
    "dead_code_min_confidence": 80
  },
  "tool_status": {
    "pytest_cov": true,
    "vulture": true,
    "gcov": false,
    "lcov": false,
    "cppcheck": false
  },
  "files": {
    "src/core/parser.py": {
      "file_md5": "a1b2c3...",
      "test_path": "test/generated_unit/core/test_parser.py",
      "functions": {
        "parse_header": {
          "func_md5": "d4e5f6...",
          "line_range": [12, 45],
          "signature": "parse_header(data: bytes, strict: bool = False) -> Header",
          "is_async": false,
          "class_name": null,
          "dimensions": ["functional", "boundary", "exception", "security"],
          "cases": [
            {
              "id": "parse_header_functional_normal",
              "type": "normal",
              "dimension": "functional",
              "description": "标准输入返回预期的 Header 对象"
            },
            {
              "id": "parse_header_boundary_empty",
              "type": "boundary",
              "dimension": "boundary",
              "description": "空 bytes 输入的边界行为"
            }
          ]
        }
      }
    },
    "src/core/lexer.cpp": {
      "file_md5": "7g8h9i...",
      "test_path": "test/generated_unit/core/test_lexer.cpp",
      "functions": {
        "Tokenize": {
          "func_md5": "j1k2l3...",
          "line_range": [30, 78],
          "signature": "std::vector<Token> Tokenize(const std::string& input, size_t max_tokens = 1024)",
          "is_async": false,
          "class_name": "Lexer",
          "dimensions": ["functional", "boundary", "exception", "performance"],
          "cases": [
            {
              "id": "Lexer_Tokenize_functional_normal",
              "type": "normal",
              "dimension": "functional",
              "description": "标准输入返回正确的 Token 序列"
            },
            {
              "id": "Lexer_Tokenize_boundary_max_tokens",
              "type": "boundary",
              "dimension": "boundary",
              "description": "超过 max_tokens 时截断并正确终止"
            },
            {
              "id": "Lexer_Tokenize_exception_invalid_utf8",
              "type": "error",
              "dimension": "exception",
              "description": "非法 UTF-8 字节序列抛出 std::runtime_error"
            }
          ]
        }
      }
    }
  }
}
```

## 字段说明

### 顶层字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `version` | string | 基线格式版本 |
| `generated_at` | string | ISO 8601 时间戳 |
| `languages` | string[] | 检测到的语言列表 |
| `test_frameworks` | object | 各语言对应的测试框架，键为语言，值为框架名 |
| `source_dirs` | string[] | 扫描的源码目录 |
| `mode_last_run` | string | 上次运行模式（`full` / `incremental`） |
| `summary` | object | 汇总统计 |
| `coverage_config` | object | 覆盖率配置（可选，未配置时使用默认值） |
| `tool_status` | object | 工具可用状态（环境预检自动写入） |
| `files` | object | 以文件路径为键的文件级数据 |

### summary

| 字段 | 类型 | 说明 |
|------|------|------|
| `total_files` | int | 扫描到的源文件数 |
| `total_functions` | int | 需要测试的函数总数 |
| `total_cases` | int | 测试用例总数 |

### files > 文件对象

| 字段 | 类型 | 说明 |
|------|------|------|
| `file_md5` | string | 文件内容 MD5 |
| `test_path` | string | 对应的测试文件路径 |
| `functions` | object | 以函数名为键的函数级数据 |

### functions > 函数对象

| 字段 | 类型 | 说明 |
|------|------|------|
| `func_md5` | string | 函数体 MD5 |
| `line_range` | int[2] | 函数起止行号 |
| `signature` | string | 完整函数签名 |
| `is_async` | bool | 是否异步函数 |
| `class_name` | string? | 所属类名，顶层函数为 null |
| `dimensions` | string[] | 适用的测试维度 |
| `cases` | object[] | 测试用例描述列表 |

### cases > 用例对象

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | string | 用例唯一标识（`函数名_维度_类型`） |
| `type` | string | 用例类型（normal / boundary / error 等） |
| `dimension` | string | 所属维度 |
| `description` | string | 用例行为描述 |

## 设计约束

- `test_frameworks` 的值由各语言参考文档定义（Python → pytest，C++ → gtest）
- 增量模式通过对比 `file_md5` 和 `func_md5` 判定变更范围
- `cases` 只存描述元数据，**不含**测试代码、输入输出值
- `coverage_config` 为可选字段，缺失时使用默认阈值（语句 70%、函数 70%、分支 60%）
- `tool_status` 由环境预检自动写入，不应手动修改

### coverage_config

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `statement_threshold` | int | 70 | 语句覆盖率最低阈值（%） |
| `function_threshold` | int | 70 | 函数覆盖率最低阈值（%） |
| `branch_threshold` | int | 60 | 分支覆盖率最低阈值（%） |
| `exclude_dirs` | string[] | [] | 排除覆盖率统计的目录 |
| `dead_code_min_confidence` | int | 80 | dead code 检测的最低置信度（%） |

### tool_status

| 字段 | 类型 | 说明 |
|------|------|------|
| `pytest_cov` | bool | Python 覆盖率工具 pytest-cov 是否可用 |
| `vulture` | bool | Python dead code 检测工具 vulture 是否可用 |
| `gcov` | bool | C++ 覆盖率工具 gcov 是否可用 |
| `lcov` | bool | C++ 覆盖率报告工具 lcov 是否可用 |
| `cppcheck` | bool | C++ 静态分析工具 cppcheck 是否可用 |
