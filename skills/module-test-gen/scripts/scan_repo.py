#!/usr/bin/env python3
"""
scan_repo.py — Scan a repository and output discovered modules, features, and code files.

Usage:
    python scan_repo.py <repo_root> [--language python|cpp] [--output json|yaml]

Outputs a JSON structure suitable for generating index.yml and per-module config files.
"""

import argparse
import ast
import json
import os
import sys
from pathlib import Path
from typing import Any

# Directories to always skip
SKIP_DIRS = {
    "__pycache__",
    ".git",
    ".venv",
    "venv",
    "env",
    "node_modules",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
    "dist",
    "build",
    "egg-info",
    ".eggs",
}

# Test directories to skip (we don't scan existing tests)
TEST_DIRS = {"tests", "test", "testing"}


def should_skip_dir(dirname: str) -> bool:
    """Check if a directory should be skipped during scanning."""
    lower = dirname.lower()
    if lower in SKIP_DIRS or lower in TEST_DIRS:
        return True
    if lower.startswith("."):
        return True
    if lower.endswith(".egg-info"):
        return True
    return False


def find_python_modules(repo_root: Path) -> list[dict]:
    """
    Discover Python modules in the repository.

    A module is a directory containing __init__.py, or a standalone .py file
    in the top-level source directory.

    Returns a list of dicts: [{"name": str, "path": str, "files": [str]}]
    """
    modules = []
    seen_paths = set()

    # Look for src/ layout first
    src_dir = repo_root / "src"
    search_roots = []
    if src_dir.is_dir():
        search_roots.append(src_dir)
    search_roots.append(repo_root)

    for search_root in search_roots:
        for dirpath, dirnames, filenames in os.walk(search_root):
            # Filter out directories we should skip
            dirnames[:] = [d for d in dirnames if not should_skip_dir(d)]

            rel_dir = Path(dirpath).relative_to(repo_root)

            # Check if this directory is a Python package
            if "__init__.py" in filenames:
                # Only register as module if it's a top-level package
                # (not a sub-package of an already-found module)
                is_subpackage = False
                for seen in seen_paths:
                    try:
                        rel_dir.relative_to(seen)
                        is_subpackage = True
                        break
                    except ValueError:
                        continue

                if not is_subpackage:
                    py_files = collect_py_files(Path(dirpath), repo_root)
                    if py_files:
                        module_name = rel_dir.name if rel_dir != Path(".") else repo_root.name
                        modules.append({
                            "name": module_name,
                            "path": str(rel_dir),
                            "files": py_files,
                        })
                        seen_paths.add(rel_dir)

    # If no packages found, look for standalone .py files in root
    if not modules:
        root_py = [
            f for f in os.listdir(repo_root)
            if f.endswith(".py")
            and f not in ("setup.py", "conftest.py", "manage.py")
            and not f.startswith("test_")
        ]
        if root_py:
            modules.append({
                "name": repo_root.name,
                "path": ".",
                "files": [str(Path(f)) for f in root_py],
            })

    return modules


def collect_py_files(package_dir: Path, repo_root: Path) -> list[str]:
    """Collect all .py files in a package directory, returning paths relative to repo_root."""
    py_files = []
    for dirpath, dirnames, filenames in os.walk(package_dir):
        dirnames[:] = [d for d in dirnames if not should_skip_dir(d)]
        for f in filenames:
            if f.endswith(".py") and not f.startswith("test_"):
                rel = Path(dirpath, f).relative_to(repo_root)
                py_files.append(str(rel))
    return sorted(py_files)


def extract_features_from_file(filepath: Path) -> list[dict]:
    """
    Parse a Python file and extract features (public classes, public functions).

    Returns: [{"name": str, "type": "class"|"function", "line": int}]
    """
    features = []
    try:
        source = filepath.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source, filename=str(filepath))
    except (SyntaxError, UnicodeDecodeError):
        return features

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
            docstring = ast.get_docstring(node) or ""
            features.append({
                "name": node.name,
                "type": "class",
                "line": node.lineno,
                "docstring": docstring[:200],
                "methods": [
                    m.name for m in ast.walk(node)
                    if isinstance(m, ast.FunctionDef) and not m.name.startswith("_")
                ],
            })
        elif isinstance(node, ast.FunctionDef) and not node.name.startswith("_"):
            docstring = ast.get_docstring(node) or ""
            # Collect parameter info
            args = []
            for arg in node.args.args:
                if arg.arg != "self":
                    annotation = ""
                    if arg.annotation:
                        try:
                            annotation = ast.unparse(arg.annotation)
                        except Exception:
                            pass
                    args.append({"name": arg.arg, "type": annotation})

            return_type = ""
            if node.returns:
                try:
                    return_type = ast.unparse(node.returns)
                except Exception:
                    pass

            features.append({
                "name": node.name,
                "type": "function",
                "line": node.lineno,
                "docstring": docstring[:200],
                "parameters": args,
                "return_type": return_type,
            })

    return features


def extract_imports(filepath: Path, repo_root: Path) -> list[str]:
    """
    Extract project-internal imports from a Python file.

    Returns relative file paths of imported modules within the project.
    """
    imports = []
    try:
        source = filepath.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source, filename=str(filepath))
    except (SyntaxError, UnicodeDecodeError):
        return imports

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                resolved = resolve_import(alias.name, repo_root)
                if resolved:
                    imports.append(resolved)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                resolved = resolve_import(node.module, repo_root)
                if resolved:
                    imports.append(resolved)

    return sorted(set(imports))


def resolve_import(module_name: str, repo_root: Path) -> str | None:
    """Try to resolve a dotted module name to a file path relative to repo_root."""
    parts = module_name.split(".")
    # Try as a direct file
    candidate = repo_root / Path(*parts)
    if candidate.with_suffix(".py").is_file():
        return str(candidate.with_suffix(".py").relative_to(repo_root))
    # Try as a package
    if (candidate / "__init__.py").is_file():
        return str((candidate / "__init__.py").relative_to(repo_root))
    # Try under src/
    candidate = repo_root / "src" / Path(*parts)
    if candidate.with_suffix(".py").is_file():
        return str(candidate.with_suffix(".py").relative_to(repo_root))
    if (candidate / "__init__.py").is_file():
        return str((candidate / "__init__.py").relative_to(repo_root))
    return None


def scan_module(module: dict, repo_root: Path) -> dict:
    """
    Scan a module and return its full structure with features and dependencies.
    """
    result = {
        "name": module["name"],
        "path": module["path"],
        "language": "python",
        "test_framework": "pytest",
        "features": [],
    }

    # Group features by file
    for filepath_str in module["files"]:
        filepath = repo_root / filepath_str
        if not filepath.is_file():
            continue

        file_features = extract_features_from_file(filepath)
        file_imports = extract_imports(filepath, repo_root)

        for feature in file_features:
            related_code = [filepath_str]
            # Add imported files as related code
            for imp in file_imports:
                if imp not in related_code:
                    related_code.append(imp)

            result["features"].append({
                "name": feature["name"],
                "type": feature["type"],
                "primary_file": filepath_str,
                "related_code": related_code,
                "details": feature,
            })

    return result


def main():
    parser = argparse.ArgumentParser(description="Scan a repository for testable modules")
    parser.add_argument("repo_root", help="Path to the repository root")
    parser.add_argument("--language", choices=["python", "cpp"], default="python")
    parser.add_argument("--output", choices=["json", "yaml"], default="json")
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    if not repo_root.is_dir():
        print(f"Error: {repo_root} is not a directory", file=sys.stderr)
        sys.exit(1)

    if args.language == "python":
        modules = find_python_modules(repo_root)
    else:
        print(f"Language '{args.language}' not yet supported", file=sys.stderr)
        sys.exit(1)

    results = {
        "project": repo_root.name,
        "language": args.language,
        "modules": [scan_module(m, repo_root) for m in modules],
    }

    print(json.dumps(results, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
