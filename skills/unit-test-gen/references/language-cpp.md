# C++ 语言参考 — 单元测试生成器

本文档详细说明 C++ 代码的扫描规则、函数分析方法、Google Test 测试代码的生成规范。
是 SKILL.md 中通用流程的 C++/gtest 特定实现。

---

## 函数扫描规则

### 扫描范围

对每个 `.cpp` / `.cc` / `.cxx` 源文件，提取以下函数/方法（头文件 `.h` / `.hpp`
仅提取含有函数体（`{ ... }`）的内联函数和模板函数）：

| 类型 | 示例 | 是否扫描 |
|------|------|----------|
| 自由函数 | `int foo(int x) { ... }` | 是 |
| 命名空间函数 | `ns::foo(int x)` | 是 |
| 类的公共方法 | `class C { void m(); }` | 是 |
| 类的私有/保护方法 | `private: void m();` | 是 |
| 静态方法 | `static void m();` | 是 |
| const 方法 | `void m() const;` | 是 |
| 模板函数 | `template<T> T foo(T x)` | 是 |
| 运算符重载 | `operator+`、`operator==` 等 | 是 |
| 构造/析构函数 | `C()`, `~C()`, `C(const C&)` | 仅构造函数 |
| lambda | `[...](...) { ... }` | 否 |
| 友元函数 | `friend void f();` | 否 |
| 宏定义 | `#define FOO ...` | 否 |

### 过滤规则

以下情况跳过，**不生成测试**：

1. **纯虚函数**：`virtual void foo() = 0;`（无函数体，无法直接测试）。

2. **`= default` 函数**：`C() = default;`、`C& operator=(const C&) = default;`
   （编译器生成的默认实现，测试价值低）。

3. **`= delete` 函数**：`C(const C&) = delete;`（不可调用，无需测试）。

4. **仅声明无定义的头文件函数**：
   ```cpp
   // header.h — 仅有声明
   void foo(int x);  // 无函数体，跳过
   ```

5. **预处理器包裹的函数**：
   ```cpp
   #ifdef SOME_FLAG
   void foo() { ... }  // 跳过（条件编译，无法确定是否可编译）
   #endif
   ```

6. **匿名命名空间中的 static 函数**：如果函数仅在匿名命名空间内可见
   且没有外部引用，跳过。但如果可以通过测试文件 include 同一个头文件
   访问到，则不跳过。

7. **main 函数**：`int main(int argc, char* argv[])`。

8. **getter/setter（单行实现）**：仅含 `return member_;` 或 `member_ = value;`
   的单行函数。

### 签名提取

对每个要测试的函数，提取：

- 函数名
- 所属类和命名空间（如有）
- 参数列表：`[{"name": str, "type": str, "default": str | None}, ...]`
- 返回类型
- 模板参数列表（如有）
- cv 限定符（const、volatile）
- 是否 static
- 是否 virtual
- 源码行号范围 `[start, end]`
- 函数体源码的 MD5

---

## 函数行为分析（tree-sitter 特征检测）

对每个函数的 tree-sitter AST 做遍历，记录以下特征。这些特征决定了要生成哪些测试维度。

### 检测项对照表

| 特征 | tree-sitter 节点 / 检测条件 | 标记 |
|------|---------------------------|------|
| 数值运算 | `binary_expression` 含 `+`/`-`/`*`/`/`/`%` 运算符 | `has_numeric_op` |
| 浮点类型 | 参数或返回值类型含 `float`/`double`/`long double` | `has_float_type` |
| STL 数学调用 | `std::abs`、`std::sqrt`、`std::pow` 等调用 | `uses_stl_math` |
| try/catch | `try_statement` | `has_try` |
| throw 语句 | `throw_statement` | `has_throw` |
| noexcept | 函数声明含 `noexcept` | `has_noexcept` |
| 文件 IO | 调用 `std::fstream`、`fopen`、`ifstream`、`ofstream` | `has_file_io` |
| 网络 | 调用 `boost::asio`、`curl_*`、`socket` 等 | `has_network` |
| 数组下标访问 | `subscript_expression`（如 `arr[i]`） | `has_index_access` |
| 裸指针操作 | 指针解引用 `*p`、`->` 成员访问、`&` 取地址 | `has_raw_pointer` |
| new/delete | `new_expression`、`delete_expression` | `has_new_delete` |
| 缓冲区操作 | 调用 `memcpy`、`strcpy`、`strcat`、`memmove` | `has_buffer_op` |
| 模板 | `template_declaration` | `has_template` |
| 智能指针 | 使用 `std::unique_ptr`/`std::shared_ptr`/`std::weak_ptr` | `uses_smart_ptr` |
| 虚函数 | `virtual` 函数声明 | `has_virtual` |
| STL 算法 | 调用 `std::sort`、`std::find`、`std::transform` 等 | `uses_stl_algo` |
| 排序操作 | `std::sort`、`std::stable_sort`、`std::partial_sort` | `has_sort` |
| 递归调用 | 函数体内调用自身名称 | `has_recursion` |
| 字符串操作 | `std::string::` 方法调用（`substr`、`find`、`replace` 等） | `has_str_ops` |
| 迭代 | `for` 循环、`while` 循环、range-based for | `has_iteration` |
| 无副作用 | 没有修改外部状态、IO 调用或网络调用 | `is_pure` |
| 子进程调用 | `system()`、`exec*`、`popen()` | `has_subprocess` |
| 格式化字符串 | `printf`、`sprintf`、`snprintf`、`fprintf` 调用 | `has_printf` |
| SQL 操作 | `sqlite3_*`、`mysql_*`、`PQ*` 调用 | `has_sql_ops` |
| Shell 格式化 | 字符串拼接传入 `system()`/`popen()` 参数 | `has_shell_format` |
| 大型容器构造 | 循环内 `push_back`/`emplace_back`、`reserve` 未使用 | `has_container_growth` |
| 移动语义 | `std::move` 调用 | `has_move_semantics` |

### 维度判定规则

根据特征标记组合判定适用维度：

```python
dimensions = ["functional", "boundary"]   # 必选

if has_try or has_throw or has_file_io or has_network:
    dimensions.append("exception")

if has_numeric_op or uses_stl_math or has_float_type:
    dimensions.append("data_integrity")

if has_sort or has_recursion or has_template \
        or has_new_delete or has_container_growth:
    dimensions.append("performance")

if has_subprocess or has_buffer_op or has_sql_ops \
        or has_printf or has_raw_pointer or has_shell_format:
    dimensions.append("security")
```

---

## 各维度的 gtest 测试策略

### 功能性测试

- 正向路径：标准输入 → 预期输出
- 等价类划分：有效等价类和无效等价类各选一个代表值

```cpp
TEST(ParseHeaderTest, FunctionalNormal) {
    // 标准 bytes 输入返回正确的 Header 对象
    std::vector<uint8_t> data = {0x01, 0x02, 0x03, 0x04};
    data.resize(64, 0x00);

    auto result = parse_header(data);

    ASSERT_NE(result, nullptr);
    EXPECT_EQ(result->version, 1);
    EXPECT_EQ(result->length, 64);
}
```

### 边界测试

使用 `test_helpers::BOUNDARY_VALUES` 和 `INSTANTIATE_TEST_SUITE_P`：

```cpp
TEST(ParseHeaderTest, BoundaryEmptyInput) {
    // 空输入应抛出 std::invalid_argument
    std::vector<uint8_t> empty;
    EXPECT_THROW(parse_header(empty), std::invalid_argument);
}

class BoundaryIntTest : public ::testing::TestWithParam<int> {};

TEST_P(BoundaryIntTest, ComputeRateBoundary) {
    // 各种边界整数值应得到合理输出
    int value = GetParam();
    auto result = compute_rate(value);
    EXPECT_TRUE(std::holds_alternative<int>(result)
             || std::holds_alternative<double>(result));
}

INSTANTIATE_TEST_SUITE_P(
    BoundaryInt,
    BoundaryIntTest,
    ::testing::ValuesIn(test_helpers::INT_BOUNDARIES)
);
```

边界值查表（`test_helpers::BOUNDARY_VALUES`）：

| 类型 | 边界值 |
|------|--------|
| `int` | `0`, `-1`, `1`, `INT_MAX`, `INT_MIN` |
| `long` | `0L`, `-1L`, `1L`, `LONG_MAX`, `LONG_MIN` |
| `float` | `0.0f`, `INF`, `-INF`, `NAN`, `FLT_MIN`, `FLT_MAX` |
| `double` | `0.0`, `INF`, `-INF`, `NAN`, `DBL_MIN`, `DBL_MAX` |
| `std::string` | `""`, `" "`, `"a"`, `std::string(10000, 'a')`, `"\x00"` |
| `std::vector` | 空向量、单元素、嵌套空、`std::vector<int>(1000)` |
| `std::map` | 空 map、单元素、空 key |
| `nullptr_t` | `nullptr` |

### 异常容错测试

- 非法输入 → `EXPECT_THROW(..., std::invalid_argument)`
- 越界值 → `EXPECT_THROW(..., std::out_of_range)`
- 模拟 IO 失败（文件不存在、权限不足）
- 模拟网络失败（超时、连接拒绝）

```cpp
TEST(ParseHeaderTest, ExceptionTruncated) {
    // 截断的数据应抛出 std::invalid_argument
    std::vector<uint8_t> truncated = {0x01, 0x02};  // 预期 64 字节
    EXPECT_THROW(parse_header(truncated), std::invalid_argument);
}

TEST(LoadConfigTest, ExceptionFileNotFound) {
    // 配置文件不存在时应抛出 std::runtime_error
    EXPECT_THROW(load_config("/nonexistent/path.yaml"), std::runtime_error);
}

TEST(FetchUserTest, ExceptionTimeout) {
    // 网络超时时应抛出 std::runtime_error
    MockHttpClient mock_client;
    EXPECT_CALL(mock_client, get(::testing::_))
        .WillOnce(::testing::Throw(std::runtime_error("timeout")));

    EXPECT_THROW(fetch_user(mock_client, 123), std::runtime_error);
}
```

### 数据完整性测试

**精度验证**：
```cpp
TEST(ComputeRateTest, DataIntegrityPrecision) {
    // 浮点运算结果应在容差范围内
    double result = compute_rate(0.1, 0.2);
    test_helpers::assertApprox(result, 0.3, 1e-9);
}
```

**确定性验证**：
```cpp
TEST(FormatIdTest, DataIntegrityDeterministic) {
    // 纯函数多次调用结果一致
    test_helpers::assertDeterministic(format_id, "user", 42);
}
```

**往返验证**：
```cpp
TEST(EncodeDecodeTest, DataIntegrityRoundtrip) {
    // encode 后 decode 应还原原值
    std::vector<json> originals = {json{"a": 1}, json::array(), "hello", 3.14};
    for (const auto& original : originals) {
        EXPECT_EQ(decode(encode(original)), original);
    }
}
```

---

## Mock 实现细节（C++）

### Mock 外部边界的具体实现

| 依赖类型 | Mock 方式 |
|----------|-----------|
| 文件读取 | 使用临时文件（`std::filesystem::temp_directory_path()`）或 Mock 文件接口 |
| 配置加载 | Mock `ConfigLoader` 接口类，返回固定配置 |
| 数据库 | Mock 数据库接口类（`MOCK_METHOD`），或使用内存 SQLite |
| 网络请求 | Mock `HttpClient` 接口类，返回预设响应 |
| 类方法 | GoogleMock 的 `MOCK_METHOD` 宏 |
| 纯数据变换库 | 直接使用真实库（无副作用，不需要 mock） |
| 子进程调用 | Mock 子进程执行接口，构造安全返回值 |
| 系统调用 | Mock 系统调用包装接口 |

**纯数据变换永远不需要 mock**：STL 算法、字符串处理、数值计算等直接构造输入调用即可。

### Mock 需求判定

扫描同时输出 mock 建议：

```python
mocks_needed = []
if has_file_io:
    mocks_needed.append(("file_io", "use temp_directory_path or mock IFileReader"))
if has_network:
    mocks_needed.append(("network", "mock IHttpClient interface"))
if has_subprocess:
    mocks_needed.append(("subprocess", "mock IProcessRunner interface"))
if has_sql_ops:
    mocks_needed.append(("database", "mock IDatabase interface or use in-memory SQLite"))
# 类方法如果有复杂构造函数依赖
if class_name and has_complex_deps:
    mocks_needed.append(("class_deps", "use MOCK_METHOD or dependency injection"))
```

### GoogleMock 接口模式

对于需要 mock 的外部依赖，推荐使用接口 + 依赖注入模式：

```cpp
// 接口定义（被测代码中已有或新增）
class IFileReader {
public:
    virtual ~IFileReader() = default;
    virtual std::string read(const std::string& path) = 0;
};

// Mock 类（测试代码中）
class MockFileReader : public IFileReader {
public:
    MOCK_METHOD(std::string, read, (const std::string& path), (override));
};

// 被测函数接受接口
void process_data(IFileReader& reader, const std::string& path);
```

如果被测代码不接受接口（紧耦合），使用如下策略：
- 对于 `protected`/`private` 方法：通过友元类或测试夹具访问
- 对于全局/静态函数：通过函数指针或预处理器宏替换

---

## gtest 测试代码生成规范

### 文件头

每个生成的测试文件顶部固定格式：

```cpp
// AUTO-GENERATED by unit-test-gen skill. DO NOT EDIT.
// Source: src/core/parser.cpp
// Regenerate with: /unit-test-gen auto

#include <gtest/gtest.h>
#include <gmock/gmock.h>

#include "test/generated_unit/_helpers.hpp"

#include "src/core/parser.h"  // 被测代码头文件
```

**include 路径**：
- 默认假设项目根目录为 include 搜索起点
- 如果项目使用 CMake，通过 `target_include_directories` 设置
- 测试文件的 include 路径与源码结构镜像

### 测试函数命名

格式：`TEST(<类名或模块名><Test>, <函数名>_<维度>_<描述>)`

示例：
- `TEST(ParseHeaderTest, FunctionalNormal)`
- `TEST(ParseHeaderTest, BoundaryEmptyInput)`
- `TEST(ParseHeaderTest, ExceptionTruncated)`
- `TEST(ComputeRateTest, DataIntegrityPrecision)`
- `TEST(SortDataTest, PerformanceLargeInput)`
- `TEST(ExecuteCommandTest, SecurityInjection)`

类方法命名：`TEST(<类名>Test, <方法名>_<维度>_<描述>)`

自由函数命名：`TEST(<函数名 PascalCase>Test, <维度>_<描述>)`

### 功能性测试模板

```cpp
TEST(ParseHeaderTest, FunctionalNormal) {
    // 标准 bytes 输入返回正确的 Header 对象
    std::vector<uint8_t> data = {0x01, 0x02, 0x03, 0x04};
    data.resize(64, 0x00);

    auto result = parse_header(data);

    ASSERT_NE(result, nullptr);
    EXPECT_EQ(result->version, 1);
    EXPECT_EQ(result->length, 64);
}
```

### 边界测试模板

使用 `INSTANTIATE_TEST_SUITE_P` 参数化：

```cpp
class BoundaryIntTest : public ::testing::TestWithParam<int> {};

TEST_P(BoundaryIntTest, ComputeRateBoundary) {
    int value = GetParam();
    auto result = compute_rate(value);
    EXPECT_NO_THROW({ auto r = compute_rate(value); });
}

INSTANTIATE_TEST_SUITE_P(
    Boundary,
    BoundaryIntTest,
    ::testing::ValuesIn(test_helpers::INT_BOUNDARIES)
);
```

单次边界值测试：

```cpp
TEST(ParseHeaderTest, BoundaryEmptyInput) {
    std::vector<uint8_t> empty;
    EXPECT_THROW(parse_header(empty), std::invalid_argument);
}

TEST(ParseHeaderTest, BoundarySingleByte) {
    std::vector<uint8_t> single = {0x01};
    EXPECT_THROW(parse_header(single), std::invalid_argument);
}
```

### 异常容错测试模板

```cpp
TEST(ParseHeaderTest, ExceptionTruncated) {
    // 截断的数据应抛出 std::invalid_argument
    std::vector<uint8_t> truncated = {0x01, 0x02};
    EXPECT_THROW(parse_header(truncated), std::invalid_argument);
}

TEST(LoadConfigTest, ExceptionFileNotFound) {
    // 配置文件不存在时应抛出异常
    EXPECT_THROW(load_config("/nonexistent/path.yaml"), std::runtime_error);
}

TEST(FetchUserTest, ExceptionTimeout) {
    // 网络超时时应抛出异常
    MockHttpClient mock_client;
    EXPECT_CALL(mock_client, get(::testing::_))
        .WillOnce(::testing::Throw(std::runtime_error("timeout")));

    EXPECT_THROW(fetch_user(mock_client, 123), std::runtime_error);
}
```

### 数据完整性测试模板

**精度验证**：
```cpp
TEST(ComputeRateTest, DataIntegrityPrecision) {
    // 浮点运算结果应在容差范围内
    double result = compute_rate(0.1, 0.2);
    test_helpers::assertApprox(result, 0.3, 1e-9);
}
```

**确定性验证**：
```cpp
TEST(FormatIdTest, DataIntegrityDeterministic) {
    // 纯函数多次调用结果一致
    test_helpers::assertDeterministic<format_id, std::string, int>(
        std::make_tuple(std::string("user"), 42), 5);
}
```

**往返验证**：
```cpp
TEST(EncodeDecodeTest, DataIntegrityRoundtrip) {
    // encode 后 decode 应还原原值
    std::vector<std::string> originals = {"hello", "", "a" + std::string(1000, 'b')};
    for (const auto& original : originals) {
        EXPECT_EQ(decode(encode(original)), original);
    }
}
```

### 性能测试模板

**基本负载测试**：
```cpp
TEST(SortDataTest, PerformanceLargeInput) {
    // 大规模输入下排序应在合理时间内完成
    auto large_input = test_helpers::generateLargeVector<int>(
        test_helpers::PERFORMANCE_CONFIG["large"]);
    auto start = std::chrono::high_resolution_clock::now();
    auto result = sort_data(large_input);
    auto elapsed = std::chrono::high_resolution_clock::now() - start;
    // 不做硬性超时断言，记录时间供 CI 报告
    EXPECT_EQ(result.size(), large_input.size());
    EXPECT_TRUE(std::is_sorted(result.begin(), result.end()));
}
```

**可扩展性测试**：
```cpp
TEST(SearchIndexTest, PerformanceScalability) {
    // 验证处理时间随输入规模线性增长
    auto small = test_helpers::generateLargeVector<int>(100);
    auto large = test_helpers::generateLargeVector<int>(10000);
    double ratio = test_helpers::assertScalability(
        search_index, small, large, 200.0);
    // ratio 记录在报告中供人工审查
}
```

**递归深度测试**：
```cpp
TEST(FibonacciTest, PerformanceDeepRecursion) {
    // 较深递归不应导致栈溢出
    auto result = fibonacci(30);
    EXPECT_GT(result, 0);
}
```

**内存稳定性测试**：
```cpp
TEST(BuildReportTest, PerformanceMemory) {
    // 大量数据拼接不应导致内存异常
    std::vector<std::string> chunks;
    chunks.reserve(10000);
    for (int i = 0; i < 10000; ++i) {
        chunks.push_back("chunk_" + std::to_string(i));
    }
    auto result = build_report(chunks);
    EXPECT_FALSE(result.empty());
}
```

### 安全测试模板

**缓冲区溢出测试**：
```cpp
TEST(BufferOpTest, SecurityOverflow) {
    // 缓冲区操作不应越界写入
    std::vector<uint8_t> small_buf(4, 0);
    // 使用 EXPECT_NO_THROW 或 EXPECT_DEATH（取决于安全性级别）
    EXPECT_NO_THROW({ copy_to_buffer(small_buf, "test"); });
}
```

**命令注入测试**：
```cpp
TEST(ExecuteCommandTest, SecurityInjection) {
    // 用户输入中的特殊字符不应被执行为 shell 命令
    MockProcessRunner mock_runner;
    EXPECT_CALL(mock_runner, run(::testing::_))
        .WillRepeatedly(::testing::Return(0));

    for (const auto& [malicious, desc] : test_helpers::COMMAND_INJECTION_INPUTS) {
        EXPECT_NO_THROW(execute_command(mock_runner, malicious));
    }
}
```

**SQL 注入测试**：
```cpp
TEST(QueryUserTest, SecuritySqlInjection) {
    // 用户输入中的 SQL 片段不应改变查询语义
    MockDatabase mock_db;
    EXPECT_CALL(mock_db, execute(::testing::_))
        .WillRepeatedly(::testing::Return(MockResult{}));

    for (const auto& [malicious, desc] : test_helpers::SQL_INJECTION_INPUTS) {
        EXPECT_NO_THROW(query_user(mock_db, malicious));
        // 验证使用了参数化查询
        auto call_args = mock_db.last_query();
        EXPECT_THAT(call_args, ::testing::Not(::testing::HasSubstr(malicious)));
    }
}
```

**格式化字符串漏洞测试**：
```cpp
TEST(PrintfTest, SecurityFormatString) {
    // 用户输入不应直接作为 printf 格式字符串
    for (const auto& [malicious, desc] : test_helpers::FORMAT_STRING_INPUTS) {
        EXPECT_NO_THROW(safe_format(malicious));
    }
}
```

**路径遍历测试**：
```cpp
TEST(ReadFileTest, SecurityPathTraversal) {
    // 用户控制的文件路径不应越界访问
    std::filesystem::path safe_dir = std::filesystem::temp_directory_path() / "safe_test";
    std::filesystem::create_directories(safe_dir);
    std::ofstream(safe_dir / "allowed.txt") << "ok";

    for (const auto& [malicious, desc] : test_helpers::PATH_TRAVERSAL_INPUTS) {
        auto result = read_file(safe_dir, malicious);
        // 函数应拒绝路径遍历尝试
        EXPECT_TRUE(!result.has_value()
            || result->find("error") != std::string::npos)
            << "Path traversal not blocked: " << desc;
    }
}
```

**输入清洗验证**：
```cpp
TEST(SanitizeInputTest, SecurityXss) {
    // 输出应清洗 XSS 向量
    for (const auto& [malicious, desc] : test_helpers::XSS_INPUTS) {
        auto result = sanitize_input(malicious);
        EXPECT_THAT(result, ::testing::Not(::testing::HasSubstr("<script>")))
            << "XSS vector not sanitized: " << desc;
    }
}
```

### 模板函数测试模板

```cpp
template <typename T>
class TemplateTest : public ::testing::Test {};

using TemplateTypes = ::testing::Types<int, float, double, std::string>;
TYPED_TEST_SUITE(TemplateTest, TemplateTypes);

TYPED_TEST(TemplateTest, FunctionalNormal) {
    TypeParam value = test_helpers::default_value<TypeParam>();
    auto result = template_func(value);
    EXPECT_NO_THROW({ auto r = template_func(value); });
}
```

### 类方法测试模板

```cpp
class ParserTest : public ::testing::Test {
protected:
    void SetUp() override {
        parser_ = std::make_unique<Parser>(false);  // strict=false
    }

    void TearDown() override {
        parser_.reset();
    }

    std::unique_ptr<Parser> parser_;
};

TEST_F(ParserTest, ParseFunctionalNormal) {
    // 标准输入应正确解析
    auto result = parser_->parse({0x01, 0x02, 0x03});
    EXPECT_NE(result, nullptr);
}

TEST_F(ParserTest, ParseBoundaryEmpty) {
    // 空输入边界情况
    auto result = parser_->parse({});
    EXPECT_EQ(result, nullptr);
}
```

如果构造函数依赖复杂（如需要数据库连接、文件管理器等），用 Mock 注入：

```cpp
class NodeTest : public ::testing::Test {
protected:
    void SetUp() override {
        auto mock_folder_mgr = std::make_unique<MockFolderManager>();
        EXPECT_CALL(*mock_folder_mgr, get_path(::testing::_))
            .WillRepeatedly(::testing::Return("/tmp/test"));
        node_ = std::make_unique<Node>(std::move(mock_folder_mgr), "test");
    }

    std::unique_ptr<Node> node_;
};

TEST_F(NodeTest, ProcessFunctionalNormal) {
    auto result = node_->process({1, 2, 3});
    EXPECT_THAT(result, ::testing::ElementsAre(2, 4, 6));
}
```

---

## 执行 Google Test

### 前提条件

项目需要集成 Google Test。推荐的 CMake 配置：

```cmake
# CMakeLists.txt 中添加
find_package(GTest REQUIRED)
enable_testing()

# 测试目标
add_executable(unit_tests
    test/generated_unit/core/test_parser.cpp
    test/generated_unit/utils/test_format.cpp
)
target_link_libraries(unit_tests PRIVATE GTest::gtest GTest::gmock)
target_include_directories(unit_tests PRIVATE ${CMAKE_SOURCE_DIR})

include(GoogleTest)
gtest_discover_tests(unit_tests)
```

### 命令

```bash
# 构建
cmake --build build

# 执行全部测试
ctest --test-dir build --output-on-failure

# 或直接运行 gtest binary
./build/unit_tests --gtest_color=yes

# 运行特定测试
./build/unit_tests --gtest_filter="ParseHeaderTest.*"

# 输出 XML 报告
./build/unit_tests --gtest_output=xml:test/generated_unit/gtest_report.xml
```

### 常用参数

- `--gtest_filter=<pattern>`：按模式过滤测试（支持 `*` 和 `?` 通配符）
- `--gtest_repeat=<n>`：重复运行 n 次
- `--gtest_shuffle`：随机顺序执行
- `--gtest_output=xml:<path>`：输出 XML 报告
- `--gtest_break_on_failure`：失败时触发断点
- `--gtest_print_time=0`：不显示执行时间

### 退出码

- 0：全部通过
- 1：有失败

### 增量模式执行

从 `test_cases.json` 读出变更过的文件列表，构建时只编译受影响的测试：

```bash
cmake --build build --target unit_tests
./build/unit_tests --gtest_filter="ParserTest.*:FormatTest.*"
```

---

## 常见坑和应对

### 1. include 路径问题

生成的测试文件可能因 include 路径不正确而编译失败。解决方案：
- 确保 `CMakeLists.txt` 中设置了正确的 `target_include_directories`
- 通常将项目根目录加入 include 搜索路径
- 头文件 include 使用从项目根目录开始的相对路径

### 2. 链接错误

测试文件中引用的符号在链接时找不到。常见原因：
- 忘记将源文件加入 CMake 的测试目标
- 模板函数的实现不在头文件中（应在头文件中定义，或显式实例化）
- `static` 函数或匿名命名空间的函数无法被外部测试文件访问

### 3. 私有/保护方法测试

C++ 的访问控制比 Python 严格。私有方法测试策略：
- 通过公有接口间接测试（推荐）
- 使用 `FRIEND_TEST` 宏（需要修改源文件，通常不推荐）
- 通过测试夹具的 `#define private public` hack（不推荐，仅作为最后手段）

### 4. 全局状态

被测代码如果依赖全局变量或单例，测试间可能互相污染。解决方案：
- 在 `SetUp()`/`TearDown()` 中重置全局状态
- 使用 `::testing::Environment` 做全局初始化/清理

### 5. 随机性

被测函数如果使用 `std::rand()` 或 `<random>`，测试中用固定种子：
```cpp
TEST(MyTest, Deterministic) {
    std::mt19937 rng(42);  // 固定种子
    auto result = my_random_func(rng);
    // 结果可预测
}
```

### 6. 时间依赖

函数如果依赖 `std::chrono::system_clock::now()`，通过依赖注入传入时间源，
或使用 `libfaketime` 环境变量。

### 7. 模板实例化

模板函数测试需要显式列出要测试的类型：
```cpp
using TypesToTest = ::testing::Types<int, float, double>;
TYPED_TEST_SUITE(TemplateFuncTest, TypesToTest);
```

### 8. RAII 和资源管理

被测代码使用 RAII 管理资源时，测试中不需要手动释放。但如果使用 `EXPECT_DEATH`
测试，需注意 death test 会 fork 进程，资源清理行为可能不同。
