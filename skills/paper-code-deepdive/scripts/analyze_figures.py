#!/usr/bin/env python3
"""
Stage 2c: Figure analysis with three-source cross-validation.

This script is the figure-handling workhorse. It does the mechanical prep that
LLM vision alone cannot handle reliably:

  1. Renders relevant PDF pages at high DPI so the model can see them clearly.
  2. Optionally crops/tiles large figures into sub-regions for focused analysis.
  3. Extracts the caption verbatim.
  4. Greps in-text references to each figure ("as shown in Fig. N").
  5. Extracts equations near the figure.

The JUDGMENT — filling the structured figure schema from these three sources —
is done by Claude after running this script. The script's job is to make sure
Claude has all three sources in front of it, so it doesn't have to rely on
vision alone.

Usage:
    python analyze_figures.py <paper.pdf> --claims paper_claims.json \
        [--out figure_analysis.json] [--images-dir figure_images/]

Output:
    - figure_analysis.json: structured extraction, one entry per target figure,
      containing caption + in-text refs + equations + paths to rendered images.
    - figure_images/: directory of rendered page images (PNG, 200 DPI).

Dependencies:
    pdfplumber (for text) and pypdfium2 or pymupdf (for rendering).
    pip install pdfplumber pymupdf
"""

import argparse
import json
import re
import sys
from pathlib import Path


def load_pages_text(pdf_path: Path) -> list[str]:
    """Extract text page by page."""
    try:
        import pdfplumber
        with pdfplumber.open(pdf_path) as pdf:
            return [page.extract_text() or "" for page in pdf.pages]
    except ImportError:
        from pypdf import PdfReader
        reader = PdfReader(str(pdf_path))
        return [p.extract_text() or "" for p in reader.pages]


def render_page(pdf_path: Path, page_number: int, out_path: Path, dpi: int = 200):
    """
    Render a single PDF page (1-indexed) to PNG at specified DPI.

    Tries pymupdf (fitz) first, falls back to pypdfium2.
    """
    try:
        import fitz  # pymupdf
        doc = fitz.open(str(pdf_path))
        page = doc[page_number - 1]
        zoom = dpi / 72.0
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat)
        pix.save(str(out_path))
        doc.close()
        return out_path
    except ImportError:
        pass

    try:
        import pypdfium2 as pdfium
        doc = pdfium.PdfDocument(str(pdf_path))
        page = doc[page_number - 1]
        scale = dpi / 72.0
        pil = page.render(scale=scale).to_pil()
        pil.save(str(out_path))
        return out_path
    except ImportError:
        print(
            "ERROR: need pymupdf (fitz) or pypdfium2 for rendering. "
            "Install with: pip install pymupdf",
            file=sys.stderr,
        )
        sys.exit(1)


def find_figure_page(pages: list[str], figure_number: int) -> int | None:
    """
    Find page number (1-indexed) where Figure N appears. Looks for the caption.
    """
    patterns = [
        re.compile(rf"\bFigure\s+{figure_number}[:.]", re.IGNORECASE),
        re.compile(rf"\bFig\.\s*{figure_number}[:.]", re.IGNORECASE),
    ]
    for page_idx, page_text in enumerate(pages):
        for pat in patterns:
            if pat.search(page_text):
                return page_idx + 1
    return None


def extract_caption(pages: list[str], figure_number: int) -> str:
    """
    Extract Figure N caption verbatim (up to ~600 chars after the 'Figure N:').
    """
    patterns = [
        re.compile(
            rf"(?s)\b(Figure|Fig\.)\s+{figure_number}[:.]\s*(.{{10,1500}}?)(?=\n\s*\n|\n\s*(?:Figure|Fig\.)\s+\d+|\Z)",
            re.IGNORECASE,
        ),
    ]
    full = "\n".join(pages)
    for pat in patterns:
        m = pat.search(full)
        if m:
            return f"Figure {figure_number}: {m.group(2).strip()}"
    return ""


def extract_in_text_references(pages: list[str], figure_number: int) -> list[str]:
    """
    Find every sentence in the paper that references this figure.
    Returns list of sentences (with some context).
    """
    full = "\n".join(pages)
    # Patterns for references (excluding the caption itself)
    ref_patterns = [
        rf"\bFigure\s+{figure_number}\b",
        rf"\bFig\.\s*{figure_number}\b",
        rf"\bFig\s+{figure_number}\b",
    ]
    sentences = []
    # naive sentence split
    for sentence in re.split(r"(?<=[.!?])\s+(?=[A-Z])", full):
        if re.match(rf"(?i)\s*(Figure|Fig\.)\s*{figure_number}\s*[:.]", sentence):
            # this is the caption, skip
            continue
        for pat in ref_patterns:
            if re.search(pat, sentence):
                clean = re.sub(r"\s+", " ", sentence).strip()
                if len(clean) > 20 and clean not in sentences:
                    sentences.append(clean)
                break
    return sentences


def extract_nearby_equations(pages: list[str], figure_page: int) -> list[dict]:
    """
    Extract numbered equations on the figure's page and the page before/after.
    """
    if figure_page is None:
        return []
    results = []
    pages_to_check = range(max(0, figure_page - 2), min(len(pages), figure_page + 1))
    for page_idx in pages_to_check:
        text = pages[page_idx]
        for m in re.finditer(
            r"(?m)([^\n]{10,400})\s+\((\d+(?:\.\d+)?)\)\s*$", text
        ):
            results.append({
                "equation_number": m.group(2),
                "page": page_idx + 1,
                "text_line": m.group(1).strip(),
                "proximity_to_figure": page_idx + 1 - figure_page,
            })
    return results


def analyze_one_figure(
    pages: list[str],
    pdf_path: Path,
    figure_number: int,
    images_dir: Path,
) -> dict:
    """Run the full analysis protocol for one figure."""
    page_num = find_figure_page(pages, figure_number)
    caption = extract_caption(pages, figure_number)
    in_text = extract_in_text_references(pages, figure_number)
    equations = extract_nearby_equations(pages, page_num) if page_num else []

    rendered_images = []
    if page_num is not None:
        images_dir.mkdir(parents=True, exist_ok=True)
        img_path = images_dir / f"figure_{figure_number}_page_{page_num}.png"
        render_page(pdf_path, page_num, img_path, dpi=200)
        rendered_images.append(str(img_path))
        # Also render the previous page if figure could span — safe to also have it
        if page_num > 1:
            prev_path = images_dir / f"figure_{figure_number}_page_{page_num - 1}_context.png"
            render_page(pdf_path, page_num - 1, prev_path, dpi=200)
            rendered_images.append(str(prev_path))

    return {
        "figure_number": figure_number,
        "page": page_num,
        "rendered_images": rendered_images,
        "caption": caption,
        "in_text_references": in_text,
        "nearby_equations": equations,
        "schema_to_fill": (
            "Claude: read figure_analysis_protocol.md and figure_schemas.md. "
            "Open the rendered image(s) above. Then fill the appropriate "
            "structured schema (architecture_diagram / data_flow_diagram / "
            "algorithm_box / visualization / plot) using all three sources: "
            "vision, caption+in_text_references, and nearby_equations. "
            "Add fields with confidence levels. Anything you can't fill "
            "confidently goes in 'unresolved_questions' — those are Stage 3 "
            "code-verification tasks."
        ),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path, help="Path to paper PDF")
    parser.add_argument(
        "--claims",
        type=Path,
        required=True,
        help="Path to paper_claims.json from Stage 1",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("figure_analysis.json"),
        help="Output JSON path",
    )
    parser.add_argument(
        "--images-dir",
        type=Path,
        default=Path("figure_images"),
        help="Directory for rendered images",
    )
    parser.add_argument(
        "--figures",
        type=str,
        default=None,
        help="Comma-separated figure numbers to analyze, overriding claims. E.g. '1,2,3'",
    )
    args = parser.parse_args()

    if not args.pdf.exists():
        print(f"ERROR: {args.pdf} not found", file=sys.stderr)
        sys.exit(1)

    # Determine target figures
    target_figures: list[int] = []
    if args.figures:
        target_figures = [int(x.strip()) for x in args.figures.split(",") if x.strip()]
    else:
        if not args.claims.exists():
            print(f"ERROR: {args.claims} not found. Run Stage 1 first.", file=sys.stderr)
            sys.exit(1)
        claims = json.loads(args.claims.read_text())
        fig_set = set()
        for inn in claims.get("innovations", []):
            for fig in inn.get("location_in_paper", {}).get("figures", []):
                fig_set.add(int(fig))
        # Always include Fig 1 and Fig 2 as defaults (architectural hero figures)
        fig_set.update([1, 2])
        target_figures = sorted(fig_set)

    print(f"Analyzing figures: {target_figures}", file=sys.stderr)

    pages = load_pages_text(args.pdf)
    print(f"Loaded {len(pages)} pages", file=sys.stderr)

    results = {
        "pdf_path": str(args.pdf),
        "figures_analyzed": [],
        "protocol_reference": "references/figure_analysis_protocol.md",
        "schema_reference": "references/figure_schemas.md",
    }

    for fig_num in target_figures:
        print(f"  Processing Figure {fig_num}...", file=sys.stderr)
        try:
            result = analyze_one_figure(pages, args.pdf, fig_num, args.images_dir)
            results["figures_analyzed"].append(result)
        except Exception as e:
            print(f"    WARNING: failed to process Figure {fig_num}: {e}",
                  file=sys.stderr)
            results["figures_analyzed"].append({
                "figure_number": fig_num,
                "error": str(e),
            })

    args.out.write_text(json.dumps(results, indent=2, ensure_ascii=False))
    print(f"Wrote {args.out}", file=sys.stderr)
    print(f"Rendered images in {args.images_dir}/", file=sys.stderr)
    print(
        "\nNext: Claude should open each rendered image, apply the "
        "three-source protocol from figure_analysis_protocol.md, fill the "
        "schemas from figure_schemas.md, and update this JSON file with "
        "per-figure structured extraction + unresolved_questions.",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
