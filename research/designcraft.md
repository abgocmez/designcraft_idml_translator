# R2: Verifying output with DesignCraft (designcraft-cli v0.6.0)

Scope: DesignCraft (DC) is used only to check an IDML: geometry, overset, preflight, fonts and glyphs, and renders. It never writes text.
Tested snippet: `research/designcraft_verify_snippet.py`. Its self-test output is in `dc_artifacts/selftest_output.txt` (copied at the end of this file).
Evidence files are in `research/dc_artifacts/`. The scripts that built the test variants are `variants.py` and `hyph.py`.

## TL;DR

| Topic | Finding |
|---|---|
| Page-export bug | `--page N` is a **0-based page index**. The prototype passed 1..4. Index 4 does not exist, so the CLI printed `designcraft-cli: no such page`, exited with code 1 and stopped. The prototype's "p1..p3" PNGs are really pages 2–4, and the cover was never rendered (byte-identical, checked with `cmp`). Fix: `--page 0..n-1`, or `--all-pages DIR`, which writes `page-001.png…`. |
| Story mapping | Primary method is **geometric**: DC frame bounds are matched to IDML `TextFrame` bounds, which gives `ParentStory`. The fallback is **rank**: DC numbers stories in the order of `<idPkg:Story src>` in designmap.xml (not `StoryList`). The fallback is only accepted if it agrees with every geometric match. Tested on the sample, on the TR/DE outputs and on a copy with the story order reversed: 18/18 correct, 18/18 text-verified on the sample. No text is involved, so it works on translations. |
| Hyphenation | **English only.** DC bundles only "US English hyphenation patterns (Liang/TeX)". With `$ID/Turkish` or `$ID/German: 2006 Reform`, DC does not hyphenate at all. Words longer than the column are split mid-word with no hyphen. `[No Language]` also turns hyphenation off. |
| designmap `<Language>` | DC does **not** need it. Adding a `<Language>` element changes nothing in DC, and an undeclared or even bogus AppliedLanguage gives no warning (`warnings: []`). For InDesign, adding the element is still the safe choice (see §4). |
| Missing glyphs | Use **`preflight.run`**. It reports `kind:"missingGlyphs"`, `"Missing glyphs in <Family> <Style>: ğ Ğ ş …"`, and the results matched fontTools exactly. Bundled fonts (Source Sans 3 / Source Serif 4) live inside the exe, so fontTools cannot check them. If a font is missing locally (`missingFont`), its glyphs cannot be checked. |
| Speed | Starting the process costs about 5 ms and opening the sample about 45 ms. Every query takes 50–60 ms, a 4-page PNG export about 110 ms and a 4-page PDF about 130–150 ms. Putting several `--cmd` in one run saves the open: 18× `story.get` in one run takes 54 ms. |

## 1. Commands and output shapes

`designcraft-cli commands` lists 447 commands; the full list is in `dc_artifacts/commands_v0.6.0.json`. `designcraft-cli describe <id>` gives `{id,label,menu,params,shortcut}`. The `params` field is a one-line text signature, not a schema.

CLI usage:
```
designcraft-cli run [--in FILE | --sample] [--cmd ID[=JSON]]... [--page N] [--scale S] [--pdf-options JSON] [--export OUT] [--all-pages DIR]
   (--page, --scale and --pdf-options apply to the exports that follow them)
designcraft-cli script [FILE|-] [--in FILE] [--save OUT] [--export OUT] [--keep-going]
designcraft-cli bench FILE [--runs N] | perf | mcp | app | links | --version
```

- **stdout** holds one compact JSON value per `--cmd`, in order. The value is not wrapped in `{"result":…}`.
- **stderr** holds export notices, for example `wrote X.png (630×810, 43.6 ms, 103 glyphs)` or `wrote X.pdf (4 pages, 552435 bytes)`, and errors (`designcraft-cli: invalid parameters for \`table.get\`: …`, `designcraft-cli: no such page`).
- **Errors abort the run.** The first failing command or export sets exit code 1. Results printed before it stay on stdout, and nothing after it runs. Always check the exit code and that the number of results equals the number of commands.

Relevant commands and the real shapes seen (trimmed):

| Command | Params | Output |
|---|---|---|
| `document.inspect` | `{}` | `{activeLayer, canUndo, characterStyles[], dirty, layers[], pageCount, paragraphStyles[], parents:[{id,items,label}], path, selection, settings:{facingPages,intent,pageHeight,pageWidth}, spreads:[{index, pages:[{bounds,columns,index,margins,name,parent,side}], items:[…]}], stories:[{id, frames:[frameId…], length, lines, overset, paragraphs, preview}], swatches[], title, tool}`. Each item has `{id, kind:"<text frame>"\|"<image>"\|"<rectangle>"\|"<ellipse>"…, bounds:[x0,y0,x1,y1], layer, fill, stroke:{swatch,weight}, hidden, locked, name}`. Text frames add `story`, `columns`, `columnRule`; images add `asset`. **There are no `rotation` or `page` fields.** Full example: `dc_artifacts/inspect_sample_en.json`. |
| `story.get` | `{story}` or `{frame}` | `{direction, frames, id, length, lines, overset:null, paragraphs, text, vertical}`. `text` is plain text. Special characters are private-use code points: U+E000 is the page-number marker, U+E009 a table anchor, U+E00A a footnote anchor. **Table cell text and footnote text are not included.** `overset` is always `null` here, so use `document.inspect` for overset. |
| `table.get` | `{story?, table?}` | Needs the caret inside the table: run `text.select={"story":S,"anchor":B,"focus":B}` first, where B is the UTF-8 byte offset of U+E009. Returns `{anchor, cells:[{row,col,rowSpan,colSpan,text,fill,insets,style,vj}], columns:[{width}], rows:[{height,kind,mode}], options, story, table, …}`. There is no per-cell overset field. The `table` parameter is the table's DC id (stories and tables share one id space), not an index. |
| `footnote.list` | `{story?}` | `[{story, id, index, anchor, text}]` |
| `preflight.run` | `{minPpi?:150}` | `{errors, warnings, issues:[{severity:"error"\|…, kind, message, item?, page?}]}`. Kinds seen: `overset` (`item` = DC frame id, `page` = 0-based page index, message `"Overset text: 525 characters"`), `missingGlyphs` (no item or page), `missingFont`. |
| `font.list` | `{}` | `[{family, style, characters, missing, styleMissing, source:"bundled"\|"installed"\|"document"\|"added"\|null}]` with missing fonts listed first. |
| `file.exportPdf` | `{path?, pages?:"1-3"\|[1,3] (1-based), …}` | `{path, bytes, pages, warnings}` |
| `file.openIdml` | `{path\|base64}` | `{index, documentFonts, warnings}`. This is the only place where import warnings appear, and they were `[]` for every variant tried. Without `--in`, the CLI starts with an `Untitled-1` document and the opened IDML becomes active (index 1). |
| `spelling.check` | `{story?, suggestions?}` | `[{story,start,end,word,suggestions}]` (not tested for TR/DE) |
| `hyphenation.list/addException` | | user exception words only, no dictionary listing |
| `find.find` | `{find, grep?, …}` | `[{story,start,end,text}]`. Offsets are UTF-8 bytes. It does not search table cells. |
| `file.package` | `{dir, idml?, pdf?}` | Copies links and a report. **Bundled fonts are not copied**, so it cannot be used to get font files out. |

Nothing exposes line-level data: no line or glyph positions, no composer output, no hyphenation dictionary listing. The only line information is the `lines` count per story. To see line breaks, export a PDF and read the lines with PyMuPDF (`fitz`, installed). That is the method used in §4.

**JSON escaping and paths.** Building `--cmd` with `json.dumps` inside a Python subprocess argument list works with backslash paths and with non-ASCII text, whether `ensure_ascii` is True or False. The "use forward slashes" rule only matters for hand-written JSON in a shell. The snippet normalises paths to `/` anyway (`_fwd`).

## 2. Story mapping (DC story id → `Stories/Story_uXX.xml`)

Observations:
- DC renumbers stories (2..19 in the sample). Ids follow the order of the **`<idPkg:Story src>` elements in designmap.xml**. Reversing that order reverses the DC ids. Reversing `StoryList` has no effect. Ids can skip numbers, because tables and other objects share the id space.
- DC frame ids are not IDML `Self` values either, but they stayed the same across the sample, the TR/DE outputs and the reordered copy.
- `document.inspect` item `bounds` are spread coordinates in which the **top-left of the spread's leftmost page is (0,0)**. In IDML, x is shifted by −612 for two-page spreads and y by −396. DC spread `i` corresponds to the i-th `<idPkg:Spread>` in designmap.
- **Parent (master) spread items are not listed** in `inspect`, even with `layout.parents.edit={"on":true}`. Their stories (2 and 3 here, the folios) appear in `stories` with frame ids that are not on any page.

Method (`story_map()` in the snippet):
1. **Geometry, primary.** For every IDML spread, collect the `TextFrame` elements, recursing into Groups. Compose the `ItemTransform` matrices, transform the `PathPointArray` anchors and take the bounding box. Subtract the top-left of the leftmost page. Match each DC text frame on the same spread index within 0.5 pt. That gives the DC story → IDML `ParentStory` → story file (resolved through each story file's `Story/@Self`). Conflicting matches raise an error.
2. **Rank fallback.** Sort the DC story ids and pair them with the `<idPkg:Story>` order. Use this only for stories that geometry did not map, such as master-page stories, and only if the rank mapping agrees with **every** geometric match. Otherwise raise an error.
3. If the counts differ or anything stays unmapped, raise an error. Never guess.

Evidence (self-test):
- Sample: 16 stories mapped by geometry and 2 by rank (the master folios). Compared with `story.get` text, **18/18 identical**. The comparison ignores PIs, table cells and footnotes, since `story.get` leaves those out.
- TR and DE outputs: the mapping is identical to the sample, though the text differs completely.
- Copy with the `<idPkg:Story>` order reversed: DC ids change (2,4,5,…; 3 is skipped), but the frame → file mapping is identical. The rank fallback followed the new order correctly.

Limits not covered by the sample: inline or anchored frames, text on paths, and stories with no frame. The sample has none of these; `anchored.list` returns `[]`. Such stories would fall into the rank fallback. If the rank check fails, the verify module should report "unmapped" instead of falling back to text similarity. Text similarity is the prototype's old approach, it is weak on translated output, and the snippet does not need it.

## 3. The page-export bug

- `--page` takes a **0-based page index** (the page position across spreads, so page "3" on spread 1 is `--page 2`). `--page 4` on a 4-page document → `designcraft-cli: no such page`, exit code 1, and the run stops.
- The prototype's `export_pages` ran `--page 1 … --page 4`. Pages with index 1, 2 and 3 were written as `_p1.._p3`, then index 4 failed. Its exit code and stderr were ignored. `cmp` confirms `idml-demo/out/sample_tr_src_p1.png == page-002.png`, and the same holds for p2 = page 3 and p3 = page 4. **The cover page was never compared**, and the file names are off by one.
- With no `--page`, the export is page 0. The PDF export ignores `--page`.
- Fix: `--page i --export X_p{i+1}.png` for `i in range(pageCount)` in one run, or `--all-pages DIR` (writes `DIR/page-001.png` …). Check exit code 0 and count the `wrote …` lines on stderr (the snippet does both).
- Output: 630×810 px at scale 1, which is 612×792 pt plus 9 pt bleed on each side (1 px/pt). `--scale 2` gives 1260×1620.
- Timing: render times reported per page were 43 / 23 / 10 / 4 ms (the first page includes font warm-up). Wall time for all 4 pages is about 100–130 ms including startup.

## 4. Hyphenation (EN / TR / DE)

**How it was tested.** Copies of the sample were rewritten byte for byte (lxml; `mimetype` kept first and stored). Story `u20` (DC story 9) was given long-word text. `Justification="LeftJustified"` and `Hyphenation=true/false` were set on its ParagraphStyleRange and `AppliedLanguage` on its CharacterStyleRange. Its frame `u1f` was narrowed to 120 pt. A designmap `<Language>` element was added or left out. For each variant: `story.get` gave the line count, and a PDF of page 2 was read with PyMuPDF to count lines ending in a hyphen. A PNG crop is in `dc_artifacts/hyphenation_compare.png` and the full line dump in `dc_artifacts/hyphenation_lines.json`.

| Text | AppliedLanguage | Hyphenation | designmap `<Language>` | Lines | Lines ending in "-" |
|---|---|---|---|---|---|
| EN | English: USA | on | (already present) | 10 | **5** (`not-`, `tel-`, `dem-`, `extraordi-`, `incomprehen-`) |
| EN | English: USA | off | | 11 | 0 |
| EN | [No Language] | on | | 11 | 0 |
| DE | German: 2006 Reform | on | no | 10 | **0** |
| DE | German: 2006 Reform | on | **yes** | 10 | **0** |
| DE | English: USA | on | | 13 | 8 (English patterns: `Arbeit-sunfähig-`) |
| TR | Turkish | on | no | 10 | **0** |
| TR | Turkish | on | **yes** | 10 | **0** |
| TR | English: USA | on | | 10 | 7 (`Çekoslova-`, `Afyonkarahisarlılaş-` …) |

The DE/TR rows with hyphenation off give the same lines as the rows with it on.

**Conclusions**
- DC hyphenates only text whose language is English. The binary contains a single pattern set, `DesignCraft US English hyphenation patterns (Liang/TeX notation)`. There are no German or Turkish patterns, and no dictionary-listing command.
- With TR or DE applied, DC does not hyphenate. Words wider than the column are **split mid-word with no hyphen**, for example `Donaudampfschifffa|hrtsgesellschaft`.
- What this means for verification: DC's DE/TR line breaks will not match InDesign, which hyphenates with its own dictionaries. DC's line counts and overset for DE/TR are a **pessimistic** estimate, because without hyphenation text needs at least as many lines. A story that fits in DC will almost certainly fit in InDesign. An overset in DC may be a false alarm if it is small. Report DE/TR overset as "overset in DC (no TR/DE hyphenation; InDesign may fit)", together with the overflow size from preflight (`Overset text: N characters`).
- Do **not** set English as the AppliedLanguage just to please DC. That produces wrong breaks (`Arbeit-sunfähig-`) and breaks spelling and hyphenation in InDesign.
- A possible extra check: look for forced mid-word breaks in narrow frames by comparing PDF line ends against the story text. A line that ends inside a word with no hyphen means the word is wider than the column. The snippet does not include this; it is optional.

**designmap `<Language>` requirement**
- DC: **not required.** Adding `<Language Self="Language/$ID/Turkish" …/>` or `…German%3a 2006 Reform…` changed nothing. `file.openIdml` returned `warnings: []` with an undeclared `$ID/Turkish` and even with a made-up `$ID/Klingon: Bogus`. DC does not validate languages.
- InDesign (not testable here): IDML from InDesign normally declares every language it uses in designmap.xml. The sample declares only `[No Language]` and `English: USA`. InDesign resolves `$ID/Turkish` by name from its built-in language list, so an AppliedLanguage alone probably works, but this could not be verified without InDesign. **Recommendation to the translator team:** to stay strictly within "change AppliedLanguage only", the DC check passes either way. Adding the matching `<Language>` element (copy the attributes InDesign writes: `Name`, `PrimaryLanguageName`, `SublanguageName`, `Id`, `SingleQuotes`/`DoubleQuotes`, `HyphenationVendor`/`SpellingVendor="Hunspell"`) is the safer choice for InDesign, and DC does not care. The ids used in the test were German: 2006 Reform = 1797 and Turkish = 287; they still need checking against a real InDesign export.

## 5. Missing glyphs

Options checked:
- **(a) fontTools.** Version 4.61.1 is installed. It works for *installed* fonts in `C:\Windows\Fonts`. But the sample's fonts (Source Sans 3, Source Serif 4) are `source:"bundled"` and **compiled into designcraft.exe**: there are no TTF/OTF files under `C:\Program Files\DesignCraft`, and `file.package` does not copy them. So fontTools cannot check the sample.
- **(b) DC `preflight.run` (recommended).** It reports `{"kind":"missingGlyphs","severity":"error","message":"Missing glyphs in Bell MT Regular: ğ Ğ ş Ş İ ẞ"}`. Checked against fontTools: Bell MT lacks `ğşİẞ` (plus capitals), Book Antiqua lacks only `ẞ`, Arial, Courier New and Source Sans 3 lack only the test CJK/Thai characters, and preflight agreed exactly in every case. It covers bundled, installed and document fonts in one call (about 55 ms). If the font itself is missing, you get `{"kind":"missingFont","message":"Missing font: Nonexistent Sans"}` and `font.list` shows `missing:true`. No glyph check is possible then, so report "unverifiable".
- **(c) Render and detect.** Not needed. In the PDF export the missing characters are simply left out of the text layer and no fallback font shows up, so (b) is strictly better.

The applied fonts in the sample (Source Sans 3 / Source Serif 4) cover all of `ğĞşŞıİçÇöÖüÜ ßẞäöüÄÖÜ „“‚‘ «»`. The TR and DE outputs show 0 missing glyphs.

Caveat: the result depends on the fonts on this machine. Production fonts that are absent here appear as `missingFont`, and their glyphs cannot be checked.

## 6. Preflight, warnings and diffing "new issues only"

- Sample: `{"errors":0,"issues":[],"warnings":0}`. TR: the same. DE: `{"item":45,"kind":"overset","message":"Overset text: 525 characters","page":2,"severity":"error"}`. Frame 45 is the second frame of story 11 = `Story_u26.xml`. `page:2` is the 0-based index of the page named "3".
- `font.list` lists the same 6 faces for EN, TR and DE (all bundled, none missing). Only the `characters` counts change.
- **Diff approach** (`new_issues()` in the snippet): the key is `(kind, item, page, message with digits replaced by #)`, so a changed overflow count does not count as a new issue. Frame ids stay the same when the geometry is unchanged, which the geometry gate guarantees. For `missingGlyphs` the diff is per font: only characters that are newly missing count. Fonts that become missing are reported as `missingFont`.
- **Warnings when opening a file:** neither `run --in` nor stderr reports any. `file.openIdml` has a `warnings` field (font files skipped), which was `[]` in every case, including a bogus language. Language problems are therefore invisible. The verify module should check AppliedLanguage values against a known list itself.

## 7. Timings (sample, 4 pages, 18 stories; wall time including process start, best of 3)

| Operation | ms |
|---|---|
| `--version` (process start only) | 5–8 |
| `document.inspect` | 48–58 |
| `preflight.run` | 54–58 |
| `font.list` | 48–49 |
| `story.get` (1 story) | 51–52 |
| 18× `story.get` in one run | 54 |
| inspect + preflight + font.list in one run | 78–79 |
| 4-page PNG export (one run) | 99–127 |
| 4-page PDF export | 128–151 |

Opening the IDML costs about 45 ms and dominates every query. Several `--cmd` in one run share that cost, so the verify module should batch: inspect + preflight + font.list (+ story.get) in one run, and exports in a second run. A full check of one document costs about 0.3 s.

## 8. Geometry gate

- Fields **present** on every item: `id, kind, bounds, layer, fill, stroke, hidden, locked, name`. Text frames add `story, columns, columnRule`; images add `asset`. Fields **absent**: `rotation` and `page`. The page has to be worked out from the item centre against `spread.pages[].bounds` (`geometry()` does this). A rotated item could only be detected through its bounding box.
- **Stability:** `document.inspect` is byte-for-byte deterministic across runs. Sample versus TR/DE outputs: all item ids, kinds, bounds, columns, story links, page counts and spreads are identical (`geometry_diff` → none). Values that legitimately change are `stories[].length/lines/preview/overset` and `font.list[].characters`. One bounds value is `173.99999999999997`, so round to 3 decimals (snippet) or compare with a tolerance.
- **Nested, anchored and table items:** the sample has no groups and no anchored or inline frames (`anchored.list` → `[]`). Its one table lives in a story and shows up only as U+E009 in `story.get`; `table.get` (after `text.select`) gives cells, column widths and minimum row heights, but **no composed geometry or overflow per cell**. Parent-spread items are not listed. For the gate this means: compare page items, plus spreads and page count, plus the overset list. Table overflow and anchored-object movement cannot be checked from `inspect`; use the rendered page (PNG) for those.

## 9. Recommendations for the `verify` module

1. Run 1 per file (source and output): `document.inspect` + `preflight.run` + `font.list`. Run 2: PNG export with 0-based `--page`, or `--all-pages`. Optional run 3: PDF export with PyMuPDF line analysis for DE/TR line-break checks.
2. **Gate on:** `geometry_diff == []`; no new `overset` stories (from `inspect`, mapped to story files with `story_map`, and label DE/TR overset as possibly false alarms due to missing hyphenation); no new `missingGlyphs`; no new `missingFont`; `pageCount` and spreads unchanged.
3. Map stories with geometry plus the rank check. Raise an error rather than fall back to text similarity.
4. Always check the exit code and that the number of results equals the number of `--cmd`. One bad command aborts the rest.
5. Text checks with `story.get` must allow for PIs and private-use anchors, and must pull table text with `table.get` and footnote text with `footnote.list`.
6. Never rely on DC to confirm hyphenation or language for TR/DE. Check AppliedLanguage values in Python against an allow-list, and decide separately whether to add designmap `<Language>` elements for InDesign. DC is indifferent.
7. Compare PNGs page by page, including page 1, and use the snippet's `_p{1-based}` naming.

## Snippet API (`research/designcraft_verify_snippet.py`)

`dc_run(idml, cmds) -> list`, `cmd(id, params)`, `inspect(idml)`, `geometry(inspect)`, `geometry_diff(a, b)`, `overset(inspect)`, `story_map(idml_path, inspect) -> {dc_id: "Stories/Story_uXX.xml"}` (and `story_map.last_methods`), `export_pngs(idml, out_prefix, page_count, scale=None)`, `export_pdf(idml, path, pages=None)`, `preflight(idml) -> {preflight, fonts}`, `missing_glyphs(preflight_result) -> {"Family Style": {chars}, "!unverifiable": {...}}`, `new_issues(before, after)`.

Self-test output (`python research/designcraft_verify_snippet.py`, PYTHONIOENCODING=utf-8):
```
== inspect / determinism
sample: pageCount=4 spreads=3 stories=18 inspect 58 ms (min of 3)
inspect deterministic across runs: True

== story_map (geometry + rank fallback)
  dc  2 -> Stories/Story_ue.xml     via rank
  dc  3 -> Stories/Story_u10.xml    via rank
  dc  4 -> Stories/Story_u16.xml    via geometry
  ... (dc 5..18 via geometry)
  dc 19 -> Stories/Story_u3e.xml    via geometry
  text check on sample: 18/18 stories identical; mismatches: []
  reversed <idPkg:Story> order: DC ids [2, 4, 5, 6] ...; frame->file mapping identical to sample: True ; methods: {'geometry': 16, 'rank': 2}

== TR output sample_tr.idml
  story_map identical to sample: True
  geometry diffs vs sample: none
  overset DC stories: [] -> []
  preflight: {"errors": 0, "issues": [], "warnings": 0}
  new issues vs source: []
  missing glyphs: none

== DE output sample_de.idml
  story_map identical to sample: True
  geometry diffs vs sample: none
  overset DC stories: [11] -> ['Stories/Story_u26.xml']
  preflight: {"errors": 1, "issues": [{"item": 45, "kind": "overset", "message": "Overset text: 525 characters", "page": 2, "severity": "error"}], "warnings": 0}
  new issues vs source: [{"item": 45, "kind": "overset", "message": "Overset text: 525 characters", "page": 2, "severity": "error"}]
  missing glyphs: none

== export_pngs (4 pages, 0-based --page)
  sample_p1.png: 630x810 render 47.4 ms, 103 glyphs
  sample_p2.png: 630x810 render 26.3 ms, 1171 glyphs
  sample_p3.png: 630x810 render 10.1 ms, 3410 glyphs
  sample_p4.png: 630x810 render 5.5 ms, 466 glyphs
  wall for all 4: 127 ms

== timings (wall, min of 3 runs, includes process start)
  document.inspect                                55 ms
  preflight.run                                   58 ms
  font.list                                       49 ms
  story.get (1 story)                             52 ms
  18x story.get in one run                        54 ms
  inspect+preflight+font.list in one run          79 ms
  file.exportPdf (4 pages)                       151 ms
  export_pngs (4 pages)                          116 ms
  no-op open (version)                             8 ms

== missing-glyph check on a synthetic preflight result
   {'Bell MT Regular': {'Ğ', 'İ', 'Ş', 'ş', 'ẞ', 'ğ'}}

OK
```
