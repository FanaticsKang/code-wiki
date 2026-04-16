#!/usr/bin/env python3
"""
analyze_function.py — 对单个函数做 AST 特征分析。

用于 Claude 在生成测试时需要快速了解某个函数的特征、适用维度、mock 建议。
scan_repo.py 是全仓库扫描，此脚本是单函数深入分析。

用法：
    python analyze_function.py <file> --function <name> [--class <ClassName>] [--language auto|python|cpp]
"""

import argparse
import ast
import json
import sys
from pathlib import Path

# 复用 scan_repo.py 的分析逻辑
sys.path.insert(0, str(Path(__file__).parent))
from scan_repo import (  # noqa: E402
    PythonAnalyzer,
    PythonFeatureDetector,
    _detect_float_type,
    _extract_signature,
    _is_stub,
)

# 尝试导入 C++ 分析器
try:
    from scan_repo import CppAnalyzer  # noqa: E402
    _CPP_AVAILABLE = True
except ImportError:
    _CPP_AVAILABLE = False


def analyze_python_function(filepath: Path, func_name: str,
                            class_name: str | None = None) -> dict | None:
    """分析 Python 函数。"""
    source = filepath.read_text(encoding="utf-8", errors="replace")
    try:
        tree = ast.parse(source, filename=str(filepath))
    except SyntaxError as e:
        print(f"语法错误: {e}", file=sys.stderr)
        return None

    func_node = _find_python_function(tree, func_name, class_name)
    if func_node is None:
        return None

    if _is_stub(func_node):
        return {
            "name": func_name,
            "is_stub": True,
            "note": "存根函数（仅 pass 或 ...），不生成测试",
        }

    detector = PythonFeatureDetector()
    detector.visit(func_node)
    has_float = _detect_float_type(func_node)

    analyzer = PythonAnalyzer()
    features = detector.features
    features["has_recursion"] = any(
        True for node in ast.walk(func_node)
        if isinstance(node, ast.Call)
        and ((isinstance(node.func, ast.Name) and node.func.id == func_name)
             or (isinstance(node.func, ast.Attribute) and node.func.attr == func_name))
    )

    return {
        "name": func_name,
        "class_name": class_name,
        "language": "python",
        "signature": _extract_signature(func_node),
        "is_async": isinstance(func_node, ast.AsyncFunctionDef),
        "line_range": [
            func_node.lineno,
            func_node.end_lineno or func_node.lineno,
        ],
        "decorators": [ast.unparse(d) for d in func_node.decorator_list],
        "features": features,
        "has_float_type": has_float,
        "dimensions": analyzer.decide_dimensions(features, has_float),
        "mocks_needed": analyzer.decide_mocks(features, class_name),
    }


def _find_python_function(tree: ast.Module, func_name: str,
                          class_name: str | None = None):
    """在 Python AST 中查找指定函数节点。"""
    if class_name:
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name == class_name:
                for child in node.body:
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        if child.name == func_name:
                            return child
        return None

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == func_name:
                return node
    return None


def analyze_cpp_function(filepath: Path, func_name: str,
                         class_name: str | None = None) -> dict | None:
    """分析 C++ 函数。"""
    if not _CPP_AVAILABLE:
        print("错误：C++ 分析需要 tree-sitter 依赖", file=sys.stderr)
        return None

    analyzer = CppAnalyzer()  # type: ignore[misc]
    # 使用 CppAnalyzer 的 extract_functions 提取所有函数，再找到目标
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        result = analyzer.extract_functions(filepath, Path(tmp))

    for fdata in result.get("functions", {}).values():
        if fdata["name"] == func_name:
            if class_name and fdata.get("class_name") != class_name:
                continue
            return {
                "name": func_name,
                "class_name": fdata.get("class_name"),
                "namespace": fdata.get("namespace"),
                "language": "cpp",
                "signature": fdata["signature"],
                "is_template": fdata.get("is_template", False),
                "is_static": fdata.get("is_static", False),
                "is_virtual": fdata.get("is_virtual", False),
                "features": fdata["features"],
                "dimensions": fdata["dimensions"],
                "mocks_needed": fdata["mocks_needed"],
            }

    return None


def main():
    parser = argparse.ArgumentParser(description="分析单个函数的 AST 特征")
    parser.add_argument("filepath", help="源文件路径")
    parser.add_argument("--function", required=True, help="函数名")
    parser.add_argument("--class", dest="class_name", default=None,
                        help="所属类名（如果是方法）")
    parser.add_argument("--language", default="auto",
                        choices=["auto", "python", "cpp"],
                        help="语言（默认 auto，从文件扩展名推断）")
    args = parser.parse_args()

    path = Path(args.filepath)
    if not path.is_file():
        print(f"错误：文件 {path} 不存在", file=sys.stderr)
        sys.exit(1)

    # 确定语言
    ext = path.suffix.lower()
    language = args.language
    if language == "auto":
        if ext in {".py"}:
            language = "python"
        elif ext in {".cpp", ".cc", ".cxx", ".h", ".hpp", ".hh", ".hxx"}:
            language = "cpp"
        else:
            print(f"错误：不支持的文件扩展名 {ext}", file=sys.stderr)
            sys.exit(1)

    # 分析
    if language == "python":
        result = analyze_python_function(path, args.function, args.class_name)
    else:
        result = analyze_cpp_function(path, args.function, args.class_name)

    if result is None:
        print(
            f"错误：未找到函数 "
            f"{args.class_name + '::' if args.class_name and language == 'cpp' else ''}"
            f"{args.class_name + '.' if args.class_name and language == 'python' else ''}"
            f"{args.function}",
            file=sys.stderr,
        )
        sys.exit(1)

    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
