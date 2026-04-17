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
