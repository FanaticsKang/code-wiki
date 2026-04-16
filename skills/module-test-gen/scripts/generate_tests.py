#!/usr/bin/env python3
"""
generate_tests.py — Read a module config YAML and generate pytest test files.

Usage:
    python generate_tests.py <config.yml> --output-dir tests/ --repo-root /path/to/repo

Generates one test file per feature, plus a conftest.py with shared fixtures.
"""

import argparse
import re
import sys
from pathlib import Path

import yaml


def slugify(text: str) -> str:
    """Convert a feature name to a valid Python identifier."""
    slug = re.sub(r"[^\w\s]", "", text)
    slug = re.sub(r"\s+", "_", slug.strip())
    slug = slug.lower()
    if slug and slug[0].isdigit():
        slug = "f_" + slug
    return slug or "unnamed"


def generate_conftest(output_dir: Path) -> str:
    """Generate conftest.py content with marker registration."""
    return '''"""Shared fixtures and marker registration for module tests."""
import pytest


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line("markers", "manual: test from engineer-specified target")
    config.addinivalue_line("markers", "auto: test from auto-discovered target")
'''


def generate_test_file(feature: dict, module_name: str) -> str:
    """
    Generate a pytest test file for a single feature.

    Args:
        feature: Feature dict from config YAML
        module_name: Name of the module

    Returns:
        Python source code as string
    """
    feature_name = feature["name"]
    feature_slug = slugify(feature_name)
    source = feature.get("source", "auto")

    lines = []
    lines.append(f'"""Tests for feature: {feature_name} (module: {module_name})"""')
    lines.append("import pytest")
    lines.append("")

    # Add imports for related code
    related_files = feature.get("related_code", [])
    import_comments = []
    for rc in related_files:
        path = rc.get("path", "") if isinstance(rc, dict) else rc
        import_comments.append(f"# Related: {path}")
    if import_comments:
        lines.extend(import_comments)
        lines.append("")

    # Generate test class
    class_name = "Test" + "".join(
        word.capitalize() for word in feature_name.replace("-", " ").replace("_", " ").split()
    )
    lines.append(f"class {class_name}:")
    lines.append(f'    """Tests for feature: {feature_name}"""')
    lines.append("")

    test_targets = feature.get("test_targets", [])
    if not test_targets:
        lines.append("    @pytest.mark.auto")
        lines.append(f"    def test_{feature_slug}_placeholder(self):")
        lines.append(f'        """Placeholder: no test targets defined for {feature_name}"""')
        lines.append("        pytest.skip('No test targets defined')")
        lines.append("")
    else:
        for i, target in enumerate(test_targets):
            description = target.get("description", f"Test {i+1}")
            target_source = target.get("source", "auto")
            test_slug = slugify(description)
            # Truncate long slugs
            if len(test_slug) > 60:
                test_slug = test_slug[:60].rstrip("_")

            marker = "manual" if target_source == "manual" else "auto"
            lines.append(f"    @pytest.mark.{marker}")
            lines.append(f"    def test_{test_slug}(self):")
            lines.append(f'        """')
            lines.append(f"        {description}")
            lines.append(f"        Source: {target_source}")
            lines.append(f'        """')
            lines.append(f"        # TODO: Implement test for: {description}")
            lines.append(f"        raise NotImplementedError(")
            lines.append(f'            "Test not yet implemented: {description}"')
            lines.append(f"        )")
            lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Generate pytest tests from module config")
    parser.add_argument("config", help="Path to module config YAML")
    parser.add_argument("--output-dir", required=True, help="Output directory for test files")
    parser.add_argument("--repo-root", default=".", help="Repository root path")
    args = parser.parse_args()

    config_path = Path(args.config)
    if not config_path.is_file():
        print(f"Error: {config_path} not found", file=sys.stderr)
        sys.exit(1)

    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    module_name = config.get("module", "unknown")
    features = config.get("features", [])

    output_dir = Path(args.output_dir) / f"module_{slugify(module_name)}"
    output_dir.mkdir(parents=True, exist_ok=True)

    # Write __init__.py
    (output_dir / "__init__.py").write_text("")

    # Write conftest.py
    conftest_path = output_dir / "conftest.py"
    conftest_path.write_text(generate_conftest(output_dir))
    print(f"  Created: {conftest_path}")

    # Write test files
    for feature in features:
        feature_slug = slugify(feature["name"])
        test_filename = f"test_{feature_slug}.py"
        test_path = output_dir / test_filename
        content = generate_test_file(feature, module_name)
        test_path.write_text(content, encoding="utf-8")
        print(f"  Created: {test_path}")

    print(f"\nGenerated {len(features)} test file(s) in {output_dir}")


if __name__ == "__main__":
    main()
