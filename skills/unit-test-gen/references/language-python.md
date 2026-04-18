# Python 语言参考 — 单元测试生成器

本文档详细说明 Python 代码的扫描规则、函数分析方法、pytest 测试代码的生成规范。
是 SKILL.md 中通用流程的 Python/pytest 特定实现。

---

## 函数扫描规则

### 扫描范围

对每个 `.py` 文件，提取以下函数/方法：

| 类型 | 示例 | 是否扫描 |
|------|------|----------|
| 模块级公共函数 | `def foo(x): ...` | 是 |
| 模块级私有函数 | `def _foo(x): ...` | 是 |
| 类的公共方法 | `class C: def m(self): ...` | 是 |
| 类的私有方法 | `class C: def _m(self): ...` | 是 |
| `@staticmethod` / `@classmethod` | 各种类方法装饰器 | 是 |
| `@property` getter | `@property def x(self): ...` | 是 |
| 异步函数 | `async def foo(): ...` | 是 |
| 嵌套函数 | 函数内部的 `def` | 否 |
| lambda | `lambda x: x+1` | 否 |

### 过滤规则

以下情况跳过，**不生成测试**：

1. **存根函数**：函数体只有 `pass` 或 `...`（包括 Protocol、抽象方法等占位实现）。

2. **`@property` setter**：`@x.setter def x(self, v): ...` 通常只是简单赋值，
   测试价值低，且与 getter 成对出现时会重复。

3. **主程序块内函数**：
   ```python
   if __name__ == "__main__":
       def helper(): ...   # 跳过
   ```

4. **私有模块**：文件名以 `_` 开头的模块（如 `_internal.py`），但 `__init__.py`
   除外。

5. **纯重导出**：文件内只有 `from x import y` 这类语句，没有实际函数定义。

6. **被 `@typing.overload` 标记的函数**：这些是类型声明占位，不是真实实现。

### 签名提取

对每个要测试的函数，提取：

- 函数名
- 所属类（如有）
- 参数列表：`[{"name": str, "annotation": str, "default": str | None}, ...]`
- 返回类型注解
- 装饰器列表
- 是否 async
- 源码行号范围 `[start, end]`
- 函数体源码的 MD5

---

## 函数行为分析（AST 特征检测）

对每个函数的 AST 做遍历，记录以下特征。这些特征决定了要生成哪些测试维度。

### 检测项对照表

| 特征 | AST 节点 / 检测条件 | 标记 |
|------|---------------------|------|
| 数值运算符 | `ast.BinOp`（`Add`/`Sub`/`Mult`/`Div`/`Pow`/`Mod`） | `has_numeric_op` |
| math 库调用 | `ast.Call` 且 `func.value.id == "math"` | `uses_math` |
| numpy 库调用 | `import numpy` + 任何 `np.*` 调用 | `uses_numpy` |
| 浮点类型注解 | 参数或返回值注解含 `float` | `has_float_type` |
| try/except | `ast.Try` | `has_try` |
| raise 语句 | `ast.Raise` | `has_raise` |
| assert 语句 | `ast.Assert` | `has_assert` |
| 文件 IO | 调用 `open`、`pathlib.Path.read_*`、`pathlib.Path.write_*` | `has_file_io` |
| os.path 使用 | `ast.Attribute` 且 `value.id == "os"` 且 `attr == "path"` | `uses_os_path` |
| 网络调用 | import `requests`/`httpx`/`aiohttp`/`urllib` + 调用 | `has_network` |
| 索引访问 | `ast.Subscript`（如 `x[0]`、`x[-1]`） | `has_index_access` |
| 切片 | `ast.Slice` | `has_slicing` |
| len 调用 | `ast.Call` 且 `func.id == "len"` | `uses_len` |
| 字符串方法 | `.split`、`.join`、`.strip`、`.replace` 等 | `has_str_ops` |
| 正则 | import `re` + `re.*` 调用 | `uses_regex` |
| 迭代 | `ast.For` 或 `ast.comprehension` | `has_iteration` |
| 无副作用 | 没有赋值到 self、global、或调用 IO/网络 | `is_pure` |
| 排序操作 | `sorted()` 或 `.sort()` | `has_sort` |
| 递归调用 | 函数体内调用自身名称 | `has_recursion` |
| 大型推导式 | `ast.DictComp`、`ast.SetComp` | `has_large_comprehension` |
| 循环内字符串拼接 | `ast.AugAssign` 且 `op=Add`、值为字符串 | `has_string_concat_in_loop` |
| 子进程调用 | `subprocess.*`、`os.system()`、`os.popen()` | `has_subprocess` |
| eval/exec | `eval()`、`exec()` | `has_eval_exec` |
| SQL 操作 | `sqlite3.*`、`psycopg2.*`、`cursor.execute()` | `has_sql_ops` |
| pickle 反序列化 | `pickle.loads()`、`pickle.load()` | `has_pickle` |
| 不安全 YAML | `yaml.load()`（非 SafeLoader） | `has_yaml_unsafe` |
| Shell 格式化 | f-string（`ast.JoinedStr`）或 `.format()` | `has_shell_format` |

### 维度判定规则

根据特征标记组合判定适用维度：

```python
dimensions = ["functional", "boundary"]   # 必选

if has_try or has_raise or has_file_io or has_network:
    dimensions.append("exception")

if has_numeric_op or uses_math or uses_numpy or has_float_type:
    dimensions.append("data_integrity")

if has_sort or has_recursion or has_large_comprehension \
        or has_string_concat_in_loop \
        or (has_iteration and has_file_io):
    dimensions.append("performance")

if has_subprocess or has_eval_exec or has_sql_ops \
        or has_pickle or has_yaml_unsafe or has_shell_format:
    dimensions.append("security")
```

---

## 各维度的 pytest 测试策略

### 功能性测试

- 正向路径：标准输入 → 预期输出
- 等价类划分：有效等价类和无效等价类各选一个代表值

```python
def test_parse_header_functional_normal():
    """标准 bytes 输入返回正确的 Header 对象"""
    data = b"\\x01\\x02\\x03\\x04" + b"\\x00" * 60
    result = parse_header(data)
    assert isinstance(result, Header)
    assert result.version == 1
    assert result.length == 64
```

### 边界测试

使用 `BOUNDARY_VALUES`（定义在 `_helpers.py`）和 `@pytest.mark.parametrize`：

```python
@pytest.mark.parametrize("empty_input", [b"", bytes(), bytearray()])
def test_parse_header_boundary_empty_bytes(empty_input):
    """空字节序列应抛出 ValueError"""
    with pytest.raises(ValueError):
        parse_header(empty_input)


@pytest.mark.parametrize("value", BOUNDARY_VALUES["int"])
def test_compute_rate_boundary_int(value):
    """各种边界整数值应得到合理输出"""
    result = compute_rate(value)
    assert isinstance(result, (int, float))
```

边界值查表（`_helpers.BOUNDARY_VALUES`）：

| 类型 | 边界值 |
|------|--------|
| `int` | `0`, `-1`, `1`, `sys.maxsize`, `-sys.maxsize-1` |
| `float` | `0.0`, `inf`, `-inf`, `nan`, `1e-308`, `1e308` |
| `str` | `""`, `" "`, `"中文"`, `"\x00"`, `"a" * 10000` |
| `list`/`dict`/`set` | 空集合、单元素、嵌套空 |
| `Optional[T]` | `None` |

### 异常容错测试

- 非法输入类型 → `pytest.raises(TypeError)`
- 越界值 → `pytest.raises(ValueError)`
- 模拟 IO 失败（`FileNotFoundError`、`PermissionError`）
- 模拟网络失败（超时、404、500）

```python
def test_parse_header_exception_truncated():
    """截断的数据应抛出明确的 ValueError"""
    truncated = b"\\x01\\x02"  # 预期 64 字节
    with pytest.raises(ValueError, match="truncated|length"):
        parse_header(truncated)


def test_load_config_exception_file_not_found(tmp_path):
    """配置文件不存在时应抛出 FileNotFoundError"""
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "nonexistent.yaml")


@patch("requests.get")
def test_fetch_user_exception_timeout(mock_get):
    """网络超时时应抛出 TimeoutError"""
    mock_get.side_effect = TimeoutError("timeout")
    with pytest.raises(TimeoutError):
        fetch_user(123)
```

### 数据完整性测试

**精度验证**：
```python
def test_compute_rate_data_integrity_precision():
    """浮点运算结果应在容差范围内"""
    result = compute_rate(0.1, 0.2)
    assert_approx(result, 0.3, tol=1e-9)
```

**确定性验证**：
```python
def test_format_id_data_integrity_deterministic():
    """纯函数多次调用结果一致"""
    assert_deterministic(format_id, "user", 42, runs=5)
```

**往返验证**：
```python
def test_encode_decode_data_integrity_roundtrip():
    """encode 后 decode 应还原原值"""
    for original in [{"a": 1}, [], "hello", 3.14]:
        assert decode(encode(original)) == original
```

---

## Mock 实现细节（Python）

### Mock 外部边界的具体实现

| 依赖类型 | Mock 方式 |
|----------|-----------|
| 文件读取 | `pytest` 的 `tmp_path` fixture 构造真实临时文件；或 `patch("builtins.open", mock_open(...))` |
| 配置加载 | `patch("yaml.safe_load", return_value={...})` |
| 数据库/ORM | `patch("module.db_client", MagicMock())` |
| 网络请求 | `patch("requests.get", return_value=mock_response(...))` |
| 类方法 | `MagicMock(spec=Class)` |
| numpy/pyarrow | 直接使用真实库（纯数据变换，无副作用） |
| 异步函数 | `call_async(coro)` 包装，或 `pytest-asyncio` |

**纯数据变换永远不需要 mock**：numpy 操作、字符串处理、数值计算等直接构造输入调用即可。

### Mock 需求判定

扫描同时输出 mock 建议：

```python
mocks_needed = []
if has_file_io:
    mocks_needed.append(("file_io", "use tmp_path fixture or patch open()"))
if has_network:
    mocks_needed.append(("network", "patch requests.get / httpx.get"))
if uses_os_path and not is_pure:
    mocks_needed.append(("os_path", "consider patch os.path.exists"))
if has_subprocess:
    mocks_needed.append(("subprocess", "patch subprocess.run / os.system"))
if has_sql_ops:
    mocks_needed.append(("database", "patch sqlite3.connect and mock cursor"))
# 类方法如果有复杂 __init__ 依赖
if class_name and has_complex_deps:
    mocks_needed.append(("class_deps", "use MagicMock(spec=Class)"))
```

---

## pytest 测试代码生成规范

### 文件头

每个生成的测试文件顶部固定格式：

```python
# AUTO-GENERATED by unit-test-gen skill. DO NOT EDIT.
# Source: src/core/parser.py
# Regenerate with: /unit-test-gen auto

import sys
from pathlib import Path

# 让生成的测试能找到源码
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
from unittest.mock import MagicMock, patch, mock_open

from test.generated_unit._helpers import (
    call_async,
    assert_approx,
    assert_deterministic,
    BOUNDARY_VALUES,
    mock_file,
    mock_response,
    generate_large_input,
    assert_scalability,
    PERFORMANCE_CONFIG,
    MALICIOUS_INPUTS,
)

from src.core.parser import parse_header, Header  # 被测代码
```

**路径层数** `parents[2]` 需要根据测试文件所在深度调整：
- `test/generated_unit/test_x.py` → `parents[2]`
- `test/generated_unit/core/test_parser.py` → `parents[3]`

### 测试函数命名

格式：`test_<函数名>_<维度>_<描述>`

示例：
- `test_parse_header_functional_normal`
- `test_parse_header_boundary_empty_bytes`
- `test_parse_header_exception_truncated`
- `test_compute_rate_data_integrity_precision`
- `test_sort_data_performance_large_input`
- `test_execute_command_security_injection`

类方法命名：`test_<类名小写>_<方法名>_<维度>_<描述>`

### 功能性测试模板

```python
def test_parse_header_functional_normal():
    """标准 bytes 输入返回正确的 Header 对象"""
    data = b"\\x01\\x02\\x03\\x04" + b"\\x00" * 60
    result = parse_header(data)
    assert isinstance(result, Header)
    assert result.version == 1
    assert result.length == 64
```

### 边界测试模板

使用 `BOUNDARY_VALUES` 和 `parametrize`：

```python
@pytest.mark.parametrize("empty_input", [b"", bytes(), bytearray()])
def test_parse_header_boundary_empty_bytes(empty_input):
    """空字节序列应抛出 ValueError"""
    with pytest.raises(ValueError):
        parse_header(empty_input)


@pytest.mark.parametrize("value", BOUNDARY_VALUES["int"])
def test_compute_rate_boundary_int(value):
    """各种边界整数值应得到合理输出"""
    result = compute_rate(value)
    assert isinstance(result, (int, float))
```

### 异常容错测试模板

```python
def test_parse_header_exception_truncated():
    """截断的数据应抛出明确的 ValueError"""
    truncated = b"\\x01\\x02"  # 预期 64 字节
    with pytest.raises(ValueError, match="truncated|length"):
        parse_header(truncated)


def test_load_config_exception_file_not_found(tmp_path):
    """配置文件不存在时应抛出 FileNotFoundError"""
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "nonexistent.yaml")


@patch("requests.get")
def test_fetch_user_exception_timeout(mock_get):
    """网络超时时应抛出 TimeoutError"""
    mock_get.side_effect = TimeoutError("timeout")
    with pytest.raises(TimeoutError):
        fetch_user(123)
```

### 数据完整性测试模板

**精度验证**：
```python
def test_compute_rate_data_integrity_precision():
    """浮点运算结果应在容差范围内"""
    result = compute_rate(0.1, 0.2)
    assert_approx(result, 0.3, tol=1e-9)
```

**确定性验证**：
```python
def test_format_id_data_integrity_deterministic():
    """纯函数多次调用结果一致"""
    assert_deterministic(format_id, "user", 42, runs=5)
```

**往返验证**：
```python
def test_encode_decode_data_integrity_roundtrip():
    """encode 后 decode 应还原原值"""
    for original in [{"a": 1}, [], "hello", 3.14]:
        assert decode(encode(original)) == original
```

### 性能测试模板

**基本负载测试**：
```python
def test_sort_data_performance_large_input():
    """大规模输入下排序应在合理时间内完成"""
    large_input = generate_large_input("list", PERFORMANCE_CONFIG["large"]["size"])
    import time
    start = time.perf_counter()
    result = sort_data(large_input)
    elapsed = time.perf_counter() - start
    # 不做硬性超时断言，记录时间供 CI 报告
    assert isinstance(result, list)
    assert len(result) == len(large_input)
```

**可扩展性测试**：
```python
def test_search_index_performance_scalability():
    """验证处理时间随输入规模线性增长"""
    small = generate_large_input("list", 100)
    large = generate_large_input("list", 10000)
    ratio = assert_scalability(search_index, small, large, max_ratio=200.0)
    # ratio 记录在报告中供人工审查
```

**递归深度测试**：
```python
def test_fibonacci_performance_deep_recursion():
    """较深递归不应导致栈溢出"""
    # 使用不会触发 sys.setrecursionlimit 的值
    result = fibonacci(30)
    assert isinstance(result, int)
    assert result > 0
```

**内存稳定性测试**：
```python
def test_build_report_performance_memory():
    """大字符串拼接不应导致内存异常"""
    chunks = [f"chunk_{i}" for i in range(10000)]
    result = build_report(chunks)
    assert isinstance(result, str)
    assert len(result) > 0
```

### 安全测试模板

**命令注入测试**：
```python
@patch("subprocess.run")
def test_execute_command_security_injection(mock_run):
    """用户输入中的特殊字符不应被执行为 shell 命令"""
    mock_run.return_value = MagicMock(returncode=0, stdout=b"ok")
    for malicious, desc in MALICIOUS_INPUTS["command_injection"]:
        execute_command(malicious)
        # 验证传入 subprocess.run 的参数未被 shell 解释
        call_args = mock_run.call_args
        if isinstance(call_args[0][0], str):
            # 如果是字符串调用，验证未使用 shell=True
            assert call_args[1].get("shell") is not True, \
                f"shell=True 与用户输入组合不安全: {desc}"
    mock_run.reset_mock()
```

**SQL 注入测试**：
```python
@patch("sqlite3.connect")
def test_query_user_security_sql_injection(mock_connect):
    """用户输入中的 SQL 片段不应改变查询语义"""
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = None
    mock_connect.return_value.cursor.return_value = mock_cursor

    for malicious, desc in MALICIOUS_INPUTS["sql_injection"]:
        query_user(malicious)
        # 验证使用了参数化查询而非字符串拼接
        for call in mock_cursor.execute.call_args_list:
            sql = call[0][0] if call[0] else ""
            assert malicious not in sql, \
                f"用户输入直接拼接到 SQL 中: {desc}"
    mock_cursor.reset_mock()
```

**路径遍历测试**：
```python
def test_read_file_security_path_traversal(tmp_path):
    """用户控制的文件路径不应越界访问"""
    safe_dir = tmp_path / "safe"
    safe_dir.mkdir()
    (safe_dir / "allowed.txt").write_text("ok")

    for malicious, desc in MALICIOUS_INPUTS["path_traversal"]:
        result = read_file(safe_dir, malicious)
        # 函数应拒绝路径遍历尝试
        assert result is None or "error" in str(result).lower(), \
            f"路径遍历未被阻止: {desc}"
```

**eval/exec 安全测试**：
```python
def test_evaluate_expression_security_code_injection():
    """eval/exec 不应执行任意代码"""
    dangerous_inputs = [
        "__import__('os').system('echo pwned')",
        "open('/etc/passwd').read()",
        "().__class__.__bases__[0].__subclasses__()",
    ]
    for dangerous in dangerous_inputs:
        with pytest.raises((ValueError, TypeError, AttributeError)):
            evaluate_expression(dangerous)
```

**输入清洗验证**：
```python
def test_sanitize_input_security_xss():
    """输出应清洗 XSS 向量"""
    for malicious, desc in MALICIOUS_INPUTS["xss"]:
        result = sanitize_input(malicious)
        assert "<script>" not in result.lower(), \
            f"XSS 向量未被清洗: {desc}"
```

### 异步函数测试模板

```python
def test_fetch_data_functional_normal():
    """异步函数的同步测试"""
    result = call_async(fetch_data(user_id=1))
    assert result["id"] == 1
```

或使用 `pytest-asyncio`（如果项目已引入）：

```python
@pytest.mark.asyncio
async def test_fetch_data_functional_normal():
    result = await fetch_data(user_id=1)
    assert result["id"] == 1
```

默认优先使用 `call_async()` 包装，避免对 `pytest-asyncio` 的依赖。

### 类方法测试模板

```python
class TestParser:
    """Parser 类的测试"""

    def setup_method(self):
        """每个测试前的准备"""
        self.parser = Parser(strict=False)

    def test_parser_parse_functional_normal(self):
        """标准输入应正确解析"""
        result = self.parser.parse(b"valid data")
        assert result is not None

    def test_parser_parse_boundary_empty(self):
        """空输入边界情况"""
        result = self.parser.parse(b"")
        assert result is None
```

如果 `__init__` 依赖复杂（如需要数据库连接、文件管理器等），用 `MagicMock(spec=...)`：

```python
def test_node_process_functional_normal():
    """节点处理的标准流程"""
    mock_folder_mgr = MagicMock(spec=FolderManager)
    mock_folder_mgr.get_path.return_value = Path("/tmp/test")
    node = Node(folder_manager=mock_folder_mgr, name="test")
    result = node.process([1, 2, 3])
    assert result == [2, 4, 6]
```

---

## 执行 pytest

### 命令

```bash
python -m pytest test/generated_unit/ -v --tb=short
```

### 常用参数

- `-v`：显示每个测试的名称和结果
- `--tb=short`：失败时只显示简短回溯
- `-x`：第一个失败就停止
- `-k "boundary"`：只跑名字里含 "boundary" 的测试
- `--co`：仅收集测试，不执行（用于验证测试能被 pytest 发现）

### 退出码

- 0：全部通过
- 1：有失败
- 2：被中断
- 3：内部错误
- 4：命令行参数错误
- 5：没收集到测试（说明生成的文件没被 pytest 识别）

### 增量模式执行

从 `test_cases.json` 读出变更过的文件列表，只跑对应测试：

```bash
python -m pytest \
  test/generated_unit/core/test_parser.py \
  test/generated_unit/utils/test_format.py \
  -v --tb=short
```

---

## 覆盖率收集（Python）

### 依赖

`pytest-cov`（环境预检自动检查，未安装时尝试 `pip install pytest-cov -i https://pypi.org/simple/`）。

### 收集命令

```bash
python -m pytest test/generated_unit/ \
  --cov --cov-branch \
  --cov-report=json:coverage.json \
  --cov-report=term-missing \
  -v --tb=short
```

- `--cov`：启用覆盖率收集（语句覆盖率和函数覆盖率）
- `--cov-branch`：同时收集分支覆盖率
- `--cov-report=json:coverage.json`：输出 JSON 格式报告（用于解析详细数据）
- `--cov-report=term-missing`：终端输出未覆盖的行号

### 覆盖率配置

使用项目根目录的 `.coveragerc` 或 `pyproject.toml [tool.coverage]`。如果没有，覆盖率统计所有源码目录。

### 指标解析

从 `coverage.json` 提取三种指标：

| 指标 | JSON 路径 | 计算方式 |
|------|----------|---------|
| 语句覆盖率 | `files[<path>].summary.covered_lines / num_statements` | 已执行语句占比 |
| 函数覆盖率 | `files[<path>].functions` 中 `count > 0` 的比例 | 已调用函数占比 |
| 分支覆盖率 | `files[<path>].summary.covered_branches / num_branches` | 已走分支占比 |

### 总计指标

从 `coverage.json` 的顶层 `totals` 字段直接读取：

```python
totals = data["totals"]
statement_pct = totals["covered_lines"] / totals["num_statements"] * 100
branch_pct = totals["covered_branches"] / totals["num_branches"] * 100
```

---

## Dead Code 检测（Python）

### 依赖

`vulture`（环境预检自动检查，未安装时尝试 `pip install vulture -i https://pypi.org/simple/`）。

### 检测命令

```bash
vulture <source_dirs> --min-confidence 80 --sort-by-size
```

- `--min-confidence`：最低置信度阈值（来自 `coverage_config.dead_code_min_confidence`，默认 80）
- `--sort-by-size`：按代码大小排序，优先展示最可能的无用代码

### 输出格式

```
<file>:<line>: unused <type> '<name>' (<confidence>%)
```

### 解析策略

1. 逐行解析输出，提取 `文件路径:行号:类型:名称:置信度`
2. 过滤已知误报：
   - 入口函数：`main`、`if __name__ == "__main__"` 下的调用
   - CLI handler：带 `@click.command`、`argparse` 相关装饰器的函数
   - 测试辅助：`conftest.py` 中的 fixture
3. 与覆盖率 0% 的函数列表交叉验证，两处都标记的优先级更高

### 局限性

- 动态调用（`getattr(obj, name)`）会导致误报
- 插件/注册机制调用的函数会被误报
- 报告中标注为「候选项」，建议用户复核

---

## 常见坑和应对

### 1. 路径问题

生成的测试可能因 `sys.path` 未正确设置而 import 失败。解决方案：
- 在每个测试文件顶部用 `sys.path.insert(0, ...)`
- 或在 `test/generated_unit/conftest.py` 中集中设置
- 优先使用相对 import（如果项目是正规 package）

### 2. 循环 import

源码内部循环 import 时，`from src.x import Y` 可能失败。此时退化为 `import src.x`
然后 `src.x.Y` 引用。

### 3. 类方法的 fixture

`setup_method` 在每个测试前执行，适合轻量初始化。如果初始化开销大，用 `@pytest.fixture`
+ `scope="class"`。

### 4. 全局状态

被测代码如果依赖全局状态（如 singleton、module-level 变量），测试间可能互相污染。
用 `monkeypatch` 隔离，或在 `setup_method` 中重置。

### 5. 随机性

被测函数如果使用 `random.*`，测试中 `monkeypatch.setattr("random.random", lambda: 0.5)`
固定返回值；或传入 `random.Random(42)` 类似的 seeded 对象。

### 6. 时间依赖

函数如果依赖 `datetime.now()`，用 `freezegun` 或 `patch("module.datetime")`。
