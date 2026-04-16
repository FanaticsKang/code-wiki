# Hidden Details Checklist

The highest-value output of this skill. Papers systematically omit a set of details that are essential for reimplementation. Go through this checklist for every innovation in Stage 4, checking the code.

Missing one of these is the single most common reason reproductions fail to match paper results.

## How to use this list

For each innovation, for each category below, answer:
1. What does the code actually do for this?
2. Did the paper say anything about it? (usually no)
3. Is the choice likely to matter for results?

If the answer to (1) is "not applicable" for this innovation (e.g., LayerNorm placement in a pure-loss innovation), skip it. Otherwise, surface it in the final report even if the paper didn't mention it — especially if the paper didn't mention it.

---

## Category 1: Initialization

Papers rarely specify how layers are initialized. Code always does.

- [ ] **Weight init scheme** — `xavier_uniform`, `kaiming_normal`, `trunc_normal`, custom? Look for `nn.init.*` calls or `reset_parameters()` methods.
- [ ] **Bias init** — zero? specific value? Some gates are initialized to drive sigmoid output near 0 or 1.
- [ ] **Learnable gates/scalars** — what initial value? Zero-init of a gate is a very different training dynamic than one-init.
- [ ] **LayerNorm γ / β** — usually γ=1, β=0, but some papers use custom init (e.g., ReZero uses γ=0).
- [ ] **Embedding init** — normal(0, σ) where σ depends on dim? Scaled by `1/sqrt(d)`?
- [ ] **Position embeddings** — learned, sinusoidal, RoPE, ALiBi? If learned, how initialized?
- [ ] **Output projection init** — some architectures zero-init the output projection of each residual block to stabilize training.

## Category 2: Normalization

- [ ] **Pre-norm vs post-norm** — where exactly is LayerNorm applied? Paper diagrams are often ambiguous on this.
- [ ] **Which norm type** — LayerNorm, RMSNorm, GroupNorm, BatchNorm? These are not interchangeable.
- [ ] **Norm in residual branch** — inside the residual (`x + norm(f(x))`) or outside (`norm(x + f(x))`)?
- [ ] **Final norm before output head** — some architectures have one; some don't.
- [ ] **ε in norm** — `1e-5` vs `1e-6` rarely matters, but very small models and fp16 training can be sensitive.
- [ ] **Bias in norm** — RMSNorm has no bias; some LayerNorm implementations optionally remove it.

## Category 3: Activation functions

- [ ] **Which activation** — ReLU, GELU (which variant? exact or tanh-approx?), SiLU/Swish, GLU/SwiGLU?
- [ ] **Activation location** — before or after projection?
- [ ] **Gated activation** — is there an explicit gate (SwiGLU-style)? Papers often write "FFN" and leave the gating implicit.

## Category 4: Attention details

- [ ] **Scaling** — `/ sqrt(d_k)`, `/ sqrt(d_head)`, or something else? Missing this is a very common bug.
- [ ] **Softmax dtype** — is softmax computed in fp32 even when the rest is fp16/bf16? This matters for stability.
- [ ] **Mask type** — causal, bidirectional, block, local? Exact implementation?
- [ ] **Mask value** — `-inf`, `-1e9`, `-1e4`? Affects fp16 behavior.
- [ ] **Attention dropout** — applied? Where (on softmax output)?
- [ ] **QK norm** — some recent papers apply LayerNorm/RMSNorm to Q and K before attention.
- [ ] **Output projection presence** — is there a final linear after attention? Usually yes, but some variants skip it.
- [ ] **Number of heads per layer** — varies? Constant?
- [ ] **KV caching behavior at inference** — does it exist? What's cached?

## Category 5: Dropout and regularization

- [ ] **Dropout rate(s)** — often paper says "we use dropout 0.1", code has multiple dropouts with different rates.
- [ ] **Dropout locations** — after attention? After FFN? On embeddings? On residual?
- [ ] **DropPath / stochastic depth** — common in vision transformers, rarely mentioned in papers.
- [ ] **Weight decay** — which parameters does it apply to? Usually excludes biases and norm parameters. Paper rarely specifies.
- [ ] **Label smoothing** — applied? Value?

## Category 6: Numerical stabilizers

Code is full of small `+1e-6` or `.clamp(...)` that don't appear in paper equations.

- [ ] **Epsilons** — `log(x + eps)`, `sqrt(x + eps)`, `x / (y + eps)`. What's eps?
- [ ] **Clamps** — `.clamp(min=..., max=...)` on logits, attention scores, ratios?
- [ ] **Log-space computation** — is something the paper writes as `a * b` actually computed as `exp(log(a) + log(b))` in code?
- [ ] **Softmax stabilization** — subtract max before exp? Usually handled by `torch.nn.functional.softmax`, but custom softmax needs manual care.

## Category 7: Training/inference branching

- [ ] **`if self.training:` branches** — what changes between train and eval?
- [ ] **Dropout behavior** — automatic via `.train()/.eval()`, but worth confirming.
- [ ] **BatchNorm stats** — using running mean/var at inference?
- [ ] **Temperature/sampling** — inference uses sampling or argmax? Temperature value?
- [ ] **EMA weights** — does inference use an EMA copy of the model? What decay?
- [ ] **Sliding window / chunking** — inference may chunk inputs the training loop doesn't.

## Category 8: Loss function details

- [ ] **Coefficient values** — paper says `L = L_main + L_aux`, code says `L = L_main + 0.01 * L_aux`. The coefficient matters a lot.
- [ ] **Loss reduction** — `mean` vs `sum` vs `none`? Matters when combining losses.
- [ ] **Masking in loss** — are padding tokens masked? How?
- [ ] **Ignore index** — is there an `ignore_index=-100` on CrossEntropy?
- [ ] **Class weights** — present? Computed from data?
- [ ] **Loss warmup** — some papers gradually ramp up auxiliary loss weights. Check for step-dependent coefficients.

## Category 9: Optimizer and schedule

- [ ] **Optimizer type and betas** — AdamW(β1=0.9, β2=0.95) is different from AdamW(β1=0.9, β2=0.999).
- [ ] **Parameter groups** — different learning rates for different parts of the model? Common for freezing pretrained backbones.
- [ ] **Weight decay exclusions** — which params don't get weight decay?
- [ ] **Gradient clipping** — value and type (norm vs value)?
- [ ] **Learning rate schedule** — warmup steps, decay type (cosine / linear / constant), min_lr?
- [ ] **Schedule variables** — by steps? epochs? tokens processed?

## Category 10: Data and input processing

- [ ] **Input normalization** — mean/std values for image input? Text tokenization special tokens?
- [ ] **Augmentations** — which, in what order, with what probabilities?
- [ ] **Collate function** — how is batching done? Padding side? Bucketing?
- [ ] **Input truncation / max length** — what's the actual cap at train vs eval?
- [ ] **Special tokens** — BOS, EOS, pad, mask — which are used where?

## Category 11: Precision and memory

- [ ] **Mixed precision** — fp16, bf16, fp8? Which ops upcast?
- [ ] **Gradient checkpointing** — where applied?
- [ ] **Flash attention / xformers** — which attention implementation is actually running?

## Category 12: Discrepancies to call out explicitly

When paper and code disagree, the disagreement itself is the finding. These are common places:

- Equation says softmax → code uses sigmoid (or vice versa)
- Paper says "ReLU" → code uses GELU (often because author copy-pasted from Transformer baseline)
- Paper says "L = L1 + L2" → code has coefficients
- Paper equation has `/ sqrt(d)` → code doesn't (or vice versa)
- Paper says "we use N layers" → code default is different
- Paper's architecture diagram shows X → code `forward()` does Y
- Paper says "random initialization" → code loads pretrained weights

For each discrepancy, note:
- Where in paper (section/equation/figure)
- Where in code (file:line)
- Likely explanation (bug? typo? paper simplified? code evolved?)
- Likely impact on results

## How to report these in Stage 4

For each innovation's section in the final report, include an "Details the paper omits" subsection that's a compressed version of this checklist — only the items that apply. Example:

> **Details the paper omits for Gated Cross-Attention**
>
> - Gates (`α`, `β`) are initialized to `0.0` via `nn.Parameter(torch.zeros(1))`. Paper says "learnable gate" but not the init; this init closes the path at training start so the frozen LM dominates initially.
> - Gate is scalar per layer (not per head). Code: `models/flamingo/xattn.py:47`.
> - Attention uses LayerNorm on both Q (from LM) and K/V (from vision) before the dot product. Paper's Figure 2 shows the norms but doesn't discuss them.
> - Cross-attention output dropout is 0.0 by default; FFN dropout is 0.1.

This is the single most useful part of the report for reproducers.
