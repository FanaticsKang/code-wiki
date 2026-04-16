#!/usr/bin/env python3
"""
scan_repo.py — 扫描 Python 代码仓库，提取所有可测试函数。

输出 JSON 结构包含每个文件和函数的元信息（签名、MD5、AST 特征、适用维度）。
Claude 读取此输出后决定生成哪些 pytest 测试用例。

用法：
    python scan_repo.py <repo_root> [--source core,utils] [--baseline test_cases.json]

如果提供 --baseline，输出中会包含与基线对比的变更信息。
"""

import argparse
import ast
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# 排除规则
# ---------------------------------------------------------------------------

SKIP_DIRS = {
    "__pycache__", ".git", ".venv", "venv", "env",
    "node_modules", ".tox", ".mypy_cache", ".pytest_cache",
    "dist", "build", ".eggs", ".github", ".claude",
    "docs", "scripts", "third_party", "vendor",
}

TEST_DIRS = {"test", "tests", "testing"}


def should_skip_dir(path: Path, repo_root: Path) -> bool:
    """判断目录是否应跳过。"""
    name = path.name.lower()
    if name in SKIP_DIRS or name in TEST_DIRS:
        return True
    if name.startswith("."):
        return True
    if name.endswith(".egg-info"):
        return True
    return False


def should_skip_file(path: Path) -> bool:
    """判断文件是否应跳过。"""
    name = path.name
    if not name.endswith(".py"):
        return True
    # 私有模块（但 __init__.py 保留）
    if name.startswith("_") and name != "__init__.py":
        return True
    # 生成的代码
    if name.endswith("_generated.py"):
        return True
    return False


# ---------------------------------------------------------------------------
# AST 特征分析
# ---------------------------------------------------------------------------

class FeatureDetector(ast.NodeVisitor):
    """扫描函数体，记录影响测试维度的 AST 特征。"""

    def __init__(self):
        self.features = {
            "has_numeric_op": False,
            "uses_math": False,
            "uses_numpy": False,
            "has_float_type": False,
            "has_try": False,
            "has_raise": False,
            "has_assert": False,
            "has_file_io": False,
            "uses_os_path": False,
            "has_network": False,
            "has_index_access": False,
            "has_slicing": False,
            "uses_len": False,
            "has_str_ops": False,
            "uses_regex": False,
            "has_iteration": False,
            # 性能相关
            "has_sort": False,
            "has_recursion": False,
            "has_large_comprehension": False,
            "has_string_concat_in_loop": False,
            # 安全相关
            "has_subprocess": False,
            "has_eval_exec": False,
            "has_sql_ops": False,
            "has_pickle": False,
            "has_yaml_unsafe": False,
            "has_shell_format": False,
        }

    def visit_BinOp(self, node: ast.BinOp) -> None:
        if isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div,
                                ast.Pow, ast.Mod, ast.FloorDiv)):
            self.features["has_numeric_op"] = True
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        # math.*, numpy.*, requests.*, etc.
        if isinstance(node.func, ast.Attribute):
            if isinstance(node.func.value, ast.Name):
                name = node.func.value.id
                if name == "math":
                    self.features["uses_math"] = True
                elif name in ("np", "numpy"):
                    self.features["uses_numpy"] = True
                elif name in ("requests", "httpx", "aiohttp", "urllib"):
                    self.features["has_network"] = True
                elif name == "re":
                    self.features["uses_regex"] = True
                # 安全：subprocess.*, os.system(), os.popen()
                elif name == "subprocess":
                    self.features["has_subprocess"] = True
                elif name == "os" and node.func.attr in ("system", "popen"):
                    self.features["has_subprocess"] = True
                # 安全：pickle.loads / pickle.load
                elif name == "pickle" and node.func.attr in ("loads", "load"):
                    self.features["has_pickle"] = True
                # 安全：sqlite3.*, psycopg2.*
                elif name in ("sqlite3", "psycopg2"):
                    self.features["has_sql_ops"] = True
                # 安全：yaml.load (非 SafeLoader)
                elif name == "yaml" and node.func.attr == "load":
                    self.features["has_yaml_unsafe"] = True
            # .sort() 方法调用
            if node.func.attr == "sort":
                self.features["has_sort"] = True
            # 安全：cursor.execute()
            if node.func.attr == "execute":
                self.features["has_sql_ops"] = True
            # x.split() / x.join() / x.replace() 等字符串方法
            if node.func.attr in (
                "split", "join", "strip", "replace", "format",
                "startswith", "endswith", "lower", "upper",
            ):
                self.features["has_str_ops"] = True

        if isinstance(node.func, ast.Name):
            if node.func.id == "open":
                self.features["has_file_io"] = True
            elif node.func.id == "len":
                self.features["uses_len"] = True
            elif node.func.id == "sorted":
                self.features["has_sort"] = True
            # 安全：eval(), exec()
            elif node.func.id in ("eval", "exec"):
                self.features["has_eval_exec"] = True

        self.generic_visit(node)

    def visit_Try(self, node: ast.Try) -> None:
        self.features["has_try"] = True
        self.generic_visit(node)

    def visit_Raise(self, node: ast.Raise) -> None:
        self.features["has_raise"] = True
        self.generic_visit(node)

    def visit_Assert(self, node: ast.Assert) -> None:
        self.features["has_assert"] = True
        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript) -> None:
        self.features["has_index_access"] = True
        if isinstance(node.slice, ast.Slice):
            self.features["has_slicing"] = True
        self.generic_visit(node)

    def visit_For(self, node: ast.For) -> None:
        self.features["has_iteration"] = True
        self.generic_visit(node)

    def visit_ListComp(self, node: ast.ListComp) -> None:
        self.features["has_iteration"] = True
        self.generic_visit(node)

    def visit_DictComp(self, node: ast.DictComp) -> None:
        self.features["has_large_comprehension"] = True
        self.generic_visit(node)

    def visit_SetComp(self, node: ast.SetComp) -> None:
        self.features["has_large_comprehension"] = True
        self.generic_visit(node)

    def visit_While(self, node: ast.While) -> None:
        self.features["has_iteration"] = True
        self.generic_visit(node)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        # 检测 += 拼接（字符串或列表在循环中拼接的性能反模式）
        if isinstance(node.op, ast.Add) and isinstance(node.target, ast.Name):
            self.features["has_string_concat_in_loop"] = True
        self.generic_visit(node)

    def visit_JoinedStr(self, node: ast.JoinedStr) -> None:
        # 检测 f-string（安全风险：可能传入 subprocess/eval）
        self.features["has_shell_format"] = True
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        # os.path.*
        if isinstance(node.value, ast.Name) and node.value.id == "os" and node.attr == "path":
            self.features["uses_os_path"] = True
        self.generic_visit(node)


def detect_float_type(func_node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """检测参数或返回值注解中是否含 float。"""
    def has_float_in_annotation(ann):
        if ann is None:
            return False
        try:
            s = ast.unparse(ann)
            return "float" in s.lower()
        except Exception:
            return False

    for arg in func_node.args.args:
        if has_float_in_annotation(arg.annotation):
            return True
    if has_float_in_annotation(func_node.returns):
        return True
    return False


def detect_recursion(func_node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """检测函数是否存在直接递归调用（函数体内调用自身名称）。"""
    func_name = func_node.name
    for node in ast.walk(func_node):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id == func_name:
                return True
            if isinstance(node.func, ast.Attribute) and node.func.attr == func_name:
                return True
    return False


def decide_dimensions(features: dict, has_float: bool) -> list[str]:
    """根据特征决定适用维度。"""
    dims = ["functional", "boundary"]  # 必选

    if (features["has_try"] or features["has_raise"]
            or features["has_file_io"] or features["has_network"]):
        dims.append("exception")

    if (features["has_numeric_op"] or features["uses_math"]
            or features["uses_numpy"] or has_float):
        dims.append("data_integrity")

    if (features["has_sort"] or features["has_recursion"]
            or features["has_large_comprehension"]
            or features["has_string_concat_in_loop"]
            or (features["has_iteration"] and features["has_file_io"])):
        dims.append("performance")

    if (features["has_subprocess"] or features["has_eval_exec"]
            or features["has_sql_ops"] or features["has_pickle"]
            or features["has_yaml_unsafe"] or features["has_shell_format"]):
        dims.append("security")

    return dims


def decide_mocks(features: dict, class_name: str | None) -> list[dict]:
    """根据特征决定需要的 mock。"""
    mocks = []
    if features["has_file_io"]:
        mocks.append({
            "type": "file_io",
            "suggestion": "使用 tmp_path fixture 或 patch('builtins.open')",
        })
    if features["has_network"]:
        mocks.append({
            "type": "network",
            "suggestion": "patch requests.get / httpx.get 并用 mock_response 构造响应",
        })
    if features["uses_os_path"]:
        mocks.append({
            "type": "filesystem_query",
            "suggestion": "考虑 patch os.path.exists / os.path.isfile",
        })
    if features["has_subprocess"]:
        mocks.append({
            "type": "subprocess",
            "suggestion": "patch subprocess.run / os.system 并构造安全返回值",
        })
    if features["has_sql_ops"]:
        mocks.append({
            "type": "database",
            "suggestion": "patch sqlite3.connect / psycopg2.connect 并 mock cursor",
        })
    return mocks


# ---------------------------------------------------------------------------
# 函数提取
# ---------------------------------------------------------------------------

def is_stub(func_node) -> bool:
    """判断是否为存根函数（仅 pass 或 ...）。"""
    body = func_node.body
    # 可能有 docstring
    start = 0
    if (body and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)):
        start = 1
    remaining = body[start:]
    if len(remaining) != 1:
        return False
    stmt = remaining[0]
    if isinstance(stmt, ast.Pass):
        return True
    if (isinstance(stmt, ast.Expr)
            and isinstance(stmt.value, ast.Constant)
            and stmt.value.value is Ellipsis):
        return True
    return False


def has_decorator(func_node, name: str) -> bool:
    """检查函数是否有特定装饰器。"""
    for dec in func_node.decorator_list:
        if isinstance(dec, ast.Name) and dec.id == name:
            return True
        if isinstance(dec, ast.Attribute) and dec.attr == name:
            return True
    return False


def is_property_setter(func_node) -> bool:
    """检查是否为 @x.setter。"""
    for dec in func_node.decorator_list:
        if isinstance(dec, ast.Attribute) and dec.attr == "setter":
            return True
    return False


def is_overload(func_node) -> bool:
    """检查是否有 @overload 装饰器。"""
    return has_decorator(func_node, "overload")


def extract_signature(func_node) -> str:
    """提取函数签名文本。"""
    try:
        # 尝试从 args 构造
        parts = []
        for arg in func_node.args.args:
            s = arg.arg
            if arg.annotation:
                try:
                    s += ": " + ast.unparse(arg.annotation)
                except Exception:
                    pass
            parts.append(s)
        sig = f"{func_node.name}({', '.join(parts)})"
        if func_node.returns:
            try:
                sig += " -> " + ast.unparse(func_node.returns)
            except Exception:
                pass
        return sig
    except Exception:
        return func_node.name + "(...)"


def get_source_segment(source_lines: list[str], node) -> str:
    """提取函数的源码。"""
    start = node.lineno - 1
    end = node.end_lineno if hasattr(node, "end_lineno") else start + 1
    return "\n".join(source_lines[start:end])


def md5_text(text: str) -> str:
    return hashlib.md5(text.encode("utf-8", errors="replace")).hexdigest()


def extract_functions_from_file(
    filepath: Path, repo_root: Path
) -> dict:
    """从一个 Python 文件提取所有可测试函数。"""
    try:
        source = filepath.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source, filename=str(filepath))
    except (SyntaxError, UnicodeDecodeError) as e:
        return {"error": str(e), "functions": {}}

    source_lines = source.splitlines()
    file_md5 = md5_text(source)
    rel_path = str(filepath.relative_to(repo_root))

    functions = {}

    # 遍历顶层和类内的函数
    def process_func(func_node, class_name=None):
        # 过滤
        if is_stub(func_node):
            return
        if is_property_setter(func_node):
            return
        if is_overload(func_node):
            return

        # 特征分析
        detector = FeatureDetector()
        detector.visit(func_node)
        detector.features["has_recursion"] = detect_recursion(func_node)
        has_float = detect_float_type(func_node)

        dims = decide_dimensions(detector.features, has_float)
        mocks = decide_mocks(detector.features, class_name)

        func_source = get_source_segment(source_lines, func_node)
        func_md5 = md5_text(func_source)

        key = f"{class_name}.{func_node.name}" if class_name else func_node.name

        functions[key] = {
            "name": func_node.name,
            "class_name": class_name,
            "func_md5": func_md5,
            "line_range": [func_node.lineno, func_node.end_lineno or func_node.lineno],
            "signature": extract_signature(func_node),
            "is_async": isinstance(func_node, ast.AsyncFunctionDef),
            "decorators": [
                ast.unparse(d) if hasattr(ast, "unparse") else str(d)
                for d in func_node.decorator_list
            ],
            "features": detector.features,
            "has_float_type": has_float,
            "dimensions": dims,
            "mocks_needed": mocks,
        }

    for node in tree.body:
        # 跳过 if __name__ == "__main__" 块
        if isinstance(node, ast.If):
            continue

        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            process_func(node)
        elif isinstance(node, ast.ClassDef):
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    process_func(child, class_name=node.name)

    return {
        "file_md5": file_md5,
        "path": rel_path,
        "functions": functions,
    }


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def detect_language_and_framework(repo_root: Path) -> dict:
    """检测语言和测试框架。"""
    result = {"languages": [], "test_frameworks": {}}

    # 检测 Python
    has_py = any(repo_root.rglob("*.py"))
    if has_py:
        result["languages"].append("python")
        # 默认 pytest；后续可从 pyproject.toml 等读出精确信息
        result["test_frameworks"]["python"] = "pytest"

    # 检测 C++ (预留)
    has_cpp = any(repo_root.rglob("*.cpp")) or any(repo_root.rglob("*.hpp"))
    if has_cpp:
        result["languages"].append("cpp")
        # 预留：根据 CMakeLists 判断 gtest/catch2
        result["test_frameworks"]["cpp"] = "gtest"

    return result


def walk_sources(repo_root: Path, source_dirs: list[str] | None) -> list[Path]:
    """遍历源码目录，返回所有应扫描的 .py 文件。"""
    if source_dirs:
        roots = [repo_root / d for d in source_dirs]
    else:
        roots = [repo_root]

    files = []
    for root in roots:
        if not root.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirpath_obj = Path(dirpath)
            # 剔除要跳过的子目录
            dirnames[:] = [
                d for d in dirnames
                if not should_skip_dir(dirpath_obj / d, repo_root)
            ]
            # 不扫描 test/generated_unit 自身
            rel = dirpath_obj.relative_to(repo_root)
            if str(rel).startswith("test/generated_unit") or str(rel).startswith(
                "test\\generated_unit"
            ):
                continue

            for fname in filenames:
                fpath = dirpath_obj / fname
                if not should_skip_file(fpath):
                    files.append(fpath)

    return sorted(files)


def compare_with_baseline(
    current: dict, baseline_path: Path | None
) -> dict:
    """与 test_cases.json 基线对比，标注变更。"""
    if not baseline_path or not baseline_path.is_file():
        return {
            "is_incremental": False,
            "changed_files": list(current["files"].keys()),
            "new_files": list(current["files"].keys()),
            "removed_files": [],
            "changed_functions": {},
            "unchanged_functions": {},
        }

    try:
        with open(baseline_path, "r", encoding="utf-8") as f:
            baseline = json.load(f)
    except Exception:
        return {
            "is_incremental": False,
            "changed_files": list(current["files"].keys()),
            "new_files": list(current["files"].keys()),
            "removed_files": [],
            "changed_functions": {},
            "unchanged_functions": {},
        }

    baseline_files = baseline.get("files", {})
    current_files = current["files"]

    changed_files = []
    new_files = []
    removed_files = []
    changed_functions = {}  # filepath -> [func_key, ...]
    unchanged_functions = {}  # filepath -> [func_key, ...]

    for fpath, finfo in current_files.items():
        if fpath not in baseline_files:
            new_files.append(fpath)
            changed_files.append(fpath)
            changed_functions[fpath] = list(finfo["functions"].keys())
            continue

        baseline_finfo = baseline_files[fpath]
        if baseline_finfo.get("file_md5") == finfo["file_md5"]:
            # 文件未变
            unchanged_functions[fpath] = list(finfo["functions"].keys())
            continue

        changed_files.append(fpath)
        # 按函数粒度对比
        baseline_funcs = baseline_finfo.get("functions", {})
        cur_funcs = finfo["functions"]
        changed_functions[fpath] = []
        unchanged_functions[fpath] = []
        for fkey, fdata in cur_funcs.items():
            if fkey not in baseline_funcs:
                changed_functions[fpath].append(fkey)
            elif baseline_funcs[fkey].get("func_md5") != fdata["func_md5"]:
                changed_functions[fpath].append(fkey)
            else:
                unchanged_functions[fpath].append(fkey)

    for fpath in baseline_files:
        if fpath not in current_files:
            removed_files.append(fpath)

    return {
        "is_incremental": True,
        "changed_files": changed_files,
        "new_files": new_files,
        "removed_files": removed_files,
        "changed_functions": changed_functions,
        "unchanged_functions": unchanged_functions,
    }


def main():
    parser = argparse.ArgumentParser(
        description="扫描仓库提取可测试函数",
    )
    parser.add_argument("repo_root", help="仓库根目录")
    parser.add_argument("--source", default=None,
                        help="限定扫描的目录，逗号分隔")
    parser.add_argument("--baseline", default=None,
                        help="基线 test_cases.json 路径（用于增量对比）")
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    if not repo_root.is_dir():
        print(f"错误: {repo_root} 不是有效目录", file=sys.stderr)
        sys.exit(1)

    source_dirs = None
    if args.source:
        source_dirs = [s.strip() for s in args.source.split(",") if s.strip()]

    # 检测语言/框架
    lang_info = detect_language_and_framework(repo_root)

    # 扫描所有 .py 文件
    files = walk_sources(repo_root, source_dirs)

    result = {
        "languages": lang_info["languages"],
        "test_frameworks": lang_info["test_frameworks"],
        "source_dirs": source_dirs or ["."],
        "files": {},
    }

    for fpath in files:
        finfo = extract_functions_from_file(fpath, repo_root)
        if finfo.get("functions"):  # 只保留有函数的文件
            result["files"][str(fpath.relative_to(repo_root))] = finfo

    # 汇总
    total_functions = sum(
        len(f["functions"]) for f in result["files"].values()
    )
    result["summary"] = {
        "total_files": len(result["files"]),
        "total_functions": total_functions,
    }

    # 基线对比
    baseline_path = Path(args.baseline) if args.baseline else None
    result["incremental"] = compare_with_baseline(result, baseline_path)

    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
