# PLAN: `idml-translate` (Phase 0 output, awaiting approval)

Status: **draft for approval**. No production code has been written. Evidence lives in:
- `research/idml_coverage.md` (R1): IDML text inventory, sample survey, test files in `fixtures/`
- `research/designcraft.md` (R2): DesignCraft behaviour; tested snippet `research/designcraft_verify_snippet.py`
- `research/prompts.md` (R3): Hy-MT2 template measurements; harness in `research/eval/`

---

## 0. Baseline and what the research changed

### Prototype baseline (reproduced 2026-10-12, TR, fresh TM, `demo_translate.py`)
| Metric | Value |
|---|---|
| Segments | 52 (1 tagged), 45 model calls, 26 TM hits |
| Time | 52.5 s (including the first model load) |
| Geometry | identical |
| Overset | story 11 (`Story_u26`) on the first pass, fixed by concise retranslation. The earlier recorded run had none, so the result is not deterministic (no seed). |
| PNGs | 3 of 4, and **wrong pages**: `--page` counts from 0, so "p1..p3" were pages 2–4 and the cover was never rendered or compared (R2, confirmed by me). |
| Quality (TR) | "Notes on the Grid" → "İletken Şebeke Üzerine Notlar"; "The Quiet" / "Art of Layout" translated separately → "Sessizlik" / "Düzen Sanatı"; "BUILD" → "İNŞA ET" (verb); "Kickers" left in English; "heads" → "başlar"; "Pull quotes" → "Tırnak işaretlerini çekin"; "QUARTERLY" → "ÇEYREK YILLIK" |

### Research findings that change the target design in PROMPT.md
1. **DesignCraft cannot be the main safety check.** On import it silently drops anchored text frames, variable instances, hyperlinks and notes, and flattens tracked changes (R1). A broken edit in those would pass every DC check. → The **package diff gate (our own canonical XML comparison) is the primary safety net**. DC adds geometry, overset, glyph and render checks.
2. **DC does not report item `rotation` or `page`**, and does not list master-spread items (R2). → The geometry gate compares `id/kind/bounds/story/columns` plus spreads and page count, and derives the page from the item centre. Master and spread geometry are additionally covered by requiring `Spreads/*` and `MasterSpreads/*` to be byte-identical (stronger than DC).
3. **DC hyphenates English only** (R2). Its TR/DE line breaks never hyphenate, so its overset is a **pessimistic** estimate. → Overset is reported as "overset in DesignCraft (no TR/DE hyphenation; may fit in InDesign)" with the overflow character count from `preflight.run`. The fit loop still runs, but the report says this.
4. **Missing glyphs come from `preflight.run`** (`kind: missingGlyphs`), which matched fontTools exactly. fontTools cannot read the bundled fonts. → No fontTools dependency.
5. **Story mapping by frame geometry**, with designmap `<idPkg:Story>` order as a cross-checked fallback for master stories. It never compares text, so it works on translations. It raises an error rather than guess (R2, 18/18 correct).
6. **The glossary is the biggest quality lever** (R3): short-segment reference hits rose from 37% / 50% to 77% / 93% (TR / DE). Context alone added only 6–7 points, but context combined with ALL-CAPS folding added 43 points (TR).
7. **Multi-paragraph headings** must be translated as one unit joined with `⟦n⟧`. That form kept the boundary and produced a natural headline 18/18; newline and tag forms gave a natural headline 0/18 (R3).
8. **The concise check reduces to a length gate.** "Length ≥ 0.80 × normal translation" caught 30/34 deliberate omissions (all 14 dropped sentences). Back-translation added no detections at a 0% false-positive threshold (R3). PROMPT.md requires a back-translation check, so it stays as a second gate at Δ ≥ −0.25. The length default goes from 0.75 to **0.80** (configurable).
9. **New failure mode: context bleed.** The model sometimes translates the synopsis into the output (6/288 calls, only when there were no neighbouring paragraphs). A 3-gram echo detector caught 6/6 with 0 false flags in 686 outputs.
10. Corrections to the brief: the page-number marker is `<?ACE 18?>` (ACE 3 is something else). `<Content>`'s parent is not always a CSR (XMLElement, HyperlinkTextSource), so the language goes on the **nearest ancestor CSR**.

---

## 1. Scope decisions (from R1's inventory)

| Construct | Decision | Reason |
|---|---|---|
| Story body, threaded stories, master-spread stories, text on path, stories of anchored or grouped frames | **translate** | Ordinary `<Content>` in story files |
| Tables (incl. header/footer rows, multi-paragraph cells) | **translate**, one segment per cell paragraph | |
| Footnotes | **translate**, separate segment; `<?ACE 4?>` + TAB stay first | |
| Hyperlink text (`HyperlinkTextSource`) | **translate**; the wrapper is a run boundary | names and URLs never translated |
| XMLElement-wrapped text | **translate**; the wrapper is a run boundary | BackingStory skipped |
| Conditional text | **translate visible and hidden**; hidden text is excluded from fit and listed in the report | `AppliedConditions` never touched |
| Tracked changes | **warn**. Translate `InsertedText`, **skip `DeletedText`** (never part of the sentence) | The report recommends accepting/rejecting changes first |
| Cross-reference source text | **translate as its own atomic segment** + warning "update cross-references will regenerate it" | |
| TOC/index *stories* | translate + warning (regeneration overwrites) | |
| Notes (editorial) | **skip** (not printed), reported | |
| Unplaced stories | translate + flagged "unplaced" | |
| Linked stories (InCopy) | translate + warning (updating the link overwrites) | |
| **Attribute-held visible text**: custom text variables, xref-format `CustomText` ("on page"), index topics, TOC title, section marker/prefix, numbering expressions with letters, alt text / actual text, bookmarks | **skip, listed in the report with location and text** | Editing attributes is outside invariant 1. A v2 option with an explicit invariant extension. |
| Images/PDF/EPS links, outlined text | **flag unreachable** (list links; heuristic warning for compound-path groups) | |
| Names/IDs (styles, swatches, `Cell@Name`, etc.) | never touched | |
| Unknown elements | handled generically: a known run wrapper is walked through; anything else is an immovable inline object (slot boundary). An unknown element that contains `<Content>` is treated as a nested container, and a warning is raised. | Do not whitelist; never drop |
| `.indd`, RTL, CJK | out of scope | |

Special characters (R1 §3): TAB, U+2028 and fixed-width spaces (U+2002–U+200A, U+2007, U+202F) → placeholders, keeping the exact character. NBSP → placeholder when between a number and a unit, else a normal space with the original restored by position where possible. Soft hyphen U+00AD and in-word U+200B → stripped before MT and not re-inserted (reported in stats). PIs and inline objects → slot boundaries, never moved. Control characters must never be written (validated).

Swatch-name captions ("Ink Plum", "Paper Warm"): a segment whose whole text equals a swatch name in `Resources/Graphic.xml` is kept by default (`keep_swatch_names = true`). It names the swatch the reader sees in the Swatches panel.

---

## 2. Architecture

```
load → extract → plan-context → translate → postprocess/QA → inject → verify → fit-loop → report
```
Package layout (stdlib + lxml; PyYAML optional for YAML glossaries, already installed):
```
idml_translate/
  __init__.py, __main__.py
  model.py        # shared data classes (orchestrator-owned, written before wave 2)
  config.py       # Config, LanguageSpec, glossary/DNT loading        (orchestrator)
  data/languages.toml                                                  (orchestrator)
  idml_io.py      # zip package read/write, canonical diff            (I1)
  extract.py      # slots, segments, roles, context, inventory        (I1)
  markup.py       # encode segment → model text; decode output → slot texts (I1)
  inject.py       # write slot texts + AppliedLanguage                (I1)
  casing.py       # locale-aware case detection/restore               (I2)
  backend.py      # TranslationBackend protocol, OllamaBackend, IdentityBackend (I2)
  prompts.py      # templates P/S/T/TS/C/B/R                          (I2)
  validate.py     # validators                                        (I2)
  tm.py           # SQLite translation memory                         (I2)
  translate.py    # routing, retries, glossary/DNT application        (I2)
  dc.py           # DesignCraft CLI wrapper (from R2 snippet)         (I3)
  verify.py       # gates                                             (I3)
  fit.py          # fit loop                                          (I3)
  report.py       # report.json + HTML                                (I4)
  cli.py          # argparse, pipeline, exit codes                    (I4)
tests/ ...
```

### 2.1 Shared data classes (`model.py`)
```python
SlotAttr = Literal["text", "tail"]

@dataclass
class Slot:
    entry: str                 # zip entry, e.g. "Stories/Story_u26.xml"
    path: str                  # stable XPath-like locator of the element (for reports/tests)
    attr: SlotAttr             # "text" of <Content> or "tail" of a PI inside <Content>
    source: str                # original full text (incl. edge whitespace)
    csr_path: str | None       # nearest ancestor CharacterStyleRange (for AppliedLanguage)
    # runtime-only: the lxml element is held by the Document, never serialised

Role = Literal["headline","cover_title","deck","kicker","folio","running_head","body","caption",
               "pull_quote","table_header","table_cell","footnote","xref","toc","index","other"]

@dataclass
class Segment:
    id: str                    # "<story>#<n>" stable within a document
    story: str                 # story Self, e.g. "u26"
    entry: str
    slots: list[Slot]          # all slots of the paragraph(s), in order
    letter_slots: list[int]    # indices into slots that carry letters (get <gN> tags when ≥ 2)
    para_breaks: list[int]     # for joined headings: slot index where each next paragraph starts
    container: Literal["story","cell","footnote","xref","note"]
    para_style: str            # e.g. "ParagraphStyle/Cover Title"
    char_caps: bool            # AllCaps/SmallCaps from style/CSR (resolved through the style hierarchy)
    role: Role
    prev_text: str | None      # neighbour paragraph plain text (≤ 300 chars)
    next_text: str | None
    hidden: bool               # in a hidden condition
    on_master: bool
    capacity_hint: int | None  # source chars of the story (fit ordering), not a hard limit
    flags: list[str]

@dataclass
class Encoded:                 # produced by markup.encode
    text: str                  # what the model sees, e.g. "<g0>Every page begins as</g0><g1> an empty…</g1>" with ⟦n⟧
    placeholders: dict[str,str]   # "⟦1⟧" → "\t"
    tags: int                  # number of <gN> pairs (0 = plain)
    para_marks: list[str]      # placeholders that are paragraph boundaries (order-strict)
    case_fold: Literal["none","sentence"]   # ALL-CAPS folding applied
    code_like: bool            # no run of ≥ 3 letters outside DNT → never sent to the model

@dataclass
class Translation:
    segment_id: str
    status: Literal["translated","tm","kept_source","code_like","skipped"]
    slot_texts: list[str] | None   # final text per slot (edges restored), None if kept source
    output_raw: str | None
    template: str              # "P","S","T","TS","C"
    attempts: int
    issues: list["Issue"]
    concise: bool = False

@dataclass
class Issue:
    severity: Literal["error","warning","info"]
    code: str                  # e.g. "tag_mismatch","untranslated","overset","skipped_attribute_text"
    message: str
    segment_id: str | None = None
    entry: str | None = None
    page: int | None = None    # 1-based for humans
    frame: int | None = None   # DC frame id
    data: dict = field(default_factory=dict)
```

### 2.2 Module interfaces
```python
# idml_io.py
class IdmlPackage:
    @classmethod
    def open(cls, path: Path) -> "IdmlPackage"          # reads all entries + ZipInfo, parses Stories/*.xml lazily
    entries: list[zipfile.ZipInfo]                     # original order
    def read(self, name: str) -> bytes
    def story_tree(self, name: str) -> etree._Element  # parsed with remove_blank_text=False, resolve_entities=False
    def story_entries(self) -> list[str]
    def designmap(self) -> etree._Element              # read-only
    def write(self, out: Path, changed: dict[str, etree._Element]) -> None
        # only entries in `changed` are reserialised (original XML declaration bytes kept); all others are
        # copied byte-for-byte with original ZipInfo (order, compression, date_time); mimetype first + stored.
        # Writes to a temp file; the caller moves it into place after the hard gates.
def canonical_diff(src: Path, out: Path, allow: AllowPolicy) -> list[Issue]
    # non-story entries: byte equality. Story entries: mask allowed payload (Content text, PI tails,
    # CSR@AppliedLanguage, plus CSR@Tracking/HorizontalScale only when allow.tracking), then C14N equality.
    # Also checks entry order, names, compress types, mimetype first/stored.

# extract.py
def extract(pkg: IdmlPackage, cfg: Config) -> tuple[list[Segment], list[Issue]]
    # Issues = inventory: skipped constructs (with reason), unreachable content, attribute-held text, warnings.
def assign_roles(segments: list[Segment], pkg: IdmlPackage, cfg: Config) -> None
def join_headings(segments: list[Segment], cfg: Config) -> list[Segment]
    # consecutive paragraphs, same story & heading-like style, each ≤ 6 words, no terminal punctuation, max 3

# markup.py
def encode(seg: Segment, dnt: list[str], lang: LanguageSpec) -> Encoded
def decode(enc: Encoded, seg: Segment, output: str, lang: LanguageSpec) -> list[str]   # raises DecodeError
    # splits by tags and para marks, restores placeholders, edge whitespace and case

# inject.py
def inject(pkg: IdmlPackage, segments: list[Segment], results: list[Translation],
           lang: LanguageSpec) -> dict[str, etree._Element]      # changed story trees
    # writes only Translation.slot_texts; sets AppliedLanguage on the nearest CSR of each changed slot;
    # never writes a segment whose slot_texts count ≠ len(slots) (raises). Kept-source segments untouched.

# backend.py
class TranslationBackend(Protocol):
    model_id: str
    def translate(self, batch: list["Request"], ctx: "RunContext") -> list["Response"]
@dataclass
class Request: segment_id: str; prompt: str; options: dict; max_tokens: int
@dataclass
class Response: segment_id: str; text: str; done_reason: str; seconds: float; tokens: int
class OllamaBackend:   # urllib to 127.0.0.1:11434 only (host refused otherwise), seed, keep_alive "30m",
                       # num_ctx 2048, num_predict = 2×src_chars+32, workers 1|2
class IdentityBackend: # returns the source text (round-trip test mode)

# translate.py
def translate_all(segments, cfg, lang, backend, tm, glossary, dnt) -> list[Translation]
def translate_concise(seg, normal: Translation, cfg, lang, backend, tm, glossary, dnt) -> Translation | None

# validate.py
def validate(seg: Segment, enc: Encoded, output: str, lang: LanguageSpec,
             dnt: list[str], ctx: ValidationContext) -> list[Issue]     # empty = pass

# casing.py
def detect_case(text: str) -> Literal["upper","title","sentence","lower","mixed"]
def upper(text: str, locale: str) -> str     # tr: i→İ, ı→I; de: ß→SS (or ẞ per config)
def lower(text: str, locale: str) -> str     # tr: I→ı, İ→i
def capitalize_first(text: str, locale: str) -> str

# tm.py
class TranslationMemory:
    def __init__(self, path: Path)
    def get(self, key: TMKey) -> list[str] | None
    def put(self, key: TMKey, slot_texts: list[str], meta: dict) -> None
@dataclass(frozen=True)
class TMKey: source: str; target: str; context_class: str; glossary_hash: str; model_id: str; template_version: str
    # context_class = role group (heading/kicker/folio/table_header/table_cell/caption/body/footnote) + "concise" flag

# dc.py (from R2 snippet)
def run(idml: Path, cmds: list[str]) -> list[dict]       # checks exit code + result count
def inspect(idml) -> dict; def preflight(idml) -> dict; def fonts(idml) -> list
def story_map(idml: Path, inspect: dict) -> dict[int, str]
def export_pngs(idml, out_prefix, page_count) -> list[Path]   # 0-based --page, files _p1.._pN
def export_pdf(idml, path) -> Path

# verify.py
@dataclass
class VerifyResult:
    hard_fail: bool
    gates: dict[str, "GateResult"]    # geometry, package_diff, reopen, overset, preflight, glyphs, languages
    overset: list[Issue]              # with entry, DC frame, 1-based page, overflow chars
def verify(src: Path, out: Path, allow: AllowPolicy, lang: LanguageSpec,
           src_cache: dict | None = None) -> VerifyResult

# fit.py
def fit(src, out_tmp, pkg, segments, results, cfg, lang, translator) -> FitResult   # see §4

# report.py
def write_report(run: RunRecord, out_dir: Path) -> tuple[Path, Path]   # report.json, <name>_<lang>_report.html

# cli.py
def main(argv: list[str] | None = None) -> int
```

### 2.3 Segment model details
- One segment per paragraph inside its container (story body, cell, footnote, xref source). Inline objects and PIs split slots but not segments. `<Br/>` and `ParagraphBreakType` end a paragraph.
- A slot is translatable if it contains a letter. Whitespace-only, number-only and empty slots are never changed.
- 1 letter slot → plain text. ≥ 2 letter slots → `<gN>…</gN>` per letter slot (Structured Data 1). Empty tag content is allowed in output (TR has no article for `<g0>The </g0>`).
- Edge whitespace of each slot is preserved exactly; only the trimmed core is translated. If a translated core is empty, the slot keeps its leading edge only when the neighbour does not already supply whitespace, so no double spaces are created.
- Placeholders `⟦n⟧` for: TAB, U+2028, fixed spaces, URLs, e-mails, numbers with units, DNT terms, and paragraph boundaries in joined headings. Look-alikes `⟨n⟩ 〚n〛 〔n〕` are normalised before validation. Checked as a multiset (TR reorders legitimately); paragraph marks are order-strict.
- **ALL CAPS** (literal text, ≥ 2 letters, not code-like, no caps style): send sentence case, restore with locale-aware upper. **Caps from style** (`Capitalization="AllCaps"`, resolved through style inheritance and CSR overrides): send literal, don't touch case. Lost initial capital (source starts uppercase, output lowercase) → locale-aware capitalise first letter.
- **Code-like** (no run of ≥ 3 letters outside DNT, e.g. `C=100 M=0 Y=0 K=0`, `M3 Y8`) → never sent to the model; kept as is (40/40 correct in R3).

### 2.4 Roles and context (plan-context)
- Role from (in order): config `style_roles` overrides; container (cell in header row → `table_header`, cell → `table_cell`, footnote, xref); master-spread story → `folio`/`running_head`; paragraph style name keywords (Title, Head, Kicker, Deck, Caption, Folio, Pull, Quote, Footnote, Body); fallback by length.
- Neighbours: prev/next paragraph of the same story; for table cells, the column header and the row's first cell; for one-paragraph stories, the spatially nearest story on the same page (from spread geometry). R3: context bleed happened only without neighbours, so S/TS always get some neighbour.
- Synopsis: `--synopsis` / config value if given. Otherwise an auto synopsis built without the model: `"{document name}. Headings: {first 3 headline/cover-title texts}."`. **R3 measured only a hand-written synopsis; the auto synopsis is re-measured on the eval set at the start of Phase 1** (acceptance: no worse than −5 points on short refs vs hand-written; otherwise the CLI recommends `--synopsis`).

---

## 3. Translation (templates measured by R3)

| Class | Condition | Template | TR / DE measured |
|---|---|---|---|
| P | plain, ≥ 7 words | Terminology + Default (`Translate the following segment into {lang}, without additional explanation.`) | body refs 100 / 100%, 0 added text |
| S | plain, ≤ 6 words or role ∈ headline/kicker/folio/table/caption/pull quote | Terminology + Contextual (document, style, role, prev, next) | short refs 77 / 93%; ALL CAPS with folding 100 / 93%, case 100 / 100% |
| T | tags or placeholders, long | Structured Data 1 + Terminology | tags 100 / 100%, placeholders 100 / 100% |
| TS | tags/placeholders, short; joined headings | T + `### Context (do not translate)` | heading boundary 18/18, natural 18/18 |
| C | concise retranslation (fit) | Style "concise. Keep every statement, name and number" → second attempt prototype "as short as possible" | length 0.90 / 0.86 of normal (p50) |
| B | back-translation | Default into English, `temperature 0, top_k 1` | |
| R | retry | structural failure → T at T=0.2; plain failure → S at T=0.2; context bleed or too long → without context | fixed 30/32 failures |

Exact strings: `research/prompts.md` §2 (copied into `prompts.py` with a `TEMPLATE_VERSION` that is part of the TM key). Caveat from R3: the "model-card" wordings were reproduced from memory (no internet); they are measured, which is what matters, and swapping is a one-line change.

Sampling: `temperature 0.7, top_p 0.6, top_k 20, repeat_penalty 1.05`, **fixed `seed` (default 42)** so results are reproducible; retries at 0.2. `num_ctx 2048`, `keep_alive "30m"`, `num_predict = 2 × source chars + 32`. One request at a time by default; `--workers 2` gives about +18%. No batching (only +10–16% faster and loses per-segment context; R3).

**Validators** (all mandatory; `validate.py`):
1. `done_reason == "stop"` (not truncated); no control characters.
2. Tags: identical `<gN>` sequence, valid nesting, no text outside tags.
3. Placeholders: multiset equal after look-alike normalisation; paragraph marks in order.
4. Numbers: digit multiset with `.`/`,` removed (`1,200` → `1.200` passes).
5. DNT terms verbatim.
6. Untranslated: casefolded identity with source (code-like exempt) → soft fail → retry → if still identical, accept with a `review` flag (e.g. DE "Cyan" is correct).
7. No added prefix ("Here is", "Translation:"), surrounding quotes, notes or extra lines.
8. Context bleed: 3-gram overlap with the synopsis translation (S/TS only).
9. Length ratio (chars, markers stripped), body only: TR 0.92–2.06, DE 0.97–2.32 (R3 p5×0.9 … p95×1.15). Short: `len ≤ 3 × src + 12`.

Retry policy: up to 2 retries (R templates), then **keep source text** for that segment and flag it (invariant 4).

TM: SQLite at `<out>/.idml-translate/tm.sqlite` (or `--tm PATH`), key `(encoded source, target, context class, glossary hash, model id, template version)`. Concise results stored under their own context class. `--resume` = reuse TM + skip completed stages.

Glossary/DNT: per-project CSV (`source,target[,note]`) or YAML; DNT as a text file (one term per line) or CSV. The glossary is matched whole-word, case-insensitive, longest match first; DNT terms also get identity glossary lines (R3 format) and are protected by placeholders. After translation, glossary targets are verified (warning only: inflection in TR/DE legitimately changes the form; check by stem prefix).

---

## 4. Fit strategy (overset)

Triggered only for stories that are overset in the output but not in the source (DC `document.inspect` + `story_map`).

1. **Concise retranslation**, per overset story: order its segments by expansion (target chars / source chars) descending; retranslate in groups of 3 with C (then the stronger C2). Accept a candidate only if: all validators pass; `len(candidate) ≥ 0.80 × len(normal)` (configurable `fit.min_length_ratio`); the back-translation check passes (greedy BT of candidate vs greedy BT of normal, content-word recall Δ ≥ −0.25, and every number present). Re-inject and re-check after each group (DC check ≈ 0.1 s). Stop when the story fits.
2. **Optional, off by default (`--allow-tracking`)**: on the affected paragraphs only, `Tracking` ≥ −10 or `HorizontalScale` ≥ 97 on their CSRs, smallest change first. Every change is logged in the report. The package diff gate allows exactly these attributes on exactly those CSRs.
3. Otherwise leave it overset: report with story file, page (1-based), DC frame id, overflow characters, and the note that DC does not hyphenate TR/DE; show the frame outlined in red in the preview.

Frames are never resized, pages never added. A concise result never replaces a normal translation that fails validation.

---

## 5. Verification gates (`verify.py`)

| Gate | Hard? | Check |
|---|---|---|
| package_diff | **hard** (output not written) | non-story entries byte-identical; story entries C14N-equal after masking the allowed payload; entry order/names/compression identical; `mimetype` first + stored |
| geometry | **hard** (output not written) | DC items `id/kind/bounds(rounded 3)/story/columns`, page derived from item centre; spreads and page count identical |
| reopen | **hard** (output not written) | DC opens the output; `file.openIdml.warnings` ⊆ source warnings; command count = result count |
| languages | **hard** | every `AppliedLanguage` written is from the language table |
| glyphs | **hard** (output written, exit code ≠ 0) | no new `missingGlyphs`/`missingFont` vs source (`preflight.run`) |
| overset | soft (report) | no new overset vs source after the fit loop; otherwise flagged with page/frame |
| preflight | soft (report) | only new issues count (key: kind, item, page, message with digits masked) |
| segments | soft (report) | count of kept-source / review-flagged segments |

The output is written to a temp file and moved to `<name>_<lang>.idml` only after the blocking gates pass. **Round-trip mode** `--identity` uses `IdentityBackend`: the output must pass package_diff with *zero* changed payload (stories byte-identical, because unchanged stories are never reserialised).

Exit codes: 0 all gates passed (soft flags allowed); 2 usage/config error; 3 a hard gate failed (output not written, or written with glyph failure); 4 backend unavailable.

---

## 6. Outputs and CLI

```
idml-translate translate IN.idml --to tr [--from en] [--out DIR] [--glossary FILE] [--dnt FILE]
               [--synopsis TEXT] [--allow-tracking] [--pdf] [--dry-run] [--resume] [--workers N]
               [--identity] [--config FILE]
idml-translate extract IN.idml --out segments.jsonl
idml-translate verify SRC.idml OUT.idml [--to tr]
```
Run as `python -m idml_translate …` (plus a `pyproject.toml` console script). `--dry-run`: extract, check that Ollama and DC are reachable, write `segments.jsonl` and an estimate; no model calls, no IDML. Every subprocess and file call uses `encoding="utf-8"`; the CLI reconfigures stdout/stderr to UTF-8 (L9).

Outputs in `--out` (default: next to the input, `out/`): `<name>_<lang>.idml`, optional `<name>_<lang>.pdf`, `<name>_<lang>_report.html`, `<name>_<lang>_report.json`, `<name>_<lang>_pages/src_pN.png|out_pN.png`. The HTML is one file with relative PNG links. It shows side-by-side pages with overset frames outlined in red (CSS overlay from DC bounds, 1 px/pt + 9 pt bleed offset; no image library), flagged segments (source / output / reason), skipped content, the gate table, timings, TM and model stats.

Language table `data/languages.toml` (adding fr/es/it/pt/nl/pl = config only):
```toml
[tr]
name = "Turkish"
idml = "$ID/Turkish"
casing_locale = "tr"
ratio_body = [0.92, 2.06]
dc_hyphenation = false
[de]
name = "German"
idml = "$ID/German: 2006 Reform"
casing_locale = "de"
ratio_body = [0.97, 2.32]
dc_hyphenation = false
sharp_s_upper = "SS"
```
Hyphenation (L6) is reported per language from this table (R2 measured: DC hyphenates EN only). Loose justified lines: optional PDF line analysis with PyMuPDF (already installed) in a later iteration. It is not in v1 scope; the report states that hyphenation is unavailable in DC for TR/DE.
German/Turkish spelling (L7): LanguageTool and hunspell are not installed and need downloads → v1 flags review candidates only (e.g. the doubled-s compound pattern `Zeichensstile`, words not in the TM or glossary). A spelling backend is a later option.

---

## 7. Test plan

Runner: pytest (see question 3). Fixtures: `idml-demo/sample_en.idml` (read only, never modified) and R1's `fixtures/fx_table, fx_footnote, fx_nested, fx_vars_links, fx_master_caps, fx_misc` (+ wave-3 adversarial files `fixtures/adv_*.idml`).

| Area | Tests |
|---|---|
| idml_io | write with no changes = byte-identical zip; entry order, compression, mimetype; changed story keeps its XML declaration; `canonical_diff` catches: attribute change, PI change, element added, text outside payload, recompressed entry |
| extract | sample: 53 `Content`, 3 PIs, 1 table (15 cells), 1 footnote, master stories `ue`/`u10` flagged; u18 joined into one heading segment; every fixture: expected segment counts, roles, skipped inventory (Note, DeletedText, attribute text) |
| markup | encode/decode round trip; edge whitespace; placeholders for each special character; `&amp;`, `<`, emoji; empty tag content; joined headings |
| inject | **identity round trip on every fixture** (story bytes identical); AppliedLanguage on nearest CSR only; **tag fuzz**: 1,000 random valid/invalid outputs per fixture segment, invalid ones never written, valid ones always pass package_diff |
| casing | Turkish i/İ/ı/I both directions, German ß, mixed scripts, style AllCaps vs literal caps |
| validate | every validator, positive and negative cases taken from R3 raw outputs |
| tm | key separation by context class/glossary/model/template; resume |
| backend | Ollama client against a local fake HTTP server (no GPU); refuses non-localhost URLs |
| dc / verify | sample vs prototype outputs (geometry same; DE overset detected; story map 18/18); page export writes 4 PNGs incl. the cover; skip if DC is missing |
| fit | fake backend + fake verifier: order by expansion, 0.80 gate, BT gate, stop on fit, tracking off by default |
| report/cli | JSON schema, HTML contains every flagged item, exit codes |
| **e2e** (marked `slow`, needs Ollama) | sample → tr and de: all hard gates pass; L3 strings: "Notes on the Grid" → contains "Izgara"; "QUARTERLY" → all-caps rendering (e.g. "ÜÇ AYLIK"); "The Quiet"/"Art of Layout" translated jointly; prototype vs production comparison table |
| performance | 50 paragraphs < 3 min excluding first load (R3 measured 43 s TR / 38 s DE) |

The e2e reference checks are written **before** looking at the production output and are never adjusted to pass.

---

## 8. Risks and open questions

1. **Glossary dependence.** R3's high scores used a glossary written with knowledge of the references (an upper bound). Without a glossary, short TR strings score about 37–50%. → Question 1.
2. **InDesign behaviour can't be tested here**: hand-written constructs (variables, hyperlinks, notes, changes, XML) in the test files, and whether InDesign needs a designmap `<Language>` for `$ID/Turkish`. → Question 2.
3. **DC overset is pessimistic for TR/DE** (no hyphenation). The fit loop may shorten text that would fit in InDesign. Mitigation: only act on stories DC reports overset; the report states it.
4. **Fixed object positions limit word order** (footnote refs, variables, CSR boundaries): expect some tag failures in TR/DE; those segments keep the source and are flagged (R3: 30/32 failures fixed by one retry).
5. **Auto synopsis** quality is unmeasured (§2.4); re-measured at the start of Phase 1.
6. **Template wording** was reproduced from memory (R3 caveat); the measurements stand for the strings actually used.
7. **Regenerated text** (xrefs, TOC, index, variable `ResultText`) may be overwritten by InDesign on update; reported.
8. `pytest` is not installed; installing it needs PyPI. → Question 3.

---

## 9. Task breakdown (Phase 1 onwards)

Before wave 2 (orchestrator, ~1 h): `git init`; write `model.py`, `config.py`, `data/languages.toml`, package skeleton with the signatures above as stubs, shared test helpers (`tests/conftest.py`: fixture paths, fake backend, fake verifier); commit. Re-measure the auto synopsis with R3's harness.

All subagents run with `model: "haiku"` (user decision). Briefs are therefore fully explicit (exact signatures, file paths, test commands), and the orchestrator reviews and re-runs every agent's tests before merging.

| Agent | Isolation | Owns | Definition of done |
|---|---|---|---|
| I1 | worktree | `idml_io.py`, `extract.py`, `markup.py`, `inject.py` + tests | identity round trip on all fixtures; tag fuzz passes; canonical diff catches each mutation class |
| I2 | worktree | `casing.py`, `backend.py`, `prompts.py`, `validate.py`, `tm.py`, `translate.py` + tests | all validators tested with R3 cases; fake-server backend tests; routing matches §3 |
| I3 | worktree | `dc.py`, `verify.py`, `fit.py` + tests | gates on sample + prototype outputs; 4 PNGs incl. cover; fit loop tests with fakes |
| I4 | worktree | `report.py`, `cli.py`, `pyproject.toml` + tests | CLI and exit codes; HTML with side-by-side pages and overlays from a canned RunRecord |
| Orchestrator | main | merge, integration, e2e TR/DE, performance | full suite green |
| Q1 (wave 3) | worktree | `fixtures/adv_*`, regression tests | each found failure becomes a test |
| Q2 (wave 3) | read-only | review report | findings fixed and re-run |
| Phase 3 | main | README, final reports TR/DE, prototype vs production comparison | |

---

## 10. Decisions (answered 2026-10-12)
1. Glossary: **ship a starter publishing glossary** (`glossaries/publishing_{tr,de}.csv`), on by default, `--no-default-glossary` to disable; e2e report shows the sample with and without it.
2. Languages: **AppliedLanguage only**; opt-in `--declare-languages`, documented as unverified.
3. Tests: **`pip install --user pytest`** (dev only).

### Original questions

1. **Glossary policy.** Short headings are only reliable with a glossary. **Recommended:** ship a general publishing/typography starter glossary per language (`glossaries/publishing_{tr,de}.csv`, ~60 terms such as grid, kicker, pull quote, swatch, folio, leading, kerning, feature, quarterly). It is written from domain knowledge, used by default, and can be disabled with `--no-default-glossary`. The e2e report shows the sample **with and without** it, so the effect is visible and not hidden in a tuned test. Alternative: no default glossary; the L3 e2e checks then run only with an explicit project glossary.
2. **designmap `<Language>` elements.** DC ignores them; InDesign may want them, but we can't verify that, and the language `Id` values are unverified. **Recommended:** stay strictly within invariant 1 (set `AppliedLanguage` only) and offer an opt-in `--declare-languages`, documented as unverified. Alternative: always add them.
3. **pytest.** It is not installed, and installing it needs PyPI once (dev-only; the tool itself stays stdlib + lxml and offline). **Recommended:** `pip install --user pytest` once. Alternative: stdlib `unittest` only (pytest can still run those tests later).
