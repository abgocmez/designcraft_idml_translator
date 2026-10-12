# R3: Hy-MT2-7B prompt templates for idml-translate (measured)

Model `hf.co/tencent/Hy-MT2-7B-GGUF:Q4_K_M` on Ollama 0.13.5 (RTX 4060 8 GB), `/api/chat`, single user turn,
no system prompt, sampling `temperature 0.7, top_p 0.6, top_k 20, repeat_penalty 1.05` unless stated.
Evaluation set: `research/eval/eval_set.jsonl` (93 items). Harness: `research/eval/run_eval.py`. Raw calls:
`research/eval/results/raw.jsonl`; per-call metrics: `results/metrics.jsonl`; all tables: `results/summary.md`.
Full rerun from scratch: `python research/eval/run_eval.py` (≈25 min of model time; this run used 1294 s for the
first pass + ≈2.5 min for the follow-up stages).

---

## 0. Recommendations at a glance

| Segment class | Template | Measured result (TR / DE) |
|---|---|---|
| Plain body (≥ 7 words, no markup) | **P: Terminology + Default** (V2; no terms → plain Default V1b) | body refs 100% / 100% (11 refs); tags/numbers/DNT 100%; 0 added text; 0 context bleed |
| Short or ambiguous (≤ 6 words, or role headline/kicker/folio/table/caption/pull quote) | **S: Terminology + Contextual** (V4g) + ALL-CAPS folding | short refs 77% / 93% as-is; ALL-CAPS items with folding 100% / 93% ref, 100% / 100% case |
| Tagged or placeholder, long | **T: Structured Data 1 + Terminology** (V3g) | tags 100% / 100%, placeholders (multiset) 100% / 100%, refs 94% / 83% |
| Tagged or placeholder, short | **TS: Structured Data 1 + Terminology + Context** (V3cg) with echo guard → fall back to T | same structure scores; fixes sense ("The Grid Issue" → "Sayısı"/"Ausgabe" rather than "Sorunu"/"Problematik") |
| Consecutive short paragraphs of one heading (e.g. Cover Title "The Quiet" + "Art of Layout") | join with `⟦n⟧`, translate with TS | boundary kept 18/18, natural headline 18/18 |
| Concise (overset fit) | **C: Style "concise, keep every statement"** (V5b) | length 0.90 / 0.86 of normal translation (p50) |
| Concise acceptance | length ≥ **0.80 ×** normal translation, plus (optional) greedy back-translation Δ ≥ −0.25 | catches 30/34 deliberate omissions (sentence drops 14/14, clause drops 16/20); rejects 3/40 real concise outputs |
| Back-translation | **B: Default into English, greedy** (`temperature 0, top_k 1`) | see §10: adds no detections beyond the length gate in this set |
| Retry (validator failure) | **R: T for markup / S for plain, temperature 0.2**; context-bleed flag → retry *without* context | fixed 30/32 failures; the 2 left were German "Cyan" (correct as is) |
| Placeholder format | **`⟦n⟧`**, normalise look-alikes `⟨n⟩ 〚n〛 〔n〕` back to `⟦n⟧` before validating | 99% multiset kept; the only format that survived a template *without* placeholder rules |
| Batching | **No.** Send one segment per request; optionally 2 parallel requests | batching was only +10–16% faster and cannot carry per-segment context or glossary |
| Throughput | 50 segments in 43 s (TR) / 38 s (DE) sequential; 37 s / 31 s with 2 parallel requests | target "50 < 3 min" is met by about 4× |

The single biggest quality lever was the **glossary** (Terminology template). Context alone (V4) gave modest gains
(short items +6–7 pp) but large gains when combined with ALL-CAPS folding (+43 pp TR, +15 pp DE). Lower temperature
does **not** fix wrong word senses (§11).

### Caveats (read before using the numbers)
- **Template wording.** I had no network access beyond Ollama, so I could not re-read the Hy-MT2 model card. "V1b"
  is the Hunyuan-MT English default template as I know it (`Translate the following segment into {lang}, without
  additional explanation.`). Terminology/Contextual are English renderings of the Hunyuan-MT (v1) Chinese
  templates. "V1", "V3" and "V5a" are the prototype's wording (`demo_translate.py`), which looks copied from the Hy-MT2
  card. If the card's exact wording differs, rerun the harness with it; the harness makes this a one-line change.
- **Glossary circularity.** I wrote the eval glossary (`build_eval_set.py: GLOSSARY`), knowing the reference
  expectations. V2/V4g/V3g reference scores therefore measure *"the model applies glossary terms"*. They are an upper
  bound, not unaided translation quality. V1b vs V4 is the unaided comparison.
- References are substring checks I wrote myself (`any_of` / `all_of` / `must_not`), not human judgments. n is
  small (61 referenced items per language; 8 tagged; 20 placeholder items). Differences of 1–2 items are noise.
- The main grid ran one sample per cell with a fixed seed (42), so it is reproducible. Sampling/multipara stages
  used random seeds.

---

## 1. Method

**Eval set** (`build_eval_set.py` regenerates `eval_set.jsonl`): 35 real segments from `sample_en.idml`, in reading
order with real prev/next neighbours: folios, kickers, cover titles, headline, decks, caption, 5 body paragraphs,
footnote, pull quote, swatch captions, every table header and cell. Plus 58 synthetic items:
- tagged runs: 2–4 tags, a tag around one word mid-sentence, nested tags, DNT inside tags, the real 2-run paragraph;
- placeholders: 5 sentences × 4 formats (`⟦n⟧`, `{n}`, `<xn/>`, `[[n]]`) for tab, line break, URL+email,
  number-with-unit, key name;
- numbers/units/dates (`8 pt`, `3.5 mm`, `1,200`, `40%`, `March 15, 2026`, ranges);
- DNT (`DesignCraft`, `InDesign`, `IDML`, `PDF`, `Pantone 186 C`, `Quarterly`);
- ALL CAPS (8), Title Case (3), typographic terms (kerning, leading, gutter, bleed, widow/orphan, pull quote,
  baseline grid);
- multi-paragraph heading forms (coordinator request): `⟦1⟧`/`{1}`/`<x1/>`/`[[1]]` boundary, `\n`, and
  `<g0>The Quiet</g0><g1>Art of Layout</g1>`.

Each item has id, source, category, role, paragraph style, prev/next, DNT list, per-language glossary hits
(attached automatically when the source term occurs) and per-language reference checks.

**Metrics** (`run_eval.py: evaluate`). `tag_ok` means same `<gN>` sequence (multiset, order) and valid
nesting. Also: `tag_text_outside` (text outside every tag, which would be lost); `ph_multiset` / `ph_ok` (+order);
`numbers_ok` (digit strings with `.`/`,` removed, as a multiset, so `1,200`→`1.200` and `3.5`→`3,5` pass;
`numbers_strict_ok` without normalisation); `dnt_ok` (verbatim); `untranslated` (casefolded identity, minus the
code-like exemption, §8); `mostly_source` (≥ 50% of ≥ 3 source content words copied); `added_any` (prefix such as
"Here is/Translation:", added surrounding quotes, notes, extra lines, leaked context labels); `len_ratio`
(target/source characters, markers stripped); `ref_ok`; `case_ok` (all-caps source → all-caps output).

**Variants**

| id | description |
|---|---|
| V1 | prototype default (`Translate the following text into X. Note that you should **only output the translated result without any additional explanation**:`) |
| V1b | model-card default (`Translate the following segment into X, without additional explanation.`) |
| V2 | Terminology (glossary hits + DNT as identity terms) + V1b |
| V4 | Contextual / Structured Data 2: synopsis, paragraph style, role, prev/next + instruction |
| V4g | V4 with the terminology block first |
| V3 | Structured Data 1 (prototype tagged prompt; for placeholder items rule 1 names the actual placeholders) |
| V3g | V3 + `### Terminology` section |
| V3cg | V3g + `### Context (do not translate)` section |
| V3b | Hunyuan-MT v1 "formatted" template (`<source>…</source>` → `<target>…</target>`) |
| V5a / V5b | Style "concise" (prototype wording / "keep every statement, name and number") |

---

## 2. Recommended templates (exact strings)

Python `str.format` placeholders. `{lang}` is the full English language name (`Turkish`, `German`). Blank lines are
significant. Omit a block entirely when it would be empty.

### 2.1 Terminology block (shared)
One line per glossary entry whose source term occurs in the segment (whole word, case-insensitive; longest match
first; drop a shorter term that only occurs inside a longer matched one). Then one identity line per DNT term
present:
```
Refer to the following translation:
{source_term} translates to {target_term}
{dnt_term} translates to {dnt_term}
```

### 2.2 P: plain body (≥ 7 words, no tags/placeholders)
```
{terminology_block}

Translate the following segment into {lang}, without additional explanation.

{source_text}
```
With no terms, this reduces to exactly V1b (`Translate the following segment into {lang}, without additional
explanation.\n\n{source_text}`). V1 (prototype) and V1b scored the same on refs (TR 51%/51%, DE 46%/51%). V1b
lost one tag on an untagged prompt, which is irrelevant here because tagged text goes to T. V1b is shorter and is the
card wording.

### 2.3 S: short or ambiguous (≤ 6 words, or role ∈ headline, kicker, folio, table header/cell, caption, pull quote)
```
{terminology_block}

Document: {synopsis}
Paragraph style: {style_name}
Segment role: {role_description}
Previous paragraph: {prev_text, clipped to 300 chars}
Next paragraph: {next_text, clipped to 300 chars}

Refer to the information above and translate the following text into {lang}. Note that you do not need to translate the information above, and do not add any explanation:

{source_text}
```
Role descriptions used: `headline`, `kicker (short section label above a headline)`, `folio (page footer with page
number and magazine name)`, `table column header`, `table cell`, `image caption`, `body text paragraph`, `footnote`,
`pull quote`. Synopsis used: `Spring issue of a design magazine, 'Quarterly'; feature article about layout grids and
typography.`

**Always give prev/next paragraphs.** All 6 context-bleed cases (§9) happened on items whose only context was the
synopsis (6/288 such calls; 0/140 on real items with neighbours).

Pre/post-processing for S (and TS):
- **ALL CAPS** (every letter uppercase, ≥ 2 letters, not code-like): send sentence case (`s.lower()`, first letter
  upper), then uppercase the output locale-aware (TR `i→İ`, `ı→I` before `upper()`). If the caps come from
  `Capitalization="AllCaps"` in the style (e.g. Kicker "Feature · Design"), send the literal text and leave the
  output's case alone. §7.
- **Lost initial capital**: if the source starts uppercase and the output starts lowercase, uppercase the first letter
  locale-aware. Glossary targets get pasted lowercase ("ızgara Üzerine Notlar"): 1–2 cases per 84 in V2/V4g TR.

### 2.4 T: tagged or placeholder segments (long)
```
### Task
Translate the user-facing text within the following XML data into {lang}.

### Terminology
{source_term} translates to {target_term}
{dnt_term} translates to {dnt_term}

### Strict Rules
1. **Structure Preservation:** You MUST keep every tag (<g0>, </g0>, <g1>, …) exactly once, in the same order, wrapping the words that correspond to the original.
2. **Selective Translation:** Translate ONLY the text between the tags.
3. **Strict Non-Translation:** NEVER translate, rename, add or remove tags.
Output ONLY the translated XML.

### Source Data
{source_text}
```
For placeholder-only segments, rule 1 becomes: `1. **Structure Preservation:** You MUST keep every placeholder (⟦1⟧,
⟦2⟧) exactly once, in the same order, at the position that corresponds to the original.` (list the placeholders that
actually occur). Segments with both tags and placeholders use the tag wording; placeholders were still kept.

### 2.5 TS: tagged or placeholder segments (short, ≤ 6 words)
T plus a context section between Terminology and Strict Rules:
```
### Context (do not translate)
Document: {synopsis}
Paragraph style: {style_name}
Segment role: {role_description}
Previous paragraph: {prev}
Next paragraph: {next}
```
Guard with the synopsis-echo check (§9). If flagged, retry with T.

### 2.6 Multi-paragraph headings (coordinator item 1)
Join consecutive paragraphs that share one heading style (Cover Title / Headline) and are short. Example: Story_u18
"The Quiet" `<Br/>` "Art of Layout" becomes `The Quiet⟦1⟧Art of Layout`. Translate with TS and split the output at
`⟦1⟧`. Measured outputs: TR `Düzenlemenin Sessiz⟦1⟧Sanatı`, DE `Die stille⟦1⟧Kunst des Layouts` (§5). Line lengths
change (TR line 1 gets longer), so the fit check must cover these frames.

### 2.7 C: concise retranslation (overset fit)
```
Please translate the following text into {lang}. Note that the translation style must strictly conform to [**concise**]. Keep every statement, name and number of the original; shorten only the wording:

{source_text}
```
Second, stronger attempt if C is not short enough (prototype wording V5a):
```
Please translate the following text into {lang}. Note that the translation style must strictly conform to [**concise: as short as possible while keeping the full meaning**]:

{source_text}
```
Tagged concise (prototype adds ` Keep it concise.` to T's task line): **not measured**. Treat it as unvalidated.

### 2.8 B: back-translation (for the concise check)
```
Translate the following segment into English, without additional explanation.

{candidate_text}
```
Options `temperature 0, top_k 1`. Back-translate the normal translation the same way, once, and compare the two
(§10).

### 2.9 R: retry-strict
- Structural failure (tags, placeholders, numbers, DNT, newline count): resend with **T** (markup) at
  `temperature 0.2`.
- Untranslated or plain-text failure: resend with **S** at `temperature 0.2`.
- Context-bleed flag (§9) or length above the upper bound: resend **without context** (P, or T for markup).
- After 2 retries: keep the source text and flag the segment (invariant 4).
Measured: 30/32 main-grid failures fixed by one retry (§11).

---

## 3. Results per variant × language

All tables below are copied from `results/summary.md` (regenerate with `--report-only`). "ph_ok" in the first table
requires placeholder *order*. Use the multiset column in §6 for validation, because Turkish legitimately reorders
`⟦1⟧ … ⟦2⟧` (SOV order: "…⟦2⟧ satır aralığıyla ⟦1⟧…").

#### Main grid: metric pass rates per variant × language (all items the variant ran on)

| variant | lang | n | ref_ok | case_ok | tag_ok | ph_ok | nl_ok | numbers_ok | dnt_ok | untranslated | mostly_source | added_any | context_leak | median s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| V1 | tr | 93 | 51% (31/61) | 79% (11/14) | 100% (8/8) | 85% (17/20) | 100% (1/1) | 100% (14/14) | 100% (5/5) | 1% (1/93) | 0% (0/47) | 0% (0/93) | 0% (0/93) | 0.47 |
| V1 | de | 93 | 46% (28/61) | 86% (12/14) | 100% (8/8) | 100% (20/20) | 100% (1/1) | 100% (14/14) | 100% (5/5) | 4% (4/93) | 0% (0/47) | 0% (0/93) | 0% (0/93) | 0.46 |
| V1b | tr | 93 | 51% (31/61) | 79% (11/14) | 88% (7/8) | 95% (19/20) | 100% (1/1) | 100% (14/14) | 100% (5/5) | 1% (1/93) | 0% (0/47) | 0% (0/93) | 0% (0/93) | 0.52 |
| V1b | de | 93 | 51% (31/61) | 93% (13/14) | 100% (8/8) | 100% (20/20) | 100% (1/1) | 100% (14/14) | 100% (5/5) | 1% (1/93) | 0% (0/47) | 0% (0/93) | 0% (0/93) | 0.47 |
| V2 | tr | 93 | 84% (51/61) | 79% (11/14) | 88% (7/8) | 100% (20/20) | 100% (1/1) | 100% (14/14) | 100% (5/5) | 1% (1/93) | 0% (0/47) | 0% (0/93) | 0% (0/93) | 0.52 |
| V2 | de | 93 | 92% (56/61) | 64% (9/14) | 100% (8/8) | 100% (20/20) | 100% (1/1) | 100% (14/14) | 100% (5/5) | 0% (0/93) | 0% (0/47) | 0% (0/93) | 0% (0/93) | 0.45 |
| V4 | tr | 93 | 59% (36/61) | 93% (13/14) | 100% (8/8) | 95% (19/20) | 100% (1/1) | 100% (14/14) | 100% (5/5) | 2% (2/93) | 0% (0/47) | 0% (0/93) | 0% (0/93) | 0.51 |
| V4 | de | 93 | 61% (37/61) | 79% (11/14) | 62% (5/8) | 95% (19/20) | 100% (1/1) | 100% (14/14) | 100% (5/5) | 4% (4/93) | 2% (1/47) | 0% (0/93) | 0% (0/93) | 0.50 |
| V4g | tr | 93 | 87% (53/61) | 71% (10/14) | 100% (8/8) | 95% (19/20) | 100% (1/1) | 100% (14/14) | 100% (5/5) | 0% (0/93) | 0% (0/47) | 0% (0/93) | 0% (0/93) | 0.52 |
| V4g | de | 93 | 90% (55/61) | 57% (8/14) | 75% (6/8) | 75% (15/20) | 100% (1/1) | 100% (14/14) | 100% (5/5) | 1% (1/93) | 0% (0/47) | 0% (0/93) | 0% (0/93) | 0.50 |
| V3 | tr | 28 | 67% (12/18) | – | 100% (8/8) | 90% (18/20) | – | 100% (1/1) | 100% (1/1) | 0% (0/28) | 0% (0/21) | 0% (0/28) | 0% (0/28) | 0.86 |
| V3 | de | 28 | 50% (9/18) | – | 100% (8/8) | 100% (20/20) | – | 100% (1/1) | 100% (1/1) | 0% (0/28) | 0% (0/21) | 0% (0/28) | 0% (0/28) | 0.80 |
| V3g | tr | 28 | 94% (17/18) | – | 100% (8/8) | 100% (20/20) | – | 100% (1/1) | 100% (1/1) | 0% (0/28) | 0% (0/21) | 0% (0/28) | 0% (0/28) | 0.89 |
| V3g | de | 28 | 83% (15/18) | – | 100% (8/8) | 100% (20/20) | – | 100% (1/1) | 100% (1/1) | 0% (0/28) | 0% (0/21) | 0% (0/28) | 0% (0/28) | 0.80 |
| V3cg | tr | 28 | 94% (17/18) | – | 100% (8/8) | 95% (19/20) | – | 100% (1/1) | 100% (1/1) | 0% (0/28) | 0% (0/21) | 0% (0/28) | 0% (0/28) | 0.92 |
| V3cg | de | 28 | 83% (15/18) | – | 100% (8/8) | 100% (20/20) | – | 100% (1/1) | 100% (1/1) | 0% (0/28) | 0% (0/21) | 0% (0/28) | 0% (0/28) | 0.82 |
| V3b | tr | 8 | 67% (4/6) | – | 100% (8/8) | – | – | 100% (1/1) | 100% (1/1) | 0% (0/8) | 0% (0/5) | 0% (0/8) | 0% (0/8) | 1.08 |
| V3b | de | 8 | 17% (1/6) | – | 75% (6/8) | – | – | 100% (1/1) | 100% (1/1) | 0% (0/8) | 0% (0/5) | 0% (0/8) | 0% (0/8) | 1.01 |

#### Short / ambiguous items (≤ 6 words, no markup) with references

| variant | lang | n | ref_ok | case_ok | untranslated | added_any |
|---|---|---|---|---|---|---|
| V1 | tr | 30 | 30% (9/30) | 79% (11/14) | 3% (1/30) | 0% (0/30) |
| V1 | de | 30 | 40% (12/30) | 86% (12/14) | 7% (2/30) | 0% (0/30) |
| V1b | tr | 30 | 37% (11/30) | 79% (11/14) | 3% (1/30) | 0% (0/30) |
| V1b | de | 30 | 50% (15/30) | 93% (13/14) | 3% (1/30) | 0% (0/30) |
| V2 | tr | 30 | 77% (23/30) | 79% (11/14) | 3% (1/30) | 0% (0/30) |
| V2 | de | 30 | 93% (28/30) | 64% (9/14) | 0% (0/30) | 0% (0/30) |
| V4 | tr | 30 | 43% (13/30) | 93% (13/14) | 7% (2/30) | 0% (0/30) |
| V4 | de | 30 | 57% (17/30) | 79% (11/14) | 10% (3/30) | 0% (0/30) |
| V4g | tr | 30 | 77% (23/30) | 71% (10/14) | 0% (0/30) | 0% (0/30) |
| V4g | de | 30 | 93% (28/30) | 57% (8/14) | 0% (0/30) | 0% (0/30) |

#### Tagged items (<gN>)

| variant | lang | n | tag_ok | tag_multiset | tag_order | tag_nesting | tag_text_outside | ref_ok | added_any |
|---|---|---|---|---|---|---|---|---|---|
| V1 | tr | 8 | 100% (8/8) | 100% (8/8) | 100% (8/8) | 100% (8/8) | 0% (0/8) | 67% (4/6) | 0% (0/8) |
| V1 | de | 8 | 100% (8/8) | 100% (8/8) | 100% (8/8) | 100% (8/8) | 0% (0/8) | 17% (1/6) | 0% (0/8) |
| V1b | tr | 8 | 88% (7/8) | 88% (7/8) | 88% (7/8) | 88% (7/8) | 0% (0/8) | 67% (4/6) | 0% (0/8) |
| V1b | de | 8 | 100% (8/8) | 100% (8/8) | 100% (8/8) | 100% (8/8) | 0% (0/8) | 17% (1/6) | 0% (0/8) |
| V2 | tr | 8 | 88% (7/8) | 88% (7/8) | 88% (7/8) | 88% (7/8) | 0% (0/8) | 83% (5/6) | 0% (0/8) |
| V2 | de | 8 | 100% (8/8) | 100% (8/8) | 100% (8/8) | 100% (8/8) | 0% (0/8) | 50% (3/6) | 0% (0/8) |
| V4 | tr | 8 | 100% (8/8) | 100% (8/8) | 100% (8/8) | 100% (8/8) | 0% (0/8) | 67% (4/6) | 0% (0/8) |
| V4 | de | 8 | 62% (5/8) | 62% (5/8) | 62% (5/8) | 100% (8/8) | 38% (3/8) | 17% (1/6) | 0% (0/8) |
| V4g | tr | 8 | 100% (8/8) | 100% (8/8) | 100% (8/8) | 100% (8/8) | 0% (0/8) | 83% (5/6) | 0% (0/8) |
| V4g | de | 8 | 75% (6/8) | 75% (6/8) | 75% (6/8) | 100% (8/8) | 25% (2/8) | 50% (3/6) | 0% (0/8) |
| V3 | tr | 8 | 100% (8/8) | 100% (8/8) | 100% (8/8) | 100% (8/8) | 0% (0/8) | 67% (4/6) | 0% (0/8) |
| V3 | de | 8 | 100% (8/8) | 100% (8/8) | 100% (8/8) | 100% (8/8) | 0% (0/8) | 17% (1/6) | 0% (0/8) |
| V3g | tr | 8 | 100% (8/8) | 100% (8/8) | 100% (8/8) | 100% (8/8) | 0% (0/8) | 83% (5/6) | 0% (0/8) |
| V3g | de | 8 | 100% (8/8) | 100% (8/8) | 100% (8/8) | 100% (8/8) | 0% (0/8) | 50% (3/6) | 0% (0/8) |
| V3cg | tr | 8 | 100% (8/8) | 100% (8/8) | 100% (8/8) | 100% (8/8) | 0% (0/8) | 83% (5/6) | 0% (0/8) |
| V3cg | de | 8 | 100% (8/8) | 100% (8/8) | 100% (8/8) | 100% (8/8) | 0% (0/8) | 50% (3/6) | 0% (0/8) |
| V3b | tr | 8 | 100% (8/8) | 100% (8/8) | 100% (8/8) | 100% (8/8) | 0% (0/8) | 67% (4/6) | 0% (0/8) |
| V3b | de | 8 | 75% (6/8) | 75% (6/8) | 75% (6/8) | 88% (7/8) | 12% (1/8) | 17% (1/6) | 0% (0/8) |

#### Numbers / DNT items

| variant | lang | n | numbers_ok | numbers_strict_ok | dnt_ok | ref_ok | added_any |
|---|---|---|---|---|---|---|---|
| V1 | tr | 10 | 100% (7/7) | 71% (5/7) | 100% (4/4) | 100% (6/6) | 0% (0/10) |
| V1 | de | 10 | 100% (7/7) | 71% (5/7) | 100% (4/4) | 83% (5/6) | 0% (0/10) |
| V1b | tr | 10 | 100% (7/7) | 71% (5/7) | 100% (4/4) | 83% (5/6) | 0% (0/10) |
| V1b | de | 10 | 100% (7/7) | 71% (5/7) | 100% (4/4) | 83% (5/6) | 0% (0/10) |
| V2 | tr | 10 | 100% (7/7) | 71% (5/7) | 100% (4/4) | 100% (6/6) | 0% (0/10) |
| V2 | de | 10 | 100% (7/7) | 71% (5/7) | 100% (4/4) | 100% (6/6) | 0% (0/10) |
| V4 | tr | 10 | 100% (7/7) | 71% (5/7) | 100% (4/4) | 100% (6/6) | 0% (0/10) |
| V4 | de | 10 | 100% (7/7) | 71% (5/7) | 100% (4/4) | 83% (5/6) | 0% (0/10) |
| V4g | tr | 10 | 100% (7/7) | 71% (5/7) | 100% (4/4) | 100% (6/6) | 0% (0/10) |
| V4g | de | 10 | 100% (7/7) | 71% (5/7) | 100% (4/4) | 83% (5/6) | 0% (0/10) |

Strict number form failed only on locale-correct conversions (`3.5 mm`→`3,5 mm`, `1,200`→`1.200`). Validate digits
with separators removed.

#### Typographic-term items

| variant | lang | n | ref_ok | added_any |
|---|---|---|---|---|
| V1 | tr | 8 | 50% (4/8) | 0% (0/8) |
| V1 | de | 8 | 12% (1/8) | 0% (0/8) |
| V1b | tr | 8 | 62% (5/8) | 0% (0/8) |
| V1b | de | 8 | 12% (1/8) | 0% (0/8) |
| V2 | tr | 8 | 100% (8/8) | 0% (0/8) |
| V2 | de | 8 | 100% (8/8) | 0% (0/8) |
| V4 | tr | 8 | 50% (4/8) | 0% (0/8) |
| V4 | de | 8 | 38% (3/8) | 0% (0/8) |
| V4g | tr | 8 | 100% (8/8) | 0% (0/8) |
| V4g | de | 8 | 100% (8/8) | 0% (0/8) |

#### Body paragraphs (real)

| variant | lang | n | ref_ok | mostly_source | added_any | context_leak |
|---|---|---|---|---|---|---|
| V1 | tr | 23 | 73% (8/11) | 0% (0/23) | 0% (0/23) | 0% (0/23) |
| V1 | de | 23 | 45% (5/11) | 0% (0/23) | 0% (0/23) | 0% (0/23) |
| V1b | tr | 23 | 73% (8/11) | 0% (0/23) | 0% (0/23) | 0% (0/23) |
| V1b | de | 23 | 45% (5/11) | 0% (0/23) | 0% (0/23) | 0% (0/23) |
| V2 | tr | 23 | 100% (11/11) | 0% (0/23) | 0% (0/23) | 0% (0/23) |
| V2 | de | 23 | 100% (11/11) | 0% (0/23) | 0% (0/23) | 0% (0/23) |
| V4 | tr | 23 | 82% (9/11) | 0% (0/23) | 0% (0/23) | 0% (0/23) |
| V4 | de | 23 | 55% (6/11) | 4% (1/23) | 0% (0/23) | 0% (0/23) |
| V4g | tr | 23 | 100% (11/11) | 0% (0/23) | 0% (0/23) | 0% (0/23) |
| V4g | de | 23 | 91% (10/11) | 0% (0/23) | 0% (0/23) | 0% (0/23) |

**Recommended routing, simulated on the main grid** (P/S/T/TS as in §2; ALL-CAPS items take the V4g+fold result):

| lang | ref_ok | case_ok | tag_ok | ph multiset | numbers | DNT | untranslated | added text |
|---|---|---|---|---|---|---|---|---|
| tr | 92% (56/61) | 100% (14/14) | 100% (8/8) | 100% (20/20) | 100% (14/14) | 100% (5/5) | 0/93 | 0/93 |
| de | 90% (55/61) | 100% (14/14) | 100% (8/8) | 100% (20/20) | 100% (14/14) | 100% (5/5) | 1/93 ("Cyan", correct) | 0/93 |

Remaining reference misses: the separately translated cover titles (`Sessizlik`, `Düzen Sanatı`, `Die Stille`;
fixed by §2.6), `Letters from Our Readers` → `Okuyucularımızdan Mektuplar` (my reference expected "okur"; this is a
reference miss, the output is fine), DE `Die Frühjahrssaison · Nr. 01`, and two DE tagged items with odd term choices
(`italisierter Schrift`, `Paragrafenstile`).

---

## 4. L3 strings: verbatim outputs per variant

#### L3 strings, verbatim outputs (✓/✗ = reference check)

| source | lang | V1 | V1b | V2 | V4 | V4g |
|---|---|---|---|---|---|---|
| `Notes on the Grid` | tr | Grid Hakkında Notlar ✗ | İletken Ağına İlişkin Notlar ✗ | Izgara Hakkında Notlar ✓ | Grid Hakkında Notlar ✗ | ızgara Üzerine Notlar ✓ |
| `Notes on the Grid` | de | Anmerkungen zur Gitterstruktur ✗ | Anmerkungen zur Gitterstruktur ✗ | Anmerkungen zum Raster ✓ | Anmerkungen zur Gitterstruktur ✗ | Anmerkungen zur Rasterstruktur ✓ |
| `QUARTERLY` | tr | AYLIK ✗ | AYDA BİR ✗ | ÜÇ AYLIK ✓ | QUARTERLY ✓ | Üç Aylık ✓ |
| `QUARTERLY` | de | QUARTALSWEISE ✓ | QUARTALSWEISE ✓ | Vierteljährlich ✓ | QUARTERLY ✓ | Vierteljährlich ✓ |
| `2  ·  QUARTERLY` | tr | 2 · ÇEYREKLI ✗ | 2 · ÇEYREK YILLIK ✗ | 2  ·  ÜÇ AYLIK ✓ | 2  ·  QUARTERLY ✓ | 2 · ÜÇ AYLIK ✓ |
| `2  ·  QUARTERLY` | de | 2 · QUARTALLICH ✓ | 2 · QUARTALSWEISE ✓ | 2  ·  VIERTELJÄHRLICH ✓ | 2  ·  QUARTERLY ✓ | 2  ·  VIERTELJÄHRLICH ✓ |
| `Feature  ·  Design` | tr | Özellik · Tasarım ✗ | Özellik · Tasarım ✗ | Dosya · Tasarım ✓ | Özel Makale · Tasarım ✓ | Dosya · Tasarım ✓ |
| `Feature  ·  Design` | de | Merkmal · Design ✗ | Merkmal · Design ✗ | Reportage · Design ✓ | Highlight · Design ✗ | Reportage · Design ✓ |
| `FEATURE` | tr | ÖZELLİKLER ✗ | ÖZELLİKLER ✗ | ÖZELLİK ✗ | ÖZEL MAKALE ✓ | Dosya ✓ |
| `FEATURE` | de | EIGENSCHAFTEN ✗ | EIGENSCHAFT ✗ | REPORTAGE ✓ | Hauptartikel ✗ | REPORTAGE ✓ |
| `Pull quotes` | tr | Tırnak işaretleri çekin ✗ | Alıntıları çekin ✗ | Öne çıkan alıntılar ✓ | Alıntıları çekin ✗ | Öne çıkan alıntılar ✓ |
| `Pull quotes` | de | Anführungszeichen ziehen ✗ | Zitate einfügen ✓ | Pull-Quotes ✓ | Zitate einfügen ✓ | Pull-Quotes ✓ |
| `Coming next` | tr | Sırada geliyor ✗ | Sırada geliyor ✗ | Gelecek sayıda ✓ | Sırada ✗ | Gelecek sayıda ✓ |
| `Coming next` | de | Als Nächstes ✓ | Als Nächstes ✓ | Demnächst ✓ | Als Nächstes ✓ | Demnächst ✓ |
| `BUILD` | tr | İNŞA ET ✗ | İNŞA ET ✗ | KARİŞİM ✗ | OLUŞTURMAK ✗ | KARİŞİM ✗ |
| `BUILD` | de | Bauen ✗ | BAUEN ✗ | Farbaufbau ✓ | ERSTELLEN ✗ | Farbaufbau ✓ |
| `SWATCH` | tr | SWATCH ✗ | SWATCH ✗ | SWATCH ✗ | ÖRNEKLER ✓ | RENK ÖRNEĞİ ✓ |
| `SWATCH` | de | SWATCH ✗ | SWATCH ✗ | Farbfeld ✓ | SWATCH ✗ | Farbfeld ✓ |
| `Kickers, rules` | tr | Kickers, kurallar ✗ | Kickers, kurallar ✗ | Üst başlıklar, çizgiler ✓ | Kickers, kurallar ✗ | Üst başlıklar, çizgiler ✓ |
| `Kickers, rules` | de | Regeln, Vorschriften ✗ | Regeln, Vorschriften ✗ | Dachzeilen, Linien ✓ | Regeln, Vorschriften ✗ | Dachzeilen, Linien ✓ |
| `Backgrounds, heads` | tr | Arka planlar, başlar ✗ | Arka planlar, başlar ✗ | Arka planlar, başlıklar ✓ | Arka planlar, başlıklar ✓ | Arka planlar, başlıklar ✓ |
| `Backgrounds, heads` | de | Hintergründe, Köpfe ✗ | Hintergründe, Köpfe ✗ | Hintergründe, Überschriften ✓ | Hintergründe, Überschriften ✓ | Hintergründe, Überschriften ✓ |
| `The Quiet` | tr | Sessizlik ✗ | Sessizlik ✗ | Sessizlik ✗ | Sessizlik ✗ | Sessizlik ✗ |
| `The Quiet` | de | Die Stille ✗ | Die Stille ✗ | Die Stille ✗ | Die Stille ✗ | Die Stille ✗ |
| `Art of Layout` | tr | Düzen Sanatı ✗ | Dizgi Sanatı ✓ | Dizgi Sanatı ✓ | Düzen Sanatı ✗ | Düzen Sanatı ✗ |
| `Art of Layout` | de | Kunst der Gestaltung ✓ | Kunst der Gestaltung ✓ | Kunst der Gestaltung ✓ | Kunst der Seitengestaltung ✓ | Kunst der Seitengestaltung ✓ |
| `A pull quote breaks up long text and draws the eye into the story.` | tr | Alıntı çerçevesi, uzun metni böler ve dikkati hikayenin içine çeker. ✓ | Alıntı kutusu, uzun metinleri böler ve okuyucunun dikkatini hikayenin içine çeker. ✓ | Öne çıkan alıntı, uzun metni böler ve okuyucunun dikkatini hikayenin içine çeker. ✓ | Alıntılı bir cümle, uzun metni böler ve okuyucunun dikkatini hikayenin içine çeker. ✓ | Öne çıkan alıntı, uzun metinleri böler ve okuyucunun dikkatini hikayenin içine çeker. ✓ |
| `A pull quote breaks up long text and draws the eye into the story.` | de | Ein Zitat unterbricht lange Texte und lenkt den Blick auf die Geschichte. ✓ | Ein Zitat unterbricht lange Texte und lenkt den Blick auf die Geschichte. ✓ | Ein Pull-Quote unterteilt lange Texte und lenkt den Blick auf die Geschichte. ✓ | Ein Zitat unterbricht lange Texte und lenkt den Blick auf die Geschichte. ✓ | Ein Pull-Quote unterbricht lange Texte und lenkt den Blick auf die jeweilige Geschichte. ✓ |

Coordinator baseline failures under the recommended route (S + folding + glossary, from the caps and throughput stages):

| source | prototype / baseline | recommended TR | recommended DE |
|---|---|---|---|
| Notes on the Grid | İzgile İlgili Notlar / İletken Şebeke Üzerine Notlar | ızgara Üzerine Notlar → after initial-cap fix **Izgara Üzerine Notlar** | Anmerkungen zur Rasterstruktur |
| Feature  ·  Design | Özellik · Tasarım | Dosya · Tasarım | Reportage · Design |
| FEATURE (caps) | ÖZELLİK | DOSYA | REPORTAGE |
| Coming next | Bir sonraki olarak | Gelecek sayıda | Demnächst |
| BUILD (CMYK build header) | İNŞA ET | **KARIŞIM** (as-is the model wrote `KARİŞİM`, a wrong Turkish uppercase; folding fixes it) | FARBAUFBAU |
| SWATCH | SWATCH | RENK ÖRNEĞİ | FARBFELD |
| USED FOR | KULLANIM AMACI | KULLANIM AMACI | WIRD ZUR VERWENDUNG VON (stilted; as-is: VERWENDET FÜR) |
| Kickers, rules | Kickers, kurallar | Üst başlıklar, çizgiler | Dachzeilen, Linien |
| Backgrounds, heads | Arka planlar, başlar | Arka planlar, başlıklar | Hintergründe, Überschriften |
| Pull quotes | Tırnak işaretlerini çekin | Öne çıkan alıntılar | Pull-Quotes |
| QUARTERLY | ÇEYREK YILLIK | ÜÇ AYLIK | VIERTELJÄHRLICH |
| 2  ·  QUARTERLY | | 2 · ÜÇ AYLIK | 2  ·  VIERTELJÄHRLICH |

Without the glossary, context + folding (V4 fold) still gives FEATURE→`ÖZEL MAKALE`, SWATCH→`ÖRNEK RENKLER`/`MUSTER`,
COMING NEXT→`BİR SONRAKİ SAYIDA`/`NÄCHSTE AUSGABE`, but BUILD→`OLUŞTUR`/`ERSTELLEN` stays wrong. Domain terms
(build, kicker, rule, pull quote) need glossary entries. Note: V4 without a glossary often keeps `QUARTERLY` (the
synopsis names the magazine "Quarterly"). Whether the folio should say ÜÇ AYLIK or keep the title is a project
decision: put it in the glossary or the DNT list.

---

## 5. Multi-paragraph heading ("The Quiet" + "Art of Layout"), coordinator item 1

#### Multi-paragraph headline ("The Quiet" + "Art of Layout"), 3 runs each

| form | variant | lang | boundary kept | ref_ok | distinct outputs |
|---|---|---|---|---|---|
| ph_br_uni | V4 | tr | 100% (3/3) | 100% (3/3) | Dizaynın Sessiz⟦1⟧Sanatı ‖ Düzenlemenin Sessiz⟦1⟧Sanatı |
| ph_br_uni | V4 | de | 100% (3/3) | 100% (3/3) | Die stille⟦1⟧Kunst der Layout-Planung ‖ Die stille⟦1⟧Kunst der Seitenlayoutierung |
| ph_br_uni | V3cg | tr | 100% (3/3) | 100% (3/3) | Düzenlemenin Sessiz⟦1⟧Sanatı |
| ph_br_uni | V3cg | de | 100% (3/3) | 100% (3/3) | Die stille⟦1⟧Kunst des Layouts |
| ph_br_uni | V3 | tr | 100% (3/3) | 100% (3/3) | Düzenlemenin Sessiz⟦1⟧Sanatı |
| ph_br_uni | V3 | de | 100% (3/3) | 100% (3/3) | Die ruhige⟦1⟧Kunst des Layouts ‖ Die sanfte⟦1⟧Kunst des Layouts |
| ph_br_brace | V4 | tr | 0% (0/3) | 100% (3/3) | Dizaynın Sessiz Sanatı ‖ Düzenlemenin Sessiz Sanatı |
| ph_br_brace | V4 | de | 100% (3/3) | 100% (3/3) | Die stille{1}Kunst der Layout-Planung ‖ Die stille{1}Kunst der Seitenlayoutierung |
| ph_br_brace | V3cg | tr | 100% (3/3) | 100% (3/3) | Düzenlemenin Sessiz{1}Sanatı |
| ph_br_brace | V3cg | de | 100% (3/3) | 100% (3/3) | Die stille{1}Kunst der Layout-Planung ‖ Die stille{1}Kunst der Seitenlayoutierung ‖ Die stille{1}Kunst des Layouts |
| ph_br_brace | V3 | tr | 100% (3/3) | 100% (3/3) | Sessiz{1} Düzenleme Sanatı |
| ph_br_brace | V3 | de | 100% (3/3) | 100% (3/3) | Die ruhige{1}Kunst des Layouts |
| ph_br_xml | V4 | tr | 0% (0/3) | 100% (3/3) | Dizaynın Sessiz Sanatı ‖ Düzenlemenin Sessiz Sanatı |
| ph_br_xml | V4 | de | 0% (0/3) | 100% (3/3) | Die stille Kunst der Layout-Planung ‖ Die stille Kunst des Layouts |
| ph_br_xml | V3cg | tr | 100% (3/3) | 100% (3/3) | Düzenin Sessiz <x1/>Sanatı ‖ Düzenlemenin Sessiz <x1/>Sanatı |
| ph_br_xml | V3cg | de | 100% (3/3) | 100% (3/3) | Die stille <x1/>Kunst des Layouts |
| ph_br_xml | V3 | tr | 100% (3/3) | 100% (3/3) | Düzenin Sessiz <x1/>Sanatı ‖ Sessiz <x1/>Düzen Sanatı |
| ph_br_xml | V3 | de | 100% (3/3) | 100% (3/3) | Die ruhige <x1/>Kunst des Layouts ‖ Die ruhige<x1/>Kunst des Layouts |
| ph_br_dbl | V4 | tr | 0% (0/3) | 100% (3/3) | Dizaynın Sessiz Sanatı ‖ Düzenlemenin Sessiz Sanatı |
| ph_br_dbl | V4 | de | 0% (0/3) | 100% (3/3) | Die stille Kunst des Layouts |
| ph_br_dbl | V3cg | tr | 67% (2/3) | 100% (3/3) | Düzenleme Sanatının Sessizliği ‖ Düzenlemenin Sessiz[[1]]Sanatı |
| ph_br_dbl | V3cg | de | 100% (3/3) | 100% (3/3) | Die ruhige[[1]]Kunst des Layouts ‖ Die stille[[1]]Kunst des Layouts |
| ph_br_dbl | V3 | tr | 100% (3/3) | 0% (0/3) | Sessizlikin[[1]]Düzenleme Sanatı ‖ Sessizlikteki[[1]]Düzen Sanatı |
| ph_br_dbl | V3 | de | 100% (3/3) | 100% (3/3) | Die ruhige[[1]]Kunst des Layouts |
| nl_br | V4 | tr | 100% (3/3) | 0% (0/3) | Sessizlik  ⏎Düzen Sanatı |
| nl_br | V4 | de | 100% (3/3) | 0% (0/3) | Die Stille  ⏎Die Kunst des Layouts |
| nl_br | V3cg | tr | 100% (3/3) | 0% (0/3) | Sessizlik  ⏎Düzenleme Sanatı |
| nl_br | V3cg | de | 100% (3/3) | 0% (0/3) | Die Stille  ⏎Die Kunst des Layouts |
| nl_br | V3 | tr | 100% (3/3) | 0% (0/3) | Sessizlik⏎Düzen Sanatı |
| nl_br | V3 | de | 100% (3/3) | 0% (0/3) | Die Stille  ⏎Die Kunst des Layouts |
| t_cover_pair | V4 | tr | 100% (3/3) | 0% (0/3) | <g0>Sessizlik</g0><g1>Dizgi Sanatı</g1> |
| t_cover_pair | V4 | de | 100% (3/3) | 0% (0/3) | <g0>Die Stille</g0><g1>Kunst der Gestaltung</g1> ‖ <g0>Die Stille</g0><g1>Kunst der Layoutgestaltung</g1> |
| t_cover_pair | V3cg | tr | 100% (3/3) | 0% (0/3) | <g0>Sessizlik</g0><g1>Dizayn Sanatı</g1> ‖ <g0>Sessizlik</g0><g1>Düzen Sanatı</g1> ‖ <g0>Sessizlik</g0><g1>Düzenleme Sanatı</g1> |
| t_cover_pair | V3cg | de | 100% (3/3) | 0% (0/3) | <g0>Die Stille</g0><g1>Kunst der Seitengestaltung</g1> ‖ <g0>Die Stille</g0><g1>Kunst der Seitenlayout</g1> |
| t_cover_pair | V3 | tr | 100% (3/3) | 0% (0/3) | <g0>Sessizlik</g0><g1>Dizayn Sanatı</g1> ‖ <g0>Sessizlik</g0><g1>Dizgi Sanatı</g1> |
| t_cover_pair | V3 | de | 100% (3/3) | 0% (0/3) | <g0>Die Stille</g0><g1>Kunst der Gestaltung</g1> |

- `⟦1⟧`: boundary kept **18/18** (V4, V3cg, V3 × TR/DE × 3 runs) and natural 2-line headline **18/18**
  (`Düzenlemenin Sessiz⟦1⟧Sanatı`, `Die stille⟦1⟧Kunst des Layouts`).
- `{1}` 15/18, `<x1/>` 12/18, `[[1]]` 11/18 boundary kept. All four failed under plain V4 (no placeholder rule),
  except `⟦1⟧`.
- `\n` and `<g0>…</g0><g1>…</g1>` keep the structure (18/18) but the model then translates each line separately
  ("Sessizlik / Düzen Sanatı", "Die Stille / Kunst der Gestaltung"): natural headline **0/18**. Use `⟦n⟧`.

---

## 6. Placeholders

#### Placeholder formats (TR+DE pooled)

| format | variant | n | ph_ok (multiset+order) | ph multiset | ph multiset after look-alike normalisation | ref_ok |
|---|---|---|---|---|---|---|
| uni | V1b | 10 | 100% (10/10) | 100% (10/10) | 100% (10/10) | 67% (4/6) |
| uni | V2 | 10 | 100% (10/10) | 100% (10/10) | 100% (10/10) | 100% (6/6) |
| uni | V4 | 10 | 100% (10/10) | 100% (10/10) | 100% (10/10) | 67% (4/6) |
| uni | V4g | 10 | 90% (9/10) | 100% (10/10) | 100% (10/10) | 100% (6/6) |
| uni | V3 | 10 | 90% (9/10) | 90% (9/10) | 90% (9/10) | 67% (4/6) |
| uni | V3g | 10 | 100% (10/10) | 100% (10/10) | 100% (10/10) | 100% (6/6) |
| uni | V3cg | 10 | 90% (9/10) | 90% (9/10) | 100% (10/10) | 100% (6/6) |
| brace | V1b | 10 | 100% (10/10) | 100% (10/10) | 100% (10/10) | 50% (3/6) |
| brace | V2 | 10 | 100% (10/10) | 100% (10/10) | 100% (10/10) | 83% (5/6) |
| brace | V4 | 10 | 90% (9/10) | 90% (9/10) | 90% (9/10) | 83% (5/6) |
| brace | V4g | 10 | 80% (8/10) | 80% (8/10) | 80% (8/10) | 100% (6/6) |
| brace | V3 | 10 | 100% (10/10) | 100% (10/10) | 100% (10/10) | 67% (4/6) |
| brace | V3g | 10 | 100% (10/10) | 100% (10/10) | 100% (10/10) | 100% (6/6) |
| brace | V3cg | 10 | 100% (10/10) | 100% (10/10) | 100% (10/10) | 100% (6/6) |
| xml | V1b | 10 | 90% (9/10) | 100% (10/10) | 100% (10/10) | 67% (4/6) |
| xml | V2 | 10 | 100% (10/10) | 100% (10/10) | 100% (10/10) | 100% (6/6) |
| xml | V4 | 10 | 90% (9/10) | 90% (9/10) | 90% (9/10) | 83% (5/6) |
| xml | V4g | 10 | 80% (8/10) | 90% (9/10) | 90% (9/10) | 100% (6/6) |
| xml | V3 | 10 | 90% (9/10) | 100% (10/10) | 100% (10/10) | 67% (4/6) |
| xml | V3g | 10 | 100% (10/10) | 100% (10/10) | 100% (10/10) | 100% (6/6) |
| xml | V3cg | 10 | 100% (10/10) | 100% (10/10) | 100% (10/10) | 100% (6/6) |
| dbl | V1b | 10 | 100% (10/10) | 100% (10/10) | 100% (10/10) | 50% (3/6) |
| dbl | V2 | 10 | 100% (10/10) | 100% (10/10) | 100% (10/10) | 83% (5/6) |
| dbl | V4 | 10 | 100% (10/10) | 100% (10/10) | 100% (10/10) | 83% (5/6) |
| dbl | V4g | 10 | 90% (9/10) | 90% (9/10) | 90% (9/10) | 100% (6/6) |
| dbl | V3 | 10 | 100% (10/10) | 100% (10/10) | 100% (10/10) | 67% (4/6) |
| dbl | V3g | 10 | 100% (10/10) | 100% (10/10) | 100% (10/10) | 100% (6/6) |
| dbl | V3cg | 10 | 100% (10/10) | 100% (10/10) | 100% (10/10) | 100% (6/6) |
| uni | **all** | 80 | 95% (76/80) | 98% (78/80) | 99% (79/80) | 83% (40/48) |
| brace | **all** | 80 | 95% (76/80) | 96% (77/80) | 96% (77/80) | 81% (39/48) |
| xml | **all** | 80 | 92% (74/80) | 98% (78/80) | 98% (78/80) | 85% (41/48) |
| dbl | **all** | 80 | 99% (79/80) | 99% (79/80) | 99% (79/80) | 81% (39/48) |

Recommendation: **`⟦n⟧`** (U+27E6/U+27E7).
- Multiset preservation: 98% raw, **99% after normalising look-alikes**. The one look-alike was `⟦1⟧`→`⟨1⟩` in V3cg
  TR. Normalise `[⟨〚〔\[](\d+)[⟩〛〕\]]` → `⟦\1⟧` before validating. The formats are statistically
  indistinguishable on single segments (96–99%). The decisive test was §5, where only `⟦n⟧` survived a template
  without placeholder rules.
- `⟦n⟧` never occurs in real copy. `{n}` collides with code and templates, `<xn/>` with the tag regime and XML
  escaping, `[[n]]` with wiki syntax.
- Validate the **multiset**, not the order: all order-only failures were legitimate Turkish/German reorderings of
  numbered placeholders.
- Real placeholder losses were semantic: V4g DE `ph_unit_*` folded "at ⟦1⟧ with ⟦2⟧ leading" into one value after the
  glossary line `leading translates to Zeilenabstand`. Retry with T fixed all of them.

---

## 7. ALL CAPS and casing

#### ALL CAPS: as-is vs sentence-case + locale upper (case_ok measured after restoring)

| variant | mode | lang | n | ref_ok | case_ok | added_any |
|---|---|---|---|---|---|---|
| V1b | asis | tr | 14 | 43% (6/14) | 79% (11/14) | 0% (0/14) |
| V1b | asis | de | 14 | 57% (8/14) | 93% (13/14) | 0% (0/14) |
| V1b | fold | tr | 14 | 50% (7/14) | 100% (14/14) | 0% (0/14) |
| V1b | fold | de | 14 | 64% (9/14) | 100% (14/14) | 0% (0/14) |
| V2 | asis | tr | 14 | 71% (10/14) | 79% (11/14) | 0% (0/14) |
| V2 | asis | de | 14 | 100% (14/14) | 64% (9/14) | 0% (0/14) |
| V2 | fold | tr | 14 | 100% (14/14) | 100% (14/14) | 0% (0/14) |
| V2 | fold | de | 14 | 100% (14/14) | 100% (14/14) | 0% (0/14) |
| V4 | asis | tr | 14 | 57% (8/14) | 93% (13/14) | 0% (0/14) |
| V4 | asis | de | 14 | 57% (8/14) | 71% (10/14) | 0% (0/14) |
| V4 | fold | tr | 14 | 93% (13/14) | 100% (14/14) | 0% (0/14) |
| V4 | fold | de | 14 | 79% (11/14) | 100% (14/14) | 0% (0/14) |
| V4g | asis | tr | 14 | 79% (11/14) | 79% (11/14) | 0% (0/14) |
| V4g | asis | de | 14 | 100% (14/14) | 50% (7/14) | 0% (0/14) |
| V4g | fold | tr | 14 | 100% (14/14) | 100% (14/14) | 0% (0/14) |
| V4g | fold | de | 14 | 93% (13/14) | 100% (14/14) | 0% (0/14) |

##### ALL CAPS outputs (V4g)

| id | lang | mode | sent | model output | final | ref |
|---|---|---|---|---|---|---|
| r_folio_spring | tr | asis | `SPRING ISSUE` | İLKYAZ SAYISI | İLKYAZ SAYISI | ✗ |
| r_folio_spring | tr | fold | `Spring issue` | İlkbahar sayısı | İLKBAHAR SAYISI | ✓ |
| r_kicker_cover | tr | asis | `THE SPRING ISSUE  ·  NO. 01` | İLkbahar Sayısı · 01. Sayı | İLkbahar Sayısı · 01. Sayı | ✓ |
| r_kicker_cover | tr | fold | `The spring issue  ·  no. 01` | İlkbahar sayısı · 01. sayı | İLKBAHAR SAYISI · 01. SAYI | ✓ |
| r_th_swatch | tr | asis | `SWATCH` | RENK ÖRNEĞİ | RENK ÖRNEĞİ | ✓ |
| r_th_swatch | tr | fold | `Swatch` | Renk örneği | RENK ÖRNEĞİ | ✓ |
| r_th_build | tr | asis | `BUILD` | KARİŞİM | KARİŞİM | ✗ |
| r_th_build | tr | fold | `Build` | Karışım | KARIŞIM | ✓ |
| r_th_usedfor | tr | asis | `USED FOR` | KULLANIM ALANI | KULLANIM ALANI | ✓ |
| r_th_usedfor | tr | fold | `Used for` | Kullanım amacı | KULLANIM AMACI | ✓ |
| r_folio_quarterly | tr | asis | `QUARTERLY` | Üç Aylık | Üç Aylık | ✓ |
| r_folio_quarterly | tr | fold | `Quarterly` | Üç Aylık | ÜÇ AYLIK | ✓ |
| c_feature | tr | asis | `FEATURE` | DOSYA | DOSYA | ✓ |
| c_feature | tr | fold | `Feature` | Dosya | DOSYA | ✓ |
| c_feature_design | tr | asis | `FEATURE  ·  DESIGN` | DOSYA · TASARIM | DOSYA · TASARIM | ✓ |
| c_feature_design | tr | fold | `Feature  ·  design` | Dosya · Tasarım | DOSYA · TASARIM | ✓ |
| c_coming_next | tr | asis | `COMING NEXT` | Gelecek sayıda | Gelecek sayıda | ✓ |
| c_coming_next | tr | fold | `Coming next` | Gelecek sayıda | GELECEK SAYIDA | ✓ |
| c_inside | tr | asis | `INSIDE THIS ISSUE` | BU SAYIDAKİLER | BU SAYIDAKİLER | ✓ |
| c_inside | tr | fold | `Inside this issue` | Bu sayının içinde | BU SAYININ İÇİNDE | ✓ |
| c_sentence | tr | asis | `WHY THE GRID STILL MATTERS` | NEDEN IZGARA HÂLÂ ÖNEMLİ? | NEDEN IZGARA HÂLÂ ÖNEMLİ? | ✓ |
| c_sentence | tr | fold | `Why the grid still matters` | Izgara Neden Hâlâ Önemli? | IZGARA NEDEN HÂLÂ ÖNEMLİ? | ✓ |
| c_folio_2 | tr | asis | `2  ·  QUARTERLY` | 2 · ÜÇ AYLIK | 2 · ÜÇ AYLIK | ✓ |
| c_folio_2 | tr | fold | `2  ·  Quarterly` | 2 · Üç Aylık | 2 · ÜÇ AYLIK | ✓ |
| c_used_for | tr | asis | `USED FOR` | KULLANIM AMACI | KULLANIM AMACI | ✓ |
| c_used_for | tr | fold | `Used for` | Kullanım amacı | KULLANIM AMACI | ✓ |
| c_typo | tr | asis | `TYPOGRAPHY` | TYPOGRAFİ | TYPOGRAFİ | ✗ |
| c_typo | tr | fold | `Typography` | Tipografi | TİPOGRAFİ | ✓ |
| r_folio_spring | de | asis | `SPRING ISSUE` | FRÜHLINGSAUSSCHNITT | FRÜHLINGSAUSSCHNITT | ✓ |
| r_folio_spring | de | fold | `Spring issue` | Frühjahrsspecial | FRÜHJAHRSSPECIAL | ✓ |
| r_kicker_cover | de | asis | `THE SPRING ISSUE  ·  NO. 01` | Die Frühjahrsspezialausgabe · Nr. 01 | Die Frühjahrsspezialausgabe · Nr. 01 | ✓ |
| r_kicker_cover | de | fold | `The spring issue  ·  no. 01` | Die Frühjahrssaison · Nr. 01 | DIE FRÜHJAHRSSAISON · NR. 01 | ✗ |
| r_th_swatch | de | asis | `SWATCH` | Farbfeld | Farbfeld | ✓ |
| r_th_swatch | de | fold | `Swatch` | Farbfeld | FARBFELD | ✓ |
| r_th_build | de | asis | `BUILD` | Farbaufbau | Farbaufbau | ✓ |
| r_th_build | de | fold | `Build` | Farbaufbau | FARBAUFBAU | ✓ |
| r_th_usedfor | de | asis | `USED FOR` | VERWENDET FÜR | VERWENDET FÜR | ✓ |
| r_th_usedfor | de | fold | `Used for` | Wird zur Verwendung von | WIRD ZUR VERWENDUNG VON | ✓ |
| r_folio_quarterly | de | asis | `QUARTERLY` | Vierteljährlich | Vierteljährlich | ✓ |
| r_folio_quarterly | de | fold | `Quarterly` | Vierteljährlich | VIERTELJÄHRLICH | ✓ |
| c_feature | de | asis | `FEATURE` | REPORTAGE | REPORTAGE | ✓ |
| c_feature | de | fold | `Feature` | Reportage | REPORTAGE | ✓ |
| c_feature_design | de | asis | `FEATURE  ·  DESIGN` | REPORTAGE · DESIGN | REPORTAGE · DESIGN | ✓ |
| c_feature_design | de | fold | `Feature  ·  design` | Reportage · Design | REPORTAGE · DESIGN | ✓ |
| c_coming_next | de | asis | `COMING NEXT` | Demnächst | Demnächst | ✓ |
| c_coming_next | de | fold | `Coming next` | Demnächst | DEMNÄCHST | ✓ |
| c_inside | de | asis | `INSIDE THIS ISSUE` | IN DIESEM HEFT | IN DIESEM HEFT | ✓ |
| c_inside | de | fold | `Inside this issue` | In dieser Ausgabe | IN DIESER AUSGABE | ✓ |
| c_sentence | de | asis | `WHY THE GRID STILL MATTERS` | WARUM DER RASTER NOCH IMMER WICHTIG IST | WARUM DER RASTER NOCH IMMER WICHTIG IST | ✓ |
| c_sentence | de | fold | `Why the grid still matters` | Warum Raster weiterhin wichtig ist | WARUM RASTER WEITERHIN WICHTIG IST | ✓ |
| c_folio_2 | de | asis | `2  ·  QUARTERLY` | 2  ·  VIERTELJÄHRLICH | 2  ·  VIERTELJÄHRLICH | ✓ |
| c_folio_2 | de | fold | `2  ·  Quarterly` | 2  ·  Vierteljährlich | 2  ·  VIERTELJÄHRLICH | ✓ |
| c_used_for | de | asis | `USED FOR` | Verwendungszweck | Verwendungszweck | ✓ |
| c_used_for | de | fold | `Used for` | Wird zum Einsatz kommen | WIRD ZUM EINSATZ KOMMEN | ✓ |
| c_typo | de | asis | `TYPOGRAPHY` | Typografie | Typografie | ✓ |
| c_typo | de | fold | `Typography` | Typografie | TYPOGRAFIE | ✓ |

**Recommendation: fold, then restore.** Send sentence case and uppercase the result locale-aware. Measured for V4g:
ref 79%→**100%** (TR), 100%→93% (DE; one miss, "DIE FRÜHJAHRSSAISON · NR. 01"); case 79%/50% → **100%/100%**. V2
fold: 100%/100% ref, 100%/100% case. Sent as is, the model returns mixed case (`İLkbahar Sayısı`, `Hauptartikel`,
`Vierteljährlich`). In Turkish it also uppercases glossary terms wrongly (`KARİŞİM` for KARIŞIM), which
locale-aware restoring avoids. Python's `str.upper()` is wrong for Turkish (`i`→`I`). Map `i→İ`, `ı→I` first.
German `ß` uppercases to `SS` with `str.upper()`; use `ẞ` only if the project wants it.

---

## 8. Untranslated validator and the code-like exemption (coordinator item 3)

#### Identity outputs (output == source) and the code-like exemption

| id | lang | code_like (exempt) | output | count (variants) |
|---|---|---|---|---|
| c_folio_2 | de | False | `2  ·  QUARTERLY` | 1 |
| c_folio_2 | tr | False | `2  ·  QUARTERLY` | 1 |
| r_caption_cmyk | de | True | `C=100 M=0 Y=0 K=0` | 5 |
| r_caption_cmyk | tr | True | `C=100 M=0 Y=0 K=0` | 5 |
| r_caption_inkplum | de | False | `Ink Plum` | 1 |
| r_folio_quarterly | de | False | `QUARTERLY` | 1 |
| r_folio_quarterly | tr | False | `QUARTERLY` | 1 |
| r_td_build1 | de | True | `C62 M95 Y30 K25` | 5 |
| r_td_build1 | tr | True | `C62 M95 Y30 K25` | 5 |
| r_td_build2 | de | True | `M62 Y78` | 5 |
| r_td_build2 | tr | True | `M62 Y78` | 5 |
| r_td_build4 | de | True | `M3 Y8` | 5 |
| r_td_build4 | tr | True | `M3 Y8` | 5 |
| r_td_charts | de | False | `Charts, Links` | 1 |
| r_td_cyan | de | False | `Cyan` | 2 |
| r_td_inkplum | de | False | `Ink Plum` | 1 |
| r_th_swatch | de | False | `SWATCH` | 3 |
| r_th_swatch | tr | False | `SWATCH` | 3 |

Heuristic: **code-like ⇔ the source, after removing DNT terms and markers, contains no run of ≥ 3 letters**
(`re.search(r"[^\W\d_]{3,}", s)` is false).
- Exempts all CMYK builds and swatch codes (`C=100 M=0 Y=0 K=0`, `C62 M95 Y30 K25`, `M62 Y78`, `M3 Y8`, `C100`): 40/40
  identity outputs exempt. It exempts no real-language item in this set.
- Code-like segments need not be sent to the model at all. They came back identical in every variant.
- Everything else that comes back identical is a **soft** failure. Retry once with S at T=0.2: 13/15 changed to a
  correct translation (SWATCH→RENK ÖRNEĞİ/Farbfeld, QUARTERLY→Üç Aylık/Vierteljährlich, `Charts, Links`→`Diagramme,
  Links`). If it is still identical, accept it with a "review" flag: the 2 survivors were DE "Cyan", which is
  correct. Known risk: 1–2-letter words ("No", "OK") would be exempt.
- Swatch-name captions ("Ink Plum", "Paper Warm", "Sunset") are swatch names in `Resources/Graphic.xml`. The model
  produces literal translations ("Mürekkep Eriği", "Kağıt Sıcaklığı", "Tinte Pflaume", "Papiertönung Warm").
  Suggestion (not measured): treat a segment equal to a swatch name as DNT by default, configurable.

---

## 9. Context bleed (new failure mode)

#### Context bleed (synopsis echoed into the output): 3-gram echo detector

Synopsis translations: TR `Bir tasarım dergisi olan ‘Quarterly’nin ilkbahar sayısı; düzen gridleri ve tipografi üzerine bir özel makale.` · DE `Frühjahrssonderausgabe einer Designzeitschrift, „Quarterly“; Feature-Artikel über Layout-Grids und Typografie.`

| variant | item has prev/next | n | flagged |
|---|---|---|---|
| V1 | yes | 70 | 0% (0/70) |
| V1 | no | 116 | 0% (0/116) |
| V1b | yes | 70 | 0% (0/70) |
| V1b | no | 116 | 0% (0/116) |
| V2 | yes | 70 | 0% (0/70) |
| V2 | no | 116 | 0% (0/116) |
| V4 | yes | 70 | 0% (0/70) |
| V4 | no | 116 | 1% (1/116) |
| V4g | yes | 70 | 0% (0/70) |
| V4g | no | 116 | 2% (2/116) |
| V3 | no | 56 | 0% (0/56) |
| V3g | no | 56 | 0% (0/56) |
| V3cg | no | 56 | 5% (3/56) |
| V3b | no | 16 | 0% (0/16) |

##### Flagged outputs

| variant | lang | id | echoed 3-grams | output |
|---|---|---|---|---|
| V4 | tr | ph_br_uni | gridleri ve tipografi | Dizaynın Sessiz⟦1⟧Sanatı: Düzenleme Gridleri ve Tipografi |
| V4g | tr | ph_br_uni | gridleri ve tipografi | Dizaynın Sessiz⟦1⟧Sanatı: Düzenleme Gridleri ve Tipografi |
| V3cg | tr | ph_url_uni | bir özel makale, düzen gridleri ve, gridleri ve tipografi, tipografi üzerine bir, ve tipografi üzerine, üzerine bir özel | ‘Quarterly’ adlı tasarım dergisinin ilkbahar sayısında, düzen gridleri ve tipografi üzerine bir özel makale ye |
| V3cg | tr | ph_url_xml | bir özel makale, düzen gridleri ve, gridleri ve tipografi | ‘Quarterly’ adlı tasarım dergisinin ilkbahar sayısında, düzen gridleri ve tipografi hakkında bir özel makale y |
| V3cg | tr | ph_url_dbl | bir özel makale, düzen gridleri ve, gridleri ve tipografi | ‘Quarterly’ adlı tasarım dergisinin ilkbahar sayısında, düzen gridleri ve tipografi hakkında bir özel makale y |
| V4g | tr | d_quarterly | bir özel makale, düzen gridleri ve, gridleri ve tipografi, tipografi üzerine bir, ve tipografi üzerine, üzerine bir özel | DesignCraft stüdyosu tarafından yılda dört kez yayımlanan ‘Quarterly’, düzen gridleri ve tipografi üzerine bir |

The contextual templates sometimes translate the background into the output, e.g. TR `ph_url_uni` (V3cg):
"‘Quarterly’ adlı tasarım dergisinin ilkbahar sayısında, düzen gridleri ve tipografi üzerine bir özel makale yer
alıyor. Şablonları ⟦1⟧ adresinden indirin…". **Every structural validator passes** (placeholders, numbers). Rate:
6/288 context calls on items without neighbours (V4 1/116, V4g 2/116, V3cg 3/56), 0/140 on real items with
prev/next. All cases were in Turkish.

Detector (cheap, no extra call per segment): translate the synopsis once per document and language (greedy V1b).
Flag any output that shares a word 3-gram with that translation. It flagged all 6 distinct bleed outputs. Over the
no-context control variants (V1, V1b, V2, V3, V3g, V3b: 686 outputs) it flagged 0. On a flag, retry without
context (P/T). A body paragraph that legitimately repeats synopsis wording could trip it, which costs only one retry.
An upper length bound alone does not catch it (TR `d_quarterly` bleed has ratio 2.03).

---

## 10. Concise translation and the back-translation check (L5)

#### Concise candidates and deliberate truncations (back-translation recall)

| candidate | lang | n | len/normal p50 | len/normal min | recall_src p50 | recall_src min | recall_vs_normalBT p50 | numbers kept |
|---|---|---|---|---|---|---|---|---|
| V5a | tr | 10 | 0.85 | 0.795 | 0.55 | 0.393 | 0.72 | – |
| V5a | de | 10 | 0.84 | 0.769 | 0.57 | 0.5 | 0.66 | – |
| V5b | tr | 10 | 0.9 | 0.822 | 0.58 | 0.393 | 0.78 | – |
| V5b | de | 10 | 0.86 | 0.831 | 0.53 | 0.375 | 0.67 | – |
| drop_sentence | tr | 7 | 0.5 | 0.24 | 0.25 | 0.143 | 0.5 | – |
| drop_sentence | de | 7 | 0.53 | 0.279 | 0.3 | 0.214 | 0.48 | – |
| drop_clause | tr | 10 | 0.57 | 0.221 | 0.34 | 0.083 | 0.54 | – |
| drop_clause | de | 10 | 0.78 | 0.425 | 0.52 | 0.25 | 0.78 | – |

Reference: content-word recall of the *normal* translation's back-translation vs source: p5=0.41, p50=0.58, min=0.286.

##### Detector sweep: flag if recall_src < R or len/normal < L

| R | L | detected (all truncations) | detected (clause drops) | flagged real concise (FP-or-true) |
|---|---|---|---|---|
| 0.6 | 0.0 | 91% (31/34) | 85% (17/20) | 60% (24/40) |
| 0.6 | 0.6 | 91% (31/34) | 85% (17/20) | 60% (24/40) |
| 0.6 | 0.7 | 91% (31/34) | 85% (17/20) | 60% (24/40) |
| 0.6 | 0.75 | 94% (32/34) | 90% (18/20) | 60% (24/40) |
| 0.6 | 0.8 | 97% (33/34) | 95% (19/20) | 65% (26/40) |
| 0.65 | 0.0 | 97% (33/34) | 95% (19/20) | 82% (33/40) |
| 0.65 | 0.6 | 97% (33/34) | 95% (19/20) | 82% (33/40) |
| 0.65 | 0.7 | 97% (33/34) | 95% (19/20) | 82% (33/40) |
| 0.65 | 0.75 | 97% (33/34) | 95% (19/20) | 82% (33/40) |
| 0.65 | 0.8 | 100% (34/34) | 100% (20/20) | 85% (34/40) |
| 0.7 | 0.0 | 97% (33/34) | 95% (19/20) | 82% (33/40) |
| 0.7 | 0.6 | 97% (33/34) | 95% (19/20) | 82% (33/40) |
| 0.7 | 0.7 | 97% (33/34) | 95% (19/20) | 82% (33/40) |
| 0.7 | 0.75 | 97% (33/34) | 95% (19/20) | 82% (33/40) |
| 0.7 | 0.8 | 100% (34/34) | 100% (20/20) | 85% (34/40) |
| 0.75 | 0.0 | 97% (33/34) | 95% (19/20) | 82% (33/40) |
| 0.75 | 0.6 | 97% (33/34) | 95% (19/20) | 82% (33/40) |
| 0.75 | 0.7 | 97% (33/34) | 95% (19/20) | 82% (33/40) |
| 0.75 | 0.75 | 97% (33/34) | 95% (19/20) | 82% (33/40) |
| 0.75 | 0.8 | 100% (34/34) | 100% (20/20) | 85% (34/40) |
| 0.8 | 0.0 | 100% (34/34) | 100% (20/20) | 92% (37/40) |
| 0.8 | 0.6 | 100% (34/34) | 100% (20/20) | 92% (37/40) |
| 0.8 | 0.7 | 100% (34/34) | 100% (20/20) | 92% (37/40) |
| 0.8 | 0.75 | 100% (34/34) | 100% (20/20) | 92% (37/40) |
| 0.8 | 0.8 | 100% (34/34) | 100% (20/20) | 92% (37/40) |
| 0.85 | 0.0 | 100% (34/34) | 100% (20/20) | 95% (38/40) |
| 0.85 | 0.6 | 100% (34/34) | 100% (20/20) | 95% (38/40) |
| 0.85 | 0.7 | 100% (34/34) | 100% (20/20) | 95% (38/40) |
| 0.85 | 0.75 | 100% (34/34) | 100% (20/20) | 95% (38/40) |
| 0.85 | 0.8 | 100% (34/34) | 100% (20/20) | 95% (38/40) |

##### Alternative: recall of the normal translation's back-translation (BT-vs-BT)

| R | detected (all) | detected (clause) | flagged real concise |
|---|---|---|---|
| 0.6 | 59% (20/34) | 40% (8/20) | 20% (8/40) |
| 0.65 | 74% (25/34) | 60% (12/20) | 30% (12/40) |
| 0.7 | 76% (26/34) | 60% (12/20) | 48% (19/40) |
| 0.75 | 76% (26/34) | 60% (12/20) | 70% (28/40) |
| 0.8 | 88% (30/34) | 80% (16/20) | 75% (30/40) |
| 0.85 | 94% (32/34) | 90% (18/20) | 80% (32/40) |

##### Recommended detector family: greedy (T=0) back-translation, relative recall

Flag if len(candidate)/len(normal) < L **or** Δ < D, where Δ = prefix-recall(source, BT0(candidate)) − prefix-recall(source, BT0(normal translation)).

| L | D | detected (all truncations) | detected (sentence drops) | detected (clause drops) | flagged real concise |
|---|---|---|---|---|---|
| 0.7 | – | 68% (23/34) | 86% (12/14) | 55% (11/20) | 0% (0/40) |
| 0.7 | -0.25 | 68% (23/34) | 86% (12/14) | 55% (11/20) | 0% (0/40) |
| 0.7 | -0.2 | 68% (23/34) | 86% (12/14) | 55% (11/20) | 2% (1/40) |
| 0.7 | -0.15 | 68% (23/34) | 86% (12/14) | 55% (11/20) | 10% (4/40) |
| 0.7 | -0.1 | 79% (27/34) | 86% (12/14) | 75% (15/20) | 28% (11/40) |
| 0.75 | – | 76% (26/34) | 86% (12/14) | 70% (14/20) | 0% (0/40) |
| 0.75 | -0.25 | 76% (26/34) | 86% (12/14) | 70% (14/20) | 0% (0/40) |
| 0.75 | -0.2 | 76% (26/34) | 86% (12/14) | 70% (14/20) | 2% (1/40) |
| 0.75 | -0.15 | 76% (26/34) | 86% (12/14) | 70% (14/20) | 10% (4/40) |
| 0.75 | -0.1 | 85% (29/34) | 86% (12/14) | 85% (17/20) | 28% (11/40) |
| 0.8 | – | 88% (30/34) | 100% (14/14) | 80% (16/20) | 8% (3/40) |
| 0.8 | -0.25 | 88% (30/34) | 100% (14/14) | 80% (16/20) | 8% (3/40) |
| 0.8 | -0.2 | 88% (30/34) | 100% (14/14) | 80% (16/20) | 10% (4/40) |
| 0.8 | -0.15 | 88% (30/34) | 100% (14/14) | 80% (16/20) | 15% (6/40) |
| 0.8 | -0.1 | 91% (31/34) | 100% (14/14) | 85% (17/20) | 30% (12/40) |

| candidates | p_src0 p50 | Δ p50 | Δ min | BT0-vs-BT0 p50 |
|---|---|---|---|---|
| real concise | 0.56 | 0.0 | -0.25 | 0.71 |
| drop_sentence | 0.3 | -0.25 | -0.5 | 0.48 |
| drop_clause | 0.45 | -0.12 | -0.4 | 0.63 |

Greedy BT of the normal translation vs source (prefix recall): p5=0.39, p50=0.56.

##### Real concise outputs

| id | lang | variant | len/normal | recall_src | recall_vs_nBT | output |
|---|---|---|---|---|---|---|
| r_cover_deck | tr | V5a | 0.947 | 0.625 | 0.875 | İletkenler, tip ve renk: Harika sayfaların nasıl oluşturulduğu ve bunları üreten araçlar. |
| r_cover_deck | tr | V5b | 0.968 | 0.625 | 0.875 | İletkenler, tip ve renk: Harika sayfaların nasıl oluşturulduğu — ve bunları üreten araçlar. |
| r_deck | tr | V5a | 0.876 | 0.5 | 0.727 | İyi bir düzen görünmezdir. İşte sayfanın altında neler oluyor: taban ızgarasından paragraf düzenleyicisine kadar. |
| r_deck | tr | V5b | 0.822 | 0.5 | 0.727 | İyi bir düzen görünmezdir. İşte sayfanın altında neler olur: temel ızgara’dan paragraf oluşturucuya kadar. |
| r_caption_hills | tr | V5a | 0.795 | 0.75 | 1.0 | Katmanlı tepelerin akşam ışığı — bu örnek için tamamen kodla üretildi. |
| r_caption_hills | tr | V5b | 0.83 | 0.75 | 1.0 | Katmanlı tepelerin akşam ışığı — bu örnek için tamamen kodla oluşturuldu. |
| r_body_1 | tr | V5a | 0.862 | 0.464 | 0.552 | Tipografi asıl işi üstlenir. Paragraf düzenleyicisi tüm olası satır sonlarını aynı anda değerlendirir; burada biraz gevşek bir satır yerine üç satır sonrasında … |
| r_body_1 | tr | V5b | 0.901 | 0.393 | 0.483 | Tipografi asıl işi üstlenir. Bir paragraf düzenleyicisi tüm olası satır sonlarını aynı anda değerlendirir; burada hafifçe gevşek bir satır yerine üç satır sonra… |
| r_body_2 | tr | V5a | 0.852 | 0.393 | 0.643 | Görseller bir yayına canlılık katar. Güçlü fotoğraflar sayfa kenarlarından taşarken, daha küçük resimler ızgara içinde kalır ve metnin etrafından dolaşmasını sa… |
| r_body_2 | tr | V5b | 0.905 | 0.5 | 0.75 | Görseller bir yayına canlılık katar. Güçlü bir fotoğraf sayfa kenarlarından taşarken, daha küçük resimler ızgara içinde kalır ve metnin etraflarından devam etme… |
| r_body_3 | tr | V5a | 0.894 | 0.56 | 0.731 | Renk her şeyi bir arada tutar. Başlıklar, kurallar ve arka planlarda tutarlı şekilde kullanılan iki‑üç renkten oluşan sınırlı palet, bir yayının kimliğini belir… |
| r_body_3 | tr | V5b | 1.009 | 0.64 | 0.808 | Renk her şeyi bir arada tutar. Başlıklar, kurallar ve arka planlarda tutarlı şekilde kullanılan iki veya üç renk tonundan oluşan sade palet, bir yayına kendine … |
| r_body_4 | tr | V5a | 0.805 | 0.6 | 0.714 | Arka planda stiller, hızlı çalışmanın sırrıdır: paragraf stilleri her öğenin sesini belirler, karakter stilleri vurguyu ayarlar ve nesne stilleri çerçeveleri tu… |
| r_body_4 | tr | V5b | 0.844 | 0.6 | 0.714 | Arka planda, stiller hızlı çalışmanın sırrıdır. Paragraf stilleri her öğenin sesini belirler, karakter stilleri vurguyu ortaya koyar ve nesne stilleri çerçevele… |
| r_body_5 | tr | V5a | 0.837 | 0.458 | 0.643 | Dizgi tamamlandığında belge, kenar boşlukları ve kesim işaretleriyle basıma hazır PDF olarak yazıcıya, açık format dosyası olarak meslektaşa veya net bir görünt… |
| r_body_5 | tr | V5b | 0.863 | 0.458 | 0.857 | Düzenleme bittikten sonra belge, kenar boşlukları ve kesim işaretleriyle basıma hazır PDF olarak yazıcıya, açık format dosyası olarak meslektaşa veya net bir gö… |
| r_footnote | tr | V5a | 0.841 | 0.625 | 0.818 | Bu örnekteki her görüntü, renk örneği ve paragraf kodla oluşturulmuştur; stok görseller yoktur. |
| r_footnote | tr | V5b | 0.929 | 0.625 | 0.909 | Bu örnekteki her görüntü, renk örneği ve paragraf kodla oluşturulmuştur; stok görseller kullanılmamıştır. |
| t_two_runs | tr | V5a | 0.857 | 0.533 | 0.562 | Her sayfa, boş bir olasılık alanıyla başlar. Önce ızgara gelir: okuma alanını çevreleyen kenar boşlukları, ritmi belirleyen sütunlar ve her satırı bir sütundan … |
| t_two_runs | tr | V5b | 0.905 | 0.567 | 0.625 | Her sayfa, boş bir olasılık alanıyla başlar. Önce ızgara gelir: okuma alanını çevreleyen kenar boşlukları, ritmi belirleyen sütunlar ve her satırı bir sütundan … |
| r_cover_deck | de | V5a | 0.862 | 0.75 | 0.667 | Gitter, Typ und Farbe: Wie großartige Seiten entstehen – und die Werkzeuge dafür. |
| r_cover_deck | de | V5b | 0.862 | 0.75 | 0.667 | Gitter, Typ und Farbe: Wie großartige Seiten entstehen – und die Werkzeuge dafür. |
| r_deck | de | V5a | 0.769 | 0.6 | 0.462 | Gute Gestaltung ist unsichtbar. So funktioniert es im Hintergrund – von der Baseline-Grid bis zum Absatzkomposer. |
| r_deck | de | V5b | 0.884 | 0.8 | 0.769 | Eine gute Layout-Struktur bleibt unsichtbar. So funktioniert es unter der Seite – von der Baseline-Grid bis zum Absatzkomponierer. |
| r_caption_hills | de | V5a | 0.989 | 0.875 | 1.0 | Abendlicht über schichtigen Hügeln – vollständig per Code für dieses Beispiel erzeugt. |
| r_caption_hills | de | V5b | 0.977 | 0.875 | 1.0 | Abendlicht über schichtigen Hügeln – vollständig in Code für dieses Beispiel erzeugt. |
| r_body_1 | de | V5a | 0.842 | 0.5 | 0.656 | Die Typografie erledigt die Hauptarbeit. Der Absatzkomponist prüft alle möglichen Zeilenumbrüche gleichzeitig und tauscht hier eine etwas lockere Zeile gegen ei… |
| r_body_1 | de | V5b | 0.842 | 0.5 | 0.656 | Die Typografie erledigt die Hauptarbeit. Ein Absatzkomponist prüft alle möglichen Zeilenumbrüche gleichzeitig und tauscht hier eine etwas lockere Zeile gegen ei… |
| r_body_2 | de | V5a | 0.825 | 0.536 | 0.741 | Bilder verleihen einer Publikation Leben. Starke Fotos überschreiten den Seitenrand, kleinere Bilder bleiben im Raster und ermöglichen es dem Text, sich darum z… |
| r_body_2 | de | V5b | 0.831 | 0.464 | 0.63 | Bilder verleihen einer Publikation Leben. Starke Fotos überschreiten den Seitenrand, während kleinere Bilder im Raster bleiben und das Textumfeld um sie herum e… |
| r_body_3 | de | V5a | 0.797 | 0.56 | 0.731 | Farbe verbindet alles. Eine begrenzte Palette aus zwei bis drei Farben, konsequent bei Überschriften, Regeln und Hintergründen verwendet, gibt einer Publikation… |
| r_body_3 | de | V5b | 0.832 | 0.56 | 0.731 | Farbe verbindet alles. Eine begrenzte Palette aus zwei bis drei Farben, die konsequent in Überschriften, Regeln und Hintergründen verwendet wird, verleiht einer… |
| r_body_4 | de | V5a | 0.845 | 0.52 | 0.593 | Im Hintergrund sorgen Stile für schnelles Arbeiten: Paragraphenstile bestimmen die Stimme jedes Elements, Charakterstile heben Schwerpunkte hervor und Objektest… |
| r_body_4 | de | V5b | 0.853 | 0.52 | 0.741 | Hinter den Kulissen sorgen Styles für schnelles Arbeiten. Absatzstile bestimmen die Stimme jedes Elements, Charakterstile heben Akzente hervor und Objektsstile … |
| r_body_5 | de | V5a | 0.821 | 0.583 | 0.483 | Sobald die Layout-Datei fertig ist, muss sie als druckbereites PDF mit Bleed- und Crop-Marken an den Drucker, als offenes Austauschformat an einen Kollegen oder… |
| r_body_5 | de | V5b | 0.895 | 0.542 | 0.448 | Sobald die Gestaltung fertig ist, muss das Dokument als druckbereites PDF mit Bleed- und Crop-Markierungen an einen Drucker, als offenes Austauschformat an eine… |
| r_footnote | de | V5a | 0.873 | 0.625 | 0.667 | Jedes Bild, jeder Farbbeispiel und jeder Absatz in diesem Beispiel wird per Code erzeugt – keine Stock-Bilder. |
| r_footnote | de | V5b | 1.008 | 0.375 | 0.667 | Jedes Bild, jede Musteransicht und jeder Absatz in diesem Beispiel wird per Code erstellt – es werden keine Vorlagen verwendet. |
| t_two_runs | de | V5a | 0.838 | 0.5 | 0.545 | Jede Seite beginnt als leeres Potentialfeld. Zuerst entsteht das Raster: Randbereiche, die den Lesebereich begrenzen, Spalten, die den Rhythmus vorgeben, sowie … |
| t_two_runs | de | V5b | 0.836 | 0.5 | 0.667 | Jede Seite beginnt als leeres Potenzialfeld. Zuerst entsteht das Raster: Randbereiche, die den Lesebereich begrenzen, Spalten, die den Rhythmus vorgeben, sowie … |

**Thresholds and findings**
- **Length gate: accept a concise candidate only if `len(concise) ≥ 0.80 × len(normal translation)`.** This detects
  **88% (30/34)** of deliberate truncations: **100% of dropped sentences (14/14)**, 80% of dropped clauses (16/20).
  It rejects 7.5% (3/40) of real concise outputs (min real ratio 0.77). A rejection only means "keep the normal
  translation", so false positives are cheap. At 0.75: 76% detection, 0% false positives.
- **Back-translation, measured honestly: it adds nothing over the length gate on this set.**
  - Absolute content-word recall of a back-translation against the English source is too noisy to use: normal
    translations reach only p50 0.56–0.58 recall, and any threshold that catches omissions flags 60–92% of real
    concise outputs.
  - The relative form is usable but weak. Δ = prefix-recall(source, BT₀(concise)) − prefix-recall(source,
    BT₀(normal)), with greedy back-translations. Real concise: Δ p50 0.0, min −0.25. Sentence drops: p50 −0.25.
    Clause drops: p50 −0.12. At D = −0.25 it adds no false positives, and also no detections beyond L = 0.80. At
    D = −0.10 it adds +5 pp clause detection for +22 pp false positives.
  - Recommendation: keep it as a cheap secondary guard (**Δ ≥ −0.25**, numbers identical, DNT present). It costs 2
    calls (≈1–3 s per body paragraph). Do not rely on it for phrase-level omissions such as "Jede Seite beginnt
    leer" (dropping "of possibility"). No lexical check here catches those reliably. Clause drops with ratio ≥ 0.85
    went undetected by every method (4/20).
- Real concise outputs save little: median length is 0.84–0.90 of the normal translation. On inspection none of
  the 3 length-flagged real outputs had dropped content (they merge sentences). A sentence-count rule therefore adds
  only false positives (5–9/40).
- V5a vs V5b: V5a is shorter (p50 0.85/0.84 vs 0.90/0.86) with similar recall. Use V5b first, V5a as the second
  attempt, both behind the same gates.

---

## 11. Sampling, determinism and retry

#### Sampling: failure-prone items, 3 runs each (random seed unless noted)

| variant | temp | lang | n | ref_ok | case_ok | mean distinct outputs /3 | items fully deterministic |
|---|---|---|---|---|---|---|---|
| V1b | 0.7 | tr | 30 | 0% (0/30) | 100% (12/12) | 1.10 | 90% |
| V1b | 0.7 | de | 30 | 37% (11/30) | 100% (12/12) | 1.30 | 80% |
| V1b | 0.2 | tr | 30 | 0% (0/30) | 100% (12/12) | 1.00 | 100% |
| V1b | 0.2 | de | 30 | 37% (11/30) | 100% (12/12) | 1.20 | 80% |
| V4 | 0.7 | tr | 30 | 37% (11/30) | 100% (12/12) | 1.60 | 50% |
| V4 | 0.7 | de | 30 | 50% (15/30) | 75% (9/12) | 1.20 | 80% |
| V4 | 0.2 | tr | 30 | 50% (15/30) | 100% (12/12) | 1.50 | 50% |
| V4 | 0.2 | de | 30 | 53% (16/30) | 75% (9/12) | 1.20 | 80% |
| V4g | 0.7 | tr | 30 | 90% (27/30) | 50% (6/12) | 1.00 | 100% |
| V4g | 0.7 | de | 30 | 100% (30/30) | 25% (3/12) | 1.00 | 100% |
| V4g | 0.2 | tr | 30 | 90% (27/30) | 50% (6/12) | 1.00 | 100% |
| V4g | 0.2 | de | 30 | 100% (30/30) | 25% (3/12) | 1.00 | 100% |
| V4-seed42 | 0.7 | tr | 9 | 33% (3/9) | – | 1.00 | 100% |
| V4-seed42 | 0.7 | de | 9 | 33% (3/9) | – | 1.00 | 100% |

- With `top_p 0.6, top_k 20`, short outputs are nearly deterministic even at T=0.7 (V4g: 100% of items give the
  same output 3/3; V1b 80–90%). A fixed `seed` makes every call reproducible (V4-seed42: 100%). **Set `seed`** so
  translation-memory misses reproduce.
- **Temperature 0.2 does not fix word-sense errors.** V1b TR stays 0% on the failure-prone items, V4 rises only
  37→50% (TR) and 50→53% (DE); V4g is 90%/100% at both temperatures. Keep the recommended T=0.7 for first attempts
  and use T=0.2 only on retries, where the change of template does the work.

#### Retry (strict template, T=0.2) on main-grid validator failures: fixed 30/32

| first variant | lang | id | failed | retry template | fixed | first output | retry output |
|---|---|---|---|---|---|---|---|
| V1 | tr | r_th_swatch | untranslated | V4g | ✓ | SWATCH | RENK ÖRNEĞİ |
| V1b | tr | r_th_swatch | untranslated | V4g | ✓ | SWATCH | RENK ÖRNEĞİ |
| V2 | tr | r_th_swatch | untranslated | V4g | ✓ | SWATCH | RENK ÖRNEĞİ |
| V4 | tr | r_folio_quarterly | untranslated | V4g | ✓ | QUARTERLY | Üç Aylık |
| V1b | tr | t_four | tag_ok | V3g | ✓ | Yapı için <g0></g0><g1>Paragraf Stilleri</g1><g2>’ni ve vurgulama için | <g0>Kullanın </g0><g1>Paragraf stillerini</g1><g2> yapı oluşturmak içi |
| V2 | tr | t_four | tag_ok | V3g | ✓ | Yapı için <g0></g0><g1>Paragraf Stilleri</g1><g2>’ni ve vurgulama için | <g0>Kullanın </g0><g1>Paragraf stillerini</g1><g2> yapı oluşturmak içi |
| V4 | tr | ph_br_brace | ph_multiset | V3g | ✓ | Düzenlemenin Sessiz Sanatı | Sessiz{1} Düzenleme Sanatı |
| V4g | tr | ph_br_brace | ph_multiset | V3g | ✓ | Düzenlemenin Sessiz Sanatı | Sessiz{1} Düzenleme Sanatı |
| V3 | tr | ph_unit_uni | ph_multiset | V3g | ✓ | ⟦2⟧⟦1⟧⟦2⟧ için rahat okuma deneyimi sunacak şekilde metin ayarlanmıştı | ⟦1⟧ metnini, rahat okuma deneyimi sunmak için ⟦2⟧ satır aralığı ile ay |
| V3cg | tr | ph_mid_uni | ph_multiset | V3g | ✓ | Görseli yerleştirmek için ⟨1⟩ tuşuna basın, ardından boyutunu ayarlama | Resmi yerleştirmek için ⟦1⟧ tuşuna basın, ardından boyutunu ayarlamak  |
| V4 | tr | c_folio_2 | untranslated | V4g | ✓ | 2  ·  QUARTERLY | 2 · ÜÇ AYLIK |
| V1 | de | r_caption_inkplum | untranslated | V4g | ✓ | Ink Plum | Tinte Pflaume |
| V1 | de | r_th_swatch | untranslated | V4g | ✓ | SWATCH | Farbfeld |
| V1b | de | r_th_swatch | untranslated | V4g | ✓ | SWATCH | Farbfeld |
| V4 | de | r_th_swatch | untranslated | V4g | ✓ | SWATCH | Farbfeld |
| V1 | de | r_td_inkplum | untranslated | V4g | ✓ | Ink Plum | Tinte Pflaume |
| V4 | de | r_td_cyan | untranslated | V4g | ✗ | Cyan | Cyan |
| V4g | de | r_td_cyan | untranslated | V4g | ✗ | Cyan | Cyan |
| V1 | de | r_td_charts | untranslated | V4g | ✓ | Charts, Links | Diagramme, Links |
| V4 | de | r_folio_quarterly | untranslated | V4g | ✓ | QUARTERLY | Vierteljährlich |
| V4 | de | t_two_runs | tag_ok | V3g | ✓ | Jede Seite beginnt als ein leeres Feld voller Möglichkeiten. Zuerst tr | <g0>Jede Seite beginnt als</g0><g1>ein leeres Feld voller Möglichkeite |
| V4 | de | t_mid_word | tag_ok | V3g | ✓ | Setzen Sie den Text in <g1>italics</g1><g2> nur dort, wo der Autor ein | <g0>Setzen Sie den Text in </g0><g1>verschiedenem Schriftgrad</g1><g2> |
| V4g | de | t_mid_word | tag_ok | V3g | ✓ | Setzen Sie den Text in <g1>italics</g1><g2> nur dort, wo der Autor ein | <g0>Setzen Sie den Text in </g0><g1>verschiedenem Schriftgrad</g1><g2> |
| V3b | de | t_mid_word | tag_ok | V3g | ✓ | <g0>Stellen Sie den Text in <g1>versetzte Schrift</g1><g2> nur dort ei | <g0>Setzen Sie den Text in </g0><g1>verschiedenem Schriftgrad</g1><g2> |
| V3b | de | t_bold_term | tag_ok | V3g | ✓ | <g0>A </g0><g1>Die Baseline-Grid-Struktur sorgt dafür, dass jede Zeile | <g0>A </g0><g1>Grundlinienraster</g1><g2>hält jede Linie in den Spalte |
| V4 | de | t_nested | tag_ok | V3g | ✓ | Lesen Sie den <g1>vollständigen Artikel</g1> auf Seite 12. | <g0>Lesen Sie die <g1>vollständige Geschichte</g1> auf Seite 12.</g0> |
| V4g | de | t_nested | tag_ok | V3g | ✓ | Lesen Sie den <g1>vollständigen Artikel</g1> auf Seite 12. | <g0>Lesen Sie die <g1>vollständige Geschichte</g1> auf Seite 12.</g0> |
| V4 | de | ph_br_xml | ph_multiset | V3g | ✓ | Die stille Kunst der Layout-Gestaltung | Die ruhige <x1/>Kunst des Layouts |
| V4g | de | ph_br_xml | ph_multiset | V3g | ✓ | Die stille Kunst der Layout-Gestaltung | Die ruhige <x1/>Kunst des Layouts |
| V4g | de | ph_unit_brace | ph_multiset | V3g | ✓ | Stellen Sie den Zeilenabstand des Textes auf {2} ein, um ein angenehme | Legen Sie den Text im Bereich {1} mit einem Zeilenabstand von {2} fest |
| V4g | de | ph_unit_dbl | ph_multiset | V3g | ✓ | Stellen Sie den Zeilenabstand des Haupttextes auf [[2]] ein, um ein an | Stellen Sie den Text in [[1]] mit einem Zeilenabstand von [[2]] ein, u |
| V4 | de | c_folio_2 | untranslated | V4g | ✓ | 2  ·  QUARTERLY | 2  ·  VIERTELJÄHRLICH |

---

## 12. Batching (numbered lines in one prompt)

#### Batching (numbered lines in one prompt)

| batch size | lang | chunks | chunks aligned | segments/s | segments with length off 0.5–2× vs single | ref_ok | case_ok |
|---|---|---|---|---|---|---|---|
| 5 | tr | 10 | 100% | 1.56 | 0 | 61% (17/28) | 82% (9/11) |
| 5 | de | 10 | 100% | 1.86 | 0 | 54% (15/28) | 82% (9/11) |
| 10 | tr | 5 | 100% | 1.59 | 0 | 61% (17/28) | 91% (10/11) |
| 10 | de | 5 | 100% | 1.91 | 1 | 57% (16/28) | 82% (9/11) |
| 1 (sequential V1b) | tr | 50 | 100% | 1.42 | – | 46% (13/28) | 73% (8/11) |
| 1 (sequential V1b) | de | 50 | 100% | 1.64 | – | 57% (16/28) | 91% (10/11) |

Alignment was perfect (30/30 chunks; 1 of 200 segments had an odd length). The speed gain is only +10–16% over
sequential V1b, though. A batch cannot carry per-segment context, role, glossary or tag rules, so its reference
score equals the no-context baseline (54–61%) against 70–80% for the routed per-segment templates. A misaligned
batch would also corrupt several segments at once. **Do not batch.** If speed is ever needed, 2 parallel requests
gave +18% (§13).

---

## 13. Throughput and Ollama options

#### Throughput (routed templates, warm model, 50 segments)

| lang | parallel requests | segments | total s | segments/s | p50 s/seg | p95 s/seg | max prompt tokens | ref_ok | added_any |
|---|---|---|---|---|---|---|---|---|---|
| tr | 1 | 50 | 43.17 | 1.16 | 0.46 | 2.97 | 212 | 80% (24/30) | 0% (0/50) |
| tr | 2 | 50 | 36.6 | 1.37 | 0.69 | 5.14 | 212 | 80% (24/30) | 0% (0/50) |
| de | 1 | 50 | 37.58 | 1.33 | 0.46 | 2.25 | 205 | 83% (25/30) | 0% (0/50) |
| de | 2 | 50 | 30.61 | 1.63 | 0.68 | 4.16 | 205 | 83% (25/30) | 0% (0/50) |

##### Routed outputs for short segments (workers=1)

| id | lang | template | output |
|---|---|---|---|
| r_folio_spring | tr | V4g | İLKYAZ SAYISI |
| r_kicker_cover | tr | V4g | İLkbahar Sayısı · 01. Sayı |
| r_cover_title_1 | tr | V4g | Sessizlik |
| r_cover_title_2 | tr | V4g | Düzen Sanatı |
| r_kicker_feature | tr | V4g | Dosya · Tasarım |
| r_headline_grid | tr | V4g | ızgara Üzerine Notlar |
| r_kicker_next | tr | V4g | Gelecek sayıda |
| r_cover_title_color | tr | V4g | Renk, Mürekkep ve Kağıt |
| r_caption_inkplum | tr | V4g | Mürekkep Eriği |
| r_caption_sunset | tr | V4g | Gün batımı |
| r_caption_cmyk | tr | V4g | C=100 M=0 Y=0 K=0 |
| r_caption_paperwarm | tr | V4g | Kağıt Sıcaklığı |
| r_th_swatch | tr | V4g | RENK ÖRNEĞİ |
| r_th_build | tr | V4g | KARİŞİM |
| r_th_usedfor | tr | V4g | KULLANIM ALANI |
| r_td_inkplum | tr | V4g | Mürekkep Erik |
| r_td_build1 | tr | V4g | C62 M95 Y30 K25 |
| r_td_bg_heads | tr | V4g | Arka planlar, başlıklar |
| r_td_build2 | tr | V4g | M62 Y78 |
| r_td_kickers_rules | tr | V4g | Üst başlıklar, çizgiler |
| r_td_cyan | tr | V4g | Siyah mavi |
| r_td_charts | tr | V4g | Grafikler, bağlantılar |
| r_td_build4 | tr | V4g | M3 Y8 |
| r_td_pullquotes | tr | V4g | Öne çıkan alıntılar |
| r_folio_quarterly | tr | V4g | Üç Aylık |
| t_link | tr | V3cg | <g0>Fotoğraf: </g0><g1>Anna Berg</g1><g2> DesignCraft için</g2> |
| t_short_head | tr | V3cg | <g0>The </g0><g1>ızgara</g1><g2> Sayısı</g2> |
| t_cover_pair | tr | V3cg | <g0>Sessizlik</g0><g1>Düzenleme Sanatı</g1> |
| ph_br_uni | tr | V3cg | Düzenlemenin Sessiz⟦1⟧Sanatı |
| ph_br_brace | tr | V3cg | Düzenlemenin Sessiz{1}Sanatı |
| ph_br_xml | tr | V3cg | Düzenin Sessiz <x1/>Sanatı |
| ph_br_dbl | tr | V3cg | Düzenin Sessiz[[1]]Sanatı |
| nl_br | tr | V4g | Sessizlik  ⏎Düzenleme Sanatı |
| r_folio_spring | de | V4g | FRÜHLINGSAUSSCHNITT |
| r_kicker_cover | de | V4g | Die Frühjahrsspezialausgabe · Nr. 01 |
| r_cover_title_1 | de | V4g | Die Stille |
| r_cover_title_2 | de | V4g | Kunst der Seitengestaltung |
| r_kicker_feature | de | V4g | Reportage · Design |
| r_headline_grid | de | V4g | Anmerkungen zur Rasterstruktur |
| r_kicker_next | de | V4g | Demnächst |
| r_cover_title_color | de | V4g | Farbe, Tinte & Papier |
| r_caption_inkplum | de | V4g | Tinte Pflaume |
| r_caption_sunset | de | V4g | Sonnenuntergang |
| r_caption_cmyk | de | V4g | C=100 M=0 Y=0 K=0 |
| r_caption_paperwarm | de | V4g | Papiertönung Warm |
| r_th_swatch | de | V4g | Farbfeld |
| r_th_build | de | V4g | Farbaufbau |
| r_th_usedfor | de | V4g | VERWENDET FÜR |
| r_td_inkplum | de | V4g | Tinte Pflaume |
| r_td_build1 | de | V4g | C62 M95 Y30 K25 |
| r_td_bg_heads | de | V4g | Hintergründe, Überschriften |
| r_td_build2 | de | V4g | M62 Y78 |
| r_td_kickers_rules | de | V4g | Dachzeilen, Linien |
| r_td_cyan | de | V4g | Cyan |
| r_td_charts | de | V4g | Diagramme, Links |
| r_td_build4 | de | V4g | M3 Y8 |
| r_td_pullquotes | de | V4g | Pull-Quotes |
| r_folio_quarterly | de | V4g | Vierteljährlich |
| t_link | de | V3cg | <g0>Bild: </g0><g1>Anna Berg</g1><g2> für DesignCraft</g2> |
| t_short_head | de | V3cg | <g0>Die </g0><g1>Raster</g1><g2>Ausgabe</g2> |
| t_cover_pair | de | V3cg | <g0>Die Stille</g0><g1>Kunst der Gestaltung</g1> |
| ph_br_uni | de | V3cg | Die ruhige⟦1⟧Kunst des Layouts |
| ph_br_brace | de | V3cg | Die stille{1}Kunst des Layouts |
| ph_br_xml | de | V3cg | Die stille <x1/>Kunst der Layout-Planung |
| ph_br_dbl | de | V3cg | Die stille[[1]]Kunst des Layouts |
| nl_br | de | V4g | Die Stille  ⏎Die Kunst des Layouts |

- **Throughput (warm model, routed templates, 50 segments)**: TR 43.2 s (1.16 seg/s), DE 37.6 s (1.33 seg/s).
  Median 0.46 s per segment; body paragraphs about 2–3 s (p95 2.3–3.0 s). With 2 concurrent requests: 36.6 s / 30.6
  s (+18–22%, while per-request p95 latency roughly doubles). A cold load adds ≈30 s once. The target of
  50 paragraphs < 3 min is met by about 4×.
- **Stop tokens**: the Modelfile template is `<|startoftext|>{prompt}<|extra_0|>{response}<|eos|>`, with stops
  `<|startoftext|>`, `<|extra_4|>`, `<|extra_0|>`, `<|eos|>`. All 1,114 main-grid calls ended with
  `done_reason: stop`, and no special tokens leaked into any output. No custom stops are needed.
- **`num_predict` cap**: the max observed output was 2.14 tokens per source character (on short strings), and the
  max of `eval_tokens − 2 × source_chars` was +2. Output/source *token* ratio reached p95 2.9 and max 3.5 (TR). A
  "3 × source tokens" cap would therefore truncate legitimate Turkish output. **Use `num_predict = 2 × len(source
  chars) + 32`** (cap at 2048). It covers every observed output with margin and still stops runaway outputs early.
  The cap works: `num_predict 8` returned `done_reason: length`. Treat `done_reason == "length"` as a validator
  failure (truncated output).
- **`num_ctx`**: the longest prompt was 281 tokens (main grid; about 212 for the routed templates), plus at most
  159 output tokens. The default context (4096, per `ollama ps`) is plenty. Set `num_ctx: 2048` explicitly so the
  tool does not depend on server defaults. I did not measure whether a smaller context is faster.
- **`keep_alive`**: `"30m"` on each request is honoured (`/api/ps` showed `expires_at` 30 min ahead). Use it so the
  model is not unloaded between the translate and fit passes. Unload at exit with `keep_alive: 0` if desired.

#### Token statistics (main grid)

output tokens per source character: {'p50': 0.63, 'p95': 1.15, 'p99': 1.79, 'max': 2.142857142857143}; max prompt tokens: 281; done_reason counts: {'stop': 1114}

---

## 14. Length-ratio validator bounds (target chars / source chars, markers stripped)

#### Length ratio target/source (chars, markers stripped)

| lang | class | n | min | p5 | p50 | p95 | max |
|---|---|---|---|---|---|---|---|
| tr | all (V2/V4g) | 178 | 0.71 | 0.89 | 1.24 | 1.8 | 2.5 |
| tr | body ≥ 7 words | 84 | 0.87 | 1.02 | 1.27 | 1.79 | 2.03 |
| tr | short ≤ 6 words | 94 | 0.71 | 0.83 | 1.16 | 1.78 | 2.5 |
| de | all (V2/V4g) | 178 | 0.82 | 1.0 | 1.33 | 2.0 | 2.5 |
| de | body ≥ 7 words | 84 | 1.03 | 1.08 | 1.36 | 2.02 | 2.48 |
| de | short ≤ 6 words | 94 | 0.82 | 0.82 | 1.29 | 2.0 | 2.5 |

These are V2/V4g outputs, excluding code-like items and outputs with added text. Recommended validator bounds
(p5 × 0.9 … p95 × 1.15; soft fail → retry):

| lang | body (≥ 7 words) | short (≤ 6 words) |
|---|---|---|
| tr | **0.92 – 2.06** (p5 1.02, p50 1.27, p95 1.79) | no ratio check; use `len ≤ 3 × src + 12` and the echo detector (p5 0.83, p50 1.16, p95 1.78) |
| de | **0.97 – 2.32** (p5 1.08, p50 1.36, p95 2.02) | as TR (p5 0.82, p50 1.29, p95 2.00) |

DE body above 2.3 was always an elaboration error (`ph_unit_uni` 2.48: "wobei der Zeilenabstand selbst bei ⟦1⟧
liegt…").

---

## 15. Validator checklist (for the implementer)

1. `done_reason == "stop"` (otherwise truncated).
2. Tags: identical `<gN>` sequence and valid nesting, and no text outside the tags when the source had none. Allow
   empty tag content: TR has no article for `<g0>The </g0>`.
3. Placeholders: normalise look-alikes, then compare multisets.
4. Numbers: digit multiset with `.`/`,` removed.
5. DNT verbatim.
6. Identity with the source: skip if code-like. Otherwise soft-fail, retry, then accept with a review flag.
7. No added prefix, quotes, notes or extra lines (0 occurrences in 2,000+ calls with these templates, but keep the
   check).
8. Synopsis-echo 3-gram check for S/TS outputs.
9. Length bounds from §14.
10. Case restore: ALL CAPS fold/unfold, plus the lost-initial-capital fix.

## 16. Files
- `research/eval/build_eval_set.py`: builds `eval_set.jsonl` (glossary, DNT, references).
- `research/eval/run_eval.py`: harness. Stages: `main, caps, concise, sampling, multipara, retry, bleed,
  batching, throughput, options`. Flags: `--resume` (reuse cached calls), `--stages`, `--report-only`.
- `research/eval/results/raw.jsonl` (every call, with prompt, options, output, timings, token counts),
  `metrics.jsonl`, `summary.md`, `summary.json`, `options.json`.
