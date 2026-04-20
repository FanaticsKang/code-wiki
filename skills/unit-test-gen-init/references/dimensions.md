# 测试维度

六个维度:`functional`、`boundary`、`exception`、`data_integrity`、`performance`、`security`。前两个对所有函数必选,后四个按函数特征按需触发。

判定规则由 `scripts/scan_repo.py` 的 `decide_dimensions` 方法实现 —— 规则即代码,本文档解释意图,以代码为准。如果对某个函数的维度判定有疑问,优先看 `features` 字段里的 AST 特征,再看 `decide_dimensions` 的 if 链如何从这些特征推出维度。

## 维度总览

| 维度 | 触发条件 | 必选 |
|---|---|---|
| 功能性（functional） | 所有函数 | 是 |
| 边界（boundary） | 所有函数 | 是 |
| 异常容错（exception） | 检测到错误处理、IO 操作、外部调用 | 否 |
| 数据完整性（data_integrity） | 检测到数值计算、浮点运算 | 否 |
| 性能（performance） | 检测到排序、递归、大规模集合构造、循环内字符串拼接等 | 否 |
| 安全（security） | 检测到子进程调用、动态代码执行、SQL 操作、不安全反序列化、缓冲区操作等 | 否 |

## 触发规则速查

### Python

| 维度 | AST 特征(任一) |
|---|---|
| exception | `try`/`raise` 语句,`open()`,`requests/httpx/aiohttp/urllib` 调用 |
| data_integrity | 数值二元运算,`math.*`/`numpy.*` 调用,`float` 类型注解 |
| performance | `sorted`/`.sort()`,自递归,大规模推导,循环内字符串拼接 |
| security | `subprocess.*`,`os.system`/`os.popen`,`eval`/`exec`,`pickle.loads`,`yaml.load`(非 safe_load),`.execute()`(SQL) |

### C++

| 维度 | tree-sitter 特征(任一) |
|---|---|
| exception | `try_statement`/`throw_statement`,`fstream/fopen/fread/fwrite`,`socket/connect/send/recv` |
| data_integrity | 数值二元运算,`std::abs/sqrt/pow/sin/cos/...`,浮点类型 |
| performance | `std::sort`,自递归,模板函数,`new`/`delete`,容器增长 |
| security | `system/popen/exec*`,`memcpy/strcpy/sprintf`,裸指针,`printf` 族,SQL 调用 |

完整规则见 `scripts/scan_repo.py` 里的 `PythonAnalyzer.decide_dimensions` 和 `CppAnalyzer.decide_dimensions`。

---

## 各维度的测试策略

下游生成测试用例时,按函数的维度字段分别设计用例。以下是每个维度的测试策略,供 LLM 或测试工程师参考。

### 功能性（必选）

- 正向路径:标准输入 → 预期输出
- 等价类划分:有效等价类和无效等价类各选一个代表值

### 边界（必选）

- 根据参数类型查表取边界值
- 参数化批量测试所有边界值
- 各语言的边界值查表见对应语言参考文档

### 异常容错（按需）

- 非法输入类型 → 预期抛出类型错误
- 越界值 → 预期抛出越界错误
- 模拟 IO 失败(文件不存在、权限不足)
- 模拟网络失败(超时、4xx/5xx)

### 数据完整性（按需）

- 精度验证:浮点结果在容差范围内
- 确定性验证:同样输入调用多次,结果必须一致
- 往返验证:`decode(encode(x)) == x`

### 性能（按需）

- 基本负载测试:大规模输入(可配置大小)下验证函数能完成执行
- 时间记录:不设硬性超时阈值,记录执行时间供报告分析
- 可扩展性测试:对比小输入和大输入的执行时间比,验证非指数增长
- 内存稳定性:验证大输入下不引发内存异常

### 安全（按需）

- 命令注入测试:特殊字符输入不触发 shell 执行
- SQL 注入测试:SQL 片段输入不改变查询语义(验证参数化查询)
- 路径遍历测试:`../` 等路径不越界访问
- 动态代码执行测试:任意代码字符串不被执行
- 输入清洗验证:恶意输入在输出中被转义或移除
- 缓冲区溢出测试(适用于无内存安全语言)
