#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scan.py —— code-wiki skill 的仓库扫描器

职责（这个脚本本身不读代码、不理解代码）：
  1. 遍历代码仓库，根据扩展名和 .gitignore 过滤出源码文件
  2. 为每个文件计算内容哈希，和上次的状态对比，找出：新增 / 修改 / 未变 / 已删除
  3. 维护 .code-wiki/state.json，记录每个文件的哈希、行数、上次处理时间
  4. 输出"待处理文件清单"供 LLM 逐个消化
  5. 提供 --next / --mark-done 等子命令，支持 LLM 按步骤推进

用法示例：
  python .code-wiki/scan.py init                 # 首次初始化，生成扫描清单
  python .code-wiki/scan.py init --folder=core/  # 只扫描 core/ 目录
  python .code-wiki/scan.py plan                 # 查看当前的待处理清单
  python .code-wiki/scan.py plan --folder=core/  # 只看 core/ 下的待处理文件
  python .code-wiki/scan.py next                 # 拿下一个待处理文件的路径
  python .code-wiki/scan.py next --folder=core/  # 拿 core/ 下下一个待处理文件
  python .code-wiki/scan.py next-folder          # 拿当前最浅文件夹下所有待处理文件
  python .code-wiki/scan.py next-folder --folder=core/dag  # 拿 core/dag 下所有待处理文件
  python .code-wiki/scan.py mark-done <file>     # 标记一个文件处理完毕
  python .code-wiki/scan.py status               # 看整体进度
  python .code-wiki/scan.py rescan               # 重新对比仓库和 state，刷新清单

所有路径都相对于仓库根目录（即脚本所在的 .code-wiki 的父目录）。
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Iterable


# ---------- 配置 ----------

# 通用的源码扩展名。不追求穷尽，够用就行；不够用时可以在
# .code-wiki/config.json 的 "extra_extensions" 里补。
DEFAULT_SOURCE_EXTS = {
    # 主流后端 / 系统
    ".py", ".pyi", ".rb", ".php", ".java", ".kt", ".kts", ".scala", ".groovy",
    ".go", ".rs", ".c", ".h", ".cc", ".cpp", ".cxx", ".hpp", ".hh", ".hxx",
    ".cs", ".fs", ".vb", ".swift", ".m", ".mm", ".dart", ".ex", ".exs",
    ".erl", ".hrl", ".clj", ".cljs", ".cljc", ".lua", ".pl", ".pm", ".r",
    ".jl", ".nim", ".zig", ".d",
    # 前端 / 脚本
    ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".vue", ".svelte",
    ".html", ".htm", ".css", ".scss", ".sass", ".less", ".styl",
    # Shell / 构建 / 配置即代码
    ".sh", ".bash", ".zsh", ".fish", ".ps1", ".bat", ".cmd",
    ".cmake", ".mk", ".make", ".gradle", ".sbt",
    # 查询 / 数据处理
    ".sql", ".graphql", ".gql", ".proto", ".thrift", ".avsc",
    # 其他
    ".tf", ".hcl",
}

# 无条件排除的目录名（无论在哪一层）。
DEFAULT_EXCLUDE_DIRS = {
    ".git", ".hg", ".svn", ".idea", ".vscode", ".vs",
    "node_modules", "bower_components", "vendor", "third_party",
    "dist", "build", "out", "target", "bin", "obj",
    ".next", ".nuxt", ".svelte-kit", ".turbo", ".cache",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".tox",
    ".venv", "venv", "env", ".env",
    "coverage", ".nyc_output",
    "wiki",            # 不扫描 wiki 自身
    ".code-wiki",      # 也不扫描脚本和状态
}

# 排除的具体文件模式（相对路径的 glob）。
DEFAULT_EXCLUDE_GLOBS = [
    "**/*.min.js", "**/*.min.css", "**/*.map",
    "**/package-lock.json", "**/yarn.lock", "**/pnpm-lock.yaml",
    "**/poetry.lock", "**/Pipfile.lock", "**/uv.lock",
    "**/Cargo.lock", "**/go.sum", "**/composer.lock",
    "**/*.snap",
]

# 超过这个行数的文件算"大文件"，清单里会给出标记提示 LLM 分批处理。
LARGE_FILE_LINES = 800

MAX_HASH_BYTES = 32 * 1024 * 1024  # 超过 32MB 的文件就跳过读取，视作二进制/数据文件


# ---------- 数据结构 ----------

@dataclass
class FileRecord:
    path: str                  # 相对仓库根的路径（正斜杠）
    size: int
    lines: int
    sha1: str
    status: str = "pending"    # pending | done | skipped
    last_scanned: str = ""     # ISO 时间，mark-done 时写入
    note: str = ""             # LLM 可以在 mark-done 时附注（比如 "样板代码，极简页"）


@dataclass
class State:
    repo_root: str
    created_at: str
    updated_at: str
    files: dict[str, FileRecord] = field(default_factory=dict)

    def to_json(self) -> dict:
        return {
            "repo_root": self.repo_root,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "files": {p: asdict(r) for p, r in self.files.items()},
        }

    @classmethod
    def from_json(cls, data: dict) -> "State":
        files = {p: FileRecord(**r) for p, r in data.get("files", {}).items()}
        return cls(
            repo_root=data.get("repo_root", ""),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
            files=files,
        )


# ---------- 路径 / IO ----------

def find_repo_root(script_path: Path) -> Path:
    """脚本放在 <repo>/.code-wiki/scan.py，所以 repo root 是脚本的祖父目录。"""
    return script_path.resolve().parent.parent


def wiki_dirs(repo_root: Path) -> tuple[Path, Path, Path]:
    wiki = repo_root / "wiki"
    code_wiki = repo_root / ".code-wiki"
    state_file = code_wiki / "state.json"
    return wiki, code_wiki, state_file


def load_state(state_file: Path, repo_root: Path) -> State:
    if state_file.exists():
        try:
            return State.from_json(json.loads(state_file.read_text(encoding="utf-8")))
        except Exception as e:
            print(f"[warn] state.json 损坏，重建一个: {e}", file=sys.stderr)
    now = datetime.now().isoformat(timespec="seconds")
    return State(repo_root=str(repo_root), created_at=now, updated_at=now)


def save_state(state: State, state_file: Path) -> None:
    state.updated_at = datetime.now().isoformat(timespec="seconds")
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(
        json.dumps(state.to_json(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_config(code_wiki_dir: Path) -> dict:
    """可选的 config.json，允许用户追加扩展名、排除项、包含项。"""
    cfg_file = code_wiki_dir / "config.json"
    if not cfg_file.exists():
        return {}
    try:
        return json.loads(cfg_file.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[warn] config.json 解析失败，忽略: {e}", file=sys.stderr)
        return {}


# ---------- .gitignore 支持（简版） ----------

def load_gitignore_patterns(repo_root: Path) -> list[str]:
    """简化版 .gitignore 读取：只读仓库根部的 .gitignore，不递归，不处理否定规则。
    想要更严格的过滤，请在 config.json 的 extra_exclude_globs 里补。"""
    gi = repo_root / ".gitignore"
    if not gi.exists():
        return []
    patterns: list[str] = []
    for line in gi.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("!"):
            continue
        patterns.append(line)
    return patterns


def match_any_glob(rel_path: str, patterns: Iterable[str]) -> bool:
    for pat in patterns:
        # 统一成 posix 风格
        if fnmatch.fnmatch(rel_path, pat):
            return True
        # 允许目录级 glob（用户在 .gitignore 写 "build/" 之类）
        if pat.endswith("/") and (rel_path + "/").startswith(pat):
            return True
        # 允许 "**/foo" 风格
        if "**" in pat and fnmatch.fnmatch(rel_path, pat):
            return True
    return False


# ---------- 扫描 ----------

def iter_source_files(repo_root: Path, config: dict, folder: str | None = None, file: str | None = None) -> Iterable[Path]:
    exts = set(DEFAULT_SOURCE_EXTS)
    exts.update(config.get("extra_extensions", []))

    exclude_dirs = set(DEFAULT_EXCLUDE_DIRS)
    exclude_dirs.update(config.get("extra_exclude_dirs", []))

    exclude_globs = list(DEFAULT_EXCLUDE_GLOBS)
    exclude_globs.extend(config.get("extra_exclude_globs", []))
    exclude_globs.extend(load_gitignore_patterns(repo_root))

    include_globs = config.get("include_only_globs", [])  # 可选白名单

    for dirpath, dirnames, filenames in os.walk(repo_root):
        # 原地裁剪目录，避免进入排除的子树
        dirnames[:] = [d for d in dirnames if d not in exclude_dirs]

        for name in filenames:
            p = Path(dirpath) / name
            rel = p.relative_to(repo_root).as_posix()

            # 定向过滤（--folder / --file）
            if not matches_target(rel, folder, file):
                continue
            # 扩展名过滤
            if p.suffix.lower() not in exts:
                continue
            # 排除 glob
            if match_any_glob(rel, exclude_globs):
                continue
            # 白名单（如果配置了）
            if include_globs and not any(fnmatch.fnmatch(rel, g) for g in include_globs):
                continue
            # 大小保护
            try:
                if p.stat().st_size > MAX_HASH_BYTES:
                    continue
            except OSError:
                continue

            yield p


def hash_and_count(p: Path) -> tuple[str, int, int]:
    h = hashlib.sha1()
    size = 0
    lines = 0
    try:
        with p.open("rb") as f:
            while True:
                chunk = f.read(65536)
                if not chunk:
                    break
                h.update(chunk)
                size += len(chunk)
                lines += chunk.count(b"\n")
    except OSError as e:
        print(f"[warn] 读取失败 {p}: {e}", file=sys.stderr)
        return "", 0, 0
    return h.hexdigest(), size, lines


def rescan(state: State, repo_root: Path, config: dict, folder: str | None = None, file: str | None = None) -> dict:
    """刷新 state：返回本次差异摘要。"""
    seen: set[str] = set()
    new_files: list[str] = []
    changed: list[str] = []
    unchanged: list[str] = []
    for p in iter_source_files(repo_root, config, folder=folder, file=file):
        rel = p.relative_to(repo_root).as_posix()
        seen.add(rel)
        sha, size, lines = hash_and_count(p)
        if not sha:
            continue
        old = state.files.get(rel)
        if old is None:
            state.files[rel] = FileRecord(path=rel, size=size, lines=lines, sha1=sha, status="pending")
            new_files.append(rel)
        elif old.sha1 != sha:
            old.sha1 = sha
            old.size = size
            old.lines = lines
            old.status = "pending"  # 改过的文件重新回到待处理
            changed.append(rel)
        else:
            unchanged.append(rel)

    # 找出已经从仓库里删掉的文件
    deleted = [p for p in list(state.files.keys()) if p not in seen]
    for p in deleted:
        state.files.pop(p, None)

    return {
        "new": new_files,
        "changed": changed,
        "unchanged_count": len(unchanged),
        "deleted": deleted,
        "total": len(state.files),
    }


# ---------- 命令 ----------

def cmd_init(args, state: State, repo_root: Path, state_file: Path, config: dict) -> int:
    wiki, code_wiki, _ = wiki_dirs(repo_root)
    wiki.mkdir(parents=True, exist_ok=True)
    (wiki / "files").mkdir(exist_ok=True)
    (wiki / "modules").mkdir(exist_ok=True)
    (wiki / "concepts").mkdir(exist_ok=True)
    (wiki / "algorithm").mkdir(exist_ok=True)
    code_wiki.mkdir(parents=True, exist_ok=True)

    diff = rescan(state, repo_root, config, folder=getattr(args, "folder", None), file=getattr(args, "file", None))
    save_state(state, state_file)

    print(f"[init] 仓库根目录: {repo_root}")
    print(f"[init] 发现源码文件: {diff['total']}")
    print(f"[init]   新增: {len(diff['new'])}")
    print(f"[init]   变更: {len(diff['changed'])}")
    print(f"[init]   未变: {diff['unchanged_count']}")
    if diff["deleted"]:
        print(f"[init]   移除: {len(diff['deleted'])}")
    print(f"[init] wiki 目录: {wiki}")
    print(f"[init] 状态文件: {state_file}")
    return 0


def cmd_rescan(args, state: State, repo_root: Path, state_file: Path, config: dict) -> int:
    diff = rescan(state, repo_root, config, folder=getattr(args, "folder", None), file=getattr(args, "file", None))
    save_state(state, state_file)
    print(f"[rescan] 新增 {len(diff['new'])} / 变更 {len(diff['changed'])} / "
          f"未变 {diff['unchanged_count']} / 删除 {len(diff['deleted'])} / 共 {diff['total']}")
    for p in diff["new"][:20]:
        print(f"  + {p}")
    for p in diff["changed"][:20]:
        print(f"  ~ {p}")
    for p in diff["deleted"][:20]:
        print(f"  - {p}")
    return 0


def matches_target(rel_path: str, folder: str | None, file: str | None) -> bool:
    """检查相对路径是否匹配指定的 folder 或 file 过滤条件。"""
    if folder is not None:
        folder = folder.strip("/")
        return rel_path.startswith(folder + "/") or rel_path == folder
    if file is not None:
        file = file.strip("/")
        return rel_path == file
    return True


def _sort_key(rec: FileRecord) -> tuple:
    """排序策略：
       1) 路径浅的先来（根目录的入口文件通常更重要）
       2) 然后按路径字典序
       保证确定性，同时让 LLM 先接触全景性高的文件。"""
    depth = rec.path.count("/")
    return (depth, rec.path)


def pending_list(state: State, folder: str | None = None, file: str | None = None) -> list[FileRecord]:
    return sorted(
        [r for r in state.files.values()
         if r.status == "pending" and matches_target(r.path, folder, file)],
        key=_sort_key,
    )


def cmd_plan(args, state: State, repo_root: Path, state_file: Path, config: dict) -> int:
    folder = getattr(args, "folder", None)
    file = getattr(args, "file", None)
    pending = pending_list(state, folder=folder, file=file)
    total = len(state.files)
    done = sum(1 for r in state.files.values() if r.status == "done")
    skipped = sum(1 for r in state.files.values() if r.status == "skipped")
    filter_desc = ""
    if folder:
        filter_desc = f" (过滤: --folder={folder})"
    elif file:
        filter_desc = f" (过滤: --file={file})"
    print(f"[plan] 总计 {total} 文件 | 已处理 {done} | 跳过 {skipped} | 待处理 {len(pending)}{filter_desc}")
    limit = args.limit or 50
    print(f"[plan] 下面列出前 {min(limit, len(pending))} 个待处理文件（按路径深度+字典序）:")
    for r in pending[:limit]:
        flag = "  [LARGE]" if r.lines >= LARGE_FILE_LINES else ""
        print(f"  - {r.path}  ({r.lines} 行, {r.size} B){flag}")
    if len(pending) > limit:
        print(f"  ... 还有 {len(pending) - limit} 个未列出")
    return 0


def cmd_next(args, state: State, repo_root: Path, state_file: Path, config: dict) -> int:
    folder = getattr(args, "folder", None)
    file = getattr(args, "file", None)
    pending = pending_list(state, folder=folder, file=file)
    if not pending:
        print("[next] 没有待处理文件了。所有文件都已处理或跳过。")
        return 0
    r = pending[0]
    flag = "LARGE" if r.lines >= LARGE_FILE_LINES else "normal"
    # 输出一行机器可读 + 几行人读信息
    print(f"NEXT_FILE: {r.path}")
    print(f"  size={r.size} lines={r.lines} flag={flag}")
    print(f"  abs={repo_root / r.path}")
    if r.lines >= LARGE_FILE_LINES:
        print("  提示: 这是大文件，请按 SKILL.md 中的分批策略处理——先骨架扫描再分段细读。")
    return 0


def _parent_dir(path: str) -> str:
    """获取文件所在的目录路径（相对仓库根）。根目录文件返回空字符串。"""
    parts = path.rsplit("/", 1)
    return parts[0] if len(parts) > 1 else ""


def cmd_next_folder(args, state: State, repo_root: Path, state_file: Path, config: dict) -> int:
    """返回当前最浅文件夹下所有待处理文件，或指定 --folder / --file 时的匹配文件。"""
    folder_filter = getattr(args, "folder", None)
    file_filter = getattr(args, "file", None)
    pending = pending_list(state, folder=folder_filter, file=file_filter)
    if not pending:
        filter_desc = ""
        if folder_filter:
            filter_desc = f" (--folder={folder_filter})"
        elif file_filter:
            filter_desc = f" (--file={file_filter})"
        print(f"[next-folder] 没有匹配的待处理文件{filter_desc}。")
        return 0

    # 如果指定了 --folder，直接使用该文件夹；否则自动检测最浅文件夹
    if folder_filter:
        folder = folder_filter.strip("/")
    elif file_filter:
        # --file 模式：按文件精确匹配，放在其父目录的上下文中
        folder = _parent_dir(pending[0].path)
    else:
        folder = _parent_dir(pending[0].path)

    # 收集该文件夹下所有待处理文件
    if folder_filter:
        folder_files = pending
    else:
        folder_files = [r for r in pending if _parent_dir(r.path) == folder]

    batch_size = config.get("batch_size", args.batch_size)
    batch = folder_files[:batch_size]

    folder_display = folder if folder else "(根目录)"
    print(f"NEXT_FOLDER: {folder_display}")
    print(f"  文件夹内待处理: {len(folder_files)} | 本次返回: {len(batch)} | batch_size={batch_size}")
    print(f"  abs_base={repo_root / folder if folder else repo_root}")
    print()
    for r in batch:
        flag = "LARGE" if r.lines >= LARGE_FILE_LINES else "normal"
        print(f"  {r.path}  lines={r.lines} size={r.size} flag={flag}")
    return 0


def _files_page_path(repo_root: Path, file_path: str) -> Path:
    """计算源码文件对应的 wiki files 页路径"""
    # 去掉扩展名，/ 替换为 __
    stem = file_path.rsplit('.', 1)[0] if '.' in file_path else file_path
    page_name = stem.replace('/', '__') + '.md'
    return repo_root / 'wiki' / 'files' / page_name


def cmd_mark_done(args, state: State, repo_root: Path, state_file: Path, config: dict) -> int:
    target = args.file.replace("\\", "/")
    # 允许传绝对路径
    if os.path.isabs(target):
        try:
            target = str(Path(target).resolve().relative_to(repo_root)).replace("\\", "/")
        except ValueError:
            print(f"[mark-done] 路径不在仓库内: {args.file}", file=sys.stderr)
            return 2
    rec = state.files.get(target)
    if rec is None:
        print(f"[mark-done] 未知文件: {target}", file=sys.stderr)
        return 2
    # 验证 files 页存在（skip 模式不要求）
    if not args.skip:
        expected_page = _files_page_path(repo_root, target)
        if not expected_page.exists():
            print(f"[mark-done] 错误: files 页不存在: {expected_page}", file=sys.stderr)
            print(f"[mark-done] 请先为 {target} 创建 wiki 页面", file=sys.stderr)
            return 2
    rec.status = "skipped" if args.skip else "done"
    rec.last_scanned = datetime.now().isoformat(timespec="seconds")
    if args.note:
        rec.note = args.note
    save_state(state, state_file)
    print(f"[mark-done] {target} -> {rec.status}")
    return 0


def cmd_status(args, state: State, repo_root: Path, state_file: Path, config: dict) -> int:
    total = len(state.files)
    done = sum(1 for r in state.files.values() if r.status == "done")
    skipped = sum(1 for r in state.files.values() if r.status == "skipped")
    pending = total - done - skipped
    pct = (done + skipped) / total * 100 if total else 0.0
    print(f"[status] 总 {total} | 完成 {done} | 跳过 {skipped} | 待处理 {pending} | 进度 {pct:.1f}%")
    if total:
        large = [r for r in state.files.values() if r.lines >= LARGE_FILE_LINES]
        print(f"[status] 大文件数量（>= {LARGE_FILE_LINES} 行）: {len(large)}")
    return 0


# ---------- 入口 ----------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="code-wiki skill 的仓库扫描器")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_init = sub.add_parser("init", help="首次初始化：创建 wiki 骨架，扫描全仓库生成待处理清单")
    p_init.add_argument("--folder", default=None, help="只扫描指定目录下的源文件")
    p_init.add_argument("--file", default=None, help="只扫描指定的源文件")
    p_rescan = sub.add_parser("rescan", help="重新扫描仓库，和 state 对比，刷新清单")
    p_rescan.add_argument("--folder", default=None, help="只重新扫描指定目录")
    p_rescan.add_argument("--file", default=None, help="只重新扫描指定文件")

    p_plan = sub.add_parser("plan", help="查看当前待处理清单")
    p_plan.add_argument("--limit", type=int, default=50, help="最多列出多少条")
    p_plan.add_argument("--folder", default=None, help="只列出指定目录下的待处理文件")
    p_plan.add_argument("--file", default=None, help="只列出指定文件")

    p_next = sub.add_parser("next", help="拿下一个待处理文件")
    p_next.add_argument("--folder", default=None, help="只在指定目录下取下一个")
    p_next.add_argument("--file", default=None, help="取指定的文件")

    p_nf = sub.add_parser("next-folder", help="拿当前最浅文件夹下所有待处理文件")
    p_nf.add_argument("--batch-size", type=int, default=10, help="每批最多返回多少个文件（默认 10，可被 config.json 覆盖）")
    p_nf.add_argument("--folder", default=None, help="只取指定目录下的待处理文件")
    p_nf.add_argument("--file", default=None, help="只取指定文件")

    p_md = sub.add_parser("mark-done", help="标记一个文件已处理完毕")
    p_md.add_argument("file", help="文件路径（相对仓库根或绝对路径）")
    p_md.add_argument("--skip", action="store_true", help="标记为 skipped 而不是 done")
    p_md.add_argument("--note", default="", help="附注（例如 '样板代码，极简页'）")

    sub.add_parser("status", help="查看整体进度")
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    script_path = Path(__file__)
    repo_root = find_repo_root(script_path)
    _, code_wiki, state_file = wiki_dirs(repo_root)
    config = load_config(code_wiki)
    state = load_state(state_file, repo_root)

    dispatch = {
        "init": cmd_init,
        "rescan": cmd_rescan,
        "plan": cmd_plan,
        "next": cmd_next,
        "next-folder": cmd_next_folder,
        "mark-done": cmd_mark_done,
        "status": cmd_status,
    }
    return dispatch[args.cmd](args, state, repo_root, state_file, config)


if __name__ == "__main__":
    sys.exit(main())
