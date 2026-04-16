#!/usr/bin/env python3
"""
Stage 3: Locate each innovation's implementation in the code repository.

This script is a SCAFFOLD. It walks the repo, filters to code files, and
runs directed grep using the key_terms from paper_claims.json. It also
extracts candidate model-definition files (files with nn.Module subclasses
or similar) and config files.

The MATCHING (deciding which of the grep hits is actually the implementation)
is done by Claude based on this output.

Usage:
    python locate_implementation.py <repo_path> --claims paper_claims.json \
        [--out code_map.json]

Output:
    code_map.json: for each innovation, candidate file:line locations, plus
    an inventory of model files and config files for orientation.

Dependencies: standard library only.
"""

import argparse
import json
import re
import sys
from pathlib import Path

# File extensions we consider "code" for this analysis
CODE_EXTENSIONS = {
    ".py", ".ipynb", ".pyx",       # Python
    ".cc", ".cpp", ".h", ".hpp",   # C++
    ".cu",                          # CUDA
    ".rs",                          # Rust
    ".jl",                          # Julia
    ".lua",                         # Lua (torch legacy)
}

CONFIG_EXTENSIONS = {".yaml", ".yml", ".json", ".toml", ".ini", ".cfg"}

# Directories to skip (vendored deps, caches, build artifacts)
SKIP_DIRS = {
    ".git", "__pycache__", "node_modules", ".venv", "venv", "env",
    ".pytest_cache", ".mypy_cache", "build", "dist", ".tox",
    "third_party", "external", ".ipynb_checkpoints",
}


def walk_repo(repo_root: Path) -> list[Path]:
    """Walk the repo, yielding code and config files, skipping junk."""
    files = []
    for path in repo_root.rglob("*"):
        if not path.is_file():
            continue
        # skip if any parent is in SKIP_DIRS
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.suffix in CODE_EXTENSIONS or path.suffix in CONFIG_EXTENSIONS:
            files.append(path)
    return files


def find_model_files(files: list[Path]) -> list[dict]:
    """
    Heuristically identify files that define the main model(s). Signals:
    - filename contains 'model', 'modeling', 'network', 'net', 'arch'
    - file contains 'class X(nn.Module)' or 'class X(Module)' or equivalent
    """
    model_files = []
    name_patterns = re.compile(
        r"(?i)\b(model|modeling|network|arch|layer|block|module)\b"
    )
    module_class_patterns = [
        re.compile(r"class\s+\w+\s*\(\s*nn\.Module\s*\)"),
        re.compile(r"class\s+\w+\s*\(\s*Module\s*\)"),
        re.compile(r"class\s+\w+\s*\(\s*nn\.Layer\s*\)"),  # paddle
        re.compile(r"class\s+\w+\s*\(\s*hk\.Module\s*\)"),  # haiku
    ]
    for f in files:
        if f.suffix != ".py":
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue

        name_hit = bool(name_patterns.search(f.name))
        class_hits = []
        for pat in module_class_patterns:
            for m in pat.finditer(text):
                line_no = text[: m.start()].count("\n") + 1
                class_name = re.search(r"class\s+(\w+)", m.group(0))
                class_hits.append({
                    "class": class_name.group(1) if class_name else "?",
                    "line": line_no,
                })

        if class_hits or name_hit:
            model_files.append({
                "path": str(f),
                "matches_name_heuristic": name_hit,
                "nn_module_classes": class_hits,
            })

    # sort: more classes = more likely to be core model file
    model_files.sort(key=lambda x: -len(x["nn_module_classes"]))
    return model_files


def find_config_files(files: list[Path]) -> list[str]:
    """Return paths to config-like files."""
    return [str(f) for f in files if f.suffix in CONFIG_EXTENSIONS]


def find_training_files(files: list[Path]) -> list[str]:
    """Find likely training entry points."""
    name_patterns = re.compile(
        r"(?i)\b(train|trainer|finetune|fit|optim|loss)\b"
    )
    results = []
    for f in files:
        if f.suffix == ".py" and name_patterns.search(f.name):
            results.append(str(f))
    return results


def grep_term(files: list[Path], term: str, max_hits: int = 50) -> list[dict]:
    """
    Grep for a term across code files. Returns list of {path, line, snippet}.
    Case-insensitive, matches term as substring OR as whole-word.
    """
    results = []
    # Build both a literal substring pattern and a word-boundary pattern
    literal = re.compile(re.escape(term), re.IGNORECASE)
    # whole-word/identifier version: treats _ as word char
    # We also allow matching across camelCase by using the raw term
    for f in files:
        if f.suffix not in CODE_EXTENSIONS:
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        for m in literal.finditer(text):
            line_no = text[: m.start()].count("\n") + 1
            # snippet: the full line
            line_start = text.rfind("\n", 0, m.start()) + 1
            line_end = text.find("\n", m.end())
            if line_end == -1:
                line_end = len(text)
            snippet = text[line_start:line_end].strip()
            results.append({
                "path": str(f),
                "line": line_no,
                "snippet": snippet[:200],
            })
            if len(results) >= max_hits:
                return results
    return results


def locate_innovation(
    innovation: dict,
    files: list[Path],
) -> dict:
    """For one innovation, run grep for each key_term and collect hits."""
    key_terms = innovation.get("key_terms", [])
    name = innovation.get("name", "")

    hits_by_term: dict[str, list[dict]] = {}
    for term in key_terms:
        if not term.strip():
            continue
        hits = grep_term(files, term.strip(), max_hits=30)
        hits_by_term[term] = hits

    # Also grep for the innovation's name itself
    if name:
        hits_by_term[f"(name) {name}"] = grep_term(files, name, max_hits=10)

    return {
        "id": innovation.get("id"),
        "name": name,
        "key_terms_searched": key_terms,
        "hits_by_term": hits_by_term,
        "instructions_for_claude": (
            "Review the hits above. For each innovation, identify the most "
            "likely file:line that implements it. Be discerning: many hits "
            "will be imports, comments, tests, or unrelated uses of the "
            "term. The implementation is usually in a nn.Module subclass "
            "(see model_files) or a training/loss function (see "
            "training_files). If no hits look like the real implementation, "
            "try synonyms, look at imports in the top model files, and/or "
            "report the innovation as 'not found in public code'."
        ),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", type=Path, help="Path to code repository root")
    parser.add_argument(
        "--claims",
        type=Path,
        required=True,
        help="Path to paper_claims.json from Stage 1",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("code_map.json"),
    )
    args = parser.parse_args()

    if not args.repo.exists() or not args.repo.is_dir():
        print(f"ERROR: {args.repo} is not a directory", file=sys.stderr)
        sys.exit(1)

    if not args.claims.exists():
        print(f"ERROR: {args.claims} not found. Run Stage 1 first.", file=sys.stderr)
        sys.exit(1)

    claims = json.loads(args.claims.read_text())
    innovations = claims.get("innovations", [])
    if not innovations:
        print("ERROR: no innovations found in claims file. Curate it first.",
              file=sys.stderr)
        sys.exit(1)

    print(f"Walking {args.repo}...", file=sys.stderr)
    files = walk_repo(args.repo)
    print(f"Found {len(files)} code/config files", file=sys.stderr)

    model_files = find_model_files(files)
    config_files = find_config_files(files)
    training_files = find_training_files(files)
    print(f"  {len(model_files)} model files, {len(config_files)} configs, "
          f"{len(training_files)} training files", file=sys.stderr)

    result = {
        "repo_path": str(args.repo),
        "repo_inventory": {
            "total_files": len(files),
            "model_files": model_files[:20],  # top 20
            "config_files": config_files[:20],
            "training_files": training_files[:20],
        },
        "innovations": [
            locate_innovation(inn, files) for inn in innovations
        ],
        "next_steps_for_claude": (
            "1. For each innovation: pick the top 1-3 hits that look like "
            "the real implementation. Verify by reading the surrounding "
            "code — an implementation should be a nn.Module subclass or a "
            "forward/loss function, not just a mention in a comment. "
            "2. Update this JSON with a 'resolved_location' field per "
            "innovation: {file, start_line, end_line, reason}. "
            "3. For any innovation you can't locate, note what you tried "
            "and mark it as unresolved."
        ),
    }

    args.out.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    print(f"Wrote {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
