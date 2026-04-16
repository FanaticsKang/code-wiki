# Innovation Signals

This reference helps Stage 1 identify the *real* core innovations in a paper, separating them from background, incremental tweaks, and engineering details.

## What counts as an innovation

A "core innovation" in this skill's sense is something that satisfies **at least two** of these:

1. The paper gives it a proper name (capitalized, often with "the" in front: "the Perceiver Resampler").
2. It appears in the Abstract's contribution sentences.
3. It has its own subsection in the Method (not just a paragraph).
4. It's the subject of an ablation row that shows meaningful delta.
5. It appears as a labeled block in Figure 1 or Figure 2.
6. It has its own equation or algorithm block.

Things that usually aren't the "core innovation" even if they feel novel:
- Data preprocessing choices (unless the paper is explicitly about data)
- Training tricks like learning rate schedules (unless the paper is about optimization)
- Implementation optimizations (unless the paper is about systems)
- Evaluation protocols

## The contribution bullet list trick

Most ML papers have a bullet list near the end of the Introduction that reads like:

> Our contributions are:
> 1. We propose X, a novel mechanism for ...
> 2. We show that X achieves ... on ...
> 3. We release the code at ...

**Bullet 1 (and sometimes 2) are almost always the true innovations.** The others are usually "we ran experiments" and "we released code". Don't mistake those for contributions.

## Distinguishing architectural innovations from training innovations

Both are valid, but they need different analysis in Stage 4:

- **Architectural** (new module, new connection pattern, new attention variant) — code lives in the `nn.Module` subclass and its `forward()`
- **Training** (new loss, new optimizer behavior, new curriculum) — code lives in the training loop and loss module, not the model
- **Data/input** (new tokenization, new augmentation) — code lives in the dataset class and collate_fn
- **Inference** (new decoding, new sampling, new calibration) — code lives in a generate/decode function

Mark which category in the `paper_claims.json` so Stage 3 knows where to look.

## Ranking when there are many candidates

If a paper seems to have 5+ candidate innovations, prioritize:

1. Ones that appear in **both** the Abstract and a named Method subsection
2. Ones with their own ablation row
3. Ones with a dedicated figure

Deprioritize or merge:
- Two "innovations" that are actually just different views of the same mechanism
- Innovations that are explicitly described as straightforward combinations of prior work ("we use standard X with Y")

3 innovations is the practical ceiling for one deepdive report. If the user wants more, generate separate reports.

## Red flags — things that look like innovations but aren't

- "We use a Transformer" — that's architecture choice, not innovation
- "We train on dataset X with objective Y" — that's setup, not innovation
- "We scale to N parameters" — only if the paper is explicitly a scaling paper
- Renamed standard components — if "Our Novel Attention" is literally standard attention with a different name, it's marketing, not innovation. Check the equations: if they're standard scaled dot-product attention, treat the novelty as "the claim", not "the mechanism".

## Example

Paper: **"Flamingo: a Visual Language Model for Few-Shot Learning"**

Signals in the Abstract:
- "Perceiver Resampler" (named, prominent)
- "gated cross-attention-dense layers" (named)
- "few-shot learning" (this is a capability claim, not an innovation)

Signals in Figure 1/2:
- Perceiver Resampler is a labeled block
- GATED XATTN-DENSE blocks are visually distinct

Signals in Method subsections:
- §3.1 Visual processing and the Perceiver Resampler
- §3.2 Conditioning frozen language models on visual representations (this is about gated xattn)

Conclusion: 2 core innovations — (1) Perceiver Resampler, (2) Gated Cross-Attention-Dense. "Few-shot learning" is a capability, not a mechanism to deepdive.
