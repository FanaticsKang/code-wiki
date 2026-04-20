# `test_cases.json` 字段说明

本文档列出基线文件的完整字段。字段分为三类:
- **扫描器管理**:每次扫描都会被重写
- **用户编辑**:扫描会保留用户的修改
- **下游工具管理**:由测试生成器、覆盖率报告器等其他工具写入

## 顶层字段

| 字段 | 类型 | 管理者 | 说明 |
|---|---|---|---|
| `version` | string | 扫描器 | 基线格式版本,当前为 `"1.0"` |
| `generated_at` | string | 扫描器 | 最后一次扫描的 ISO 8601 时间戳 |
| `languages` | [string] | 扫描器 | 检测到的语言,`"python"` / `"cpp"` |
| `test_frameworks` | object | 扫描器 | 每种语言的默认测试框架,如 `{"python": "pytest", "cpp": "gtest"}` |
| `source_dirs` | [string] | 扫描器 | 本次扫描限定的源码目录;未限定时为 `["."]` |
| `mode_last_run` | string | 扫描器 | `"full"` 或 `"incremental"` |
| `summary` | object | 扫描器 | 汇总计数,见下 |
| `coverage_config` | object | 用户 | 覆盖率阈值等用户编辑项,见下 |
| `tool_status` | object | 下游 | 运行时工具可用性,由 `run_and_report` 维护 |
| `files` | object | 混合 | 每个源文件一项,key 为相对路径 |

## `summary`

```json
{
  "total_files": 42,
  "total_functions": 187,
  "total_cases": 612
}
```

`total_cases` 是所有函数 `cases` 数组长度之和。首次扫描时为 0,下游测试生成器填充 `cases` 后才会非零。

## `coverage_config`

用户可编辑。扫描器只在该字段缺失时写入默认值,后续扫描一律保留。

```json
{
  "statement_threshold": 90,
  "function_threshold": 100,
  "branch_threshold": 90,
  "exclude_dirs": [],
  "dead_code_min_confidence": 80
}
```

## `tool_status`

由运行时工具(如覆盖率报告器)写入,扫描器只保留不修改。示例:

```json
{
  "pytest_cov": true,
  "vulture": true,
  "gcov": false,
  "lcov": false,
  "cppcheck": false
}
```

## `files[<path>]`

每个源文件一项。key 是相对于仓库根的 POSIX 风格路径。

| 字段 | 类型 | 管理者 | 说明 |
|---|---|---|---|
| `file_md5` | string | 扫描器 | 文件原始内容的 MD5 |
| `test_path` | string | 扫描器(可手改) | 生成的测试文件路径;可以被手动编辑,后续扫描保留 |
| `functions` | object | 混合 | 函数 key(如 `Class.method` / `Namespace::Class::method`)→ 函数条目 |

## `files[<path>].functions[<key>]`

函数 key 的格式:
- Python 自由函数:`parse_header`
- Python 类方法:`Parser.parse_header`
- C++ 自由函数:`tokenize` 或 `ns::tokenize`
- C++ 类方法:`Lexer::tokenize` 或 `ns::Lexer::tokenize`

| 字段 | 类型 | 管理者 | 说明 |
|---|---|---|---|
| `name` | string | 扫描器 | 函数名(不含类/命名空间限定) |
| `class_name` | string \| null | 扫描器 | 所属类名(裸类名,不含命名空间),自由函数为 `null` |
| `namespace` | string \| null | 扫描器(仅 C++) | C++ 命名空间,支持嵌套如 `"outer::inner"` |
| `func_md5` | string | 扫描器 | 函数源代码原始文本的 MD5 |
| `line_range` | [int, int] | 扫描器 | 起止行号(从 1 开始,闭区间) |
| `signature` | string | 扫描器 | 函数签名字符串,供人类阅读 |
| `dimensions` | [string] | 扫描器 | 适用的测试维度,见 `dimensions.md` |
| `features` | object | 扫描器 | AST 特征布尔标志,用于解释 dimensions 的判定依据 |
| `mocks_needed` | [object] | 扫描器 | 基于特征建议的 mock,每项含 `type` 和 `suggestion` |
| `cases` | [object] | 下游 | 具体测试用例描述,扫描器永远不写,函数 MD5 未变时保留 |

### Python 特有字段

| 字段 | 说明 |
|---|---|
| `is_async` | 是否 `async def` |
| `decorators` | 装饰器文本列表 |
| `has_float_type` | 参数或返回值是否有 `float` 相关类型注解 |

### C++ 特有字段

| 字段 | 说明 |
|---|---|
| `is_template` | 是否模板函数或模板类成员 |
| `is_static` | 是否 `static` 成员 |
| `is_virtual` | 是否 `virtual` 成员 |

## MD5 变化的传播规则

- **`file_md5` 变了但文件内所有 `func_md5` 都没变**:可能是文件级的非函数改动(全局常量、import、顶层注释等)。该文件所有函数的 `cases` 保留。
- **`func_md5` 变了**:该函数的 `cases` 被清空为 `[]`。这是唯一会导致 `cases` 丢失的情况,也是下游重新生成测试的信号。
- **函数从文件里消失**:从基线里删除。
- **新增函数**:加入基线,`cases` 初始化为 `[]`。

## `incremental` 字段(仅调试模式)

仅在调试模式下,扫描器的 stdout 输出会额外包含 `incremental` 字段,用于人工诊断变化。工作流模式下不会写进文件。

```json
{
  "is_incremental": true,
  "changed_files": ["src/parser.py"],
  "new_files": ["src/new_module.py"],
  "removed_files": ["src/obsolete.py"]
}
```
