# Build `idml-translate`: layout-safe, fully local IDML translation (production)

You are building a production-quality command-line tool that translates Adobe InDesign IDML
documents into another language **without ever altering the design**. Everything runs locally:
a local translation model served by Ollama, and DesignCraft (an InDesign-like desktop app with a
headless CLI) for verification. **No external or cloud APIs of any kind.**

Do not start coding immediately. Work through the phases below in order. Phase 0 (planning) ends
with a written plan that the user must approve before any implementation starts.

---

## 1. Environment (verified on this machine; re-verify, don't assume)

| Item | Value |
|---|---|
| OS | Windows 11; shells: PowerShell and Git Bash |
| GPU | RTX 4060 Laptop, 8 GB VRAM; 32 GB RAM |
| Python | 3.14, `lxml` 6.1 installed (user site-packages, so do **not** run with `python -I`) |
| Model runtime | Ollama 0.13.5, `http://127.0.0.1:11434` (start with `ollama serve` if not running) |
| Model | `hf.co/tencent/Hy-MT2-7B-GGUF:Q4_K_M` (Apache-2.0, 33+ languages incl. Turkish, German) |
| DesignCraft CLI | `C:\Program Files\DesignCraft\designcraft-cli.exe` (v0.6.0) |
| DesignCraft MCP | registered in Claude Code as `designcraft` (`designcraft-cli mcp`) |
| Work root | `C:\Programming\craft-studio\` |
| Project dir | `C:\Programming\craft-studio\idml-translator\` |
| Prototype | `idml-translator\demo_translate.py`. It works but is throwaway; mine it for lessons, do not extend it |
| Sample input | `idml-demo\sample_en.idml` (4 pages, 18 stories, a table, a footnote, inline character formatting) |
| Prototype outputs | `idml-demo\out\` (TR/DE results, page PNGs, JSON reports) |

### DesignCraft facts established so far
- `file.open` / `file.openIdml` accept **only `.idml` and `.designcraft`**. `.indd` is out of scope.
- Usage: `designcraft-cli run --in FILE --cmd ID[=JSON] ... [--page N --export OUT.png]`.
  Results print as one JSON line per command and are **not** wrapped in `{"result": …}`.
- On Windows, paths inside `--cmd` JSON must use forward slashes; backslashes cause "invalid escape".
- `document.inspect` returns pages, spreads, items with `bounds`, and stories with `overset`.
- `story.get={"story":N}` returns plain text only, with no formatting runs. **Never use DesignCraft
  to write text**: it would lose inline formatting. DesignCraft is for verification only.
- **Story IDs are renumbered on IDML import.** They do not match `Stories/Story_uXX.xml`. Map
  stories by content or by frame, never by ID arithmetic.
- Other useful commands: `preflight.run`, `font.list` (missing fonts),
  `file.exportPdf` (`{path, pages}`), `describe <cmd>`, `commands`.
- The prototype exported only 3 of 4 page PNGs. Investigate the cause (page indexing? spreads?).

### Model facts (from the Hy-MT2 model card, confirmed in the prototype)
- There is no system prompt. Recommended sampling: `temperature 0.7, top_p 0.6, top_k 20,
  repeat_penalty 1.05`.
- The official prompt templates are Default, Terminology, Style, Delimiters, Structured Data 1
  (preserve XML/tags) and Structured Data 2 (background/context). Language names must be English
  full names. Use these templates; do not invent new prompt styles without measuring them.
- The first call takes about 30 s (model load). After that, about 0.5–1.5 s per paragraph.

---

## 2. Non-negotiable invariants

1. **Only the text payload may change**: the `.text` of `<Content>` elements and the `.tail` of
   processing instructions inside `<Content>`. The only other permitted edit is setting
   `AppliedLanguage` on the enclosing `CharacterStyleRange`. Everything else must stay
   byte-for-byte identical, or be shown identical by canonical XML comparison: all other files
   in the zip, all attributes and all processing instructions (`<?ACE n?>`).
2. **Geometry is frozen.** Every page item's `id/kind/bounds/rotation/page` reported by
   `document.inspect` must match the source exactly. A mismatch is a hard failure, and the output
   must not be written.
3. **The package stays valid IDML.** `mimetype` must be the first zip entry and stored
   uncompressed, and every other entry keeps its original compression. The output must reopen in
   DesignCraft without warnings that the source did not already have.
4. **Never write a broken segment.** If tags, placeholders, numbers or do-not-translate terms
   cannot be preserved, keep the source text for that segment and flag it in the report.
5. **Never silently drop meaning to make text fit.** See section 4.5.
6. The input file is never modified. No network access other than `127.0.0.1:11434`.

---

## 3. Lessons from the prototype (must be addressed)

| # | Finding | Required handling |
|---|---|---|
| L1 | Text appears as the `.tail` of PIs inside `<Content>`, e.g. the footnote `<Content><?ACE 4?>\tText</Content>`. The naive `node.text` misses it. | Model each run as a *slot* (element + `text`/`tail`). PIs are fixed boundaries and never touched. |
| L2 | Leading and trailing whitespace of runs carries inter-run spacing. | Preserve each slot's edge whitespace exactly; translate only the trimmed core. |
| L3 | Short segments (headlines, kickers, folios, table cells, swatch names) were mistranslated without context: "Notes on the Grid" → "İzgile İlgili Notlar", "QUARTERLY" → "Çeyreklik", "FEATURE" → "ÖZELLİK", "Pull quotes" → "Tırnak işaretleri çekin". | Context-aware prompting (Structured Data 2): document synopsis, previous/next paragraphs, paragraph style name and segment role (headline, table header, caption…). Add a glossary and a do-not-translate (DNT) list. Use more context for short segments. |
| L4 | ALL-CAPS source came back mixed-case. | Detect the case pattern (ALL CAPS, Title Case) and restore it with **locale-aware** casing. Turkish i→İ and ı→I; Python's `str.upper()` is wrong for Turkish. Also check whether caps come from a style (`Capitalization="AllCaps"`) rather than from the literal text; if so, leave the text alone. |
| L5 | "Concise retranslation" fixed overset but dropped content ("Jede Seite beginnt leer"). | Concise candidates must pass a meaning-preservation check and a minimum length ratio; see section 4.5. |
| L6 | Turkish justified text showed wide word gaps; hyphenation seems unsupported for `$ID/Turkish`. | Test whether DesignCraft hyphenates each target language. Report it per language, and flag loose justified lines if they can be measured. |
| L7 | German grammar slips ("Zeichensstile", "Objektsstile"). | Optional local QA pass (spelling with LanguageTool offline or hunspell, if installable without a network service). At minimum, flag them for review. |
| L8 | The sample repeats body paragraphs, so the translation memory got 26 hits on 52 segments. | Keep the translation memory, but key it on source plus context class, so identical text in different roles can differ when needed. |
| L9 | The console mangled UTF-8 (`„` displayed as garbage), but the files were fine. | Always set `PYTHONIOENCODING=utf-8` and use explicit `encoding="utf-8"` in every subprocess and file call. |

---

## 4. Target design (refine it in Phase 0, don't rubber-stamp it)

### 4.1 Pipeline
```
load → extract → plan-context → translate → postprocess/QA → inject → verify → fit-loop → report
```

### 4.2 Extraction coverage (inventory in Phase 0, then decide what is in scope)
Stories, including those on master spreads; tables (`Cell`); footnotes; notes; nested and anchored
text frames; text variables (`designmap.xml`); hyperlink text; conditional text (hidden
conditions); tracked changes; index topics; TOC titles; bookmarks; alt text and object export
options. Each type is either translated or **explicitly listed in the report as skipped, with the
reason**. Also flag text the tool cannot reach: outlined text, text inside placed images or PDFs,
and linked (not embedded) stories.

### 4.3 Segment model
One segment per paragraph (split at `<Br/>`). It holds:
- ordered slots;
- the tag-encoded source (`<g0>…</g0>`, used only when there are 2+ letter-bearing slots);
- protected placeholders (`⟦1⟧`) for tabs, forced line breaks, special characters, URLs,
  emails, numbers with units and DNT terms;
- story, paragraph style, role and neighbour IDs;
- a frame-capacity hint (characters that fit in the source).

### 4.4 Translation
- Backend interface: `translate(batch, ctx) -> results`. Ollama Hy-MT2 is the only
  implementation now, but keep the interface swappable.
- Template choice per segment: plain (Default + Terminology), tagged (Structured Data 1 +
  Terminology), and short or ambiguous segments (Structured Data 2 with background).
- Validators, all mandatory:
  - tag sequence and nesting identical;
  - placeholders identical as a multiset;
  - digits and numbers preserved;
  - DNT terms present verbatim;
  - output not identical to the source (untranslated);
  - no explanations or quotes added by the model;
  - length ratio within per-language bounds.
- Retry policy: up to 2 retries with lower temperature and a stricter prompt; after that, keep
  the source text and flag the segment.
- Translation memory in SQLite, keyed by (source, target language, context class, glossary
  version, model id).
- Glossary and DNT are per project YAML/CSV files, applied in prompts and verified afterwards.

### 4.5 Fit strategy (when DesignCraft reports overset)
In order, stop at the first that works:
1. Retranslate the overset story's segments with the Style template ("concise"). Accept a
   candidate only if it passes all validators, its length is ≥ 75% of the normal translation
   (configurable), and a **back-translation check** confirms that no clause or fact was dropped.
   Use the same local model; compare key content words or numbers. Prefer the paragraphs with
   the largest expansion first.
2. Optional, **off by default** and enabled per config: a local tracking adjustment of at most
   −10 or a horizontal scale of at least 97% on the affected paragraphs only. Every change is
   logged.
3. Otherwise leave it overset, flag it in the report with page and frame, and show it in red in
   the preview.

Frames are never resized and pages are never added.

### 4.6 Verification gates (all automatic, all in the report)
- Geometry identical (hard gate).
- No new overset compared with the source.
- `preflight.run` issues compared with the source (only new issues count).
- Missing fonts (`font.list`) and missing glyphs: check every target-language character against
  the applied font's character map (fontTools if fonts are locatable; otherwise render-and-detect
  with DesignCraft). Turkish ğ ş ı İ, German ß, etc.
- Package diff: only allowed files and nodes changed (canonical XML diff).
- Round-trip test mode: an "identity translator" must produce an output equivalent to the input.

### 4.7 Outputs
`<name>_<lang>.idml`, an optional PDF, `<name>_<lang>_report.html` (side-by-side page PNGs,
overset items, flagged segments with source and translation, skipped content, timings, and
translation memory and model stats), plus a machine-readable `report.json`. Exit code is non-zero
if any hard gate fails.

### 4.8 CLI
```
idml-translate translate IN.idml --to tr [--from en] [--out DIR] [--glossary FILE] [--dnt FILE]
               [--allow-tracking] [--pdf] [--dry-run] [--resume]
idml-translate extract IN.idml --out segments.jsonl     # for review and debugging
idml-translate verify SRC.idml OUT.idml                   # gates only
```
Language support: start with **en→tr and en→de**. Make the language table data-driven: IDML
language name, casing locale, length-ratio bounds and hyphenation support. Adding other
Latin-script languages (fr, es, it, pt, nl, pl) should only need config changes. RTL and CJK
are out of scope.

---

## 5. Process

### Phase 0: Plan (no production code)
1. Read the prototype, its outputs and this prompt. Run the prototype once to reproduce the
   baseline.
2. Run the research subagents (section 6, wave 1) **in parallel**.
3. Write `PLAN.md` containing:
   - module layout and interfaces (exact function signatures and data classes);
   - the scope decisions from the extraction inventory;
   - the chosen prompt templates with measured results;
   - the fit-strategy thresholds;
   - the test plan and fixture list;
   - risks and open questions;
   - a task breakdown mapped to subagents.
4. **Stop and ask the user to approve `PLAN.md`.** Ask at most three questions, each with a
   recommended default.

### Phase 1: Build (after approval)
Run the implementation subagents (wave 2) against the interfaces fixed in `PLAN.md`. Integrate,
then run the full test suite.

### Phase 2: Harden
Run wave 3 (adversarial fixtures, review). Fix the findings, re-run everything, and update the
baseline comparison: prototype vs production on `sample_en.idml` for TR and DE.

### Phase 3: Deliver
README (install, usage, config, limitations), a final report on the sample in both languages,
and a short summary to the user with the honest limitations.

---

## 6. Subagents

Give every subagent a self-contained brief: goal, inputs, exact deliverable path, constraints
(local only, no edits outside its area) and a definition of done. Their final reports are not
shown to the user, so relay the important findings yourself. Run independent agents in the same
turn so they execute in parallel. For implementation agents that touch separate modules, use
`isolation: "worktree"` (initialise a git repo in the project dir first), then merge.

**Wave 1: research (parallel, read-only except their report file)**
- **R1 IDML coverage** (Explore or general-purpose): inventory every place translatable text can
  live in IDML, and which PIs, special characters and elements appear inside `<Content>`. Use the
  IDML spec knowledge plus the sample, and build 3–5 small synthetic IDMLs (via DesignCraft
  `file.exportIdml` after scripted edits) that exercise tables, footnotes, nested frames,
  variables, hyperlinks and master-page text. Deliverable: `research/idml_coverage.md` and the
  fixture files.
- **R2 DesignCraft verification** (general-purpose): confirm the commands, output shapes and
  quirks (story renumbering, page export indexing, JSON escaping). Write a robust story-to-file
  mapping. Test hyphenation for TR and DE. Find the best method for detecting missing glyphs.
  Measure the run time of verification calls. Deliverable: `research/designcraft.md` and a
  tested `verify` prototype snippet.
- **R3 Model and prompts** (general-purpose): build a small evaluation set of about 60 segments
  from the sample and fixtures: short headlines, ALL CAPS, tagged runs, placeholders, numbers,
  DNT terms and table cells. Measure each Hy-MT2 template variant on tag preservation, placeholder
  preservation, untranslated rate and the L3 failures. Also measure the back-translation check
  for concise mode. Deliverable: `research/prompts.md` with the numbers and the recommended
  templates.

**Wave 2: implementation (parallel after `PLAN.md` approval, one module each, with unit tests)**
- **I1** `idml_io` + `extract` + `inject` (slots, segments, package writer, canonical diff).
- **I2** `translate` (backend interface, Ollama client, templates, validators, retries,
  translation memory, glossary/DNT, casing).
- **I3** `verify` + `fit` (DesignCraft wrapper, gates, fit loop).
- **I4** `report` + `cli` (HTML/JSON report, side-by-side previews, CLI and exit codes).

You (the orchestrator) own the interfaces, the integration and the end-to-end test.

**Wave 3: hardening (parallel)**
- **Q1 Adversarial QA** (general-purpose): try to break the invariants. Use empty paragraphs,
  emoji, `&amp;`/`<` in text, very long paragraphs, runs that are only whitespace, nested
  tables, footnotes inside table cells, text on master pages and overset text in the source.
  Add each failure as a regression test.
- **Q2 Code review** (reviewer): correctness first, then simplicity. Pay special attention to
  XML mutation, zip writing, encoding and Turkish casing.

---

## 7. Testing requirements
- Unit tests per module (pytest).
- **Identity round-trip:** with an identity translator, the output is equivalent to the input
  for every fixture (canonical XML; non-story files byte-identical).
- **Tag fuzz:** feed the injector random valid and invalid model outputs; invalid ones must never
  be written.
- **End-to-end** on `sample_en.idml` for tr and de: all hard gates pass, and the L3 strings are
  translated correctly. Expected references: "Notes on the Grid" → e.g. "Izgara Üzerine Notlar",
  and "QUARTERLY" → an all-caps Turkish rendering such as "ÜÇ AYLIK".
- Performance target: 50 paragraphs in under 3 minutes on this GPU, excluding the first model
  load.

## 8. Definition of done
- [ ] `PLAN.md` approved; research reports exist.
- [ ] All tests green; identity round-trip passes on all fixtures.
- [ ] TR and DE outputs of the sample: geometry identical, no new overset (or overset flagged
      with reasons), zero broken tags, all L1–L9 handled or explicitly reported.
- [ ] HTML report opens and shows side-by-side pages and every flagged item.
- [ ] README documents installation, configuration, language addition and limitations
      (`.indd` requires InDesign export to IDML; no RTL/CJK; text in images is not translated).

## 9. Working rules
- Local only: no cloud APIs, no telemetry, no uploading documents anywhere.
- Never modify `sample_en.idml` or any input. Write only inside the project dir and
  `C:\Programming\craft-studio\`.
- Prefer the standard library plus `lxml`. Any new dependency must install offline-capable
  (pip wheel) and must be justified in `PLAN.md`.
- Report honestly. If a gate fails or a language behaves badly, say so with evidence (report
  links, numbers). Do not tune tests to pass.
