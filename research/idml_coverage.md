# IDML coverage: where translatable text lives (research R1)

Scope of this report: where translatable text lives in an IDML package and which nodes can appear inside
or next to `<Content>`. This decides what the translator can handle under the invariant (the translator
changes only `Content.text`, the `.tail` of PIs inside `Content`, and `AppliedLanguage` on the enclosing
CSR).

Evidence comes from three sources:
- **sample**: `idml-demo/sample_en.idml`, surveyed with `research/scripts/survey_idml.py` (full JSON in
  `research/scripts/sample_survey.json`).
- **DC**: DesignCraft 0.6.0 CLI experiments, and the fixtures in `fixtures/`.
- **spec**: IDML specification knowledge. Rows marked *unverified (spec knowledge)* could not be
  checked here.

Abbreviations: PSR = `ParagraphStyleRange`, CSR = `CharacterStyleRange`, PI = processing instruction.

---

## 1. Inventory

"Safe?" means the construct can be translated correctly while changing nothing except `Content`
text, PI tails and CSR `AppliedLanguage`.

| # | What / XML location | Example (abridged) | Safe? | Recommended scope | Reason / risks |
|---|---|---|---|---|---|
| 1 | **Story body**, `Stories/Story_*.xml`: `Story > PSR > CSR > Content` | `<CSR AppliedCharacterStyle="…/Accent"><Content>Every page begins as</Content></CSR>` | yes | **translate** | Main case: 37 of 53 `Content` elements in the sample. Each CSR boundary is a formatting run, so the run order is fixed, which limits word reordering (sample u26: an `Accent` run followed by a plain run in one sentence). |
| 2 | **Stories whose frame is on a master spread**: `MasterSpreads/*.xml` `TextFrame@ParentStory` → a normal story file | sample `ue`: `<Content><?ACE 18?>  ·  QUARTERLY</Content>`; `u10`: `SPRING ISSUE  ·  <?ACE 18?>` | yes | **translate** | Story files look exactly like body stories, so placement can only be found in the spreads. One master story renders on every page that uses that master, so a fit check must cover all of them. Folios are short, contain ACE 18/19, and use fixed spacing (double spaces around `·`). |
| 3 | **Threaded stories** (one story, many frames, `TextFrame@PreviousTextFrame/NextTextFrame`) | sample `u26` spans 2 frames (DC frames 44, 45) | yes | **translate** | Translate each story once, never per frame. Overflow causes overset at the last frame. |
| 4 | **Tables**: `CSR > Table > Cell > PSR > CSR > Content`; header and footer rows have the same shape and differ only in `Table@HeaderRowCount/FooterRowCount` | `<Cell Name="0:0"><PSR AppliedParagraphStyle="…/Table Head"><CSR><Content>SWATCH</Content>` | yes | **translate** (one segment per cell paragraph) | 15 of 53 `Content` elements in the sample. `Row/Column/Cell@Name` are coordinates ("0:1"); never translate them. A cell can hold several paragraphs (`<Br/>` inside a Cell, `fx_table` 2:2) and several CSRs (`fx_table` 2:1). Fixed row heights can overset cell text. Header text in the sample is literal upper case without an AllCaps style (see #27). The Table is an inline object in its parent paragraph: the host paragraph text and the table must not be merged into one segment. |
| 5 | **Footnotes**: `CSR(Position=Superscript) > Footnote > PSR > CSR > Content`; text starts with `<?ACE 4?>` + separator TAB | `<Content><?ACE 4?>	Every image, swatch and paragraph…</Content>` | yes | **translate** as a separate segment; the host sentence continues across the reference | `<?ACE 4?>` (footnote number) must stay first, and the TAB after it is real story text. In `fx_footnote` the `ACE 4` + TAB sit inside a bold run. The prototype's `NESTED` handles this correctly. |
| 6 | **Endnotes** (InDesign 2018+): endnote story + references | — | probably | **translate** (as stories) | *unverified (spec knowledge)* for the InDesign shape. DC 0.6.0 export flattens endnotes: the reference disappears from the body and the endnote story is plain text with a literal `1\t` number. |
| 7 | **Notes** (editorial comments): `CSR > Note > PSR > CSR > Content`, between `Content` siblings | `fx_misc`: `<Content> Note anchor</Content><Note UserName="QA">…<Content>Reviewer note…</Content></Note><Content> here. </Content>` | yes | **skip-with-reason** (not printed) | Leave untouched; optionally translate behind a flag. Notes split the host text into two `Content` siblings, so the host paragraph has a fixed insertion point there. DC drops notes on import. |
| 8 | **Anchored / inline objects** in a story: `CSR > TextFrame|Rectangle|Group|…` with `AnchoredObjectSetting`; an anchored TextFrame's text is in **its own story file** (`TextFrame@ParentStory`) | `fx_nested`: `<Content>…before the anchor. </Content><TextFrame Self="u8" ParentStory="u9">…</TextFrame><Content> Main story after…</Content>` | yes | **translate** the child story as a normal story; treat the anchor as a fixed inline object in the host | The host's `Content` is split around the object. Don't walk into anchored frames looking for `Content`: there is none inside (walking in is harmless). DC refuses to anchor text frames, and on import it drops an anchored TextFrame (story becomes frameless/overset, no warning). |
| 9 | **Groups / buttons / multi-state objects** in spreads (`Group > TextFrame`, `MultiStateObject > State > …`) | — | yes | **translate** via the stories they reference | Text is always in a story file. *unverified (spec knowledge)* for button/form field values. |
| 10 | **Text on a path**: `Spreads/*.xml` `<TextPath ParentStory="ua" …/>` inside a path item | `fx_misc`: `<TextPath Self="u9tp" ParentStory="ua" PathEffect="RainbowPathEffect" …/>` | yes | **translate** | Path length is fixed and overset is invisible, so length matters a lot here. The survey counts TextPath stories as placed. |
| 11 | **Text variables**: `designmap.xml` `<TextVariable VariableType="CustomTextType"><CustomTextVariablePreference Contents="Widget Pro"/>` (other types carry `TextBefore`/`TextAfter`/`Format`); in stories `<TextVariableInstance Name ResultText AssociatedTextVariable/>` between `Content` siblings | `fx_vars_links`: `<Content>Buy the </Content><TextVariableInstance Name="Product" ResultText="Widget Pro" AssociatedTextVariable="dTextVariablenProduct"/><Content> today. Visit </Content>` | **no** for the definition (attribute text); yes for the surrounding text | **translate** the surrounding text, with the instance as a fixed inline object; the variable `Contents`/`TextBefore`/`TextAfter` and `ResultText` are **skip-with-reason (report)** | Translating `Contents` needs an invariant extension (attribute edit). `ResultText` is a cached value; whether InDesign recomputes it on open is *unverified*. The sample has only the two built-in `XrefChapterNumber/XrefPageNumber` variables (no Contents) and no instances. DC export bug: DC writes variables as raw private-use chars (U+E107, U+E108) inside `<Content>` and drops custom definitions. DC import drops `TextVariableInstance`. |
| 12 | **Hyperlinks**: in stories `PSR > HyperlinkTextSource > CSR > Content`; in the designmap `<Hyperlink Name Source>` + `<HyperlinkURLDestination DestinationURL Name>` | `fx_vars_links`: `<HyperlinkTextSource Self="uf002" Name="Site link"><CSR><Content>our website</Content></CSR></HyperlinkTextSource>` | yes (link text); n/a (designmap) | **translate** link text; **skip** names, URLs and `mailto:` | The source wrapper is a run boundary like a CSR (the prototype walks through it transparently, which is correct). The link text must stay inside the wrapper, so tags must not be dropped or merged. Names are not printed. DC 0.6.0 neither exports nor imports URL/email hyperlinks. |
| 13 | **Text anchors / hyperlink text destinations**: `CSR > HyperlinkTextDestination Name=… DestinationUniqueKey=…` before or between `Content` | `<HyperlinkTextDestination Self="…/a134217729" Name="Second paragraph: the cross-reference ta"/>` | n/a | **skip** (fixed inline object) | `Name` is auto-generated from source text (DC) but not printed. Leaving it in English is harmless. |
| 14 | **Cross-reference source**: `PSR > CrossReferenceSource AppliedFormat=… > CSR > Content` holding **generated** text | `<CrossReferenceSource AppliedFormat="CrossReferenceFormat/f1"><CSR><Content>“Second paragraph: the cross-reference target.”</Content>…` | yes (text edit) but regenerated | **translate as its own atomic segment, and report "update cross-references"** | If skipped, English stays visible until the user runs Update Cross-References. When that runs, InDesign regenerates the text from the translated target plus the format, overwriting our text. Never merge it into the surrounding sentence. |
| 15 | **Cross-reference formats**: designmap `CrossReferenceFormat > BuildingBlock BlockType="CustomStringBuildingBlock" CustomText="&quot; on page "` | sample: 11 formats, 18 custom strings (`"`, `" on page `, ` on page `, `page `) | **no** (attribute) | **skip-with-reason (report)** | Regenerated xrefs will contain English "on page". Translating these needs an invariant extension (v2 option). |
| 16 | **Conditional text**: `CSR@AppliedConditions="Condition/…"`; designmap `<Condition Name Visible="true/false"/>` | `fx_misc`: `<CSR AppliedConditions="Condition/Hidden"><Content>Hidden condition text.</Content>` | yes | **translate visible and hidden** (hidden text is usually an alternate version), but exclude hidden text from fit checks; option to skip hidden | Never touch `AppliedConditions`. A condition boundary is a CSR boundary (fixed run order). Hidden text is still stored in `Content`. |
| 17 | **Tracked changes**: `Story@TrackChanges`; `Change ChangeType="InsertedText|DeletedText|MovedText"` wrapping CSRs (or Content) | `fx_misc`: `<Change ChangeType="DeletedText" UserName="QA"><CSR><Content>Deleted words.</Content></CSR></Change>` | partly | **warn**; translate `InsertedText`, **skip `DeletedText`** (not in the output), `MovedText` *unverified* | Recommend asking users to accept or reject all changes first. If not handled, deleted text gets translated and segments break across the `Change` wrapper. Exact InDesign shape (Change as child of PSR vs CSR) is *unverified (spec knowledge)*. DC flattens changes on export (deleted text reappears as plain text) and on import. |
| 18 | **Index**: designmap `Index > Topic Name="…" SortOrder` (nested Topics); in stories `<PageReference ReferencedTopic=… PageReferenceType=…/>` between `Content` siblings | `fx_misc`: `<Content> </Content><PageReference … ReferencedTopic="ixTopicnTermsTopicnIndex term"/><Content>Index term here. </Content>` | **no** (topic names are attributes) | **skip-with-reason (report)**; the PageReference is a fixed inline object | A generated index story is ordinary text and would get translated, but regenerating the index overwrites it from the (English) topics. Topic translation is a v2 option. |
| 19 | **TOC**: `Resources/Styles.xml` `TOCStyle@Title` (and entry styles); generated TOC story (`Story@AppliedTOCStyle != "n"`) | sample: all stories `AppliedTOCStyle="n"`, no TOCStyle with a title | Title: no; TOC story: yes | TOC story: **translate (provisional)**; `Title`: **skip-with-reason (report)** | Regenerating the TOC overwrites the story from the translated headings, which is consistent. The title is an attribute. |
| 20 | **Bookmarks** (PDF): designmap `Bookmark@Name` | — | no | **skip-with-reason (report)** | Attribute. *unverified (spec knowledge)* shape. |
| 21 | **Alt text / actual text**: spreads `PageItem > ObjectExportOption CustomAltText CustomActualText AltTextSourceType="SourceCustom"` | `fx_misc`: `<ObjectExportOption CustomAltText="Alt text: a placeholder graphic frame" …/>` | **no** (attribute) | **skip-with-reason (report)**; strong v2 candidate (accessibility) | DC `object.altText` is not exported to IDML. The shape is *unverified (spec knowledge)*. |
| 22 | **XML structure**: `XMLElement MarkupTag=…` wrapping `Content` (or PSR/CSR) inside stories; `XML/BackingStory.xml` (`XmlStory`), `XML/Tags.xml`; `XMLAttribute@Value` | `fx_misc`: `<CSR FontStyle="Bold"><XMLElement MarkupTag="XMLTag/title"><Content>Tagged title</Content></XMLElement></CSR>` | yes (wrapped Content) | **translate** wrapped `Content` (the wrapper is a run boundary); **skip** BackingStory text and attributes | So `Content`'s parent is **not always a CSR**: `AppliedLanguage` goes on the nearest ancestor CSR. Unplaced XML content in the BackingStory is not printed. Shape is *unverified (spec knowledge)*. DC 0.6.0 neither exports nor imports XML structure. |
| 23 | **Paragraph end** `<Br/>`, always a sibling of `Content` inside a CSR | sample: 20 `Br`; `<Content>…</Content><Br/>` | n/a | **segment boundary** | Never inside `Content`. Paragraph-split titles become two segments: sample u18 is `The Quiet` / `<Br/>` / `Art of Layout`. See risks. |
| 24 | **Column/frame/page break**: a CSR with `ParagraphBreakType="NextColumn|NextFrame|NextPage|…"` holding `<Br/>` | DC: `<CSR … ParagraphBreakType="NextFrame"><Br/></CSR>` | n/a | **segment boundary**, untouched | Verified by DC export. |
| 25 | **`<?ACE n?>` PIs** inside `Content` | `<Content>SPRING ISSUE  ·  <?ACE 18?></Content>` | yes (PI untouched, tails editable) | **atomic placeholder** | See §3. |
| 26 | **Special Unicode characters** (literal in `Content`) | U+2028, U+00AD, U+00A0, U+202F, U+2002/3, U+200B… | yes | **placeholder / normalise** per §3 | See §3. |
| 27 | **Capitalization**: `Capitalization="AllCaps|SmallCaps|CapToSmallCap"` on ParagraphStyle/CharacterStyle (Styles.xml) or as a CSR/PSR override | sample: `ParagraphStyle/Kicker` AllCaps, used by u16 `THE SPRING ISSUE  ·  NO. 01`, u1c `Feature  ·  Design`, u2e `Coming next`; `fx_master_caps`: style + CSR override | yes | **translate in natural case**; keep source casing patterns | Text under AllCaps is stored in any case: u1c/u2e are mixed case and display as caps, u16 is literal caps. Header cells (`SWATCH`, `BUILD`) are literal caps with no caps style. Rule: if a source run is all upper case, upper-case the target with a locale-aware mapping (Turkish i → İ). Otherwise keep the model's case. Whether InDesign's display AllCaps is language-aware (Turkish dotted i) is *unverified*. |
| 28 | **AppliedLanguage** | sample: only `ParagraphStyle/$ID/[No paragraph style]` = `$ID/English: USA`; 0 of 56 CSRs set it; designmap `Language` list = `[No Language]`, `English: USA` | yes (CSR attr is in scope) | set on the **nearest CSR** of every translated `Content` (incl. Cell, Footnote, Note, HyperlinkTextSource, Change, XMLElement contexts) | It can also come from PSR overrides, character styles and `Preferences.xml TextDefault`. Run order: CSR > PSR > char style > para style. DC accepts `AppliedLanguage="$ID/Turkish"` with no matching `<Language>` element and keeps it on export. InDesign's behaviour with a language missing from the designmap list is *unverified* (see risks). |
| 29 | **Story-level attributes**: `Story@TrackChanges/StoryTitle/AppliedTOCStyle`, `StoryPreference` | all 18 sample stories `TrackChanges="false" AppliedTOCStyle="n" StoryTitle="$ID/"` | n/a | untouched | `TrackChanges="true"` triggers the #17 warning. |
| 30 | **PSR without CSR / Content directly under PSR / empty CSRs** | sample: 0 PSRs without CSR. DC exports empty `<CSR …/>` (empty cells, trailing empty paragraph) | n/a | tolerate | InDesign always writes CSRs; a bare `PSR > Content` from third-party writers is *unverified (spec knowledge)*. Empty CSRs must not get an `AppliedLanguage` (no text in them). |
| 31 | **Multiple `Content` siblings in one CSR** around inline objects (TextVariableInstance, PageReference, HyperlinkTextDestination, Note, anchored frames, Footnote/Table siblings) | `fx_nested`, `fx_vars_links`, `fx_misc`, DC probe | yes | slots kept in order, each a separate run | An object's position between two `Content`s is fixed, so the translation must place text on the correct side of each object. |
| 32 | **Linked stories** (InCopy `.icml`, `story.placeAndLink`), `Link` with `LinkResourceURI` | — | yes for text, but… | **flag**: translate, but warn | Updating the link overwrites the translation from the source. *unverified (spec knowledge)* markup. |
| 33 | **Paragraph numbering and bullets text**: `ParagraphStyle@NumberingExpression` (e.g. `Step ^#.^t`), `BulletChar` | sample: only bullet U+2022 on `[No paragraph style]` | no (attribute) | **skip-with-reason (report)** when the expression contains letters | Words like "Step"/"Chapter" in numbering stay English. |
| 34 | **Section marker / prefix**: designmap `Section@Marker`, `@SectionPrefix` (printed via `<?ACE 19?>`) | sample: `Marker="" SectionPrefix=""` | no (attribute) | **skip-with-reason (report)** if non-empty | Visible text outside the invariant. |
| 35 | **Footnote options**: `Preferences.xml FootnoteOption Prefix/Suffix/Separator` | sample: `Prefix="" Suffix=""` | no | skip | Usually punctuation. |
| 36 | **Overset text / pasteboard frames** | — | yes | **translate** + report | It is still story content. |
| 37 | **Outlined text** (converted to polygons or compound paths) | — | — | **flag-unreachable** | No text left; only a heuristic warning is possible. |
| 38 | **Placed images / PDF / EPS with text** (`Image`, `PDF`, `EPS`, `Link`); embedded `<Contents>` base64 | sample: 2 embedded `Image` (`<Contents>` in Spread_ua/ub) | — | **flag-unreachable** (list links) | Note `<Contents>` ≠ `<Content>`: an element-name match must be exact. |
| 39 | **Names and IDs**: style, swatch, layer, `StoryTitle`, `Cell@Name`, `Hyperlink@Name`, `Topic@Self`, XML tag names | — | — | **never translate** | Referenced by `Self` ids or not visible. |

## 2. Sample survey results (`sample_en.idml`)

Command: `PYTHONIOENCODING=utf-8 python research/scripts/survey_idml.py ../idml-demo/sample_en.idml --json research/scripts/sample_survey.json`

- **Package**: 29 zip entries. `mimetype` is first and stored; the other 28 are deflated. 18 stories, 1 master spread
  (`MasterSpread_u4`, 2 pages), 3 spreads, 4 pages (page 1 has no master; pages 2–4 use `A-Parent`).
- **Placement**: master spread: 2 TextFrames (stories **`ue`, `u10`**) and 2 GraphicLines. Spreads: 17
  TextFrames (16 stories; `u26` is threaded over 2 frames), 4 Rectangles, 2 embedded Images, 4 Ovals.
  0 unplaced stories, 0 TextPaths, 0 anchored objects, 0 groups.
- **Story elements**: 54 PSR, 56 CSR, **53 `Content`**, 20 `Br`, 1 `Footnote`, 1 `Table` (5 Row, 3 Column,
  15 Cell), 1 CSR `Properties/Leading`. 0 Note, Change, HyperlinkTextSource, TextVariableInstance,
  XMLElement, PageReference or AppliedConditions.
- **`Content` ancestor paths**: `PSR/CSR` × 37; `PSR/CSR/Table/Cell/PSR/CSR` × 15;
  `PSR/CSR/Footnote/PSR/CSR` × 1. All 53 parents are CSRs.
- **Inside `Content`**: only PIs. `<?ACE 18?>` × 2 (master stories `ue` and `u10`) and `<?ACE 4?>` × 1 (the footnote).
  No child elements.
- **Siblings of `Content`** (per-Content occurrence counts): `Br` × 19, `Properties` × 1 (u30, before
  `Content`). Never two `Content`s in one CSR.
- **Non-ASCII and control characters in `Content`**: U+0009 TAB × 1 (after `ACE 4` in the footnote),
  U+00B7 MIDDLE DOT × 4, U+2014 EM DASH × 4, U+201C × 1, U+201D × 1. No NBSP, U+2028, soft hyphens or
  fixed spaces. Spacing is plain ASCII double spaces around `·`.
- **Table** (`u3f` in story `u3e`): `HeaderRowCount=1 BodyRowCount=4 FooterRowCount=0 ColumnCount=3`.
  Every cell has exactly 1 PSR / 1 CSR / 1 `Content`. Header cells `SWATCH`, `BUILD`, `USED FOR` use style
  `Table Head` (not AllCaps, so they are literally upper case).
- **Footnote** (story `u26`): `CSR Position="Superscript" > Footnote > PSR(Footnote) > CSR > Content`,
  text `<?ACE 4?>\tEvery image, swatch and paragraph in this sample is generated in code — no stock assets.`
- **Paragraph styles with Capitalization**: `ParagraphStyle/Kicker` = `AllCaps` (stories u16, u1c, u2e).
  All others are `Normal`.
- **AppliedLanguage**: only `ParagraphStyle/$ID/[No paragraph style]` = `$ID/English: USA`. All 56 CSRs
  inherit. The designmap declares the languages `$ID/[No Language]` and `$ID/English: USA`.
- **designmap text-bearing attributes**: 2 built-in `TextVariable`s (XrefChapterNumber/XrefPageNumber, no
  Contents), 11 `CrossReferenceFormat`s with 18 `CustomStringBuildingBlock CustomText` strings (English
  `" on page "`, `"page "`), 1 `Section` (`Marker=""`, `SectionPrefix=""`). No Hyperlink, Bookmark, Index,
  Condition or XML parts.
- **Other**: all stories have `TrackChanges="false"`; `FootnoteOption Prefix="" Suffix=""`. Title story u18
  is two paragraphs (`The Quiet` `<Br/>` `Art of Layout`).
- **DC round trip of the sample** (`file.exportIdml` after open): all 53 `Content` strings are preserved
  (multiset equal). Story, spread and master ids and file names are renumbered (`Story_u26` → `Story_ub`). Only 4 of 29
  entries are byte-identical (`mimetype`, `container.xml`, `Graphic.xml`, `Preferences.xml`).

## 3. Special characters and PIs: what segmenters and placeholders must handle

General rules:

1. Any PI inside `Content` is an **immovable atomic object**. Under the invariant only the text
   between PIs changes, so a PI is a hard slot boundary. Send it to the model as a numbered self-closing
   token (e.g. `<x1/>`) and require exactly one occurrence of each token, in order.
2. Strip leading and trailing whitespace of each slot before translation and re-attach it afterwards.
   Examples: `"SPRING ISSUE  ·  "` before ACE 18, and `"\tEvery image…"` after ACE 4.
3. Never build XML by string concatenation. lxml escapes `&`, `<` and `>`. `fx_master_caps` contains the
   literal text `&amp;` (stored as `&amp;amp;`) to catch double escaping or unescaping.
4. Don't split CLI or JSON text with `str.splitlines()`: it also splits on U+2028, U+2029, U+0085, VT and FF. This was
   hit while building the fixtures.

Why ACE exists (inference): `<?ACE n?>` encodes an InDesign internal character whose code n is an
XML-illegal control character (3, 4, 7, 8, 18 = 0x12, 19 = 0x13). So every ACE value is an object
marker, never text.

| Item | Storage | Verified | Meaning | Treatment |
|---|---|---|---|---|
| `<?ACE 18?>` | PI in Content | sample + DC (U+E000 ↔ ACE 18) | Current page number | atomic token |
| `<?ACE 19?>` | PI | DC (U+E001) | Section marker (prints `Section@Marker`) | atomic token |
| `<?ACE 4?>` | PI, first in footnote text | sample + DC (only honoured inside Footnote) | Footnote number | atomic token; keep first; the following TAB is a separate whitespace prefix |
| `<?ACE 7?>` | PI | DC (U+E005) | Indent to here | atomic token |
| `<?ACE 8?>` | PI | DC (U+E006) | Right indent tab | atomic token |
| `<?ACE 3?>` | PI | DC import **drops** it | End nested style here | atomic token. *Meaning unverified (spec knowledge)* |
| other `<?ACE n?>` (1, 2, 5, 6, 9–17, 20+) | PI | DC drops all of them on import | Next/previous page number etc., *unverified* (DC exports its next/prev page markers U+E007/U+E008 as `ACE 18`, lossy) | atomic token; never interpret |
| any other PI | PI | — | — | atomic token |
| `<Br/>` | element, sibling of Content | sample | paragraph end | segment boundary |
| `ParagraphBreakType` CSR + `<Br/>` | CSR attr | DC | column/frame/page/odd/even break | segment boundary |
| TAB U+0009 | literal | sample, fixtures | tab | **placeholder token** (`<tab/>`), count preserved; models turn tabs into spaces |
| U+2028 LINE SEPARATOR | literal | `fx_table`, `fx_master_caps` | forced line break (Shift+Enter) | **placeholder token** (`<lb/>`); keep the count, the position may move within the slot |
| U+00AD SOFT HYPHEN | literal | `fx_master_caps` | discretionary hyphen | **strip** before MT (it breaks the word for the model); don't re-insert |
| U+200B ZERO WIDTH SPACE | literal | `fx_master_caps` | discretionary line break (InDesign) | strip inside words. Keep (as a token) in URLs and paths |
| U+200C / U+200D ZWNJ / ZWJ | literal | DC probe (kept literally) | non-joiner / joiner; part of emoji ZWJ sequences | keep inside emoji sequences; otherwise strip (Latin) or keep as-is (scripts that need them) |
| U+FEFF | literal | DC probe (kept) | zero-width no-break | keep as token. Where InDesign emits it is *unverified* |
| U+00A0 NO-BREAK SPACE | literal | fixtures | nonbreaking space | between digit/currency/unit or abbreviation and number: **token**. Otherwise normalise to a space and apply target-language typography rules afterwards (e.g. French U+202F before `;:!?`) |
| U+202F NARROW NBSP, U+2007 FIGURE SPACE | literal | `fx_master_caps` | nonbreaking (fixed width) / figure space | same as NBSP (token in numbers) |
| U+2002 EN, U+2003 EM, U+2004–U+2006, U+2008 PUNCT, U+2009 THIN, U+200A HAIR, U+2001 FLUSH | literal | U+2002/3, U+2009/A in DC probe | fixed-width spaces (designer intent) | **token** (keep exact char and count) |
| U+2011 NON-BREAKING HYPHEN | literal | `fx_master_caps` | nonbreaking hyphen | pass through; accept `-` in output (low risk) |
| U+2029 PARAGRAPH SEPARATOR | literal (DC keeps it) | DC probe | not an InDesign character | pass through as a token |
| Control chars (U+0003, U+0007, U+0008…) | — | DC strips them | illegal in XML 1.0 | must never be written; validate output |
| Emoji / astral planes / skin-tone modifiers | literal | `fx_master_caps` (U+1F600, U+1F44D U+1F3FD) | — | no special handling; treat text as code points (lxml/Python str), never UTF-16 units |
| Private-use U+E000–U+F8FF | literal | DC leaks U+E107/U+E108 for variables | (DC bug artefact) | token; report as suspicious |
| Inline objects between Content siblings (Footnote, Table, anchored frames, Note, TextVariableInstance, PageReference, HyperlinkTextDestination) | elements | fixtures | fixed-position objects | slot boundary: tokens `<x n/>` like PIs, order fixed |
| Run wrappers (CSR, HyperlinkTextSource, XMLElement, Change, CrossReferenceSource) | elements | fixtures | formatting/link runs | paired tags `<gN>…</gN>` (prototype style); CrossReferenceSource content is a separate segment; `DeletedText` is excluded |

## 4. Fixtures

All fixtures are in `fixtures/`. They are reproducible with `PYTHONIOENCODING=utf-8 python fixtures/build_fixtures.py`, and the
details are in `fixtures/README.md`. All six reopen in DC with `document.inspect` and `file.openIdml`
with **0 errors and 0 warnings** (`fixtures/verify.json`).

| Fixture | Built by | Covers | DC reopen notes |
|---|---|---|---|
| `fx_table.idml` | DC | header + 3 body + footer rows; cell with 5 runs (bold run with a leading space, italic run); 2 paragraphs in one cell; TAB, U+2028, `&`, `<`, NBSP; empty CSRs | clean |
| `fx_footnote.idml` | DC | 2 footnotes; formatted runs; ACE 4 + TAB inside a bold run; text continues after the reference | clean |
| `fx_nested.idml` | DC + lxml | inline anchored TextFrame with its own story (bold run, TAB); host `Content` split around it | anchored frame **dropped silently** (story frameless/overset) |
| `fx_vars_links.idml` | DC + lxml | custom-text and last-page variables (designmap + instances); URL and mailto hyperlinks; ACE 18; cross-reference source and destination | variable instances and hyperlinks **dropped silently**; xref OK |
| `fx_master_caps.idml` | DC + lxml | master-spread running head with ACE 18 + ACE 19; AllCaps and SmallCaps paragraph styles (lower-case text); CSR AllCaps override; full special-character paragraph incl. emoji, `&amp;` literal, `<b>` literal | clean (master shows 1 item) |
| `fx_misc.idml` | DC + lxml | conditions (visible + hidden), index PageReference + Topic, TextPath (native); Change Deleted/Inserted, Note, XMLElement + XML parts, alt text (patched) | Note dropped, Changes flattened, XMLElement unwrapped (silently) |

### DesignCraft 0.6.0 quirks found

- **Import renumbers everything**: story, spread and master ids and file names. Use XML diffs on the
  translator's own output, not DC re-exports, to check the invariant.
- **Constructs DC can't author from the CLI**: frames on parent spreads (`frame.create` `spread` indexes
  document spreads only); anchoring text frames (`anchored.insert` → "text frames can't be anchored
  yet"). `type.bold/italic/allCaps` only act on a selection: with a collapsed caret they do nothing and
  print **no result line**, so results can't be paired 1:1 with commands. `text.select` offsets are
  UTF-8 bytes, and each inline object counts 3 bytes, so adding a marker shifts later offsets.
- **Internal object characters** (DC `story.get` text):
  - U+E000 page number → ACE 18
  - U+E001 section marker → ACE 19
  - U+E002, U+E003, U+E004 → `ParagraphBreakType` NextColumn, NextFrame, NextPage
  - U+E005 → ACE 7; U+E006 → ACE 8
  - U+E007, U+E008 → exported as ACE 18 (lossy)
  - U+E009 table anchor; U+E00A footnote; U+E00B text anchor; U+E00C cross-reference; U+E00D index marker; U+E00E anchored object
  - variables are U+E1xx
- **Export drops or mangles**: custom text variables (definitions dropped, instances leaked into `Content` as
  U+E107/U+E108), URL/email hyperlinks, notes, tracked changes (flattened, so deleted text comes back),
  XML tags and structure, alt text, endnotes (flattened to plain text with a literal number). Typed
  control chars U+0003/7/8 are stripped. U+2029 is kept literally.
- **Export keeps**: tables (header/footer counts), footnotes, conditions, index markers and topics,
  TextPath, cross-references (`CrossReferenceSource`, `HyperlinkTextDestination`, `Hyperlink`), ACE
  4/7/8/18/19, `Capitalization` on styles and CSRs, all special Unicode characters.
- **Import drops silently**: anchored TextFrames, `TextVariableInstance`, `HyperlinkTextSource`/`Hyperlink`,
  `Note`, `Change` (flattened), `XMLElement` (unwrapped), and every ACE value except 4 (footnotes only), 7, 8, 18 and 19.
- `AppliedLanguage="$ID/Turkish"` with no `<Language>` in the designmap is accepted (`type.selectionAttrs` →
  `"language":"Turkish"`) and written back unchanged; DC does not add a `Language` element.
- DC export pretty-prints empty CSRs (`<CharacterStyleRange …/>`) and puts several `Content` siblings in one CSR
  around inline objects.
- **Upshot**: DC is a good "does it open, does it fit" check for stories, tables, footnotes, master text,
  conditions and xrefs. It **can't** check variables, hyperlinks, notes, changes, XML or anchored text
  frames.

## 5. Open risks

1. **Attribute-held visible text is out of scope under the invariant**: custom variable `Contents`,
   xref-format `CustomText`, index topics, TOC `Title`, `Section@Marker/SectionPrefix`, numbering
   expressions, alt text and bookmarks. v1 should at least **report** them. Each needs an explicit
   invariant extension to translate.
2. **Regenerated text**: cross-reference sources, TOC and index stories, and variable `ResultText` are
   caches. InDesign may overwrite them, with the translation or with English, on update.
   Whether `ResultText` is refreshed on open is *unverified*.
3. **AppliedLanguage for languages missing from designmap `<Language>` list**: DC is fine with it, but
   InDesign's behaviour (hyphenation and spelling dictionary binding) is *unverified*. We may need to
   add a `<Language>` element, which is outside the current invariant.
4. **Fixed object positions limit reordering**: footnote references, variables, index markers, notes,
   anchors and CSR/hyperlink/condition boundaries are fixed points. Languages with different word order
   (DE verb-final, TR SOV) will sometimes need text moved across them. Expect awkward output or tag
   failures. Mitigation: allow empty slots and move text between adjacent slots of the same run when
   formatting is identical.
5. **Segmentation on `<Br/>`** splits multi-paragraph titles (sample u18 `The Quiet` / `Art of Layout`)
   into separately translated fragments. Consider passing neighbouring paragraphs as context, or joining
   short consecutive paragraphs that share a style.
6. **Case**: under an AllCaps style, source text may be in any case (sample shows both). Literal-caps
   source (`SWATCH`, `THE SPRING ISSUE`) needs locale-aware upper-casing of the target (Turkish İ/ı).
7. **Tracked changes**: translating `DeletedText` wastes effort and corrupts segment context.
   Recommend a hard warning or refusal when `Change` elements or `TrackChanges="true"` are present.
8. **Hidden conditions**: hidden text is translated but invisible, so fit checks must ignore it, and
   overlapping conditions can produce many tiny runs.
9. **Things we can't verify without InDesign**: the hand-written shapes in `fx_vars_links`/`fx_misc`
   (TextVariable/Instance, Hyperlink*, Change, Note, XMLElement/BackingStory, ObjectExportOption),
   endnote markup, InCopy links, and the meaning of ACE values other than 4/7/8/18/19. The translator must
   treat unknown elements and PIs generically (pass through, act as boundaries) rather than whitelist
   known ones.
10. **Unreachable text**: outlined type and text inside placed images, PDFs or EPS. The best we can do is report
    `Image/PDF/EPS` links and compound-path-heavy groups.
11. **Prototype gaps vs. this inventory** (`demo_translate.py`):
    - Its `NESTED` set lacks `Change` and `CrossReferenceSource`, so deleted text and generated xref
      text get merged into the sentence.
    - `Note` is translated, though skip is suggested.
    - `<Contents>` vs `<Content>` is fine (it matches the exact tag).
    - It only walks `Stories/*.xml`. That covers master and TextPath stories, but not attribute-held text.
