# Report Template

The final output of Stage 4. Copy this structure and fill for each deepdive.

Save as `deepdive_<paper_shortname>.md` alongside the JSON artifacts.

---

```markdown
# Deepdive: <Paper Title>

**Paper:** <authors, venue, year>
**arXiv:** <arxiv id or link>
**Code:** <repo url + commit hash used for this analysis>
**Analyzed:** <date>

## TL;DR

<3-5 sentences. What are the core innovations? What's the most surprising finding from comparing paper to code? Any major discrepancies?>

## Setup

- **Paper version analyzed:** v<N> (arXiv date <date>)
- **Code commit:** `<sha>` from <branch>, dated <date>
- **Framework:** PyTorch X.Y / JAX / etc.
- **Reproducibility notes:** <any caveats about version mismatch, partial open-source, etc.>

---

## Innovation 1: <Name>

**Paper location:** §<X.Y>, Eq. <N-M>, Fig. <N>
**Code location:** `<path/to/file.py>:<line-range>`
**Type:** architectural | training | data | inference

### What the paper claims

<1-2 paragraphs. What is this innovation? What does the paper say it does? What's the motivation? Cite the specific equations/figures verbatim as needed. Keep this aligned with what the paper actually says — no interpretation yet.>

### What the code actually does

<The actual `nn.Module` or function, annotated. Short code blocks interspersed with explanation. Prefer showing the key parts over pasting the whole file.>

```python
class GatedCrossAttention(nn.Module):
    def __init__(self, dim, n_heads):
        super().__init__()
        self.attn = CrossAttention(dim, n_heads)
        self.ffn = FFN(dim)
        # Gates initialized to ZERO — path closed at start
        self.attn_gate = nn.Parameter(torch.zeros(1))
        self.ffn_gate = nn.Parameter(torch.zeros(1))

    def forward(self, x, context):
        x = x + self.attn(x, context) * self.attn_gate.tanh()
        x = x + self.ffn(x) * self.ffn_gate.tanh()
        return x
```

<Highlight what this code reveals that the paper didn't spell out. Keep this focused on structure/mechanism, not the laundry list of hidden details — those come in the next subsection.>

### Details the paper omits

<Bulleted list. Work through `hidden_details_checklist.md` and surface only the items that apply to this innovation. Each bullet should be specific: a value, a file:line, and why it matters.>

- **Gate initialization:** `nn.Parameter(torch.zeros(1))` at `models/xattn.py:23`. Paper says "learnable gate" but not the init. Zero-init means the cross-attention path contributes nothing at step 0, so the frozen LM's outputs are preserved initially and only gradually incorporated — a form of curriculum.
- **Gate shape:** scalar per layer, not per head. Paper is ambiguous. (`models/xattn.py:23`)
- **QK normalization:** both Q and K go through a shared LayerNorm before the dot product. Paper's Figure 2 shows these norms but doesn't discuss them. (`models/xattn.py:41-44`)
- **Attention dropout:** `0.0` at training. (`configs/flamingo_9b.yaml`)
- **Cross-attention masking:** masks out image tokens from different samples in the same batch. Not mentioned in paper. (`models/xattn.py:55-62`)

### Paper-code discrepancies

<If any. Otherwise write "None found." For each: where in paper, where in code, likely explanation, likely impact.>

- **Softmax vs. sigmoid (resolved):** Eq. 5 in paper uses softmax. Code at `models/xattn.py:48` uses softmax as expected. No discrepancy. [Retained as an example of a verified non-discrepancy.]
- **Layer count:** Paper §4.1 says "we use 32 cross-attention layers". Code default at `configs/flamingo_9b.yaml:17` is `n_xattn_layers: 24`. Likely: paper describes 9B model with 32, config shown is the 3B variant.
- **Initialization scheme for xattn projection:** Paper doesn't specify. Code uses `nn.init.trunc_normal_(std=0.02)` (`models/xattn.py:18`), same as the LM's own init.

### Reproduction checklist

<Concrete actionable items for someone reproducing this innovation. Mention exact files, values, behaviors to replicate.>

- Use `nn.Parameter(torch.zeros(1))` for gates (do NOT use `torch.ones` or random init)
- Scalar gate per layer, applied via `.tanh()` before multiplication
- Apply LayerNorm to both Q and K before attention
- Default attention dropout: 0.0
- Default xattn layer count depends on model size: 24 for 3B, 32 for 9B, 40 for 80B
- Per-batch sample masking on image tokens

### Confidence

- HIGH: mechanism (gate + residual), gate init value, scalar-per-layer shape, QK norm presence
- MEDIUM: per-sample mask logic (code is clear but paper doesn't confirm this is the intended behavior)
- LOW: none

---

## Innovation 2: <Name>

<Same structure as Innovation 1.>

---

## Innovation 3: <Name>

<Same structure as Innovation 1. Omit this whole section if the paper has only 1-2 innovations.>

---

## Cross-cutting findings

<Findings that don't belong to a single innovation: training tricks that affect all innovations together, data pipeline details, systemic choices.>

- **Mixed precision:** bf16 throughout with fp32 master weights. Softmax runs in fp32.
- **Optimizer:** AdamW(β1=0.9, β2=0.95, ε=1e-8), weight decay 0.1, applied with exclusions for biases and LayerNorm params.
- **LR schedule:** cosine decay from 1e-4 to 1e-5 over 500k steps with 5k linear warmup.
- **Gradient clipping:** 1.0 global norm.
- **Data loading:** custom shard format, shuffled at document level not sample level.

## Open questions

<Things neither paper nor code fully resolves. Honest open questions are better than fabricated answers.>

- The paper claims scaling to 80B parameters; the open-source repo only provides 3B and 9B configs. Architecture choices might differ at 80B.
- Training data mixture weights are hardcoded in a config that references paths we don't have access to.
- The paper's ablation shows +2.3 pp on benchmark X from Innovation 2, but the public code's config matches the ablation baseline, not the final model. Full config is likely unpublished.

## Appendix: extracted artifacts

- `paper_claims.json` — Stage 1 output (innovation list)
- `innovation_analysis.json` — Stage 2 output (text + equations + figure schemas)
- `code_map.json` — Stage 3 output (innovation → code location map)
- `figure_analysis.json` — Stage 2c detailed figure schemas
```

---

## Guidelines for writing the report

### Length per innovation
200-600 words of *specific, dense* content per innovation. If you're writing less than 200, you probably haven't gone deep enough. If you're over 600, you've probably drifted into generality.

### Voice
Descriptive and precise, not editorial. "The gate is initialized to zero" not "curiously, the gate is initialized to zero". Save judgment for the TL;DR and cross-cutting findings sections.

### Specificity
Every claim should have evidence: a file:line, a paper section, or a figure reference. Vague claims erode trust in the whole report.

### What to cut
If a detail doesn't affect understanding or reproduction, cut it. This is a deepdive for practitioners, not a complete code walkthrough.

### What not to cut
Never cut the discrepancies section, even if discrepancies are minor. The presence of a "none found" statement is itself evidence of careful verification.
