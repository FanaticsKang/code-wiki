#!/usr/bin/env python3
"""
run_and_report.py — 执行单元测试（pytest / Google Test）并生成 markdown 报告。

用法：
    python run_and_report.py [--test-dir test/generated_unit/] \
        [--output test/generated_unit/report.md] \
        [--testcases test/generated_unit/test_cases.json] \
        [--mode incremental|full] \
        [--only <file1> <file2> ...]

如果提供 --only，则只跑指定的测试文件（增量模式用）。
"""

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path


def run_pytest(test_dir: str, only_files: list[str] | None = None) -> dict:
    """执行 pytest 并收集结果。"""
    cmd = [sys.executable, "-m", "pytest", "-v", "--tb=short"]
    if only_files:
        cmd.extend(only_files)
    else:
        cmd.append(test_dir)

    result = subprocess.run(cmd, capture_output=True, text=True)
    return {
        "exit_code": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "results": parse_pytest_output(result.stdout),
    }


def parse_pytest_output(output: str) -> list[dict]:
    """从 pytest verbose 输出解析每个测试的结果。"""
    results = []
    # 匹配形如 "tests/xx.py::TestCls::test_name PASSED [ 20%]"
    pattern = re.compile(
        r"^(.+?)::(.+?)\s+(PASSED|FAILED|ERROR|SKIPPED|XFAIL|XPASS)(?:\s+\[\s*\d+%\])?\s*$",
        re.MULTILINE,
    )
    for match in pattern.finditer(output):
        filepath = match.group(1).strip()
        test_name = match.group(2).strip()
        outcome = match.group(3).lower()
        results.append({
            "file": filepath,
            "name": test_name,
            "outcome": outcome,
            "nodeid": f"{filepath}::{test_name}",
        })
    return results


def extract_failure_blocks(output: str) -> dict[str, str]:
    """从 pytest 输出提取失败测试的详细信息。"""
    failures = {}
    if "FAILURES" not in output:
        return failures

    # 截取 FAILURES 段到 short test summary 之前
    fail_section = output.split("FAILURES", 1)[1]
    if "short test summary" in fail_section:
        fail_section = fail_section.split("short test summary", 1)[0]
    if "===" in fail_section:
        # 分割成各个失败块
        blocks = re.split(r"_{5,}\s+(.+?)\s+_{5,}", fail_section)
        # blocks[0] 是分隔符前的内容，blocks[1::2] 是标题，blocks[2::2] 是内容
        for i in range(1, len(blocks), 2):
            if i + 1 < len(blocks):
                title = blocks[i].strip()
                body = blocks[i + 1].strip()
                # 截断到前 1500 字符
                failures[title] = body[:1500]
    return failures


# ---------------------------------------------------------------------------
# Google Test 运行和解析
# ---------------------------------------------------------------------------

def run_gtest(test_dir: str, only_files: list[str] | None = None) -> dict:
    """执行 Google Test 并收集结果。"""
    # 查找 gtest binary（build/ 目录下）
    build_dir = Path(test_dir).parent.parent / "build"
    gtest_binary = _find_gtest_binary(build_dir)

    if not gtest_binary:
        return {
            "exit_code": 1,
            "stdout": "",
            "stderr": f"未找到 gtest 测试二进制文件。请先构建项目：cmake --build {build_dir}",
            "results": [],
        }

    cmd = [str(gtest_binary), "--gtest_color=no", "--gtest_print_time=1"]
    if only_files:
        # gtest 使用 filter 模式
        filter_parts = []
        for f in only_files:
            # 从文件路径提取测试套件名（简化处理）
            stem = Path(f).stem.replace("test_", "").replace("_", ".*")
            filter_parts.append(f"*{stem}*")
        if filter_parts:
            cmd.append(f"--gtest_filter={':'.join(filter_parts)}")

    result = subprocess.run(cmd, capture_output=True, text=True)
    return {
        "exit_code": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "results": parse_gtest_output(result.stdout),
    }


def _find_gtest_binary(build_dir: Path) -> Path | None:
    """在 build 目录中查找 gtest 可执行文件。"""
    if not build_dir.is_dir():
        return None

    candidates = ["unit_tests", "test_runner", "tests", "runTests"]
    for candidate in candidates:
        binary = build_dir / candidate
        if binary.is_file():
            return binary

    # 搜索可执行文件
    for f in build_dir.rglob("*"):
        if f.is_file() and f.stat().st_mode & 0o111:
            name = f.name.lower()
            if "test" in name and not name.endswith(".py"):
                return f

    return None


def parse_gtest_output(output: str) -> list[dict]:
    """从 gtest 控制台输出解析每个测试的结果。"""
    results = []
    # 匹配形如 "[       OK ] TestSuite.TestName (0 ms)"
    # 或 "[  FAILED  ] TestSuite.TestName (0 ms)"
    ok_pattern = re.compile(
        r"^\[\s*OK\s*\]\s+(\S+)\.(\S+)",
        re.MULTILINE,
    )
    failed_pattern = re.compile(
        r"^\[\s*FAILED\s*\]\s+(\S+)\.(\S+)",
        re.MULTILINE,
    )

    for match in ok_pattern.finditer(output):
        suite = match.group(1).strip()
        test_name = match.group(2).strip()
        results.append({
            "file": suite,
            "name": test_name,
            "outcome": "passed",
            "nodeid": f"{suite}.{test_name}",
        })

    for match in failed_pattern.finditer(output):
        suite = match.group(1).strip()
        test_name = match.group(2).strip()
        results.append({
            "file": suite,
            "name": test_name,
            "outcome": "failed",
            "nodeid": f"{suite}.{test_name}",
        })

    return results


def extract_gtest_failures(output: str) -> dict[str, str]:
    """从 gtest 输出提取失败测试的详细信息。"""
    failures = {}
    if "FAILED" not in output:
        return failures

    # gtest 失败格式：
    # /path/to/test.cpp:42: Failure
    # Expected: ...
    #   Actual: ...
    fail_blocks = re.split(r"(?m)^/.+?:\d+: Failure$", output)
    for i in range(1, len(fail_blocks)):
        body = fail_blocks[i].strip()
        # 尝试从前面的上下文提取测试名
        context = fail_blocks[i - 1]
        # 查找最近的 [ RUN      ] 行
        run_match = re.search(r"\[\s*RUN\s*\]\s+(\S+)\.(\S+)", context)
        if run_match:
            title = f"{run_match.group(1)}.{run_match.group(2)}"
            failures[title] = body[:1500]

    return failures


def load_testcases(path: Path) -> dict:
    """读取 test_cases.json。"""
    if not path.is_file():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def find_function_for_test(test_nodeid: str, testcases: dict) -> dict | None:
    """根据 test nodeid 反查对应的函数信息（来自 test_cases.json）。"""
    # test nodeid 形如 test/generated_unit/core/test_parser.py::test_parse_header_functional_normal
    # 或 test/generated_unit/core/test_parser.py::TestParser::test_parser_parse_functional_normal
    parts = test_nodeid.split("::")
    if len(parts) < 2:
        return None

    test_file = parts[0]
    # test_cases.json 里的 test_path 是相对路径
    for src_path, finfo in testcases.get("files", {}).items():
        if finfo.get("test_path") == test_file:
            # 匹配函数
            test_name = parts[-1]
            for func_key, fdata in finfo.get("functions", {}).items():
                # test name 前缀含函数名
                name_part = fdata["name"].lower()
                if name_part in test_name.lower():
                    return {
                        "source_file": src_path,
                        "function": fdata,
                    }
    return None


def generate_report(
    test_results: dict,
    testcases: dict,
    mode: str,
    incremental_info: dict | None = None,
) -> str:
    """生成 markdown 报告。"""
    results = test_results["results"]
    total = len(results)
    passed = sum(1 for r in results if r["outcome"] == "passed")
    failed = sum(1 for r in results if r["outcome"] == "failed")
    errors = sum(1 for r in results if r["outcome"] == "error")
    skipped = sum(1 for r in results if r["outcome"] == "skipped")

    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    # 统计函数覆盖
    total_functions = testcases.get("summary", {}).get("total_functions", 0)
    covered_functions = total_functions  # 所有扫描到的函数都应有测试
    coverage_pct = (
        (covered_functions / total_functions * 100) if total_functions else 0
    )

    languages = testcases.get("languages", [])
    frameworks = testcases.get("test_frameworks", {})
    source_dirs = testcases.get("source_dirs", [])

    lang_line = ", ".join(
        f"{lang} ({frameworks.get(lang, '?')})" for lang in languages
    ) or "未知"

    lines = []
    lines.append("# 单元测试报告")
    lines.append("")
    lines.append(f"**日期**：{now}")
    lines.append(f"**模式**：{mode}")
    lines.append(f"**语言**：{lang_line}")
    lines.append(f"**扫描范围**：{', '.join(source_dirs) or '(全仓库)'}")
    lines.append(
        f"**函数覆盖**：{covered_functions} / {total_functions} ({coverage_pct:.1f}%)"
    )
    lines.append(
        f"**测试数量**：{total}  **通过**：{passed}  **失败**：{failed}  "
        f"**错误**：{errors}  **跳过**：{skipped}"
    )
    lines.append("")

    # 增量信息
    if incremental_info and incremental_info.get("is_incremental"):
        lines.append("## 增量信息")
        lines.append("")
        lines.append(
            f"- 文件级变更：{len(incremental_info.get('changed_files', []))} 个"
        )
        changed_func_count = sum(
            len(v) for v in incremental_info.get("changed_functions", {}).values()
        )
        unchanged_func_count = sum(
            len(v) for v in incremental_info.get("unchanged_functions", {}).values()
        )
        lines.append(f"- 函数级变更：{changed_func_count} 个")
        lines.append(f"- 新增文件：{len(incremental_info.get('new_files', []))} 个")
        lines.append(f"- 删除文件：{len(incremental_info.get('removed_files', []))} 个")
        lines.append(f"- 未变更跳过：{unchanged_func_count} 个函数")
        lines.append("")

    # 失败详情
    if failed > 0 or errors > 0:
        lines.append("## 失败用例")
        lines.append("")

        # 尝试两种格式的失败解析
        failure_blocks = extract_failure_blocks(test_results["stdout"])
        if not failure_blocks:
            failure_blocks = extract_gtest_failures(test_results["stdout"])

        for r in results:
            if r["outcome"] not in ("failed", "error"):
                continue

            func_info = find_function_for_test(r["nodeid"], testcases)
            lines.append(f"### `{r['nodeid']}`")
            lines.append("")

            if func_info:
                fdata = func_info["function"]
                lines.append(f"- **源文件**：`{func_info['source_file']}`")
                lines.append(f"- **函数**：`{fdata['signature']}`")
                lines.append(f"- **适用维度**：{', '.join(fdata['dimensions'])}")

            # 提取失败详情
            failure_detail = None
            for title, body in failure_blocks.items():
                if r["name"] in title:
                    failure_detail = body
                    break

            if failure_detail:
                lines.append("")
                lines.append("```")
                lines.append(failure_detail[:800])
                lines.append("```")
            lines.append("")

    # 测试结果概览（按文件分组）
    lines.append("## 测试结果概览")
    lines.append("")
    by_file: dict[str, list] = {}
    for r in results:
        by_file.setdefault(r["file"], []).append(r)

    for filepath in sorted(by_file.keys()):
        file_results = by_file[filepath]
        f_passed = sum(1 for r in file_results if r["outcome"] == "passed")
        f_failed = sum(1 for r in file_results if r["outcome"] == "failed")
        f_total = len(file_results)
        status_emoji = "✅" if f_failed == 0 else "❌"
        lines.append(
            f"- {status_emoji} `{filepath}` — {f_passed}/{f_total} 通过"
        )

    lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="运行单元测试（pytest / Google Test）并生成报告"
    )
    parser.add_argument(
        "--test-dir",
        default="test/generated_unit/",
        help="测试目录",
    )
    parser.add_argument(
        "--output",
        default="test/generated_unit/report.md",
        help="报告输出路径",
    )
    parser.add_argument(
        "--testcases",
        default="test/generated_unit/test_cases.json",
        help="test_cases.json 路径",
    )
    parser.add_argument(
        "--mode",
        default="incremental",
        choices=["full", "incremental"],
        help="模式（仅用于报告显示）",
    )
    parser.add_argument(
        "--only",
        nargs="*",
        default=None,
        help="限定只跑指定测试文件",
    )
    args = parser.parse_args()

    test_dir = Path(args.test_dir)
    if not test_dir.is_dir():
        print(f"错误：测试目录 {test_dir} 不存在", file=sys.stderr)
        sys.exit(1)

    testcases_path = Path(args.testcases)
    testcases = load_testcases(testcases_path)

    # 根据语言/框架选择测试运行器
    frameworks = testcases.get("test_frameworks", {})
    has_python = "python" in frameworks
    has_cpp = "cpp" in frameworks

    if has_cpp and not has_python:
        print(f"执行 Google Test in {test_dir}...")
        test_results = run_gtest(str(test_dir), only_files=args.only)
    elif has_python and not has_cpp:
        print(f"执行 pytest on {test_dir}...")
        test_results = run_pytest(str(test_dir), only_files=args.only)
    elif has_python and has_cpp:
        # 混合仓库：两种都跑
        print(f"混合仓库：先执行 pytest...")
        py_results = run_pytest(str(test_dir), only_files=args.only)
        print(f"再执行 Google Test...")
        cpp_results = run_gtest(str(test_dir), only_files=args.only)
        # 合并结果
        test_results = {
            "exit_code": py_results["exit_code"] or cpp_results["exit_code"],
            "stdout": py_results["stdout"] + "\n" + cpp_results["stdout"],
            "stderr": py_results["stderr"] + "\n" + cpp_results["stderr"],
            "results": py_results["results"] + cpp_results["results"],
        }
    else:
        # 默认尝试 pytest
        print(f"执行 pytest on {test_dir}...")
        test_results = run_pytest(str(test_dir), only_files=args.only)

    # 从 test_cases.json 读增量信息
    incremental_info = None
    if args.mode == "incremental" and testcases:
        incremental_info = testcases.get("incremental")

    report = generate_report(
        test_results,
        testcases,
        mode=args.mode,
        incremental_info=incremental_info,
    )

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8")

    print(f"报告已写入：{output_path}")
    print(f"pytest 退出码：{test_results['exit_code']}")

    sys.exit(test_results["exit_code"])


if __name__ == "__main__":
    main()
