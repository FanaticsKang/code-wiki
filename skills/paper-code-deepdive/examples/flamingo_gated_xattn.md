# Example: Flamingo Gated Cross-Attention

A worked example of applying the full paper-code-deepdive pipeline to one innovation from a real paper. This is meant as a reference for what the final output should look like — **one innovation done well** rather than an entire paper at surface level.

**Paper:** Alayrac et al., "Flamingo: a Visual Language Model for Few-Shot Learning" (NeurIPS 2022)
**Code reference:** Open-source reimplementation `lucidrains/flamingo-pytorch` (commit from 2022-10). Note that DeepMind never released official code, so the "code side" here is what reimplementers converged on after reading the paper carefully.

This example focuses on **one innovation: Gated Cross-Attention-Dense**, to show the depth expected per innovation.

---

## Stage 1: Innovation identification

From the abstract: *"…a novel architecture for visual language models, capable of processing sequences of arbitrarily interleaved visual and textual data… Flamingo models include key architectural innovations to: (i) bridge powerful pretrained vision-only and language-only models, (ii) handle sequences of arbitrarily interleaved visual and textual data…"*

Contribution bullets in Intro (paraphrased): Perceiver Resampler; Gated Cross-Attention-Dense layers; interleaved multimodal training.

Two core architectural innovations: **Perceiver Resampler** and **Gated Cross-Attention-Dense (GATED XATTN-DENSE)**. This example covers only the second.

```yaml
innovation:
  id: inn_2
  name: "Gated Cross-Attention-Dense"
  claimed_benefit: "Inject visual information into a frozen LM without destabilizing its pretrained knowledge at the start of training."
  location_in_paper:
    sections: ["3.1.2"]
    figures: [4]
    equations: []  # paper describes it inline with math, no numbered equations in main text
  key_terms: ["gated", "xattn", "cross-attention-dense", "tanh gate", "GATED XATTN"]
  type: "architectural"
```

---

## Stage 2: Innovation analysis (from paper)

### 2a. Text description (from §3.1.2)

The paper interleaves new **gated cross-attention-dense blocks** between pretrained (frozen) LM blocks. Each new block has two sub-layers: a cross-attention from LM tokens to visual tokens, then a dense (FFN) layer, each wrapped with a tanh-gated residual. The gates `α_xattn` and `α_dense` are **learnable scalars, initialized to 0**.

Key verbal claims to check:
1. The gates are scalar (per-block? per-head?)
2. Gates initialized to 0 (so at init, the block is an identity function and the frozen LM's behavior is preserved exactly)
3. `tanh` wrapper bounds gate output to (-1, 1)
4. Standard cross-attention internals (Q from LM, K/V from vision)
5. Pre-norm? Post-norm?

### 2b. Equation extraction

Paper writes (not as numbered equations, inline in §3.1.2):
- `y ← y + tanh(α_xattn) · xattn(q=y, kv=x)`
- `y ← y + tanh(α_dense) · FFW(y)`

Where `y` is the LM hidden state, `x` is the visual-token sequence from the Perceiver Resampler.

Missing from paper:
- Normalization placement (before xattn? on Q? on KV?)
- Whether `α` is scalar, per-head, or per-dimension
- Attention-internal details (scaling factor, dropout)

### 2c. Figure analysis (Figure 4)

Running the figure through the protocol:

**Source A (vision — low resolution):**
- Two stacked blocks: "XATTN" and "FFW" inside a box labeled "GATED XATTN-DENSE"
- Two gate symbols labeled `tanh(α_xattn)` and `tanh(α_dense)`
- Arrows show residual connections around each gate
- Annotation text next to gates (hard to read precisely): something about initialization

**Source B (caption + in-text):**
- Caption: "GATED XATTN-DENSE layers. Each layer applies cross-attention followed by a dense layer. The output of each is multiplied by a tanh-gated scalar α, initialized to 0 so the output equals the input at initialization."
- In-text §3.1.2: "These gates are initialized to 0 so that the model is initialized to the original LM."

**Source C (equations above):** match the vision.

Reconciliation:
- Gate mechanism: HIGH confidence, all three sources
- Zero init: HIGH confidence, caption + text
- **Scalar vs per-head:** UNRESOLVED from paper. Figure shows a single α, which suggests scalar, but a scalar could also be drawn the same way as a per-head vector. **Flag for Stage 3 code verification.**

---

## Stage 3: Code location

In the open reimplementation, grep for `gated` hits `flamingo_pytorch/flamingo_pytorch.py`:

```python
class GatedCrossAttentionBlock(nn.Module):
    def __init__(self, *, dim, dim_head=64, heads=8, ff_mult=4):
        super().__init__()
        self.attn = MaskedCrossAttention(dim=dim, dim_head=dim_head, heads=heads)
        self.attn_gate = nn.Parameter(torch.tensor([0.]))

        self.ff = FeedForward(dim, mult=ff_mult)
        self.ff_gate = nn.Parameter(torch.tensor([0.]))

    def forward(self, x, media, media_locations=None):
        x = self.attn(x, media, media_locations=media_locations) * self.attn_gate.tanh() + x
        x = self.ff(x) * self.ff_gate.tanh() + x
        return x
```

Resolved location: `flamingo_pytorch/flamingo_pytorch.py:143-160`.

---

## Stage 4: Deep compare

### What the paper claims

Gated cross-attention-dense layers inject visual information into a frozen LM. The block is two sub-layers (cross-attention, then FFN), each wrapped in a `tanh(α) * (...)` gate with `α` initialized to 0. Zero init makes the block an identity at step 0, preserving the LM's pretrained behavior; training gradually opens the gates to incorporate visual information.

### What the code actually does

Examining `GatedCrossAttentionBlock`:

- `attn_gate` and `ff_gate` are each `nn.Parameter(torch.tensor([0.]))` — **scalars** (1-element tensors), not per-head or per-dimension. Paper figure was ambiguous on this; code resolves it.
- Gate application: `self.attn(...) * self.attn_gate.tanh() + x` — residual is added *after* the gated output, matching the paper's equation.
- **No normalization inside this block.** The LayerNorm is inside `MaskedCrossAttention` and `FeedForward`.

Opening `MaskedCrossAttention` (at `flamingo_pytorch.py:88`):

```python
class MaskedCrossAttention(nn.Module):
    def __init__(self, *, dim, dim_head=64, heads=8, ...):
        ...
        self.norm = nn.LayerNorm(dim)
        self.to_q = nn.Linear(dim, inner_dim, bias=False)
        self.to_kv = nn.Linear(dim, inner_dim * 2, bias=False)
        ...

    def forward(self, x, media, ...):
        x = self.norm(x)           # pre-norm on Q
        q = self.to_q(x)
        media = rearrange(media, 'b t n d -> b (t n) d')
        k, v = self.to_kv(media).chunk(2, dim=-1)
        q = q * self.scale          # scale Q, not QK^T
        ...
```

### Details the paper omits

Running through `hidden_details_checklist.md`:

- **Gate initialization:** `nn.Parameter(torch.tensor([0.]))`. Paper says "initialized to 0" but not the exact shape. Code confirms: **scalar** (1-element tensor). Per-block, not per-head. `flamingo_pytorch.py:148, 151`.
- **Normalization placement:** **pre-norm on Q only**. K/V from visual tokens are *not* normalized before projection. Paper doesn't discuss this. `flamingo_pytorch.py:106`.
- **Attention scaling:** Q is scaled by `self.scale = dim_head ** -0.5` *before* the dot product with K. Mathematically equivalent to scaling the logits, but worth noting for reimplementers who might expect `logits / sqrt(d)`. `flamingo_pytorch.py:115`.
- **No bias in Q/K/V projections:** `nn.Linear(..., bias=False)`. Paper doesn't specify. `flamingo_pytorch.py:99-100`.
- **Cross-attention masking:** the `media_locations` argument masks so that text tokens only attend to preceding images in the interleaved sequence. Paper mentions this behavior in text but the exact masking logic is in code only. `flamingo_pytorch.py:117-130`.
- **No dropout** in either the attention or FFN by default in this implementation. Paper doesn't specify dropout in these new blocks.
- **FFN activation:** `GELU` (default in the `FeedForward` class). Paper doesn't specify.

### Paper-code discrepancies

- **Normalization placement discrepancy:** The paper's Figure 4 shows norms as small boxes that could plausibly appear on both Q and K/V paths. Code norms Q only. Likely explanation: the figure is schematic; the code follows the common pre-norm convention on the query stream only. **Minor** — unlikely to materially affect results but reimplementers who place norms differently may see divergent training dynamics.
- **None major.** The central mechanism (gate init, tanh wrap, residual order) matches between paper and this reimplementation.

### Reproduction checklist

- Use `nn.Parameter(torch.tensor([0.]))` (scalar) for each gate — **do NOT** use `nn.Parameter(torch.zeros(n_heads))` or similar.
- Two gates per block: one for cross-attention, one for FFN.
- Wrap with `.tanh()` before multiplying.
- Add residual **after** the gated output: `y = gate.tanh() * f(x) + x`.
- Pre-norm on Q only (in cross-attention); K/V unnormalized going in.
- Scale Q by `d_head^(-0.5)` before the dot product (not after).
- No bias in Q/K/V linear projections.
- FFN uses GELU, mult of 4x by default.
- No dropout by default.

### Confidence

- HIGH: gate scalar shape, zero init, tanh wrap, residual ordering, pre-norm-on-Q, Q-side scaling, no-bias projections
- MEDIUM: masking logic matches paper's intent (code is clear but paper's description of interleaved-attention is terse)
- LOW: whether the *official* DeepMind code also makes these choices — we only have reimplementations to work with. This is noted in Setup.

---

## What this example shows

1. **Depth beats breadth.** This entire document covers one innovation. A full deepdive would have one of these per innovation (2 for Flamingo). That's 200-600 words of dense specific content per innovation.

2. **Hidden details carry the value.** The "Details the paper omits" section surfaces things (gate shape, pre-norm-on-Q-only, no bias, no dropout default) that aren't in the paper but critically affect reproduction.

3. **Discrepancies must be specific, not vague.** "Normalization placement" with file:line > "some inconsistencies in normalization".

4. **Figure ambiguity → code verification.** The scalar-vs-per-head question from Figure 4 was explicitly flagged in Stage 2c and resolved in Stage 3 by reading the code. This is the Stage 2 → Stage 3 pipeline in action.

5. **Honest about confidence.** The LOW confidence on "official code matches" is important context — we are reading a reimplementation, not DeepMind's code. A real report should be explicit about this.
