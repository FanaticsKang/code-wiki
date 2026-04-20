#!/usr/bin/env python3
"""
scan_repo.py — 纯扫描器：扫描代码仓库，提取所有可测试函数（支持 Python 和 C++）。

输出包含每个函数的完整 AST 特征（features）、维度、mock 建议等原始扫描结果。
基线生成（test_cases.json）由 build_baseline.py 负责。

用法：
    python scan_repo.py <repo_root> --output .test/scan_result.json
    python scan_repo.py <repo_root> --source core,utils --output .test/scan_result.json
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

# C++ 解析（可选依赖）
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
    """判断文件是否应跳过。"""
    name = path.name
    ext = path.suffix.lower()

    if ext not in PY_EXTENSIONS and ext not in CPP_EXTENSIONS:
        return True

    if ext == ".py":
        if name.startswith("_") and name != "__init__.py":
            return True
        if name.endswith("_generated.py"):
            return True

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
            return {"error": str(e), "functions": {}, "total_funcs_found": 0}

        source_lines = source.splitlines()
        file_md5 = md5_text(source)
        rel_path = str(filepath.relative_to(repo_root))
        functions = {}
        total_funcs_found = 0

        def _process_func(func_node, class_name=None):
            nonlocal total_funcs_found
            total_funcs_found += 1

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

        return {
            "file_md5": file_md5,
            "path": rel_path,
            "functions": functions,
            "total_funcs_found": total_funcs_found,
        }

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


# Python 辅助函数

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

_CPP_DECLARATOR_WRAPPERS = {
    "pointer_declarator",
    "reference_declarator",
    "parenthesized_declarator",
}


class CppAnalyzer(LanguageAnalyzer):
    """C++ 函数提取和特征分析（基于 tree-sitter）。"""

    def __init__(self):
        if not _TS_AVAILABLE:
            raise RuntimeError(
                "C++ 扫描需要 tree-sitter 依赖。"
                "请安装: pip install tree-sitter tree-sitter-cpp"
            )
        self._language = Language(tscpp.language())
        self._parser = Parser(self._language)

    def extract_functions(self, filepath: Path, repo_root: Path) -> dict:
        source = filepath.read_text(encoding="utf-8", errors="replace")
        source_bytes = source.encode("utf-8")
        file_md5 = md5_text(source)
        rel_path = str(filepath.relative_to(repo_root))

        tree = self._parser.parse(source_bytes)
        root = tree.root_node

        functions = {}
        total_funcs_found = [0]
        self._walk_node(root, source_bytes, functions, total_funcs_found)

        return {
            "file_md5": file_md5,
            "path": rel_path,
            "functions": functions,
            "total_funcs_found": total_funcs_found[0],
        }

    def _walk_node(self, node, source_bytes: bytes,
                   functions: dict, total_funcs_found: list,
                   namespace: str = "", class_name: str | None = None):
        for child in node.children:
            if child.type == "namespace_definition":
                ns_name = self._node_text(child.child_by_field_name("name"), source_bytes)
                new_ns = f"{namespace}::{ns_name}" if namespace else ns_name
                self._walk_node(child, source_bytes, functions, total_funcs_found, new_ns, class_name)
                continue

            if child.type in ("class_specifier", "struct_specifier"):
                cn_node = child.child_by_field_name("name")
                if cn_node is None:
                    continue
                cn = self._node_text(cn_node, source_bytes)
                self._walk_node(child, source_bytes, functions, total_funcs_found, namespace, cn)
                continue

            if child.type == _CPP_TEMPLATE_DECL:
                for inner in child.children:
                    if inner.type == _CPP_FUNC_DEF:
                        self._process_function(
                            inner, source_bytes, functions, total_funcs_found,
                            namespace, class_name, is_template=True)
                    elif inner.type in (_CPP_CLASS_SPEC, _CPP_STRUCT_SPEC):
                        cn_node = inner.child_by_field_name("name")
                        if cn_node is None:
                            continue
                        cn = self._node_text(cn_node, source_bytes)
                        self._walk_node(inner, source_bytes, functions, total_funcs_found,
                                        namespace, cn)
                continue

            if child.type == _CPP_FUNC_DEF:
                self._process_function(
                    child, source_bytes, functions, total_funcs_found,
                    namespace, class_name)

            if child.children:
                self._walk_node(child, source_bytes, functions, total_funcs_found,
                                namespace, class_name)

    def _process_function(self, func_node, source_bytes: bytes,
                          functions: dict, total_funcs_found: list,
                          namespace: str, class_name: str | None,
                          is_template: bool = False):
        total_funcs_found[0] += 1

        declarator = self._unwrap_to_function_declarator(func_node, source_bytes)
        if not declarator:
            return

        func_name, qualified_class = self._extract_name_and_qualifier(
            declarator, source_bytes
        )
        if not func_name:
            return

        if func_name == "main":
            return
        if func_name.startswith("~"):
            return

        decl_text = self._node_text(declarator, source_bytes)
        if "= default" in decl_text or "= delete" in decl_text:
            return

        effective_class = qualified_class or class_name

        body_node = self._find_child(func_node, "compound_statement")
        if not body_node:
            return

        signature = self._build_signature(func_node, declarator, source_bytes)
        features = self._analyze_features(body_node, source_bytes, func_name)

        parts = []
        if namespace:
            parts.append(namespace)
        if effective_class:
            parts.append(effective_class)
        parts.append(func_name)
        qualified_name = "::".join(parts)

        dims = self.decide_dimensions(features)
        mocks = self.decide_mocks(features, effective_class)

        func_source = self._node_text(func_node, source_bytes)
        func_md5 = md5_text(func_source)

        functions[qualified_name] = {
            "name": func_name,
            "namespace": namespace or None,
            "class_name": effective_class,
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
        if node is None:
            return

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

        for child in node.children:
            self._detect_recursive(child, source_bytes, func_name, features)

    def _check_call_features(self, call_node, source_bytes: bytes,
                             features: dict, func_name: str):
        func_node = call_node.child_by_field_name("function")
        if not func_node:
            return

        call_text = self._node_text(func_node, source_bytes)

        if call_text == func_name:
            features["has_recursion"] = True

        if any(fn in call_text for fn in (
            "std::abs", "std::sqrt", "std::pow", "std::sin",
            "std::cos", "std::tan", "std::log", "std::exp",
            "std::ceil", "std::floor", "std::round",
        )):
            features["uses_stl_math"] = True

        if any(fn in call_text for fn in (
            "std::sort", "std::stable_sort", "std::partial_sort",
            "std::find", "std::find_if", "std::transform",
            "std::accumulate", "std::count", "std::remove",
        )):
            features["uses_stl_algo"] = True
            if "sort" in call_text:
                features["has_sort"] = True

        if any(fn in call_text for fn in (
            "std::fstream", "std::ifstream", "std::ofstream",
            "fopen", "fclose", "fread", "fwrite",
        )):
            features["has_file_io"] = True
            features["is_pure"] = False

        if any(fn in call_text for fn in (
            "boost::asio", "curl_", "socket", "connect", "send", "recv",
        )):
            features["has_network"] = True
            features["is_pure"] = False

        if any(fn in call_text for fn in (
            "std::make_unique", "std::make_shared",
            "std::unique_ptr", "std::shared_ptr", "std::weak_ptr",
        )):
            features["uses_smart_ptr"] = True

        if any(fn in call_text for fn in ("system", "popen", "exec")):
            features["has_subprocess"] = True
            features["is_pure"] = False

        if any(fn in call_text for fn in (
            "printf", "sprintf", "snprintf", "fprintf",
        )):
            features["has_printf"] = True

        if any(fn in call_text for fn in (
            "sqlite3_", "mysql_", "PQ", "sqlite::",
        )):
            features["has_sql_ops"] = True
            features["is_pure"] = False

        if any(fn in call_text for fn in (
            "memcpy", "strcpy", "strcat", "memmove", "strncpy",
        )):
            features["has_buffer_op"] = True

        if any(fn in call_text for fn in (
            ".substr", ".find", ".replace", ".c_str",
            ".append", ".insert", ".erase", ".compare",
        )):
            features["has_str_ops"] = True

        if any(fn in call_text for fn in (
            "push_back", "emplace_back", "insert",
        )):
            features["has_container_growth"] = True

        if "std::move" in call_text:
            features["has_move_semantics"] = True

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

    def _unwrap_to_function_declarator(self, func_node, _source_bytes: bytes):
        for child in func_node.children:
            if child.type == _CPP_FUNC_DECL:
                return child
            if child.type in _CPP_DECLARATOR_WRAPPERS:
                inner = self._peel_declarator_wrappers(child)
                if inner is not None:
                    return inner
        return None

    def _peel_declarator_wrappers(self, node):
        if node is None:
            return None
        if node.type == _CPP_FUNC_DECL:
            return node
        if node.type in _CPP_DECLARATOR_WRAPPERS:
            inner = node.child_by_field_name("declarator")
            if inner is not None:
                peeled = self._peel_declarator_wrappers(inner)
                if peeled is not None:
                    return peeled
            for child in node.children:
                peeled = self._peel_declarator_wrappers(child)
                if peeled is not None:
                    return peeled
        return None

    def _extract_name_and_qualifier(self, declarator, source_bytes: bytes):
        for child in declarator.children:
            if child.type in ("identifier", "field_identifier"):
                return self._node_text(child, source_bytes), None
            if child.type == "operator_name":
                return self._node_text(child, source_bytes), None
            if child.type == "destructor_name":
                return self._node_text(child, source_bytes), None

            if child.type == "qualified_identifier":
                return self._parse_qualified_identifier(child, source_bytes)

            if child.type == "template_function":
                for sub in child.children:
                    if sub.type in ("identifier", "field_identifier"):
                        return self._node_text(sub, source_bytes), None
                return self._node_text(child, source_bytes), None

            if child.type == _CPP_FUNC_DECL:
                return self._extract_name_and_qualifier(child, source_bytes)

        return "", None

    def _parse_qualified_identifier(self, qid_node, source_bytes: bytes):
        scope_parts: list[str] = []
        final_name = ""

        def walk(node):
            nonlocal final_name
            scope = node.child_by_field_name("scope")
            name = node.child_by_field_name("name")

            if scope is not None:
                if scope.type == "namespace_identifier":
                    scope_parts.append(self._node_text(scope, source_bytes))
                elif scope.type == "type_identifier":
                    scope_parts.append(self._node_text(scope, source_bytes))
                elif scope.type == "template_type":
                    tid = scope.child_by_field_name("name")
                    if tid is None:
                        for c in scope.children:
                            if c.type == "type_identifier":
                                tid = c
                                break
                    if tid is not None:
                        scope_parts.append(self._node_text(tid, source_bytes))
                elif scope.type == "qualified_identifier":
                    walk(scope)

            if name is not None:
                if name.type == "qualified_identifier":
                    walk(name)
                elif name.type in ("identifier", "field_identifier"):
                    final_name = self._node_text(name, source_bytes)
                elif name.type == "operator_name":
                    final_name = self._node_text(name, source_bytes)
                elif name.type == "template_function":
                    for sub in name.children:
                        if sub.type in ("identifier", "field_identifier"):
                            final_name = self._node_text(sub, source_bytes)
                            break
                    else:
                        final_name = self._node_text(name, source_bytes)
                else:
                    final_name = self._node_text(name, source_bytes)

        has_fields = (
            qid_node.child_by_field_name("name") is not None
            or qid_node.child_by_field_name("scope") is not None
        )
        if has_fields:
            walk(qid_node)
        else:
            text = self._node_text(qid_node, source_bytes)
            parts = self._split_qualified_by_scope(text)
            if parts:
                final_name = parts[-1]
                scope_parts = parts[:-1]

        qualified_class = "::".join(scope_parts) if scope_parts else None
        return final_name, qualified_class

    @staticmethod
    def _split_qualified_by_scope(text: str) -> list[str]:
        cleaned = []
        depth = 0
        for ch in text:
            if ch == "<":
                depth += 1
            elif ch == ">":
                depth = max(0, depth - 1)
            elif depth == 0:
                cleaned.append(ch)
        clean_text = "".join(cleaned)
        return [p for p in clean_text.split("::") if p]

    def _build_signature(self, func_node, declarator,
                         source_bytes: bytes) -> str:
        return_type_types = {
            "primitive_type", "qualified_identifier", "type_identifier",
            "placeholder_type_specifier", "sized_type_specifier",
            "type_descriptor", "template_type", "auto",
        }
        ret_type = ""
        for child in func_node.children:
            if child.type in return_type_types:
                ret_type = self._node_text(child, source_bytes)
                break

        outer_declarator_text = ""
        for child in func_node.children:
            if child.type == _CPP_FUNC_DECL:
                outer_declarator_text = self._node_text(child, source_bytes)
                break
            if child.type in _CPP_DECLARATOR_WRAPPERS:
                outer_declarator_text = self._node_text(child, source_bytes)
                break

        if not outer_declarator_text:
            outer_declarator_text = self._node_text(declarator, source_bytes)

        return f"{ret_type} {outer_declarator_text}".strip()


# ---------------------------------------------------------------------------
# 分析器工厂
# ---------------------------------------------------------------------------

def get_analyzer(ext: str) -> LanguageAnalyzer | None:
    if ext in PY_EXTENSIONS:
        return PythonAnalyzer()
    if ext in CPP_EXTENSIONS:
        if not _TS_AVAILABLE:
            return None
        return CppAnalyzer()
    return None


# ---------------------------------------------------------------------------
# 语言和框架检测
# ---------------------------------------------------------------------------

def detect_language_and_framework(repo_root: Path) -> dict:
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
# 测试路径计算
# ---------------------------------------------------------------------------

def _compute_test_path(source_rel_path: str) -> str | None:
    p = Path(source_rel_path)
    name = p.name
    if not name.startswith("test_"):
        name = f"test_{name}"
    return str(Path("test/generated_unit") / p.parent / name)


# ---------------------------------------------------------------------------
# 原子写入
# ---------------------------------------------------------------------------

def _write_json_atomic(data: dict, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = output_path.with_suffix(output_path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    tmp.replace(output_path)


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="扫描仓库提取可测试函数（纯扫描器，输出原始结果）",
    )
    parser.add_argument("repo_root", help="仓库根目录")
    parser.add_argument("--source", default=None,
                        help="限定扫描的目录，逗号分隔")
    parser.add_argument("--output", default=".test/scan_result.json",
                        help="输出路径（默认 .test/scan_result.json）")
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    if not repo_root.is_dir():
        print(f"错误: {repo_root} 不是有效目录", file=sys.stderr)
        sys.exit(1)

    source_dirs = None
    if args.source:
        source_dirs = [s.strip() for s in args.source.split(",") if s.strip()]

    lang_info = detect_language_and_framework(repo_root)

    if "cpp" in lang_info["languages"] and not _TS_AVAILABLE:
        print("警告: 检测到 C++ 文件但缺少 tree-sitter 依赖，"
              "C++ 文件将被跳过。安装: pip install tree-sitter tree-sitter-cpp",
              file=sys.stderr)

    files = walk_sources(repo_root, source_dirs)

    result = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "languages": lang_info["languages"],
        "test_frameworks": lang_info["test_frameworks"],
        "source_dirs": source_dirs or ["."],
        "files": {},
    }

    total_source_files = len(files)
    scanned_files = 0
    total_funcs_found = 0
    extracted_funcs = 0

    for fpath in files:
        ext = fpath.suffix.lower()
        analyzer = get_analyzer(ext)
        if analyzer is None:
            continue

        finfo = analyzer.extract_functions(fpath, repo_root)
        found = finfo.get("total_funcs_found", len(finfo.get("functions", {})))
        extracted = len(finfo.get("functions", {}))

        total_funcs_found += found
        extracted_funcs += extracted

        if finfo.get("functions"):
            rel = str(fpath.relative_to(repo_root))
            test_path = _compute_test_path(rel)
            if test_path:
                finfo["test_path"] = test_path
            result["files"][rel] = finfo
            scanned_files += 1

    skipped_files = total_source_files - scanned_files
    skipped_funcs = total_funcs_found - extracted_funcs

    result["scan_stats"] = {
        "total_source_files": total_source_files,
        "scanned_files": scanned_files,
        "skipped_files": skipped_files,
        "total_functions_found": total_funcs_found,
        "functions_extracted": extracted_funcs,
        "functions_skipped": skipped_funcs,
    }

    # 写入文件
    output_path = Path(args.output)
    _write_json_atomic(result, output_path)

    print(
        f"扫描结果已写入: {output_path}\n"
        f"  文件扫描: {scanned_files}/{total_source_files} "
        f"({round(scanned_files / total_source_files * 100, 1) if total_source_files else 0}%)\n"
        f"  函数提取: {extracted_funcs}/{total_funcs_found} "
        f"({round(extracted_funcs / total_funcs_found * 100, 1) if total_funcs_found else 0}%)",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
