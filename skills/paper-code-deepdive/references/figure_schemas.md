# Figure Schemas

Structured schemas for Stage 2c figure extraction. **Always fill a schema — do not describe figures freely.** Schemas expose uncertainty (you can't fill a field you're unsure of), which is exactly what we want to feed into Stage 3.

Output format is YAML-compatible. For each figure, produce one block matching one of the schemas below.

## When to use each schema

| Figure type | Schema |
|---|---|
| Architecture block diagram | `architecture_diagram` |
| Pipeline / data flow | `data_flow_diagram` |
| Algorithm / pseudocode box | `algorithm_box` |
| Attention / feature visualization | `visualization` (minimal) |
| Plot (loss, accuracy, etc.) | `plot` (minimal) |

---

## Schema: architecture_diagram

```yaml
figure_id: "Figure 2"  # as labeled in paper
page: 4
schema_type: architecture_diagram

blocks:
  - id: B1                    # arbitrary id, unique within this figure
    label: "Vision Encoder"   # text as it appears in figure
    type: module              # module | input | output | operation | gate | other
    repetition: 1             # integer, or "N" if figure shows Nx
    shape_in:  "[B, 3, H, W]" # if annotated, else null
    shape_out: "[B, N, D]"    # if annotated, else null
    confidence: HIGH

  - id: B2
    label: "Perceiver Resampler"
    type: module
    repetition: 1
    shape_in: null
    shape_out: "[B, 64, D]"
    confidence: HIGH

edges:
  - from: B1
    to: B2
    edge_type: forward        # forward | residual | skip | gated | attn_q | attn_k | attn_v | concat
    label: null               # any text annotation on the arrow itself
    confidence: HIGH

  - from: B2
    to: B3
    edge_type: forward
    confidence: MEDIUM        # arrow was unclear, inferred from text

annotations:
  - "× N in upper right corner of B5 — block repeats N times"
  - "dashed box encloses B2, B3, B4 — paper says this is the 'visual pathway'"
  - "α and β labels on gates — learnable scalars"

legend:
  - "solid arrow: forward pass"
  - "dashed arrow: gradient stop"

unresolved_questions:
  - "Does B2 take input from B1 only, or also from B6? Arrows cross near B6."
  - "Is the gate in B5 sigmoid or tanh? Both would look similar at this resolution."

sources_consulted:
  - vision: true
  - caption: true
  - in_text_references: ["§3.2 para 2", "§3.2 para 4"]
  - equations: ["Eq 3", "Eq 4", "Eq 5"]
```

Guidelines for filling:
- If you genuinely can't read a block label, put `label: "UNREADABLE"` and flag it as unresolved.
- Prefer fewer high-confidence entries over many low-confidence ones.
- `unresolved_questions` is **not** a failure section — it's the Stage 3 agenda. Be generous here.

---

## Schema: data_flow_diagram

For pipeline figures where blocks represent stages of processing (common in papers about multi-stage training, decoding pipelines, etc.).

```yaml
figure_id: "Figure 3"
page: 5
schema_type: data_flow_diagram

stages:
  - id: S1
    name: "Tokenize"
    input_shape: "raw text"
    output_shape: "[B, L]"
    operation_summary: "BPE tokenization"
    confidence: HIGH

  - id: S2
    name: "Encoder"
    input_shape: "[B, L]"
    output_shape: "[B, L, D]"
    operation_summary: "12 transformer layers"
    confidence: HIGH

transitions:
  - from: S1
    to: S2
    transformation: "embedding lookup"

annotations:
  - "All stages before S4 run offline, cached to disk"

unresolved_questions: []
```

---

## Schema: algorithm_box

For Algorithm blocks (`Algorithm 1: ...`). These should be transcribed almost verbatim — they're the easiest figure type to handle because they're already structured.

```yaml
figure_id: "Algorithm 1"
page: 6
schema_type: algorithm_box

title: "Training step"

inputs:
  - "x: input batch of shape [B, L]"
  - "θ: model parameters"
  - "η: learning rate"

outputs:
  - "θ': updated parameters"

steps:
  - step: 1
    content: "y_hat ← model(x; θ)"
  - step: 2
    content: "L ← cross_entropy(y_hat, y)"
  - step: 3
    content: "g ← ∇_θ L"
  - step: 4
    content: "θ' ← θ - η · g"

notes:
  - "Line 3: paper doesn't mention gradient clipping but algorithm shows raw gradient — check code"

unresolved_questions: []
```

---

## Schema: visualization (minimal)

For attention maps, generated samples, t-SNE plots, etc. We don't try to extract fine detail — just metadata.

```yaml
figure_id: "Figure 5"
page: 8
schema_type: visualization

subject: "attention maps across layers"
what_it_shows: "layer-8 head-3 attention from final token over image tokens"
architectural_claim: "model attends to object regions, not background"
relevance_to_innovation: LOW  # usually skip in Stage 4 unless paper makes a strong point
```

---

## Schema: plot (minimal)

For quantitative plots. Extract trend, not numbers (numbers come from tables).

```yaml
figure_id: "Figure 6"
page: 9
schema_type: plot

plot_type: "line_chart"
x_axis: "training steps"
y_axis: "validation loss"
compared_conditions: ["with innovation X", "without innovation X"]
qualitative_trend: "with X converges ~1.5x faster and to lower loss"
specific_numbers_in_paper_text: "§4.2 quotes final losses of 2.1 vs 2.4"
relevance_to_innovation: MEDIUM  # supports the claim that X helps
```

---

## Using the filled schemas

In Stage 3, open `figure_analysis.json` and for each figure:

1. Look at `unresolved_questions` — each is a code-reading task.
2. Look at edges with `confidence: MEDIUM` or `LOW` — verify from code's `forward()` method.
3. Look at `shape_in` / `shape_out` that are `null` — check if code reveals these via tensor operations.

In Stage 4, edges with `confidence: HIGH` go into the "paper's claim" column unchanged. Edges verified from code go into the "real implementation" column with code references.
