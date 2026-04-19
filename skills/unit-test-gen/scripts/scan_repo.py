#!/usr/bin/env python3
"""
scan_repo.py — 扫描代码仓库，提取所有可测试函数（支持 Python 和 C++）。

输出 JSON 结构包含每个文件和函数的元信息（签名、MD5、AST 特征、适用维度）。
Claude 读取此输出后补充每个函数的 `cases` 描述（测试用例元数据）。

两种用法：

1. 调试模式（stdout，默认）：
    python scan_repo.py <repo_root> [--source core,utils]
    python scan_repo.py <repo_root> --baseline test/generated_unit/test_cases.json
    → 输出完整 JSON 到 stdout，适合人工 / Claude 检视

2. 工作流模式（直写基线文件，merge 语义）：
    python scan_repo.py <repo_root> --output test/generated_unit/test_cases.json
    python scan_repo.py <repo_root> --output test/generated_unit/test_cases.json --mode full
    → 直接写入/合并基线，字段级 merge：
      - 保留用户的 `coverage_config`（仅在不存在时写入默认值）
      - 不触碰 `tool_status`（归 run_and_report.py 负责）
      - 保留未变更函数的 `cases`（LLM 产物，scanner 不管）
      - 增量模式（默认）：`--mode incremental`，只覆盖变更函数的元数据
      - 全量模式：`--mode full`，对所有函数重写元数据但仍保留 cases

调试产物（如扫描原始结果的保留副本）建议另存到 .test/generated_unit/scan_result.json：
    python scan_repo.py <repo_root> > .test/generated_unit/scan_result.json
"""

import argparse
import ast
import hashlib
import json
import os
import sys
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any

# 基线格式版本。改变字段结构时递增。
BASELINE_VERSION = "1.0"

# coverage_config 默认值（仅在基线文件中不存在 coverage_config 时写入）
DEFAULT_COVERAGE_CONFIG = {
    "statement_threshold": 70,
    "function_threshold": 70,
    "branch_threshold": 60,
    "exclude_dirs": [],
    "dead_code_min_confidence": 80,
}

# C++ 解析（可选依赖，仅扫描 C++ 文件时需要）
try:
    import tree_sitter_cpp as tscpp
    from tree_sitter import Language, Parser

    _TS_AVAILABLE = True
except ImportError:
    _TS_AVAILABLE = False

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

CPP_EXTENSIONS = {".cpp", ".cc", ".cxx", ".h", ".hpp", ".hh", ".hxx"}
PY_EXTENSIONS = {".py"}


def should_skip_dir(path: Path, _repo_root: Path) -> bool:
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
    """判断文件是否应跳过（支持 Python 和 C++）。"""
    name = path.name
    ext = path.suffix.lower()

    # 只处理已知扩展名
    if ext not in PY_EXTENSIONS and ext not in CPP_EXTENSIONS:
        return True

    # Python 私有模块（但 __init__.py 保留）
    if ext == ".py":
        if name.startswith("_") and name != "__init__.py":
            return True
        if name.endswith("_generated.py"):
            return True

    # C++ 头文件保护：跳过纯声明头文件（在解析时判断，此处先放行）

    return False


def md5_text(text: str) -> str:
    return hashlib.md5(text.encode("utf-8", errors="replace")).hexdigest()


# ---------------------------------------------------------------------------
# 语言分析器抽象基类
# ---------------------------------------------------------------------------

class LanguageAnalyzer(ABC):
    """语言特定的函数提取和特征分析基类。"""

    @abstractmethod
    def extract_functions(self, filepath: Path, repo_root: Path) -> dict:
        """从一个源文件提取所有可测试函数。"""

    @staticmethod
    @abstractmethod
    def decide_dimensions(features: dict) -> list[str]:
        """根据特征决定适用维度。"""

    @staticmethod
    @abstractmethod
    def decide_mocks(features: dict, class_name: str | None) -> list[dict]:
        """根据特征决定需要的 mock。"""


# ---------------------------------------------------------------------------
# Python 分析器
# ---------------------------------------------------------------------------

class PythonFeatureDetector(ast.NodeVisitor):
    """扫描 Python 函数体，记录影响测试维度的 AST 特征。"""

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
            "has_sort": False,
            "has_recursion": False,
            "has_large_comprehension": False,
            "has_string_concat_in_loop": False,
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
                elif name == "subprocess":
                    self.features["has_subprocess"] = True
                elif name == "os" and node.func.attr in ("system", "popen"):
                    self.features["has_subprocess"] = True
                elif name == "pickle" and node.func.attr in ("loads", "load"):
                    self.features["has_pickle"] = True
                elif name in ("sqlite3", "psycopg2"):
                    self.features["has_sql_ops"] = True
                elif name == "yaml" and node.func.attr == "load":
                    self.features["has_yaml_unsafe"] = True
            if node.func.attr == "sort":
                self.features["has_sort"] = True
            if node.func.attr == "execute":
                self.features["has_sql_ops"] = True
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
        if isinstance(node.op, ast.Add) and isinstance(node.target, ast.Name):
            self.features["has_string_concat_in_loop"] = True
        self.generic_visit(node)

    def visit_JoinedStr(self, node: ast.JoinedStr) -> None:
        self.features["has_shell_format"] = True
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if isinstance(node.value, ast.Name) and node.value.id == "os" and node.attr == "path":
            self.features["uses_os_path"] = True
        self.generic_visit(node)


class PythonAnalyzer(LanguageAnalyzer):
    """Python 函数提取和特征分析。"""

    def extract_functions(self, filepath: Path, repo_root: Path) -> dict:
        try:
            source = filepath.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source, filename=str(filepath))
        except (SyntaxError, UnicodeDecodeError) as e:
            return {"error": str(e), "functions": {}}

        source_lines = source.splitlines()
        file_md5 = md5_text(source)
        rel_path = str(filepath.relative_to(repo_root))
        functions = {}

        def _process_func(func_node, class_name=None):
            if _is_stub(func_node):
                return
            if _is_property_setter(func_node):
                return
            if _is_overload(func_node):
                return

            detector = PythonFeatureDetector()
            detector.visit(func_node)
            detector.features["has_recursion"] = _detect_recursion(func_node)
            has_float = _detect_float_type(func_node)

            dims = self.decide_dimensions(detector.features, has_float)
            mocks = self.decide_mocks(detector.features, class_name)

            func_source = _get_source_segment(source_lines, func_node)
            func_md5 = md5_text(func_source)
            key = f"{class_name}.{func_node.name}" if class_name else func_node.name

            functions[key] = {
                "name": func_node.name,
                "class_name": class_name,
                "func_md5": func_md5,
                "line_range": [func_node.lineno, func_node.end_lineno or func_node.lineno],
                "signature": _extract_signature(func_node),
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
            if isinstance(node, ast.If):
                continue
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                _process_func(node)
            elif isinstance(node, ast.ClassDef):
                for child in node.body:
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        _process_func(child, class_name=node.name)

        return {"file_md5": file_md5, "path": rel_path, "functions": functions}

    @staticmethod
    def decide_dimensions(features: dict, has_float: bool = False) -> list[str]:
        dims = ["functional", "boundary"]

        if (features.get("has_try") or features.get("has_raise")
                or features.get("has_file_io") or features.get("has_network")):
            dims.append("exception")

        if (features.get("has_numeric_op") or features.get("uses_math")
                or features.get("uses_numpy") or has_float):
            dims.append("data_integrity")

        if (features.get("has_sort") or features.get("has_recursion")
                or features.get("has_large_comprehension")
                or features.get("has_string_concat_in_loop")
                or (features.get("has_iteration") and features.get("has_file_io"))):
            dims.append("performance")

        if (features.get("has_subprocess") or features.get("has_eval_exec")
                or features.get("has_sql_ops") or features.get("has_pickle")
                or features.get("has_yaml_unsafe") or features.get("has_shell_format")):
            dims.append("security")

        return dims

    @staticmethod
    def decide_mocks(features: dict, class_name: str | None) -> list[dict]:
        mocks = []
        if features.get("has_file_io"):
            mocks.append({
                "type": "file_io",
                "suggestion": "使用 tmp_path fixture 或 patch('builtins.open')",
            })
        if features.get("has_network"):
            mocks.append({
                "type": "network",
                "suggestion": "patch requests.get / httpx.get 并用 mock_response 构造响应",
            })
        if features.get("uses_os_path"):
            mocks.append({
                "type": "filesystem_query",
                "suggestion": "考虑 patch os.path.exists / os.path.isfile",
            })
        if features.get("has_subprocess"):
            mocks.append({
                "type": "subprocess",
                "suggestion": "patch subprocess.run / os.system 并构造安全返回值",
            })
        if features.get("has_sql_ops"):
            mocks.append({
                "type": "database",
                "suggestion": "patch sqlite3.connect / psycopg2.connect 并 mock cursor",
            })
        return mocks


# Python 私有辅助函数

def _is_stub(func_node) -> bool:
    body = func_node.body
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


def _is_property_setter(func_node) -> bool:
    for dec in func_node.decorator_list:
        if isinstance(dec, ast.Attribute) and dec.attr == "setter":
            return True
    return False


def _is_overload(func_node) -> bool:
    for dec in func_node.decorator_list:
        if isinstance(dec, ast.Name) and dec.id == "overload":
            return True
        if isinstance(dec, ast.Attribute) and dec.attr == "overload":
            return True
    return False


def _detect_float_type(func_node) -> bool:
    def _has_float_in_annotation(ann):
        if ann is None:
            return False
        try:
            s = ast.unparse(ann)
            return "float" in s.lower()
        except Exception:
            return False

    for arg in func_node.args.args:
        if _has_float_in_annotation(arg.annotation):
            return True
    return _has_float_in_annotation(func_node.returns)


def _detect_recursion(func_node) -> bool:
    func_name = func_node.name
    for node in ast.walk(func_node):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id == func_name:
                return True
            if isinstance(node.func, ast.Attribute) and node.func.attr == func_name:
                return True
    return False


def _extract_signature(func_node) -> str:
    try:
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


def _get_source_segment(source_lines: list[str], node) -> str:
    start = node.lineno - 1
    end = node.end_lineno if hasattr(node, "end_lineno") else start + 1
    return "\n".join(source_lines[start:end])


# ---------------------------------------------------------------------------
# C++ 分析器
# ---------------------------------------------------------------------------

# tree-sitter C++ 节点类型常量
_CPP_FUNC_DEF = "function_definition"
_CPP_CLASS_SPEC = "class_specifier"
_CPP_STRUCT_SPEC = "struct_specifier"
_CPP_TEMPLATE_DECL = "template_declaration"
_CPP_TRY_STMT = "try_statement"
_CPP_THROW_STMT = "throw_statement"
_CPP_CALL_EXPR = "call_expression"
_CPP_BIN_EXPR = "binary_expression"
_CPP_SUBSCRIPT = "subscript_expression"
_CPP_FOR_STMT = "for_statement"
_CPP_WHILE_STMT = "while_statement"
_CPP_DO_STMT = "do_statement"
_CPP_RANGE_FOR = "range_based_for_statement"
_CPP_NEW_EXPR = "new_expression"
_CPP_DELETE_EXPR = "delete_expression"
_CPP_TYPE_DESC = "type_descriptor"
_CPP_FUNC_DECL = "function_declarator"


class CppAnalyzer(LanguageAnalyzer):
    """C++ 函数提取和特征分析（基于 tree-sitter）。"""

    def __init__(self):
        if not _TS_AVAILABLE:
            raise RuntimeError(
                "C++ 扫描需要 tree-sitter 依赖。"
                "请安装: pip install tree-sitter tree-sitter-cpp"
            )
        self._language = Language(tscpp.language())  # type: ignore[misc]
        self._parser = Parser(self._language)  # type: ignore[abstract]

    def extract_functions(self, filepath: Path, repo_root: Path) -> dict:
        source = filepath.read_text(encoding="utf-8", errors="replace")
        source_bytes = source.encode("utf-8")
        file_md5 = md5_text(source)
        rel_path = str(filepath.relative_to(repo_root))

        tree = self._parser.parse(source_bytes)
        root = tree.root_node

        functions = {}
        self._walk_node(root, source_bytes, filepath, functions)

        return {"file_md5": file_md5, "path": rel_path, "functions": functions}

    def _walk_node(self, node, source_bytes: bytes,
                   filepath: Path, functions: dict,
                   namespace: str = "", class_name: str | None = None):
        """递归遍历 tree-sitter AST，提取函数定义。"""
        for child in node.children:
            # 命名空间
            if child.type == "namespace_definition":
                ns_name = self._node_text(child.child_by_field_name("name"), source_bytes)
                new_ns = f"{namespace}::{ns_name}" if namespace else ns_name
                self._walk_node(child, source_bytes, filepath, functions, new_ns, class_name)
                continue

            # 类/结构体
            if child.type in ("class_specifier", "struct_specifier"):
                cn = self._node_text(child.child_by_field_name("name"), source_bytes)
                full_class = f"{namespace}::{cn}" if namespace else cn
                self._walk_node(child, source_bytes, filepath, functions, namespace, full_class)
                continue

            # 模板函数/模板类方法
            if child.type == _CPP_TEMPLATE_DECL:
                for inner in child.children:
                    if inner.type == _CPP_FUNC_DEF:
                        self._process_function(
                            inner, source_bytes, filepath, functions,
                            namespace, class_name, is_template=True)
                    elif inner.type in (_CPP_CLASS_SPEC, _CPP_STRUCT_SPEC):
                        cn = self._node_text(inner.child_by_field_name("name"), source_bytes)
                        full_class = f"{namespace}::{cn}" if namespace else cn
                        self._walk_node(inner, source_bytes, filepath, functions,
                                        namespace, full_class)
                continue

            # 普通函数定义
            if child.type == _CPP_FUNC_DEF:
                self._process_function(
                    child, source_bytes, filepath, functions,
                    namespace, class_name)

            # 递归子节点（处理嵌套结构）
            if child.children:
                self._walk_node(child, source_bytes, filepath, functions,
                                namespace, class_name)

    def _process_function(self, func_node, source_bytes: bytes,
                          _filepath: Path, functions: dict,
                          namespace: str, class_name: str | None,
                          is_template: bool = False):
        """处理单个函数定义节点。"""
        # 获取声明器（含函数名和参数）
        declarator = self._find_child(func_node, _CPP_FUNC_DECL)
        if not declarator:
            return

        func_name = self._extract_func_name(declarator, source_bytes)
        if not func_name:
            return

        # 过滤：main 函数
        if func_name == "main":
            return

        # 获取函数体
        body_node = self._find_child(func_node, "compound_statement")
        if not body_node:
            return  # 纯声明，无定义

        # 过滤：纯虚函数（= 0）和 = default / = delete
        decl_text = self._node_text(declarator, source_bytes)
        if "= 0" in decl_text or "=0" in decl_text.replace(" ", ""):
            return
        if "= default" in decl_text or "= delete" in decl_text:
            return

        # 过滤：析构函数
        if func_name.startswith("~"):
            return

        # 提取签名
        signature = self._build_signature(func_node, declarator, source_bytes)

        # 特征分析
        features = self._analyze_features(body_node, source_bytes, func_name)

        # 构建完整限定名
        parts = []
        if namespace:
            parts.append(namespace)
        if class_name:
            parts.append(class_name)
        parts.append(func_name)
        qualified_name = "::".join(parts)

        # 维度和 mock
        dims = self.decide_dimensions(features)
        mocks = self.decide_mocks(features, class_name)

        func_source = self._node_text(func_node, source_bytes)
        func_md5 = md5_text(func_source)

        functions[qualified_name] = {
            "name": func_name,
            "namespace": namespace or None,
            "class_name": class_name,
            "func_md5": func_md5,
            "line_range": [func_node.start_point[0] + 1, func_node.end_point[0] + 1],
            "signature": signature,
            "is_async": False,
            "is_template": is_template,
            "is_static": "static" in (self._node_text(
                self._find_child(func_node, "storage_class_specifier"),
                source_bytes) or ""),
            "is_virtual": "virtual" in (self._node_text(
                self._find_child(func_node, "virtual"),
                source_bytes) or ""),
            "features": features,
            "dimensions": dims,
            "mocks_needed": mocks,
        }

    def _analyze_features(self, body_node, source_bytes: bytes,
                          func_name: str) -> dict:
        """遍历函数体 tree-sitter AST，检测特征。"""
        features = {
            "has_numeric_op": False,
            "has_float_type": False,
            "uses_stl_math": False,
            "has_try": False,
            "has_throw": False,
            "has_file_io": False,
            "has_network": False,
            "has_index_access": False,
            "has_raw_pointer": False,
            "has_new_delete": False,
            "has_buffer_op": False,
            "has_template": False,
            "uses_smart_ptr": False,
            "has_virtual": False,
            "uses_stl_algo": False,
            "has_sort": False,
            "has_recursion": False,
            "has_str_ops": False,
            "has_iteration": False,
            "is_pure": True,
            "has_subprocess": False,
            "has_printf": False,
            "has_sql_ops": False,
            "has_shell_format": False,
            "has_container_growth": False,
            "has_move_semantics": False,
        }

        self._detect_recursive(body_node, source_bytes, func_name, features)

        return features

    def _detect_recursive(self, node, source_bytes: bytes,
                          func_name: str, features: dict):
        """递归遍历节点，检测所有特征。"""
        if node is None:
            return

        # 检查当前节点类型
        if node.type == _CPP_TRY_STMT:
            features["has_try"] = True
            features["is_pure"] = False

        elif node.type == _CPP_THROW_STMT:
            features["has_throw"] = True

        elif node.type == _CPP_CALL_EXPR:
            self._check_call_features(node, source_bytes, features, func_name)

        elif node.type == _CPP_BIN_EXPR:
            op = self._node_text(node.child_by_field_name("operator"), source_bytes)
            if op in ("+", "-", "*", "/", "%"):
                features["has_numeric_op"] = True

        elif node.type == _CPP_SUBSCRIPT:
            features["has_index_access"] = True

        elif node.type in (_CPP_FOR_STMT, _CPP_WHILE_STMT,
                           _CPP_DO_STMT, _CPP_RANGE_FOR):
            features["has_iteration"] = True

        elif node.type == _CPP_NEW_EXPR:
            features["has_new_delete"] = True
            features["is_pure"] = False

        elif node.type == _CPP_DELETE_EXPR:
            features["has_new_delete"] = True

        elif node.type == "pointer_expression":
            features["has_raw_pointer"] = True

        # 递归子节点
        for child in node.children:
            self._detect_recursive(child, source_bytes, func_name, features)

    def _check_call_features(self, call_node, source_bytes: bytes,
                             features: dict, func_name: str):
        """分析函数调用表达式的特征。"""
        func_node = call_node.child_by_field_name("function")
        if not func_node:
            return

        call_text = self._node_text(func_node, source_bytes)

        # 递归检测
        if call_text == func_name:
            features["has_recursion"] = True

        # STL 数学
        if any(fn in call_text for fn in (
            "std::abs", "std::sqrt", "std::pow", "std::sin",
            "std::cos", "std::tan", "std::log", "std::exp",
            "std::ceil", "std::floor", "std::round",
        )):
            features["uses_stl_math"] = True

        # STL 算法
        if any(fn in call_text for fn in (
            "std::sort", "std::stable_sort", "std::partial_sort",
            "std::find", "std::find_if", "std::transform",
            "std::accumulate", "std::count", "std::remove",
        )):
            features["uses_stl_algo"] = True
            if "sort" in call_text:
                features["has_sort"] = True

        # 文件 IO
        if any(fn in call_text for fn in (
            "std::fstream", "std::ifstream", "std::ofstream",
            "fopen", "fclose", "fread", "fwrite",
        )):
            features["has_file_io"] = True
            features["is_pure"] = False

        # 网络
        if any(fn in call_text for fn in (
            "boost::asio", "curl_", "socket", "connect", "send", "recv",
        )):
            features["has_network"] = True
            features["is_pure"] = False

        # 智能指针
        if any(fn in call_text for fn in (
            "std::make_unique", "std::make_shared",
            "std::unique_ptr", "std::shared_ptr", "std::weak_ptr",
        )):
            features["uses_smart_ptr"] = True

        # 子进程
        if any(fn in call_text for fn in ("system", "popen", "exec")):
            features["has_subprocess"] = True
            features["is_pure"] = False

        # printf 系列
        if any(fn in call_text for fn in (
            "printf", "sprintf", "snprintf", "fprintf",
        )):
            features["has_printf"] = True

        # SQL
        if any(fn in call_text for fn in (
            "sqlite3_", "mysql_", "PQ", "sqlite::",
        )):
            features["has_sql_ops"] = True
            features["is_pure"] = False

        # 缓冲区操作
        if any(fn in call_text for fn in (
            "memcpy", "strcpy", "strcat", "memmove", "strncpy",
        )):
            features["has_buffer_op"] = True

        # 字符串方法
        if any(fn in call_text for fn in (
            ".substr", ".find", ".replace", ".c_str",
            ".append", ".insert", ".erase", ".compare",
        )):
            features["has_str_ops"] = True

        # 容器增长
        if any(fn in call_text for fn in (
            "push_back", "emplace_back", "insert",
        )):
            features["has_container_growth"] = True

        # 移动语义
        if "std::move" in call_text:
            features["has_move_semantics"] = True

        # 通过检查参数类型推断浮点
        if any(t in call_text for t in ("float", "double")):
            features["has_float_type"] = True

    @staticmethod
    def decide_dimensions(features: dict) -> list[str]:
        dims = ["functional", "boundary"]

        if (features.get("has_try") or features.get("has_throw")
                or features.get("has_file_io") or features.get("has_network")):
            dims.append("exception")

        if (features.get("has_numeric_op") or features.get("uses_stl_math")
                or features.get("has_float_type")):
            dims.append("data_integrity")

        if (features.get("has_sort") or features.get("has_recursion")
                or features.get("has_template")
                or features.get("has_new_delete")
                or features.get("has_container_growth")):
            dims.append("performance")

        if (features.get("has_subprocess") or features.get("has_buffer_op")
                or features.get("has_sql_ops") or features.get("has_printf")
                or features.get("has_raw_pointer") or features.get("has_shell_format")):
            dims.append("security")

        return dims

    @staticmethod
    def decide_mocks(features: dict, class_name: str | None) -> list[dict]:
        mocks = []
        if features.get("has_file_io"):
            mocks.append({
                "type": "file_io",
                "suggestion": "使用 temp_directory_path 或 mock IFileReader 接口",
            })
        if features.get("has_network"):
            mocks.append({
                "type": "network",
                "suggestion": "mock IHttpClient 接口",
            })
        if features.get("has_subprocess"):
            mocks.append({
                "type": "subprocess",
                "suggestion": "mock IProcessRunner 接口",
            })
        if features.get("has_sql_ops"):
            mocks.append({
                "type": "database",
                "suggestion": "mock IDatabase 接口或使用内存 SQLite",
            })
        return mocks

    # C++ 辅助方法

    @staticmethod
    def _node_text(node, source_bytes: bytes) -> str:
        if node is None:
            return ""
        return source_bytes[node.start_byte:node.end_byte].decode("utf-8", errors="replace")

    @staticmethod
    def _find_child(node, type_name: str):
        for child in node.children:
            if child.type == type_name:
                return child
        return None

    def _extract_func_name(self, declarator, source_bytes: bytes) -> str:
        """从 function_declarator 提取函数名。"""
        # 处理 field_identifier (类方法) 和 identifier (自由函数)
        for child in declarator.children:
            if child.type in ("identifier", "field_identifier",
                              "destructor_name", "operator_name"):
                return self._node_text(child, source_bytes)
            if child.type == "qualified_identifier":
                # ns::func 的情况，取最后一段
                parts = self._node_text(child, source_bytes).split("::")
                return parts[-1] if parts else ""
            if child.type == "template_function":
                return self._node_text(child, source_bytes)
            # 递归嵌套的 declarator
            if child.type == _CPP_FUNC_DECL:
                return self._extract_func_name(child, source_bytes)
        return ""

    def _build_signature(self, func_node, declarator,
                         source_bytes: bytes) -> str:
        """构建函数签名字符串。"""
        # 返回类型
        ret_type = ""
        for child in func_node.children:
            if child.type == _CPP_TYPE_DESC:
                ret_type = self._node_text(child, source_bytes)
                break

        # 函数名和参数
        decl_text = self._node_text(declarator, source_bytes)

        # cv 限定符
        cv = ""
        # 从函数定义的直接子节点找 qualifier
        for child in func_node.children:
            if child.type == "type_qualifier":
                cv = " " + self._node_text(child, source_bytes)

        return f"{ret_type} {decl_text}{cv}".strip()


# ---------------------------------------------------------------------------
# 分析器工厂
# ---------------------------------------------------------------------------

def get_analyzer(ext: str) -> LanguageAnalyzer | None:
    """根据文件扩展名返回对应的语言分析器。"""
    if ext in PY_EXTENSIONS:
        return PythonAnalyzer()
    if ext in CPP_EXTENSIONS:
        if not _TS_AVAILABLE:
            return None  # 跳过 C++ 文件（缺少依赖）
        return CppAnalyzer()
    return None


# ---------------------------------------------------------------------------
# 语言和框架检测
# ---------------------------------------------------------------------------

def detect_language_and_framework(repo_root: Path) -> dict:
    """检测语言和测试框架。"""
    result = {"languages": [], "test_frameworks": {}}

    has_py = any(repo_root.rglob("*.py"))
    if has_py:
        result["languages"].append("python")
        result["test_frameworks"]["python"] = "pytest"

    has_cpp = (
        any(repo_root.rglob("*.cpp"))
        or any(repo_root.rglob("*.cc"))
        or any(repo_root.rglob("*.cxx"))
        or any(repo_root.rglob("*.hpp"))
    )
    if has_cpp:
        result["languages"].append("cpp")
        result["test_frameworks"]["cpp"] = "gtest"

    return result


# ---------------------------------------------------------------------------
# 文件遍历
# ---------------------------------------------------------------------------

def walk_sources(repo_root: Path, source_dirs: list[str] | None) -> list[Path]:
    """遍历源码目录，返回所有应扫描的源文件（Python + C++）。"""
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
            dirnames[:] = [
                d for d in dirnames
                if not should_skip_dir(dirpath_obj / d, repo_root)
            ]
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


# ---------------------------------------------------------------------------
# 基线对比
# ---------------------------------------------------------------------------

def compare_with_baseline(current: dict, baseline_path: Path | None) -> dict:
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
    changed_functions = {}
    unchanged_functions = {}

    for fpath, finfo in current_files.items():
        if fpath not in baseline_files:
            new_files.append(fpath)
            changed_files.append(fpath)
            changed_functions[fpath] = list(finfo["functions"].keys())
            continue

        baseline_finfo = baseline_files[fpath]
        if baseline_finfo.get("file_md5") == finfo["file_md5"]:
            unchanged_functions[fpath] = list(finfo["functions"].keys())
            continue

        changed_files.append(fpath)
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


# ---------------------------------------------------------------------------
# 测试路径计算
# ---------------------------------------------------------------------------

def _compute_test_path(source_rel_path: str) -> str | None:
    """根据源码相对路径计算测试文件路径。

    规则：source <path>/<name>.<ext> → test/generated_unit/<path>/test_<name>.<ext>
    例如：core/dag/parser.py → test/generated_unit/core/dag/test_parser.py
    """
    p = Path(source_rel_path)
    name = p.name
    if not name.startswith("test_"):
        name = f"test_{name}"
    return str(Path("test/generated_unit") / p.parent / name)


# ---------------------------------------------------------------------------
# 基线构建与 merge
# ---------------------------------------------------------------------------

# 函数级字段：这些字段由 scanner 负责写入/更新（语法/AST 层面的事实）
_SCANNER_OWNED_FUNC_FIELDS = (
    "func_md5", "line_range", "signature", "is_async",
    "class_name", "dimensions", "features", "mocks_needed",
)

# 函数级字段：这些字段由 Claude/LLM 负责，scanner 不动（语义层面的产物）
_LLM_OWNED_FUNC_FIELDS = ("cases",)


def _func_metadata_from_scan(scan_func: dict) -> dict:
    """从 scanner 原始输出提取函数级元数据字段（剔除 scanner 自己用的临时字段）。

    scanner 内部有 `name`、`decorators`、`has_float_type` 等字段，这些是调试/
    中间字段，不进基线。进基线的只有 _SCANNER_OWNED_FUNC_FIELDS。
    """
    result = {}
    for key in _SCANNER_OWNED_FUNC_FIELDS:
        if key in scan_func:
            result[key] = scan_func[key]
    return result


def build_baseline(scan_result: dict, mode: str) -> dict:
    """将 scanner 的纯扫描产物（scan_result）组织成完整基线结构。

    这只是把字段重新组织,不做 merge；merge 留给 merge_into_baseline。

    参数：
      scan_result: scanner 内部构造的扫描结果（含 languages、files 等）
      mode: "full" 或 "incremental"，写入 mode_last_run 字段

    返回：基线结构的字典（不含 cases，cases 由 Claude 后补）
    """
    baseline_files = {}
    for src_path, file_info in scan_result["files"].items():
        func_out = {}
        for func_key, func_data in file_info.get("functions", {}).items():
            func_out[func_key] = _func_metadata_from_scan(func_data)
            # 新扫描的函数 cases 为空数组，等 Claude 补
            func_out[func_key]["cases"] = []

        baseline_files[src_path] = {
            "file_md5": file_info["file_md5"],
            "test_path": file_info.get("test_path", ""),
            "functions": func_out,
        }

    total_cases = sum(
        len(f.get("cases", []))
        for fi in baseline_files.values()
        for f in fi["functions"].values()
    )

    return {
        "version": BASELINE_VERSION,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "languages": scan_result["languages"],
        "test_frameworks": scan_result["test_frameworks"],
        "source_dirs": scan_result["source_dirs"],
        "mode_last_run": mode,
        "summary": {
            **scan_result.get("summary", {}),
            "total_cases": total_cases,
        },
        "coverage_config": dict(DEFAULT_COVERAGE_CONFIG),
        # tool_status 由 run_and_report.py 的环境预检写入，scanner 不初始化
        "files": baseline_files,
    }


def merge_into_baseline(existing: dict, fresh: dict, mode: str,
                        incremental_info: dict) -> dict:
    """以字段级别将新扫描结果 merge 进已有基线。

    合并规则：
    - 顶层：scanner 负责的字段（version/generated_at/mode_last_run/languages/
      test_frameworks/source_dirs/summary）用 fresh 覆盖。
    - coverage_config: 若 existing 有则保留用户编辑值；否则用 fresh（DEFAULT）。
    - tool_status: 若 existing 有则完整保留；没有则不写入（留给 run_and_report）。
    - files: 字段级 merge
      - 新增文件：直接从 fresh 取（cases 为空待补）
      - 删除文件：从 existing 中移除
      - 文件 MD5 相同（unchanged）：完全保留 existing，连 cases 一起
      - 文件 MD5 不同但某函数 MD5 未变：保留该函数的 cases，元数据用 fresh
      - 函数 MD5 变化或新增：元数据用 fresh，cases 置空等 Claude 补
      - 函数被删除：从 existing 中移除

    全量模式（mode=full）下，仍然按 MD5 判断 cases 能否保留（避免无谓丢失）；
    mode 只影响 mode_last_run 的字面值。

    参数：
      existing: 旧 test_cases.json 的内容（可能为空 dict）
      fresh: 本次 build_baseline 构造的新基线（不含 cases）
      mode: "full" / "incremental"
      incremental_info: compare_with_baseline 的输出，用于确定未变文件

    返回：合并后的基线字典
    """
    existing_files = existing.get("files", {})
    fresh_files = fresh["files"]
    merged_files = {}

    unchanged_files = set()
    if incremental_info.get("is_incremental"):
        # 未变更文件：不出现在 changed_files 里的都算未变
        changed = set(incremental_info.get("changed_files", []))
        for fp in existing_files:
            if fp not in changed and fp in fresh_files:
                unchanged_files.add(fp)

    for src_path, fresh_finfo in fresh_files.items():
        if src_path in unchanged_files:
            # 整个文件未变：完全保留 existing（包括所有 cases）
            merged_files[src_path] = existing_files[src_path]
            # 但仍然同步 test_path（可能技能版本升级修改了路径规则）
            merged_files[src_path]["test_path"] = fresh_finfo.get(
                "test_path", existing_files[src_path].get("test_path", "")
            )
            continue

        # 文件变化或新增：逐函数合并
        existing_funcs = existing_files.get(src_path, {}).get("functions", {})
        fresh_funcs = fresh_finfo["functions"]
        merged_funcs = {}

        for func_key, fresh_func in fresh_funcs.items():
            existing_func = existing_funcs.get(func_key, {})
            merged = dict(fresh_func)  # scanner 字段 + 空 cases

            if (existing_func
                    and existing_func.get("func_md5") == fresh_func.get("func_md5")
                    and existing_func.get("cases")):
                # 函数未变，保留旧 cases
                merged["cases"] = existing_func["cases"]
            # 否则 cases 就是 fresh 里的空数组 []

            merged_funcs[func_key] = merged

        merged_files[src_path] = {
            "file_md5": fresh_finfo["file_md5"],
            "test_path": fresh_finfo.get("test_path", ""),
            "functions": merged_funcs,
        }
    # 不在 fresh 中的文件 = 被删除，自然不会进 merged_files

    # 重新计算 total_cases
    total_cases = sum(
        len(f.get("cases", []))
        for fi in merged_files.values()
        for f in fi["functions"].values()
    )

    result = {
        "version": BASELINE_VERSION,
        "generated_at": fresh["generated_at"],
        "languages": fresh["languages"],
        "test_frameworks": fresh["test_frameworks"],
        "source_dirs": fresh["source_dirs"],
        "mode_last_run": mode,
        "summary": {**fresh["summary"], "total_cases": total_cases},
        "files": merged_files,
    }

    # coverage_config: 用户编辑优先
    if "coverage_config" in existing:
        result["coverage_config"] = existing["coverage_config"]
    else:
        result["coverage_config"] = dict(DEFAULT_COVERAGE_CONFIG)

    # tool_status: 若已存在则保留（run_and_report 会在 run 阶段再次更新）
    if "tool_status" in existing:
        result["tool_status"] = existing["tool_status"]

    return result


def write_baseline_file(baseline: dict, output_path: Path) -> None:
    """原子写入基线文件（先写临时文件再 rename，避免中断导致半写状态）。"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = output_path.with_suffix(output_path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(baseline, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    tmp.replace(output_path)


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="扫描仓库提取可测试函数（支持 Python 和 C++）",
    )
    parser.add_argument("repo_root", help="仓库根目录")
    parser.add_argument("--source", default=None,
                        help="限定扫描的目录，逗号分隔")
    parser.add_argument("--baseline", default=None,
                        help="基线 test_cases.json 路径（用于增量对比）。"
                             "与 --output 同时使用时，--output 自动作为 --baseline。")
    parser.add_argument("--output", default=None,
                        help="直写/合并基线文件路径（工作流模式）。"
                             "不指定则输出 JSON 到 stdout（调试模式）。")
    parser.add_argument("--mode", default="incremental",
                        choices=["full", "incremental"],
                        help="扫描模式，写入基线的 mode_last_run 字段（默认 incremental）")
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    if not repo_root.is_dir():
        print(f"错误: {repo_root} 不是有效目录", file=sys.stderr)
        sys.exit(1)

    source_dirs = None
    if args.source:
        source_dirs = [s.strip() for s in args.source.split(",") if s.strip()]

    # 如果指定了 --output 而未显式提供 --baseline，默认把 output 当作基线来增量对比
    baseline_path = None
    if args.baseline:
        baseline_path = Path(args.baseline)
    elif args.output:
        candidate = Path(args.output)
        if candidate.is_file():
            baseline_path = candidate

    lang_info = detect_language_and_framework(repo_root)

    if "cpp" in lang_info["languages"] and not _TS_AVAILABLE:
        print("警告: 检测到 C++ 文件但缺少 tree-sitter 依赖，"
              "C++ 文件将被跳过。安装: pip install tree-sitter tree-sitter-cpp",
              file=sys.stderr)

    files = walk_sources(repo_root, source_dirs)

    result = {
        "languages": lang_info["languages"],
        "test_frameworks": lang_info["test_frameworks"],
        "source_dirs": source_dirs or ["."],
        "files": {},
    }

    for fpath in files:
        ext = fpath.suffix.lower()
        analyzer = get_analyzer(ext)
        if analyzer is None:
            continue

        finfo = analyzer.extract_functions(fpath, repo_root)
        if finfo.get("functions"):
            rel = str(fpath.relative_to(repo_root))
            # 计算测试文件路径：source path/ext → test/generated_unit/path/test_name.ext
            test_path = _compute_test_path(rel)
            if test_path:
                finfo["test_path"] = test_path
            result["files"][rel] = finfo

    total_functions = sum(
        len(f["functions"]) for f in result["files"].values()
    )
    result["summary"] = {
        "total_files": len(result["files"]),
        "total_functions": total_functions,
    }

    incremental_info = compare_with_baseline(result, baseline_path)
    result["incremental"] = incremental_info

    # 工作流模式：直写/合并基线文件
    if args.output:
        output_path = Path(args.output)
        fresh_baseline = build_baseline(result, mode=args.mode)

        existing = {}
        if baseline_path and baseline_path.is_file():
            try:
                with open(baseline_path, "r", encoding="utf-8") as f:
                    existing = json.load(f)
            except Exception as e:
                print(f"警告: 基线文件 {baseline_path} 无法解析（{e}），"
                      f"按全量处理", file=sys.stderr)
                existing = {}

        merged = merge_into_baseline(
            existing, fresh_baseline,
            mode=args.mode,
            incremental_info=incremental_info,
        )
        write_baseline_file(merged, output_path)

        # stderr 给简要摘要（便于 Claude 和用户看）
        print(
            f"基线已写入: {output_path}\n"
            f"  文件数: {merged['summary'].get('total_files', 0)} | "
            f"函数数: {merged['summary'].get('total_functions', 0)} | "
            f"用例数: {merged['summary'].get('total_cases', 0)}",
            file=sys.stderr,
        )
        if incremental_info.get("is_incremental"):
            changed = len(incremental_info.get("changed_files", []))
            new = len(incremental_info.get("new_files", []))
            removed = len(incremental_info.get("removed_files", []))
            print(
                f"  增量: 变更 {changed} 文件 | 新增 {new} | 删除 {removed}",
                file=sys.stderr,
            )
        return

    # 调试模式：stdout 输出原始扫描结果
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
