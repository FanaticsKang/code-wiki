---
name: paper-code-deepdive
description: Deep analysis skill that pairs a research paper with its open-source implementation to extract core innovations and reveal implementation details the paper doesn't document. Use this whenever a user provides both a paper (PDF/arxiv link) and a code repository, or when they mention wanting to understand "how the model is actually built", "the real architecture", "what the code actually does vs the paper", or want to "reproduce", "reimplement", or "deeply understand" a specific paper's method. Also trigger when the user gives only a paper but asks about implementation details, or only code but asks what the underlying paper says. Keywords that should trigger this: reproduce, reimplement, core module, real architecture, hidden details, paper vs code, ablation, novel contribution, innovation implementation. Do NOT use for generic paper summarization (no code involved) or generic code review (no paper involved).
---

# Paper-Code Deepdive

This skill produces a deep, verified analysis of a paper's **core innovations** and their **real implementation in code** — surfacing the details the paper leaves out and the places where code diverges from the paper.

## When to Use

Use this skill when:
- The user provides a paper AND a code repository (or links to both)
- The user wants to understand the *real* architecture/algorithm behind a paper
- The user wants to reproduce or reimplement a method
- The user suspects the code differs from the paper

Don't use it for generic paper summarization or generic code review.

## Core Principle

**Don't try to cover the whole paper.** A paper is mostly background, related work, and experiments. Only 10-20% is genuinely novel. This skill does **deep vertical analysis on the 1-3 core innovations**, not shallow horizontal coverage.

The value of this skill is in revealing **what the paper leaves unsaid**: initializations, LayerNorm placement, loss coefficients, gradient tricks, train/eval branching, numerical stabilizers. These are where reproductions fail.

## The Four-Stage Pipeline

```
[1. Locate innovations] → [2. Analyze innovation materials (text + figures + equations)]
    → [3. Locate code implementation] → [4. Deep compare and report]
```

Each stage has a dedicated script in `scripts/`. Read the stage below, then read the corresponding script's header docstring before running.

---

### Stage 1: Locate the core innovations

Most papers signal their innovations explicitly. Check these high-signal locations in order:

1. **Abstract, final 2-3 sentences** — usually "We propose..." / "Our key contribution..."
2. **Introduction, final paragraph** — frequently a "Our contributions are:" bullet list
3. **Method section, opening paragraph** — names the novel modules
4. **Named modules** — any module the paper gives a proper name (e.g., "Gated Cross-Attention", "Perceiver Resampler") is almost certainly a contribution
5. **Ablation tables** — each row is a design choice the authors thought important
6. **Figure 1 or Figure 2** — the architecture hero figure, often the entire contribution visualized

For each innovation, build a record with:
- `name` — the canonical name (use the paper's naming if it has one)
- `claimed_benefit` — what the paper says this achieves
- `location_in_paper` — section, figure, and equation references
- `key_terms` — 3-8 searchable terms used to locate this in code (class names, variable names, distinctive words)

Save to `paper_claims.json`. See `references/innovation_signals.md` for detailed guidance on what counts as an innovation and how to disambiguate.

**Stop after Stage 1 and confirm innovations with the user before proceeding.** Analyzing the wrong "innovation" wastes the rest of the pipeline. Show the user the list, ask if any are missing or mis-identified, let them pick which ones to drill into if there are more than 3.

---

### Stage 2: Analyze innovation materials

For each confirmed innovation, extract its full specification from three sources:

#### 2a. Text extraction
Read the method subsection that defines this innovation (often 0.5-2 pages). Extract:
- Verbal description of the mechanism
- Motivation (what problem does it solve)
- Any hyperparameters mentioned inline

#### 2b. Equation extraction
Copy every numbered equation in this subsection verbatim, with its equation number. Equations are the most precise source and survive translation to code best.

#### 2c. Figure extraction (critical — see below)
Figures are high-information but LLM vision is unreliable on them. Use the **three-source cross-validation** protocol documented in `references/figure_analysis_protocol.md`. Summary:

1. Render the relevant PDF page(s) at 200 DPI (use pdf-reading skill)
2. Extract the caption verbatim
3. Grep the paper for every sentence that references this figure ("as shown in Fig. N", "Figure N illustrates...")
4. Fill a structured schema (see `references/figure_schemas.md`) — **do not free-form describe the figure**
5. Flag any field that couldn't be filled confidently as `confidence: low`. These become priority targets for code verification in Stage 3.

**Never rely on vision alone.** Text + caption + equations must corroborate anything you extract from a figure. If they conflict, text/equations win.

Save to `innovation_analysis.json`, one entry per innovation.

---

### Stage 3: Locate the implementation

Do not read the whole repo. The repo might be 50k lines. Instead, search directed by the `key_terms` from Stage 1.

Follow this order:

1. **Read the README and any `docs/` pointers** — find the main model definition file and training entry point
2. **Identify the model file** — usually `model.py`, `modeling_*.py`, or a file containing `nn.Module` subclasses
3. **Grep for key_terms** — class names, distinctive variable names, paper-specific terminology
4. **Check config files** — `config.yaml`, `*.json`, `argparse` defaults. The *real* hyperparameters live here, not in the paper.
5. **Find the training loop and loss function** — `train.py`, `trainer.py`, or in the model file

For each innovation, record the file path and line range(s) that implement it. Save to `code_map.json`.

If a key_term yields zero results, the implementation may use different naming. Try:
- Common synonyms (e.g., paper says "gate", code might say "attn_gate", "xattn_gate", "tanh_gate")
- The equation structure (search for distinctive ops like `torch.einsum` patterns, unusual `reshape` sequences)
- The class inheritance (search for subclasses of `nn.Module` within files near the main model)

If it still can't be found, flag it — some papers claim things the public code doesn't contain.

---

### Stage 4: Deep compare and report

This is where the skill earns its keep. For each innovation, produce a side-by-side analysis:

**4a. Paper's ideal form** — what the paper says this is.

**4b. Code's real form** — paste the actual `nn.Module` or function, annotated line-by-line. Include `__init__` (shows real structure) and `forward` (shows real data flow).

**4c. Details the paper omits** — go through `references/hidden_details_checklist.md` systematically. This is the highest-value output. Examples:
- Initialization: paper says "learnable gate", code has `nn.Parameter(torch.zeros(1))` — initialized to zero means the path is closed at training start
- Normalization placement: pre-norm vs post-norm, which one is actually used
- Numerical stabilizers: `+ 1e-6`, `.clamp(...)`, `log(x + eps)`
- Training/inference branching: what does `if self.training:` change
- Gradient flow: where `.detach()` appears and why

**4d. Paper-code inconsistencies** — concrete differences:
- Equation says softmax, code uses sigmoid
- Paper says ReLU, code uses GELU
- Paper says `L = L1 + L2`, code has `L = L1 + 0.01 * L2`
- Paper omits a `/ sqrt(d_k)` that's actually in the code (or vice versa)

**4e. Confidence levels** — every claim in the report should be marked:
- HIGH: verified directly from code
- MEDIUM: cross-validated from paper text + equations
- LOW: inferred partly from figures or from unclear code

Use `references/report_template.md` as the structure for the final report.

---

## Output Format

A single Markdown report named `deepdive_<paper_shortname>.md`, organized by innovation. For a paper with 3 innovations, the structure is:

```
# Deepdive: <Paper Title>

## TL;DR
## Setup (paper version, code commit, environment notes)

## Innovation 1: <name>
  ### Paper's claim
  ### Real implementation (code)
  ### Details the paper omits
  ### Paper-code discrepancies
  ### Reproduction checklist

## Innovation 2: <name>
  (same structure)

## Innovation 3: <name>
  (same structure)

## Cross-cutting findings
  (training tricks, data pipeline details, etc. that span multiple innovations)

## Open questions
  (things neither the paper nor the code resolves)
```

Each innovation section should be 200-600 words of dense, specific content — not generalities.

---

## Scripts

Run scripts in order. Each produces a JSON artifact the next consumes.

- `scripts/extract_innovations.py` — Stage 1. Input: paper PDF. Output: `paper_claims.json`.
- `scripts/analyze_figures.py` — Stage 2c. Input: paper PDF + innovation list. Output: `figure_analysis.json`.
- `scripts/locate_implementation.py` — Stage 3. Input: code repo path + `paper_claims.json`. Output: `code_map.json`.
- `scripts/deep_compare.py` — Stage 4. Input: all of the above. Output: final Markdown report.

These scripts are scaffolds. They handle file IO, PDF rendering, and repo traversal. The actual analysis (reading the PDF pages, deciding what's an innovation, filling schemas) is done by Claude reading their output — the scripts deliberately leave the judgment steps to the model.

## References

Read these when the stage indicates:

- `references/innovation_signals.md` — Stage 1. Heuristics for what counts as an innovation and how to rank them.
- `references/figure_analysis_protocol.md` — Stage 2c. The three-source cross-validation procedure for figures.
- `references/figure_schemas.md` — Stage 2c. Structured schemas for architecture diagrams, data-flow diagrams, etc.
- `references/hidden_details_checklist.md` — Stage 4. The checklist of "things the paper usually doesn't mention but the code contains".
- `references/report_template.md` — Stage 4. The final report structure.

## Examples

- `examples/flamingo_gated_xattn.md` — a worked example applying the full pipeline to Flamingo's Gated Cross-Attention.

## Interaction Style

Stay in dialog with the user. Specifically:
- After Stage 1, confirm innovations before drilling in.
- If the code repo version doesn't match the paper version, flag it and ask which the user cares about.
- When reporting discrepancies, distinguish "bug in code" vs "paper glossed over this" vs "code evolved after publication" — these mean different things to the user.
- Never claim certainty you don't have. If vision-based figure reading was involved, say so.
