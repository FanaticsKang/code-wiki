#!/usr/bin/env python3
"""
analyze_function.py — 对单个函数做 AST 特征分析。

用于 Claude 在生成测试时需要快速了解某个函数的特征、适用维度、mock 建议。
scan_repo.py 是全仓库扫描，此脚本是单函数深入分析。

用法：
    python analyze_function.py <file.py> --function <name> [--class <ClassName>]
"""

import argparse
import ast
import json
import sys
from pathlib import Path

# 复用 scan_repo.py 的分析逻辑
sys.path.insert(0, str(Path(__file__).parent))
from scan_repo import (  # noqa: E402
    FeatureDetector,
    detect_float_type,
    decide_dimensions,
    decide_mocks,
    extract_signature,
    is_stub,
)


def find_function(
    tree: ast.Module,
    func_name: str,
    class_name: str | None = None,
):
    """在 AST 中查找指定函数节点。"""
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


def main():
    parser = argparse.ArgumentParser(description="分析单个函数的 AST 特征")
    parser.add_argument("filepath", help="Python 源文件路径")
    parser.add_argument("--function", required=True, help="函数名")
    parser.add_argument("--class", dest="class_name", default=None,
                        help="所属类名（如果是方法）")
    args = parser.parse_args()

    path = Path(args.filepath)
    if not path.is_file():
        print(f"错误：文件 {path} 不存在", file=sys.stderr)
        sys.exit(1)

    source = path.read_text(encoding="utf-8", errors="replace")
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as e:
        print(f"语法错误: {e}", file=sys.stderr)
        sys.exit(1)

    func_node = find_function(tree, args.function, args.class_name)
    if func_node is None:
        print(
            f"错误：未找到函数 "
            f"{args.class_name + '.' if args.class_name else ''}{args.function}",
            file=sys.stderr,
        )
        sys.exit(1)

    if is_stub(func_node):
        print(json.dumps({
            "name": args.function,
            "is_stub": True,
            "note": "存根函数（仅 pass 或 ...），不生成测试",
        }, indent=2, ensure_ascii=False))
        return

    detector = FeatureDetector()
    detector.visit(func_node)
    has_float = detect_float_type(func_node)

    result = {
        "name": args.function,
        "class_name": args.class_name,
        "signature": extract_signature(func_node),
        "is_async": isinstance(func_node, ast.AsyncFunctionDef),
        "line_range": [
            func_node.lineno,
            func_node.end_lineno or func_node.lineno,
        ],
        "decorators": [
            ast.unparse(d) for d in func_node.decorator_list
        ],
        "features": detector.features,
        "has_float_type": has_float,
        "dimensions": decide_dimensions(detector.features, has_float),
        "mocks_needed": decide_mocks(detector.features, args.class_name),
    }

    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
