# Python 语言参考 — 模块测试生成器

## 扫描 Python 代码

### 模块发现

通过以下模式识别 Python 模块：
- 包含 `__init__.py` 的目录
- `src/` 或项目根目录下的顶级包
- 包含多个 `.py` 文件且具有共同逻辑用途的目录

扫描时排除以下目录：
- `__pycache__/`、`.git/`、`.venv/`、`venv/`、`env/`、`node_modules/`
- `tests/`、`test/`（已有测试目录）
- 根目录下的 `setup.py`、`conftest.py`
- 匹配 `.gitignore` 规则的路径

### 功能发现

在模块内部，通过以下方式识别功能：

1. **公共类**：不以 `_` 开头的类。每个类通常是一个功能。
   如果类很大（超过 10 个公共方法），考虑拆分为子功能。

2. **公共函数**：不以 `_` 开头的模块级函数。将明显相关的函数归为一个功能
   （例如 `encode()` 和 `decode()` → "编码/解码"功能）。

3. **API 端点**：带有路由装饰器的函数（`@app.route`、`@router.get` 等），
   每个端点代表一个功能。

4. **数据模型**：Pydantic 模型、dataclass 或 TypedDict 定义中代表
   核心领域对象的部分。

### 依赖追踪

查找某个功能的 related_code 的方法：

1. 从包含该功能的文件开始。
2. 跟踪 `import` 和 `from ... import` 语句。
3. 只包含**项目内部**的导入（排除标准库和第三方库）。
4. 递归一层：如果 `a.py` 导入了 `b.py`，而 `b.py` 导入了 `c.py`，
   则同时包含 `b.py` 和 `c.py`。
5. 同时包含**导入了该功能所在文件**的文件（同一模块内的反向依赖）。

### 类型和签名分析

生成 test_targets 时需注意：
- 函数参数和返回值的类型注解
- 默认参数值（暗示常见用法模式）
- `*args` / `**kwargs`（需要边界测试）
- 生成器函数（`yield`）需要迭代测试
- 上下文管理器（`__enter__`/`__exit__`）需要生命周期测试
- 属性（`@property`）需要读/写测试

---

## 生成 pytest 测试

### 文件结构

```
tests/
    module_<模块名>/
        __init__.py
        conftest.py              # 共享 fixtures
        test_<功能slug>.py       # 每个功能一个文件
```

### 测试函数模板

```python
import pytest
from unittest.mock import MagicMock, patch

# 导入被测代码
from <module>.<file> import <target>


class TestFeatureName:
    """功能测试：<功能名>"""

    @pytest.mark.manual  # 或 @pytest.mark.auto
    def test_<描述性名称>(self):
        """<来自配置的 test_target 描述>"""
        # 准备
        ...
        # 执行
        ...
        # 断言
        ...
```

### Marker 注册

在测试根目录生成 `conftest.py`，注册自定义 marker：

```python
import pytest

def pytest_configure(config):
    config.addinivalue_line("markers", "manual: 来自工程师指定的测试目标")
    config.addinivalue_line("markers", "auto: 来自自动发现的测试目标")
```

### Mock 策略

- Mock 外部服务、数据库和网络调用。
- Mock 跨模块依赖（从其他模块导入的内容）。
- 不要 Mock 同一模块内的代码——那正是我们要测试的。
- 使用 `monkeypatch` 处理环境变量和简单属性替换。
- 使用 `unittest.mock.patch` 处理更复杂的 mock 场景。

### 常见测试模式

**输入/输出结构一致性：**
```python
def test_output_structure_matches_input(self):
    input_data = create_sample_input()
    result = function_under_test(input_data)
    assert type(result) == type(input_data)
    assert set(result.keys()) == set(input_data.keys())
```

**错误处理：**
```python
def test_rejects_invalid_input(self):
    with pytest.raises(ValueError, match="预期的错误模式"):
        function_under_test(invalid_input)
```

**边界情况：**
```python
@pytest.mark.parametrize("edge_input,expected", [
    (None, default_value),
    ([], empty_result),
    ({}, empty_result),
])
def test_edge_cases(self, edge_input, expected):
    assert function_under_test(edge_input) == expected
```

---

## 运行测试

### 命令

```bash
pytest tests/module_<n>/ -v --tb=short -q 2>&1
```

### 常用参数

- `-v`：详细输出，显示每个测试名称和结果
- `--tb=short`：失败时显示简短的回溯信息
- `-m manual`：只运行工程师指定的测试
- `-m auto`：只运行自动生成的测试
- `--co`：仅收集测试（干跑，验证测试发现是否正常，不实际执行）

### 解析结果

pytest 退出码：
- 0：所有测试通过
- 1：部分测试失败
- 2：测试执行被中断
- 3：内部错误
- 4：pytest 命令行参数错误
- 5：没有收集到任何测试
