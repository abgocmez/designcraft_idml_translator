# idml-translate test fixtures

Small synthetic IDML packages that exercise the places translatable text can live. They are built by
`build_fixtures.py` (run from the project root, takes ~10 s):

```
PYTHONIOENCODING=utf-8 python fixtures/build_fixtures.py            # all fixtures
PYTHONIOENCODING=utf-8 python fixtures/build_fixtures.py --only fx_table --verbose
```

How they are built:

1. **DesignCraft authors the base.** Each fixture is one `designcraft-cli run` session (`file.new` →
   `frame.create` / `table.insert` / `footnote.insert` / `text.insert` / ... → `file.exportIdml`).
2. **lxml patches what DesignCraft 0.6.0 can't author or export** (`patch_*` functions). The patch
   rewrites only the entries it touches. Entry order, the stored `mimetype` first entry and each entry's
   compression type stay the same, and every other entry is copied byte for byte.
3. **Verification.** Every fixture is re-opened with `designcraft-cli run --in F --cmd document.inspect`
   and with `file.openIdml`. The results go to `verify.json`. All six open with **no errors and no
   warnings**. DesignCraft silently drops some of the patched constructs on import (see below), so
   use DesignCraft to check that a fixture opens, not that the construct is right. Check
   translator output for those constructs with an XML diff.

Two clean builds produce byte-identical zip entries. The zip containers differ only in timestamps.

| Fixture | Built by | Exercises |
|---|---|---|
| `fx_table.idml` | DesignCraft only | Table inside a story paragraph: 1 header row, 3 body rows and 1 footer row (`HeaderRowCount=1 BodyRowCount=3 FooterRowCount=1`), 3 columns. One cell has 5 CSRs (plain / **bold " roasted"** with a leading space inside the bold run / plain / *italic "fair trade"* / plain). One cell holds two paragraphs (`<Br/>` inside the cell), a TAB and a U+2028 forced line break. Also `&`, `<or>`, `€`+NBSP, em dash, empty trailing paragraph CSR, and text before and after the table. |
| `fx_footnote.idml` | DesignCraft only | Two footnotes (`CSR Position="Superscript" > Footnote > PSR > CSR > Content`). Footnote 1 has 4 formatted runs, and the `<?ACE 4?>` number marker plus separator TAB sit **inside the bold run**. Footnote 2 is plain with a TAB and an NBSP. The body sentence continues after each reference. |
| `fx_nested.idml` | DesignCraft + `patch_nested` | An inline **anchored TextFrame** inside a CSR (`Content` / `TextFrame ParentStory=u9` + `AnchoredObjectSetting` / `Content`). Its own story `Story_u9.xml` has a bold run and a TAB. DesignCraft refuses to anchor text frames, so an anchored Rectangle was swapped for the TextFrame. |
| `fx_vars_links.idml` | DesignCraft + `patch_vars_links` | `TextVariableInstance` (custom text "Product" = "Widget Pro", and Last Page Number) between `Content` siblings. `designmap` `TextVariable` + `CustomTextVariablePreference Contents`. URL and mailto `HyperlinkTextSource` wrapping CSRs, with `Hyperlink` + `HyperlinkURLDestination` in the designmap. `<?ACE 18?>` page number. A cross-reference (`CrossReferenceSource` holding generated text, and a `HyperlinkTextDestination` on the target paragraph), exported natively by DesignCraft. |
| `fx_master_caps.idml` | DesignCraft + `patch_master_caps` | A running-head story placed on the **master spread** (`Running head · Page <?ACE 18?> · Section <?ACE 19?>`). Paragraph styles with `Capitalization="AllCaps"` and `"SmallCaps"`, whose text is stored in lower case. A CSR-level `Capitalization="AllCaps"` override. A "specials" paragraph: TAB, U+2028, U+00A0, U+202F, U+2007, U+2002, U+2003, U+00AD, U+2011, U+200B, the literal text `&amp;` (stored as `&amp;amp;`), `<b>not a tag</b>`, `AT&T`, curly quotes, emoji with a skin-tone modifier (U+1F44D U+1F3FD), and accented Latin. |
| `fx_misc.idml` | DesignCraft + `patch_misc` | Conditional text (`AppliedConditions` visible `PrintOnly` and hidden `Hidden`), an index marker (`PageReference` between `Content` siblings, `Index/Topic` in the designmap) and text on a path (`TextPath ParentStory`). These three are native DesignCraft exports. Patched in: tracked changes (`Change ChangeType="DeletedText"` and `"InsertedText"` wrapping CSRs, Story `TrackChanges="true"`), a `Note` inside a CSR, an `XMLElement` wrapping a `Content` (+ `XML/Tags.xml` and `XML/BackingStory.xml`), and `ObjectExportOption CustomAltText/CustomActualText` on a graphic frame. |

## What DesignCraft does with the patched constructs on import

Nothing below produces an error or a warning; it happens silently.

- `fx_nested`: the anchored TextFrame is dropped. Its story is reported with `frames: []` and `overset: true`.
- `fx_vars_links`: the `TextVariableInstance`s are dropped (their text disappears), and the custom variable
  is not listed. `HyperlinkTextSource`/`Hyperlink` are dropped: the text stays but `hyperlink.list` is empty.
  The cross-reference and the text anchor import fine.
- `fx_misc`: the `Note` is dropped. The `Change`s are flattened, so both the deleted and the inserted text
  show as plain text and `changes.list` is empty. The `XMLElement` is unwrapped (its text stays) and
  `xml.structure` is empty. Conditions, the index marker and the text path import fine.

## Shapes taken from spec knowledge, not checked against InDesign

The `TextVariable`/`TextVariableInstance`, `Hyperlink*`, `Change`, `Note`, `XMLElement`/BackingStory
and `ObjectExportOption` markup was written by hand from IDML spec knowledge. InDesign was not
available, so it has not been confirmed that InDesign opens these exact shapes. Treat these fixtures
as tests of the translator's XML handling, not as proof that the files open in InDesign.
