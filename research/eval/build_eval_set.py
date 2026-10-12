"""Builds research/eval/eval_set.jsonl (R3 evaluation set for Hy-MT2 prompt templates).

Real segments come from idml-demo/sample_en.idml (text copied verbatim, reading order from the
page layout); synthetic ones target tags, placeholders, numbers, DNT, casing and typographic terms.

Reference expectations ("ref") per language:
  any_of        at least one of these substrings must occur (case-insensitive, locale-aware lowering)
  must_not      none of these substrings may occur
  must_not_cs   none of these substrings may occur (case-sensitive; e.g. the noun "Stille" vs adjective "stille")
  all_of        every one of these substrings must occur
Glossary entries are attached automatically from GLOSSARY when the source term occurs in the source.

usage: python research/eval/build_eval_set.py
"""
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent

SYNOPSIS = ("Spring issue of a design magazine, 'Quarterly'; feature article about layout grids "
            "and typography.")

# Global project glossary (source term -> target term). Applied only where the term occurs.
GLOSSARY = {
  "tr": {
    "Feature": "Dosya", "pull quote": "öne çıkan alıntı", "pull quotes": "öne çıkan alıntılar",
    "baseline grid": "taban çizgisi ızgarası", "grid": "ızgara", "kicker": "üst başlık",
    "kickers": "üst başlıklar", "rules": "çizgiler", "swatch": "renk örneği", "swatches": "renk örnekleri",
    "build": "karışım", "Quarterly": "Üç Aylık", "leading": "satır aralığı", "kerning": "harf aralığı",
    "bleed": "taşma payı", "gutter": "sütun arası boşluk", "widow": "dul satır", "orphan": "yetim satır",
    "heads": "başlıklar", "paragraph composer": "paragraf dizgi motoru", "Coming next": "Gelecek sayıda",
  },
  "de": {
    "Feature": "Reportage", "pull quote": "Pull-Quote", "pull quotes": "Pull-Quotes",
    "baseline grid": "Grundlinienraster", "grid": "Raster", "kicker": "Dachzeile", "kickers": "Dachzeilen",
    "rules": "Linien", "swatch": "Farbfeld", "swatches": "Farbfelder", "build": "Farbaufbau",
    "Quarterly": "Vierteljährlich", "leading": "Zeilenabstand", "kerning": "Unterschneidung",
    "bleed": "Anschnitt", "gutter": "Spaltenabstand", "widow": "Hurenkind", "orphan": "Schusterjunge",
    "heads": "Überschriften", "paragraph composer": "Absatzsetzer", "Coming next": "Demnächst",
  },
}
DNT_GLOBAL = ["DesignCraft", "InDesign", "Pantone 186 C"]

# ── Real segments in reading order (page 1 → 4); (role, style, source[, ref]) ──
BODY = [
  "Every page begins as an empty field of possibility. The grid arrives first: margins that frame the reading area, columns that set the rhythm, and a baseline grid that keeps every line in step from one column to the next. Good layout is quiet. It lets the reader move through a story without noticing the machinery that carries them.",
  "Typography does the heavy lifting. A paragraph composer weighs every possible line break at once, trading a slightly loose line here for a much better one three lines later. The result is an even texture of type, free of rivers and ragged gaps, where hyphens appear only when they truly help.",
  "Images give a spread its pulse. A strong photograph bleeds off the edge of the page, while smaller pictures sit inside the grid and let the text wrap around them. Captions, pull quotes and running heads add layers that a careful reader can explore at their own pace.",
  "Color holds it all together. A restrained palette of two or three swatches, applied consistently to headlines, rules and backgrounds, gives a publication its voice. Spot inks, tints and gradients are all just named swatches, so a single change ripples through every page.",
  "Behind the scenes, styles are the secret to working fast. Paragraph styles define the voice of each element, character styles pick out emphasis, and object styles keep frames consistent. Change a style once and the whole document follows, from the cover to the very last page.",
  "And when the layout is done, the document must travel: to a printer as a press-ready PDF with bleed and crop marks, to a colleague as an open interchange file, or to a screen as a crisp image. A layout tool earns its keep by making every one of those journeys effortless.",
]

R = {}  # refs keyed by id: {"tr": {...}, "de": {...}}

REAL = [
  # id, role, style, source
  ("r_folio_spring", "folio", "Folio", "SPRING ISSUE"),
  ("r_kicker_cover", "kicker", "Kicker", "THE SPRING ISSUE  ·  NO. 01"),
  ("r_cover_title_1", "headline", "Cover Title", "The Quiet"),
  ("r_cover_title_2", "headline", "Cover Title", "Art of Layout"),
  ("r_cover_deck", "body", "Cover Deck", "Grids, type and color: how great pages are made — and the tools that make them."),
  ("r_kicker_feature", "kicker", "Kicker", "Feature  ·  Design"),
  ("r_headline_grid", "headline", "Headline", "Notes on the Grid"),
  ("r_deck", "body", "Deck", "A good layout is invisible. Here is what is going on underneath the page — from the baseline grid to the paragraph composer."),
  ("r_caption_hills", "caption", "Caption", "Evening light over layered hills — generated entirely in code for this sample."),
  ("r_body_1", "body", "Body", BODY[1]),
  ("r_body_2", "body", "Body", BODY[2]),
  ("r_body_3", "body", "Body", BODY[3]),
  ("r_body_4", "body", "Body", BODY[4]),
  ("r_body_5", "body", "Body", BODY[5]),
  ("r_footnote", "footnote", "Footnote", "Every image, swatch and paragraph in this sample is generated in code — no stock assets."),
  ("r_pullquote", "pullquote", "Pull Quote", "“The best layouts disappear. What remains is the story.”"),
  ("r_kicker_next", "kicker", "Kicker", "Coming next"),
  ("r_cover_title_color", "headline", "Cover Title", "Color, Ink & Paper"),
  ("r_caption_inkplum", "caption", "Caption", "Ink Plum"),
  ("r_caption_sunset", "caption", "Caption", "Sunset"),
  ("r_caption_cmyk", "caption", "Caption", "C=100 M=0 Y=0 K=0"),
  ("r_caption_paperwarm", "caption", "Caption", "Paper Warm"),
  ("r_th_swatch", "table-header", "Table Head", "SWATCH"),
  ("r_th_build", "table-header", "Table Head", "BUILD"),
  ("r_th_usedfor", "table-header", "Table Head", "USED FOR"),
  ("r_td_inkplum", "table-cell", "Table Body", "Ink Plum"),
  ("r_td_build1", "table-cell", "Table Body", "C62 M95 Y30 K25"),
  ("r_td_bg_heads", "table-cell", "Table Body", "Backgrounds, heads"),
  ("r_td_build2", "table-cell", "Table Body", "M62 Y78"),
  ("r_td_kickers_rules", "table-cell", "Table Body", "Kickers, rules"),
  ("r_td_cyan", "table-cell", "Table Body", "Cyan"),
  ("r_td_charts", "table-cell", "Table Body", "Charts, links"),
  ("r_td_build4", "table-cell", "Table Body", "M3 Y8"),
  ("r_td_pullquotes", "table-cell", "Table Body", "Pull quotes"),
  ("r_folio_quarterly", "folio", "Folio", "QUARTERLY"),
]

R["r_cover_title_1"] = {"tr": {"any_of": ["sessiz", "sakin"], "must_not": ["sessizlik"]}, "de": {"any_of": ["still", "leise", "ruhig"], "must_not_cs": ["Stille"]}}
PAIR_REF = {"tr": {"any_of": ["sessiz", "sakin"], "all_of": ["sanat"], "must_not": ["sessizlik"]},
            "de": {"all_of": ["kunst"], "any_of": ["still", "leise", "ruhig", "sanft"], "must_not_cs": ["Stille"]}}
R["r_cover_title_2"] = {"tr": {"any_of": ["sanat"], "must_not": ["düzen sanatı"]}, "de": {"any_of": ["kunst"]}}
R["r_kicker_feature"] = {"tr": {"any_of": ["dosya", "kapak konusu", "röportaj", "inceleme", "makale", "öne çıkan"], "must_not": ["özellik"]},
                         "de": {"any_of": ["reportage", "feature", "titelthema", "schwerpunkt", "bericht"], "must_not": ["merkmal", "funktion"]}}
R["r_headline_grid"] = {"tr": {"any_of": ["ızgara"], "must_not": ["izgile", "iletken", "şebeke"]},
                        "de": {"any_of": ["raster"], "must_not": ["gitter"]}}
R["r_kicker_next"] = {"tr": {"any_of": ["gelecek sayı", "sıradaki", "yakında", "sonraki sayı", "gelecek"], "must_not": ["bir sonraki olarak", "sırada geliyor"]},
                      "de": {"any_of": ["demnächst", "nächste ausgabe", "als nächstes", "vorschau", "in kürze"]}}
R["r_th_swatch"] = {"tr": {"any_of": ["renk", "örnek", "numune"], "must_not": ["swatch"]},
                    "de": {"any_of": ["farbfeld", "farbmuster", "farbe", "muster"], "must_not": ["swatch"]}}
R["r_th_build"] = {"tr": {"any_of": ["karışım", "bileşim", "formül", "değer", "yapı", "oluşum"], "must_not": ["inşa"]},
                   "de": {"any_of": ["aufbau", "zusammensetzung", "mischung", "farbwert", "werte", "rezept"], "must_not": ["bauen"]}}
R["r_th_usedfor"] = {"tr": {"any_of": ["kullanım", "kullanıl"]}, "de": {"any_of": ["verwendung", "einsatz", "verwendet", "eingesetzt"]}}
R["r_td_bg_heads"] = {"tr": {"all_of": ["arka plan", "başlık"]}, "de": {"any_of": ["überschrift", "headline", "titel", "kopfzeile"], "must_not": ["köpfe"]}}
R["r_td_kickers_rules"] = {"tr": {"any_of": ["çizgi"], "must_not": ["kurallar", "kickers"]},
                           "de": {"any_of": ["linie"], "must_not": ["regeln", "vorschriften"]}}
R["r_td_pullquotes"] = {"tr": {"any_of": ["alıntı"], "must_not": ["tırnak işaret", "çekin"]},
                        "de": {"any_of": ["pull-quote", "pullquote", "zitat"], "must_not": ["ziehen"]}}
R["r_folio_quarterly"] = {"tr": {"any_of": ["üç aylık", "quarterly"], "must_not": ["çeyrek"]},
                          "de": {"any_of": ["vierteljähr", "quartal", "quarterly"]}}
R["r_folio_spring"] = {"tr": {"any_of": ["ilkbahar", "bahar"]}, "de": {"any_of": ["frühling", "frühjahr"]}}
R["r_kicker_cover"] = {"tr": {"any_of": ["sayı"], "all_of": ["01"]}, "de": {"any_of": ["ausgabe", "heft"], "all_of": ["01"]}}
R["r_cover_title_color"] = {"tr": {"all_of": ["renk", "mürekkep", "kağıt"]}, "de": {"all_of": ["farbe", "papier"]}}
R["r_pullquote"] = {"tr": {"any_of": ["hikaye", "öykü"]}, "de": {"any_of": ["geschichte"]}}
R["r_td_charts"] = {"tr": {"any_of": ["grafik", "çizelge"]}, "de": {"any_of": ["diagramm", "grafik"]}}

# Items whose literal identity in the output is acceptable (code-like / brand-like).
IDENTITY_OK = {"r_caption_cmyk", "r_td_build1", "r_td_build2", "r_td_build4"}

# ── Synthetic items ──
SYN = []
def syn(i, cat, role, style, src, ref=None, dnt=None, **kw):
  SYN.append(dict(id=i, category=cat, role=role, style=style, source=src, ref=ref or {}, dnt=dnt, **kw))

# tagged runs (Structured Data 1)
syn("t_two_runs", "tagged", "body", "Body",
    "<g0>Every page begins as</g0><g1> an empty field of possibility. The grid arrives first: margins that frame the reading area, columns that set the rhythm, and a baseline grid that keeps every line in step from one column to the next. Good layout is quiet. It lets the reader move through a story without noticing the machinery that carries them.</g1>", real=True)
syn("t_mid_word", "tagged", "body", "Body",
    "<g0>Set the text in </g0><g1>italic</g1><g2> only where the author wants real emphasis.</g2>",
    ref={"tr": {"any_of": ["italik"]}, "de": {"any_of": ["kursiv"]}})
syn("t_bold_term", "tagged", "body", "Body",
    "<g0>A </g0><g1>baseline grid</g1><g2> keeps every line in step across columns.</g2>",
    ref={"tr": {"any_of": ["ızgara"]}, "de": {"any_of": ["grundlinienraster"]}})
syn("t_four", "tagged", "body", "Body",
    "<g0>Use </g0><g1>Paragraph Styles</g1><g2> for structure and </g2><g3>Character Styles</g3> for emphasis.",
    ref={"tr": {"any_of": ["paragraf stil"]}, "de": {"any_of": ["absatzformat", "absatzstil"]}})
syn("t_nested", "tagged", "body", "Body",
    "<g0>Read the <g1>full story</g1> on page 12.</g0>", ref={"tr": {"all_of": ["12"]}, "de": {"all_of": ["12"]}})
syn("t_link", "tagged", "caption", "Caption",
    "<g0>Photo: </g0><g1>Anna Berg</g1><g2> for DesignCraft</g2>", dnt=["DesignCraft", "Anna Berg"])
syn("t_short_head", "tagged", "headline", "Headline",
    "<g0>The </g0><g1>Grid</g1><g2> Issue</g2>", ref={"tr": {"any_of": ["ızgara"]}, "de": {"any_of": ["raster"]}})
syn("t_cover_pair", "tagged-multipara", "headline", "Cover Title",
    "<g0>The Quiet</g0><g1>Art of Layout</g1>", ref=PAIR_REF)

# placeholders: same base sentences, four marker formats
PH_BASE = [
  ("ph_tab", "Name{P1}Value{P2}Unit", "table-cell", "Table Body", {}),
  ("ph_br", "The Quiet{P1}Art of Layout", "headline", "Cover Title", PAIR_REF),
  ("ph_url", "Download the templates at {P1} and send feedback to {P2} before Friday.", "body", "Body",
   {"tr": {"any_of": ["cuma"]}, "de": {"any_of": ["freitag"]}}),
  ("ph_unit", "Set the body text at {P1} with {P2} leading for comfortable reading.", "body", "Body",
   {"tr": {"any_of": ["satır aralığı"]}, "de": {"any_of": ["zeilenabstand", "durchschuss"]}}),
  ("ph_mid", "Press {P1} to place the image, then drag to size it.", "body", "Body", {}),
]
PH_FORMATS = {"uni": lambda n: f"⟦{n}⟧", "brace": lambda n: f"{{{n}}}", "xml": lambda n: f"<x{n}/>", "dbl": lambda n: f"[[{n}]]"}
for pid, tpl, role, style, ref in PH_BASE:
  for fname, fn in PH_FORMATS.items():
    src = tpl.replace("{P1}", fn(1)).replace("{P2}", fn(2))
    cat = "multipara" if pid == "ph_br" else "placeholder"
    syn(f"{pid}_{fname}", cat, role, style, src, ref=ref, ph_format=fname)
syn("nl_br", "multipara", "headline", "Cover Title", "The Quiet\nArt of Layout",
    ref=PAIR_REF)

# numbers / dates / units
syn("n_pt", "numbers", "body", "Body", "Set captions in 8 pt type on a 12 pt baseline grid.",
    ref={"tr": {"all_of": ["8 pt", "12 pt"]}, "de": {"all_of": ["8 pt", "12 pt"]}})
syn("n_mm", "numbers", "body", "Body", "Add 3.5 mm of bleed on all four sides of the 210 × 297 mm page.",
    ref={"tr": {"all_of": ["3,5 mm", "210", "297"]}, "de": {"all_of": ["3,5 mm", "210", "297"]}})
syn("n_thousand", "numbers", "body", "Body", "The first print run of 1,200 copies sold out in 2026.",
    ref={"tr": {"all_of": ["1.200", "2026"]}, "de": {"all_of": ["1.200", "2026"]}})
syn("n_pct", "numbers", "caption", "Caption", "Tint at 40% for backgrounds, 100% for rules.",
    ref={"tr": {"any_of": ["%40"]}, "de": {"any_of": ["40 %", "40%", "40 Prozent"]}})
syn("n_date", "numbers", "folio", "Folio", "Spring 2026 · No. 01 · March 15, 2026",
    ref={"tr": {"all_of": ["2026", "15"]}, "de": {"all_of": ["2026", "15"]}})
syn("n_range", "numbers", "body", "Body", "Line length should stay between 45 and 75 characters, about 10–12 words.",
    ref={"tr": {"all_of": ["45", "75"]}, "de": {"all_of": ["45", "75"]}})

# DNT terms
syn("d_brand", "dnt", "body", "Body", "DesignCraft opens InDesign IDML files and exports press-ready PDF.",
    dnt=["DesignCraft", "InDesign", "IDML", "PDF"])
syn("d_pantone", "dnt", "caption", "Caption", "Headlines use Pantone 186 C; body text stays in black.",
    dnt=["Pantone 186 C"])
syn("d_short", "dnt", "kicker", "Kicker", "Made with DesignCraft", dnt=["DesignCraft"])
syn("d_quarterly", "dnt", "body", "Body", "Quarterly is published four times a year by the DesignCraft studio.",
    dnt=["Quarterly", "DesignCraft"])

# ALL CAPS
syn("c_feature", "caps", "kicker", "Kicker", "FEATURE",
    ref={"tr": {"any_of": ["dosya", "kapak konusu", "röportaj", "inceleme", "makale"], "must_not": ["özellik"]},
         "de": {"any_of": ["reportage", "feature", "titelthema", "schwerpunkt", "bericht"], "must_not": ["merkmal", "funktion"]}})
syn("c_feature_design", "caps", "kicker", "Kicker", "FEATURE  ·  DESIGN", ref=R["r_kicker_feature"])
syn("c_coming_next", "caps", "kicker", "Kicker", "COMING NEXT", ref=R["r_kicker_next"])
syn("c_inside", "caps", "kicker", "Kicker", "INSIDE THIS ISSUE",
    ref={"tr": {"any_of": ["sayı"]}, "de": {"any_of": ["ausgabe", "heft"]}})
syn("c_sentence", "caps", "headline", "Headline", "WHY THE GRID STILL MATTERS",
    ref={"tr": {"any_of": ["ızgara"]}, "de": {"any_of": ["raster"]}})
syn("c_folio_2", "caps", "folio", "Folio", "2  ·  QUARTERLY", ref=R["r_folio_quarterly"])
syn("c_used_for", "caps", "table-header", "Table Head", "USED FOR", ref=R["r_th_usedfor"])
syn("c_typo", "caps", "kicker", "Kicker", "TYPOGRAPHY", ref={"tr": {"any_of": ["tipografi"]}, "de": {"any_of": ["typografie"]}})

# Title Case
syn("tc_head", "titlecase", "headline", "Headline", "The Art of the Baseline Grid",
    ref={"tr": {"any_of": ["ızgara"]}, "de": {"any_of": ["grundlinienraster", "raster"]}})
syn("tc_deck", "titlecase", "headline", "Headline", "How Great Pages Are Made", ref={"tr": {"any_of": ["sayfa"]}, "de": {"any_of": ["seiten"]}})
syn("tc_section", "titlecase", "kicker", "Kicker", "Letters from Our Readers", ref={"tr": {"any_of": ["okur"]}, "de": {"any_of": ["leser"]}})

# typographic terms
syn("y_kerning", "typo", "body", "Body", "Tight kerning between capital letters makes headlines look heavier.",
    ref={"tr": {"any_of": ["harf aralı", "kerning", "karakter aralı", "harf arası"]}, "de": {"any_of": ["unterschneid", "kerning"]}})
syn("y_leading", "typo", "body", "Body", "Generous leading improves readability in long columns.",
    ref={"tr": {"any_of": ["satır aralı"]}, "de": {"any_of": ["zeilenabstand", "durchschuss"]}})
syn("y_gutter", "typo", "body", "Body", "Keep the gutter wide enough so the columns do not touch.",
    ref={"tr": {"any_of": ["sütun ara", "oluk", "boşluk"]}, "de": {"any_of": ["spaltenabstand", "zwischenschlag", "steg"]}})
syn("y_bleed", "typo", "body", "Body", "Images that touch the edge must extend into the bleed.",
    ref={"tr": {"any_of": ["taşma pay", "kesim pay", "bleed"]}, "de": {"any_of": ["anschnitt", "beschnitt"]}})
syn("y_widow", "typo", "body", "Body", "Fix every widow and orphan before the pages go to print.",
    ref={"tr": {"any_of": ["dul", "yetim", "öksüz"]}, "de": {"any_of": ["hurenkind", "schusterjung"]}})
syn("y_pullquote", "typo", "body", "Body", "A pull quote breaks up long text and draws the eye into the story.",
    ref={"tr": {"any_of": ["alıntı"], "must_not": ["çekin", "tırnak işaret"]}, "de": {"any_of": ["zitat", "pull-quote", "pullquote"], "must_not": ["ziehen"]}})
syn("y_baseline_short", "typo", "table-cell", "Table Body", "Baseline grid", ref={"tr": {"any_of": ["ızgara"]}, "de": {"any_of": ["grundlinienraster"]}})
syn("y_leading_short", "typo", "table-cell", "Table Body", "Leading", ref={"tr": {"any_of": ["satır aralı"]}, "de": {"any_of": ["zeilenabstand", "durchschuss"]}})


def glossary_for(src, lang):
  out = []
  plain = re.sub(r"<[^>]+>", " ", src)
  for s, t in GLOSSARY[lang].items():
    if re.search(r"(?<![\w-])" + re.escape(s) + r"(?![\w-])", plain, re.I):
      out.append([s, t])
  # prefer the longest match; drop entries contained in a longer matched term ("grid" inside "baseline grid")
  out.sort(key=lambda e: -len(e[0]))
  keep = []
  for s, t in out:
    if not any(s.lower() in k[0].lower() and s.lower() != k[0].lower() and
               not re.search(r"(?<![\w-])" + re.escape(s) + r"(?![\w-])",
                             re.sub(re.escape(k[0]), "", plain, flags=re.I), re.I) for k in keep):
      keep.append([s, t])
  return keep


def main():
  items = []
  order = [r[0] for r in REAL]
  texts = {r[0]: r[3] for r in REAL}
  # reading-order neighbours for real items (skip the table cells' structure: neighbours = same row)
  for k, (iid, role, style, src) in enumerate(REAL):
    prev = texts[order[k - 1]] if k > 0 else ""
    nxt = texts[order[k + 1]] if k + 1 < len(order) else ""
    items.append(dict(id=iid, category="real", role=role, style=style, source=src, prev=prev, next=nxt,
                      ref=R.get(iid, {}), identity_ok=iid in IDENTITY_OK))
  for it in SYN:
    it.setdefault("prev", "")
    it.setdefault("next", "")
    items.append(it)
  for it in items:
    dnt = it.get("dnt")
    if dnt is None:
      dnt = [d for d in DNT_GLOBAL if d in it["source"]]
    it["dnt"] = dnt
    it["glossary"] = {l: [g for g in glossary_for(it["source"], l) if g[0].lower() not in {d.lower() for d in dnt}]
                      for l in ("tr", "de")}
    src_plain = re.sub(r"<[^>]+>|⟦\d+⟧|\{\d+\}|\[\[\d+\]\]", "", it["source"])
    letters = [c for c in src_plain if c.isalpha()]
    it["case"] = ("upper" if letters and all(c.isupper() for c in letters) and len(letters) > 1 else None)
    it.setdefault("identity_ok", False)
    it.setdefault("real", it["category"] == "real")
    it["short"] = len(re.sub(r"<[^>]+>", "", it["source"]).split()) <= 6
  # documentary synopsis applies to all
  path = HERE / "eval_set.jsonl"
  with open(path, "w", encoding="utf-8") as f:
    for it in items:
      f.write(json.dumps(it, ensure_ascii=False) + "\n")
  print(f"{len(items)} items -> {path}")


if __name__ == "__main__":
  main()
