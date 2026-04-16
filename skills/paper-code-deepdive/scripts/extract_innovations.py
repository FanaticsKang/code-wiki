#!/usr/bin/env python3
"""
Stage 1: Extract innovation candidates from a paper PDF.

This script is a SCAFFOLD. It does the mechanical work of extracting text from
the high-signal regions of a paper (abstract, intro tail, method openings,
section headers, figure captions). It does NOT decide what's an innovation —
that judgment is left to Claude, which reads this script's output.

Usage:
    python extract_innovations.py <paper.pdf> [--out paper_claims.json]

Output:
    A JSON file with high-signal excerpts, to be reviewed by Claude. Claude
    then produces the final curated `paper_claims.json` after confirming
    with the user.

Dependencies:
    pypdf (pip install pypdf)
    or pdfplumber for better extraction (pip install pdfplumber)

This script prefers pdfplumber if available, falls back to pypdf.
"""

import argparse
import json
import re
import sys
from pathlib import Path


def extract_text_by_page(pdf_path: Path) -> list[str]:
    """Return list of page texts."""
    try:
        import pdfplumber
        pages = []
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                pages.append(page.extract_text() or "")
        return pages
    except ImportError:
        pass

    try:
        from pypdf import PdfReader
        reader = PdfReader(str(pdf_path))
        return [page.extract_text() or "" for page in reader.pages]
    except ImportError:
        print("ERROR: install pdfplumber or pypdf", file=sys.stderr)
        sys.exit(1)


def find_abstract(pages: list[str]) -> str:
    """Abstract is on page 1, usually between 'Abstract' keyword and 'Introduction'."""
    if not pages:
        return ""
    first = pages[0]
    # Match "Abstract" (case-insensitive) up to "Introduction" or "1." section header
    m = re.search(
        r"(?is)abstract\b[\s\S]*?(?=\b1[\s.]+introduction\b|\bintroduction\b)",
        first,
    )
    if m:
        return m.group(0).strip()
    # Fallback: just return the first ~2000 chars of page 1
    return first[:2000]


def find_intro_tail(pages: list[str]) -> str:
    """
    The last paragraph(s) of the Introduction often contain the contribution list.
    Heuristic: find 'Introduction' and search forward until we hit section 2,
    then return the last ~1500 characters before that.
    """
    full = "\n".join(pages[:5])  # intro is almost always in first 5 pages
    m = re.search(r"(?is)\bintroduction\b", full)
    if not m:
        return ""
    start = m.end()
    # find next top-level section header: "2. " or "2 Related Work" etc.
    m2 = re.search(
        r"(?im)^\s*(2[\s.]+\w|related\s+work|background|preliminaries|method|approach)",
        full[start:],
    )
    if m2:
        intro_block = full[start : start + m2.start()]
    else:
        intro_block = full[start : start + 8000]
    # return last 2000 chars (the contribution list usually at end)
    tail = intro_block[-2000:] if len(intro_block) > 2000 else intro_block
    return tail.strip()


def find_method_openings(pages: list[str]) -> list[dict]:
    """
    Find openings of Method/Approach sections and their subsections.
    Returns list of {heading, excerpt, page_hint}.
    """
    results = []
    full = "\n".join(pages)
    # Match section/subsection headers: lines like "3 Method", "3.1 Our Approach", "3.2.1 ..."
    pattern = re.compile(
        r"(?m)^\s*(\d+(?:\.\d+){0,2})\s+([A-Z][^\n]{2,80})$"
    )
    for m in pattern.finditer(full):
        section_num, heading = m.group(1), m.group(2).strip()
        # Keep only Method-like sections (heuristic: section 3 or 4 typically)
        first_digit = int(section_num.split(".")[0])
        if first_digit < 2 or first_digit > 5:
            continue
        # Skip obvious non-method headers
        if re.search(
            r"(?i)\b(experiments?|results?|evaluation|related\s+work|discussion|conclusion|limitations?|background)\b",
            heading,
        ):
            continue
        # Get ~600 chars of content following
        start = m.end()
        excerpt = full[start : start + 800].strip()
        results.append({
            "section": section_num,
            "heading": heading,
            "excerpt": excerpt,
        })
    return results


def find_figure_captions(pages: list[str]) -> list[dict]:
    """
    Extract figure captions. Matches patterns like 'Figure 1:', 'Fig. 2.',
    'Figure 3.'. Captures up to ~400 chars after.
    """
    results = []
    for page_idx, page_text in enumerate(pages):
        # match figure captions
        pattern = re.compile(
            r"(Figure|Fig\.)\s+(\d+)[:.]\s*([^\n]{10,500})"
        )
        for m in pattern.finditer(page_text):
            results.append({
                "figure_number": int(m.group(2)),
                "page": page_idx + 1,
                "caption": m.group(3).strip(),
            })
    return results


def find_named_modules(pages: list[str]) -> list[str]:
    """
    Find capitalized module-like names. Heuristic: 2-4 consecutive
    capitalized words, often preceded by 'the' or introducing a concept.

    Very noisy — Claude will filter.
    """
    full = "\n".join(pages[:10])  # usually in method section
    # Match 2-4 consecutive Capitalized Words
    pattern = re.compile(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})\b")
    counts = {}
    for m in pattern.finditer(full):
        name = m.group(1)
        # filter out common non-module phrases
        if re.search(
            r"^(We|Our|The|This|These|Figure|Table|Section|Equation|Related Work|Our Method)",
            name,
        ):
            continue
        counts[name] = counts.get(name, 0) + 1
    # return names appearing at least 3 times (likely a recurring module name)
    return [name for name, c in sorted(counts.items(), key=lambda x: -x[1]) if c >= 3][:30]


def find_equations(pages: list[str]) -> list[dict]:
    """
    Find numbered equations. PDFs often have them like '(1)', '(2)' at end of lines.
    This is noisy — Claude uses it as a pointer, then reads the PDF itself for precision.
    """
    results = []
    for page_idx, page_text in enumerate(pages):
        # match lines ending in equation numbers like (1), (2.3), etc.
        for m in re.finditer(r"(?m)([^\n]{10,300})\s+\((\d+(?:\.\d+)?)\)\s*$", page_text):
            eq_text = m.group(1).strip()
            eq_num = m.group(2)
            if len(eq_text) < 10:
                continue
            results.append({
                "equation_number": eq_num,
                "page": page_idx + 1,
                "text_near_equation": eq_text[-200:],  # last 200 chars of the line
            })
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path, help="Path to paper PDF")
    parser.add_argument("--out", type=Path, default=Path("paper_claims.json"),
                        help="Output JSON path (default: paper_claims.json)")
    args = parser.parse_args()

    if not args.pdf.exists():
        print(f"ERROR: {args.pdf} not found", file=sys.stderr)
        sys.exit(1)

    pages = extract_text_by_page(args.pdf)
    print(f"Loaded {len(pages)} pages from {args.pdf}", file=sys.stderr)

    result = {
        "pdf_path": str(args.pdf),
        "num_pages": len(pages),
        "high_signal_regions": {
            "abstract": find_abstract(pages),
            "introduction_tail": find_intro_tail(pages),
            "method_openings": find_method_openings(pages),
            "figure_captions": find_figure_captions(pages),
            "candidate_named_modules": find_named_modules(pages),
            "equation_pointers": find_equations(pages),
        },
        "instructions_for_claude": (
            "This JSON contains mechanically-extracted high-signal regions of "
            "the paper. Your job: "
            "(1) Read these regions and identify 1-3 core innovations per "
            "'innovation_signals.md' guidance. "
            "(2) For each innovation, fill: name, claimed_benefit, "
            "location_in_paper (section/figure/equation), key_terms (3-8 "
            "searchable terms), type (architectural/training/data/inference). "
            "(3) Save the curated list, overwriting this file, using the "
            "schema shown in the README section of extract_innovations.py. "
            "(4) Confirm with the user before proceeding to Stage 2."
        ),
        "target_schema_for_curated_output": {
            "innovations": [
                {
                    "id": "inn_1",
                    "name": "string, e.g. 'Gated Cross-Attention'",
                    "claimed_benefit": "string, what the paper says it achieves",
                    "location_in_paper": {
                        "sections": ["3.2"],
                        "figures": [2],
                        "equations": ["4", "5", "6"],
                    },
                    "key_terms": ["gated", "xattn", "tanh gate", "alpha"],
                    "type": "architectural | training | data | inference",
                }
            ]
        },
    }

    args.out.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    print(f"Wrote {args.out}", file=sys.stderr)
    print(f"Next: Claude should read {args.out}, curate the innovation list, "
          "and overwrite the file with the final structured result.", file=sys.stderr)


if __name__ == "__main__":
    main()
