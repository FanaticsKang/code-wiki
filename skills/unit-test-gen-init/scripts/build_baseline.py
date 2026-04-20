#!/usr/bin/env python3
"""
build_baseline.py — 从 scan_repo.py 的原始扫描结果生成 test_cases.json 基线。

职责：
  - 从原始结果中移除 features（AST 中间产物）
  - 与已有基线 merge（保留 coverage_config、tool_status、未变函数的 cases）
  - 统计扫描完整性覆盖率（文件覆盖率、函数覆盖率）

用法：
    python build_baseline.py --scan .test/scan_result.json --output test/generated_unit/test_cases.json
    python build_baseline.py --scan .test/scan_result.json --output test/generated_unit/test_cases.json --mode full
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

BASELINE_VERSION = "1.0"

DEFAULT_COVERAGE_CONFIG = {
    "statement_threshold": 70,
    "function_threshold": 70,
    "branch_threshold": 60,
    "exclude_dirs": [],
    "dead_code_min_confidence": 80,
}

# 基线中保留的函数级字段（不含 features）
_BASELINE_FUNC_FIELDS = (
    "func_md5", "line_range", "signature", "is_async",
    "class_name", "namespace", "dimensions", "mocks_needed",
    "is_template", "is_static", "is_virtual",
)


def _strip_features(scan_func: dict) -> dict:
    """从原始扫描结果的函数条目中提取基线字段，移除 features 等中间产物。"""
    result = {}
    for key in _BASELINE_FUNC_FIELDS:
        if key in scan_func:
            result[key] = scan_func[key]
    return result


def _build_fresh_baseline(scan_result: dict) -> dict:
    """从原始扫描结果构建新鲜基线（不含 features，cases 为空）。"""
    baseline_files = {}
    for src_path, file_info in scan_result.get("files", {}).items():
        func_out = {}
        for func_key, func_data in file_info.get("functions", {}).items():
            func_out[func_key] = _strip_features(func_data)
            func_out[func_key]["cases"] = []

        baseline_files[src_path] = {
            "file_md5": file_info["file_md5"],
            "test_path": file_info.get("test_path", ""),
            "functions": func_out,
        }

    return baseline_files


def _compute_scan_coverage(scan_stats: dict, baseline_files: dict) -> dict:
    """计算扫描完整性覆盖率。"""
    total_source = scan_stats.get("total_source_files", 0)
    scanned = scan_stats.get("scanned_files", 0)
    total_funcs = scan_stats.get("total_functions_found", 0)
    extracted_funcs = scan_stats.get("functions_extracted", 0)

    file_rate = round(scanned / total_source * 100, 1) if total_source else 0.0
    func_rate = round(extracted_funcs / total_funcs * 100, 1) if total_funcs else 0.0

    return {
        "total_source_files": total_source,
        "scanned_files": scanned,
        "file_scan_rate": file_rate,
        "total_functions_found": total_funcs,
        "extracted_functions": extracted_funcs,
        "function_scan_rate": func_rate,
    }


def merge_into_baseline(existing: dict, fresh_files: dict,
                        scan_result: dict, mode: str) -> dict:
    """将新鲜基线与已有基线 merge，保留用户编辑和未变函数的 cases。"""
    existing_files = existing.get("files", {})
    merged_files = {}

    for src_path, fresh_finfo in fresh_files.items():
        existing_finfo = existing_files.get(src_path)
        existing_file_md5 = existing_finfo.get("file_md5", "") if existing_finfo else ""

        # 文件 MD5 相同且文件存在：完全保留 existing
        if (existing_finfo
                and existing_file_md5 == fresh_finfo["file_md5"]):
            merged_files[src_path] = existing_finfo
            merged_files[src_path]["test_path"] = fresh_finfo.get("test_path", "")
            continue

        # 文件变化或新增：逐函数合并
        existing_funcs = existing_finfo.get("functions", {}) if existing_finfo else {}
        fresh_funcs = fresh_finfo["functions"]
        merged_funcs = {}

        for func_key, fresh_func in fresh_funcs.items():
            existing_func = existing_funcs.get(func_key, {})
            merged = dict(fresh_func)

            if (existing_func
                    and existing_func.get("func_md5") == fresh_func.get("func_md5")
                    and existing_func.get("cases")):
                merged["cases"] = existing_func["cases"]

            merged_funcs[func_key] = merged

        merged_files[src_path] = {
            "file_md5": fresh_finfo["file_md5"],
            "test_path": fresh_finfo.get("test_path", ""),
            "functions": merged_funcs,
        }

    # 计算 total_cases
    total_cases = sum(
        len(f.get("cases", []))
        for fi in merged_files.values()
        for f in fi["functions"].values()
    )

    # 扫描覆盖率
    scan_stats = scan_result.get("scan_stats", {})
    coverage = _compute_scan_coverage(scan_stats, merged_files)

    # coverage_config：用户编辑优先
    coverage_config = existing.get("coverage_config", dict(DEFAULT_COVERAGE_CONFIG))

    result = {
        "version": BASELINE_VERSION,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "languages": scan_result.get("languages", []),
        "test_frameworks": scan_result.get("test_frameworks", {}),
        "source_dirs": scan_result.get("source_dirs", ["."]),
        "mode_last_run": mode,
        "summary": {
            "total_files": len(merged_files),
            "total_functions": coverage["extracted_functions"],
            "total_cases": total_cases,
            **coverage,
        },
        "coverage_config": coverage_config,
        "files": merged_files,
    }

    # tool_status：若已有则保留
    if "tool_status" in existing:
        result["tool_status"] = existing["tool_status"]

    return result


def _write_json_atomic(data: dict, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = output_path.with_suffix(output_path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    tmp.replace(output_path)


def main():
    parser = argparse.ArgumentParser(
        description="从扫描结果生成 test_cases.json 基线",
    )
    parser.add_argument("--scan", required=True,
                        help="scan_repo.py 的原始输出路径（.test/scan_result.json）")
    parser.add_argument("--output", required=True,
                        help="基线输出路径（test/generated_unit/test_cases.json）")
    parser.add_argument("--mode", default="incremental",
                        choices=["full", "incremental"],
                        help="模式（默认 incremental）")
    args = parser.parse_args()

    scan_path = Path(args.scan)
    if not scan_path.is_file():
        print(f"错误: 扫描结果文件 {scan_path} 不存在", file=sys.stderr)
        sys.exit(1)

    with open(scan_path, "r", encoding="utf-8") as f:
        scan_result = json.load(f)

    # 读取已有基线
    output_path = Path(args.output)
    existing = {}
    if output_path.is_file():
        try:
            with open(output_path, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except Exception as e:
            print(f"警告: 基线文件 {output_path} 无法解析（{e}），按全量处理",
                  file=sys.stderr)

    # 构建新鲜基线（不含 features）
    fresh_files = _build_fresh_baseline(scan_result)

    # Merge
    merged = merge_into_baseline(existing, fresh_files, scan_result, args.mode)

    # 写入
    _write_json_atomic(merged, output_path)

    # 输出摘要
    s = merged["summary"]
    print(
        f"基线已写入: {output_path}\n"
        f"  文件扫描: {s['scanned_files']}/{s['total_source_files']} "
        f"({s['file_scan_rate']}%)\n"
        f"  函数提取: {s['extracted_functions']}/{s['total_functions_found']} "
        f"({s['function_scan_rate']}%)\n"
        f"  用例数: {s['total_cases']}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
