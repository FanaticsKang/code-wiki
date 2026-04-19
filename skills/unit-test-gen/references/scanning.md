# 扫描规则

本文档讲扫描阶段的**语言无关**规则：语言识别、排除路径。各语言的函数过滤规则
（哪些函数跳过不测）见对应语言参考文档的「函数扫描规则」章节。

---

## 语言与框架自动识别

不要求用户指定，技能自行检测：

| 语言 | 扩展名 | 默认框架 | 配置文件探测 |
|------|--------|----------|-------------|
| Python | `.py` | pytest | `pyproject.toml`、`setup.cfg`、`requirements.txt` |
| C++ | `.cpp` `.cc` `.cxx` `.h` `.hpp` | gtest | `CMakeLists.txt`、`Makefile`、`conanfile.txt` |

### 识别流程

1. 遍历源码目录，按扩展名统计文件数量
2. 有 `.py` → 标记 `python`；有 `.cpp`/`.cc`/`.cxx` → 标记 `cpp`
3. 两种都有 → 标记为混合仓库，各语言各自独立扫描和生成
4. 检查配置文件进一步确认框架

检测结果写入 `test_cases.json` 的 `languages` 和 `test_frameworks` 字段。

---

## 扫描排除规则

以下路径自动排除，无需用户指定：

| 类型 | 排除模式 |
|------|----------|
| 测试目录 | `test/`, `tests/` |
| 虚拟环境 | `.venv/`, `venv/`, `env/`, `node_modules/` |
| 缓存 | `__pycache__/`, `.tox/`, `.pytest_cache/`, `.mypy_cache/` 等各语言缓存目录 |
| 构建产物 | `build/`, `dist/`, `*.egg-info/`, `cmake-build-*/` 等 |
| 已生成代码 | `test/generated_unit/`（自身）、`*_generated.*` |
| 调试产物 | `.test/generated_unit/`（`.` 开头自动被"隐藏目录"规则排除） |
| 文档 | `docs/` |
| 工具/配置 | `.claude/`, `.git/`, `.github/`, `scripts/` |
| 第三方 | `third_party/`, `vendor/` |

`.test/generated_unit/` 是技能的调试目录，存放 `coverage.json`、`failures.json`、
`scan_result.json`（可选）、lcov 原始数据等中间产物。它和工作目录 `test/generated_unit/`
对称命名，靠 `.` 前缀触发 scanner 的"隐藏目录跳过"逻辑（见 `scan_repo.py`
的 `should_skip_dir`）。建议用户把 `.test/` 加入 `.gitignore`。

各语言可能有额外的排除规则（如 Python 的私有模块、C++ 的系统头文件等），
见对应语言参考文档。
