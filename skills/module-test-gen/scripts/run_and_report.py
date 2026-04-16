#!/usr/bin/env python3
"""
run_and_report.py — Run pytest on a test directory and generate a markdown report.

Usage:
    python run_and_report.py <test_dir> --report-path <output.md> [--config <module.yml>]

If --config is provided, the report includes feature names and source tags from the config.
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import yaml


def run_pytest(test_dir: str) -> dict:
    """
    Run pytest and collect results.

    Returns dict with:
        - exit_code: int
        - stdout: str
        - results: list of test result dicts (if json report available)
    """
    # Run pytest with JSON report
    cmd = [
        sys.executable, "-m", "pytest",
        test_dir,
        "-v",
        "--tb=short",
        f"--json-report",
        f"--json-report-file=-",
        "-q",
    ]

    # Try with json-report plugin first
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode == 4:  # pytest usage error (plugin not installed)
        # Fall back to plain pytest
        cmd = [
            sys.executable, "-m", "pytest",
            test_dir,
            "-v",
            "--tb=short",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        return {
            "exit_code": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "results": parse_verbose_output(result.stdout),
        }

    # Try to parse JSON from stdout
    try:
        report = json.loads(result.stdout)
        tests = []
        for test in report.get("tests", []):
            tests.append({
                "nodeid": test.get("nodeid", ""),
                "outcome": test.get("outcome", "unknown"),
                "duration": test.get("duration", 0),
                "message": test.get("call", {}).get("longrepr", ""),
            })
        return {
            "exit_code": result.returncode,
            "stdout": result.stderr,  # with json report, normal output goes to stderr
            "stderr": "",
            "results": tests,
        }
    except (json.JSONDecodeError, KeyError):
        return {
            "exit_code": result.returncode,
            "stdout": result.stdout + result.stderr,
            "stderr": "",
            "results": parse_verbose_output(result.stdout + result.stderr),
        }


def parse_verbose_output(output: str) -> list[dict]:
    """Parse pytest verbose output to extract test results."""
    results = []
    for line in output.split("\n"):
        line = line.strip()
        if " PASSED" in line or " FAILED" in line or " ERROR" in line or " SKIPPED" in line:
            parts = line.rsplit(" ", 1)
            if len(parts) == 2:
                nodeid = parts[0].strip()
                outcome = parts[1].strip().lower()
                results.append({
                    "nodeid": nodeid,
                    "outcome": outcome,
                    "duration": 0,
                    "message": "",
                })
    return results


def extract_feature_from_nodeid(nodeid: str) -> str:
    """Extract feature name from test node ID."""
    # nodeid looks like: tests/module_payment/test_order_creation.py::TestOrderCreation::test_xxx
    parts = nodeid.split("::")
    if len(parts) >= 2:
        class_name = parts[1]
        # Convert TestOrderCreation → Order Creation
        name = ""
        for char in class_name:
            if char.isupper() and name and not name.endswith(" "):
                name += " "
            name += char
        # Remove "Test " prefix
        if name.startswith("Test "):
            name = name[5:]
        return name.strip()
    return "Unknown"


def load_config_features(config_path: str) -> dict:
    """Load feature → test_targets mapping from config YAML."""
    if not config_path or not Path(config_path).is_file():
        return {}

    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    features = {}
    for feature in config.get("features", []):
        fname = feature["name"]
        features[fname] = {
            "source": feature.get("source", "auto"),
            "targets": {
                t["description"]: t.get("source", "auto")
                for t in feature.get("test_targets", [])
            },
        }
    return features


def generate_report(
    test_results: dict,
    module_name: str,
    config_features: dict | None = None,
) -> str:
    """Generate a markdown report from test results."""
    results = test_results["results"]
    total = len(results)
    passed = sum(1 for r in results if r["outcome"] == "passed")
    failed = sum(1 for r in results if r["outcome"] == "failed")
    errors = sum(1 for r in results if r["outcome"] == "error")
    skipped = sum(1 for r in results if r["outcome"] == "skipped")

    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    lines = []
    lines.append(f"# Module Test Report: {module_name}")
    lines.append("")
    lines.append(f"**Date**: {now}")
    lines.append(f"**Status**: {passed} passed, {failed} failed, {errors} errors, {skipped} skipped / {total} total")
    lines.append(f"**Exit code**: {test_results['exit_code']}")
    lines.append("")

    # Group results by feature (test class)
    by_feature: dict[str, list] = {}
    for r in results:
        feature = extract_feature_from_nodeid(r["nodeid"])
        by_feature.setdefault(feature, []).append(r)

    for feature_name, tests in by_feature.items():
        lines.append(f"## Feature: {feature_name}")
        lines.append("")
        lines.append("| # | Test | Source | Result | Details |")
        lines.append("|---|------|--------|--------|---------|")

        for i, test in enumerate(tests, 1):
            # Extract test method name from nodeid
            parts = test["nodeid"].split("::")
            test_name = parts[-1] if parts else test["nodeid"]
            # Clean up test name
            test_name = test_name.replace("test_", "", 1).replace("_", " ")

            outcome = test["outcome"].upper()
            emoji = {"PASSED": "✅", "FAILED": "❌", "ERROR": "⚠️", "SKIPPED": "⏭️"}.get(outcome, "❓")

            source = "auto"  # default
            if "manual" in test["nodeid"] or (
                config_features and feature_name in config_features
            ):
                # Try to match test to a target to get source
                source = "auto"  # Could be improved with better matching

            message = test.get("message", "")
            if message:
                # Truncate long messages
                message = message[:100].replace("\n", " ").replace("|", "\\|")

            lines.append(f"| {i} | {test_name} | {source} | {emoji} {outcome} | {message} |")

        lines.append("")

    # Add raw output section for failures
    if failed > 0 or errors > 0:
        lines.append("## Failure Details")
        lines.append("")
        lines.append("```")
        # Include relevant portion of pytest output
        stdout = test_results.get("stdout", "")
        # Only include FAILURES section
        if "FAILURES" in stdout:
            failure_section = stdout[stdout.index("FAILURES"):]
            lines.append(failure_section[:2000])  # Cap at 2000 chars
        else:
            lines.append(stdout[-2000:])  # Last 2000 chars
        lines.append("```")
        lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Run tests and generate report")
    parser.add_argument("test_dir", help="Directory containing test files")
    parser.add_argument("--report-path", required=True, help="Output path for markdown report")
    parser.add_argument("--config", default=None, help="Module config YAML for source annotations")
    parser.add_argument("--module-name", default=None, help="Module name for report title")
    args = parser.parse_args()

    test_dir = Path(args.test_dir)
    if not test_dir.is_dir():
        print(f"Error: {test_dir} is not a directory", file=sys.stderr)
        sys.exit(1)

    module_name = args.module_name or test_dir.name.replace("module_", "")

    print(f"Running tests in {test_dir}...")
    test_results = run_pytest(str(test_dir))

    config_features = load_config_features(args.config) if args.config else None

    report = generate_report(test_results, module_name, config_features)

    report_path = Path(args.report_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")

    print(f"Report written to {report_path}")
    print(f"Results: {test_results['exit_code']=}")

    # Exit with pytest's exit code
    sys.exit(test_results["exit_code"])


if __name__ == "__main__":
    main()
