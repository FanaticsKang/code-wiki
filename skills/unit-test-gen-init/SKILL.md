---
name: unit-test-gen-init
description: 单测生成流水线的初始化阶段:为 Python / C++ 项目扫描代码仓库并生成或增量更新 `test_cases.json` 基线文件。
---

# unit-test-gen-init

扫描代码仓库(Python 和/或 C++),生成 `test_cases.json` 基线文件 —— 记录每个可测试函数的 MD5、源码位置、签名和适用的测试维度。

## 扫描器的工作原理

扫描器是一个独立的 Python 脚本,位于 `scripts/scan_repo.py`。它会:

1. 遍历仓库,跳过测试目录、构建产物、版本控制元数据、隐藏目录,以及 third-party / vendor 树
2. 用标准库 `ast` 解析 Python 文件;用 `tree-sitter-cpp` 解析 C++ 文件(`.cpp/.cc/.cxx/.h/.hpp/.hh/.hxx`)
3. 提取每个函数/方法的签名、行号范围、所属类、命名空间(C++)、函数源代码文本的 MD5
4. 检测 AST 特征(has_try、has_file_io、has_recursion、has_subprocess 等),并按 `references/dimensions.md` 里的规则映射到测试维度
5. 如果已有基线文件存在,则按字段级合并,保留用户已编辑的部分(`coverage_config`、`cases`)
6. 原子写入(临时文件 + rename),确保崩溃时不会留下半写状态的基线

MD5 计算的是**原始源代码文本** —— 只改注释也会改变 hash。这是有意的设计:规则最简单、结果稳定,下游消费者只需要一个清晰的"是否变化"信号。

## 标准工作流

**这是 99% 的情况下应该走的流程**。不要预先询问用户任何参数 —— 按下面的决策树直接跑。

### 步骤 1:检查基线是否已存在

默认基线路径:`test/generated_unit/test_cases.json`(相对于仓库根目录)

- **文件已存在** → 走"增量扫描"分支
- **文件不存在** → 走"首次扫描"分支

不要问用户"你想放哪里" —— 默认路径就是约定。只有在默认路径不适用的罕见情况(用户明确提到另一个位置),才考虑换路径。

### 步骤 2a:首次扫描

```bash
python scripts/scan_repo.py <repo_root> --output test/generated_unit/test_cases.json --mode full
```

扫描完成后:

1. 读取 stderr 摘要(文件数、函数数)
2. 简要报告给用户,包括发现的语言(Python / C++)、函数总数、最常见的测试维度分布
3. 如果 stderr 里有"检测到 C++ 文件但缺少 tree-sitter 依赖"之类的警告,明确告诉用户要装 `pip install tree-sitter tree-sitter-cpp`,然后提议重跑一次

### 步骤 2b:增量扫描

```bash
python scripts/scan_repo.py <repo_root> --output test/generated_unit/test_cases.json
```

默认就是增量模式(`--mode` 省略时等同于 `--mode incremental`),`--output` 指向已有文件时会自动作为增量对比的基线。

扫描完成后:

1. 读取 stderr 摘要里的增量诊断(`变更 X 文件 | 新增 Y | 删除 Z`)
2. 报告给用户:多少文件变了,多少函数是新增/变更/删除
3. **重点**:如果有函数因 MD5 改变导致 `cases` 被清空,明确列出这些函数名,提醒用户可能需要重新生成测试

### 限定扫描范围(仅通过显式命令语法触发)

**默认规则:自然语言请求一律全仓扫描**。无论用户怎么说("帮我扫描 src/core"、"只看看 utils 的变化"、"快速扫一下核心模块"),都按全仓扫描处理 —— 然后在报告里只突出相关目录的部分。

只有一个例外:**用户输入以 `/unit-test-gen-init` 开头并带 `--source` 参数**,比如:

```
/unit-test-gen-init --source src/core
/unit-test-gen-init --source src/core,src/utils
```

这种显式命令格式才会触发限定扫描。这是刻意的硬区分 —— 因为 `--source` 与增量模式组合时有数据一致性陷阱,不应让自然语言的模糊请求误触发。

#### 显式命令的执行流程

当识别到 `/unit-test-gen-init --source <path>` 格式时,**执行前必须做一次破坏性检查**:

1. **读取当前基线** `test/generated_unit/test_cases.json`(如果存在)
2. **计算会被清除的条目数**:基线里哪些文件的路径不在本次 `--source` 指定的目录下
3. **如果清除数 > 0,停下来问用户**,不要先执行:

   > 检测到以下条目不在本次 `--source src/core` 范围内,增量合并会把它们从基线里清除:
   >
   > - `src/utils/helper.py`(8 个函数,其中 3 个已有 cases)
   > - `src/models/user.py`(12 个函数,其中 5 个已有 cases)
   > - ...(合计 X 个文件,Y 个函数,Z 个已填充的 cases 会一并丢失)
   >
   > 这些条目的 `cases` 是下游生成测试用例的产出,一旦清除只能重新生成。请确认:
   >
   > 1. **继续执行**,接受清除
   > 2. **取消**
   > 3. **改为全仓扫描**(推荐,若你只是想看 core 的变化)

   等用户明确选择后再执行。不要自作主张继续。

4. 如果清除数 = 0(比如首次扫描,或者基线里本来就只有 src/core 的条目),直接执行,不必确认。

5. 执行命令:

   ```bash
   python scripts/scan_repo.py <repo_root> --output test/generated_unit/test_cases.json --source <path>
   ```

6. 执行后在报告里提醒用户:"本次扫描已收窄到 `<path>`,基线现在仅包含该目录下的条目。"

#### 为什么不让自然语言触发

`--source` 的破坏性不对称:加上它容易、恢复(重扫全仓)虽然便宜但 `cases` 字段已经丢失,需要下游重新生成,代价高。用户说"扫描 core 目录"时,大概率只是想**看看 core 的情况**,而不是想把其他目录从基线里抹掉 —— 这两个意图用自然语言难以区分。显式命令语法是一个清晰的"我知道自己在做什么"信号。

## 故障排查出口:检视模式

如果扫描结果看起来异常(比如某个预期存在的函数没被抓到),可以省略 `--output`,让扫描器把完整 JSON 打到 stdout,便于人工或 `jq` 检视,不会写入任何文件:

```bash
python scripts/scan_repo.py <repo_root>
python scripts/scan_repo.py <repo_root> --source src/core  # 限定目录,仅为了减少输出量,不影响基线
```

这个模式不是常规工作流的一部分 —— 仅在诊断"为什么某函数没被扫到"这种问题时使用。

## 依赖

- Python 3.9+(使用了 `ast.unparse`、`|` 类型联合)
- C++ 扫描需要:`pip install tree-sitter tree-sitter-cpp`
  - 如果仓库里有 C++ 文件但这个依赖没装,扫描器会在 stderr 打印警告并跳过 C++ 文件(不会崩溃)。继续之前先提示用户安装依赖。

## 输出格式

基线 `test_cases.json` 长这样:

```json
{
  "version": "1.0",
  "generated_at": "2026-04-20T12:34:56+09:00",
  "languages": ["python", "cpp"],
  "test_frameworks": {"python": "pytest", "cpp": "gtest"},
  "source_dirs": ["src"],
  "mode_last_run": "incremental",
  "summary": {"total_files": 42, "total_functions": 187, "total_cases": 0},
  "coverage_config": { "...": "用户可编辑,扫描时保留" },
  "files": {
    "src/core/parser.py": {
      "file_md5": "...",
      "test_path": "test/generated_unit/core/test_parser.py",
      "functions": {
        "parse_header": {
          "func_md5": "...",
          "line_range": [12, 45],
          "signature": "parse_header(data: bytes, strict: bool = False) -> Header",
          "class_name": null,
          "dimensions": ["functional", "boundary", "exception"],
          "cases": []
        }
      }
    }
  }
}
```

完整字段(含所有可选字段):见 `references/baseline-schema.md`。
维度判定规则(什么触发 `security` 还是 `performance` 等):见 `references/dimensions.md`。

## 字段保留规则

扫描时 `coverage_config`、`tool_status`、未变函数的 `cases` 都会保留;`func_md5`变化会清空该函数的 `cases`,这是下游需要重新生成测试的信号。

## 默认跳过的内容

- **目录**:`__pycache__`、`.git`、`.venv`、`node_modules`、`test`/`tests`、  `docs`、`scripts`、`third_party`、`vendor`,以及任何以 `.` 开头或 `.egg-info`结尾的目录
- **Python 文件**:以 `_` 开头(除 `__init__.py`)、以 `_generated.py` 结尾
- **函数**:桩函数、property setter、`@overload`、C++ `main`、析构、纯虚、`= default`、`= delete`

若用户报告"我的函数被漏了",优先怀疑是否匹配上述任一规则;其次检查解析错误(Python 版本过新、文件截断、编码异常)。