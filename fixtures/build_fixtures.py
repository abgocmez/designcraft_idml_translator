"""Build the synthetic IDML test fixtures for idml-translate.

usage: python fixtures/build_fixtures.py [--verbose] [--only NAME]

Each fixture is authored with the DesignCraft headless CLI (designcraft-cli run ... file.exportIdml),
then, where DesignCraft cannot author a construct, patched with lxml (see `patch_*`). Patches
rewrite only the touched zip entries; entry order, the stored `mimetype` first entry and each
entry's compression type are preserved, all other entries are copied byte-for-byte.

Finally every fixture is re-opened with `designcraft-cli run --in F --cmd document.inspect`
and the result (warnings, stories, overset) is written to fixtures/verify.json.

Requirements: DesignCraft 0.6.0 CLI, Python 3 with lxml. No network.
"""
import copy
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

from lxml import etree

DC = r"C:\Program Files\DesignCraft\designcraft-cli.exe"
HERE = Path(__file__).resolve().parent
VERBOSE = "--verbose" in sys.argv
ONLY = sys.argv[sys.argv.index("--only") + 1] if "--only" in sys.argv else None


def fwd(p):
  return str(p).replace("\\", "/")


def run_dc(cmds, in_file=None):
  """Run one designcraft-cli session. cmds: list of (id, params|None). Returns parsed results."""
  argv = [DC, "run"]
  if in_file:
    argv += ["--in", fwd(in_file)]
  for cid, params in cmds:
    argv += ["--cmd", cid if params is None else f"{cid}={json.dumps(params, ensure_ascii=True)}"]
  p = subprocess.run(argv, capture_output=True, encoding="utf-8", errors="replace")
  # NB: not str.splitlines() -- it also splits on U+2028/U+2029/U+0085 inside JSON strings.
  out = [l for l in p.stdout.split("\n") if l.strip()]
  results = []
  for line in out:
    try:
      results.append(json.loads(line))
    except json.JSONDecodeError:
      results.append({"_raw": line})
  if VERBOSE:
    for (cid, params), r in zip(cmds, results):
      print(f"  {cid} {json.dumps(params, ensure_ascii=True)[:90] if params else ''}\n    -> {json.dumps(r, ensure_ascii=True)[:300]}")
  if p.returncode != 0 or p.stderr.strip():
    raise RuntimeError(f"designcraft-cli failed ({p.returncode}): {p.stderr.strip()}\nlast results: {results[-3:]}")
  if not results or "bytes" not in results[-1] and cmds[-1][0] == "file.exportIdml":
    raise RuntimeError(f"export did not report bytes: {results[-3:]}")
  return results


# Special characters every fixture paragraph of "specials" exercises.
# (\ue000 is DesignCraft's internal current-page-number marker -> exported as <?ACE 18?>.)
SPECIALS = ("Tab:\there | forced\u2028break | nbsp\u00a0space | narrow\u202fnbsp | figure\u2007space"
            " | en\u2002em\u2003spaces | soft\u00adhyphen | nb\u2011hyphen | zwsp\u200bhere"
            " | Fish &amp; Chips <b>not a tag</b> & AT&T | \u201cquotes\u201d \u2018single\u2019 \u2014 dash"
            " | emoji \U0001F600\U0001F44D\U0001F3FD | caf\u00e9 na\u00efve \u00a9 \u20ac 5")


WORD_LEFT = ("text.move", {"dir": "left", "word": True})


def new_doc(pages=1):
  return [("file.new", {"preset": "Letter", "pages": pages, "facingPages": False})]


def export(path):
  return [("file.exportIdml", {"path": fwd(path)})]


# ---------------------------------------------------------------- fixtures (DesignCraft part)

def fx_table(out):
  cmds = new_doc() + [
    ("frame.create", {"rect": [72, 72, 540, 500], "content": "text", "text": "Price list (table follows):\n\nText after the table.", "caret": True}),
    ("text.move", {"dir": "storyStart"}),
    ("text.move", {"dir": "down"}),
    ("text.move", {"dir": "lineStart"}),
    ("table.insert", {"rows": 3, "cols": 3, "headerRows": 1, "footerRows": 1}),
    # header row
    ("text.insert", {"text": "Item"}), ("table.nextCell", {}),
    ("text.insert", {"text": "Price & Tax"}), ("table.nextCell", {}),
    ("text.insert", {"text": "Notes"}), ("table.nextCell", {}),
    # body row 1: a cell with several formatted runs
    ("text.insert", {"text": "Coffee"}), ("table.nextCell", {}),
    ("text.insert", {"text": "\u20ac\u00a03.50"}), ("table.nextCell", {}),
    # type.bold/italic only act on a selection (no caret "typing style"), so type the whole cell
    # first, then select words with text.move(word, extend) and style them. Positions are bytes.
    ("text.insert", {"text": "Freshly roasted beans, fair trade certified."}),
    *[WORD_LEFT] * 3,                                                                    # -> start of "fair"
    ("text.move", {"dir": "right", "word": True, "extend": True}),
    ("text.move", {"dir": "right", "word": True, "extend": True}), ("type.italic", {}),  # "fair trade"
    *[WORD_LEFT] * 6,                                                                    # -> 0
    ("text.move", {"dir": "right", "word": True}),                                       # -> 7
    ("text.move", {"dir": "right", "word": True, "extend": True}), ("type.bold", {}),    # " roasted" (leading space bold)
    ("table.nextCell", {}),
    # body row 2: two paragraphs in one cell, tab, forced line break
    ("text.insert", {"text": "Tea"}), ("table.nextCell", {}),
    ("text.insert", {"text": "\u20ac\u00a02.00"}), ("table.nextCell", {}),
    ("text.insert", {"text": "Green\ttea\u2028(loose leaf)\nSecond paragraph in the same cell.", "raw": True}), ("table.nextCell", {}),
    # body row 3
    ("text.insert", {"text": "Water"}), ("table.nextCell", {}),
    ("text.insert", {"text": "free"}), ("table.nextCell", {}),
    ("text.insert", {"text": "Still <or> sparkling"}), ("table.nextCell", {}),
    # footer row
    ("text.insert", {"text": "Total"}), ("table.nextCell", {}),
    ("text.insert", {"text": "\u2014"}), ("table.nextCell", {}),
    ("text.insert", {"text": "Prices include VAT."}),
    ("document.inspect", {}),
  ]
  return cmds + export(out)


def fx_footnote(out):
  return new_doc() + [
    ("frame.create", {"rect": [72, 72, 540, 700], "content": "text", "text": "Body text with a footnote", "caret": True}),
    ("text.move", {"dir": "storyEnd"}),
    ("footnote.insert", {"text": "Footnote: bold run, then italic run & a <tag-like> run."}),
    *[WORD_LEFT] * 6,                                                                    # -> "italic"
    ("text.move", {"dir": "right", "word": True, "extend": True}),
    ("text.move", {"dir": "right", "word": True, "extend": True}), ("type.italic", {}),  # "italic run"
    *[WORD_LEFT] * 5,                                                                    # -> "bold"
    ("text.move", {"dir": "right", "word": True, "extend": True}),
    ("text.move", {"dir": "right", "word": True, "extend": True}), ("type.bold", {}),    # "bold run"
    ("footnote.goToReference", {}),
    ("text.insert", {"text": " and the sentence continues after the reference. Second note"}),
    ("footnote.insert", {"text": "Plain second footnote with\ttab and nbsp\u00a0here."}),
    ("footnote.goToReference", {}),
    ("text.insert", {"text": "."}),
    ("footnote.list", {}),
  ] + export(out)


SIDEBAR = "Sidebar: anchored text frame with its own story, a bold word and a tab	here."


def fx_nested(out):
  # DesignCraft 0.6.0 refuses `anchored.insert` for text frames ("text frames can't be anchored yet"),
  # so we anchor an empty graphic Rectangle (frame 7) inline, keep the sidebar text frame (frame 8,
  # its own story) on the page, and patch_nested() swaps the anchored Rectangle for the TextFrame.
  return new_doc() + [
    ("frame.create", {"rect": [400, 600, 560, 640], "content": "graphic"}),
    ("frame.create", {"rect": [400, 650, 560, 760], "content": "text",
                      "text": "Sidebar: anchored text frame with its own story, a bold word and a tab\there."}),
    # frame ids in a fresh document: graphic frame 7, sidebar text frame 8 / story 9
    ("text.select", {"story": 9, "anchor": SIDEBAR.index("bold"), "focus": SIDEBAR.index("bold") + 4}),
    ("type.bold", {}),
    ("frame.create", {"rect": [72, 72, 540, 400], "content": "text", "text": "Main story before the anchor. ", "caret": True}),
    ("text.move", {"dir": "storyEnd"}),
    ("anchored.insert", {"ids": [7], "position": "inline"}),
    ("text.move", {"dir": "storyEnd"}),
    ("text.insert", {"text": " Main story after the anchor.\nSecond paragraph of the main story."}),
    ("anchored.list", {}),
    ("document.inspect", {}),
  ] + export(out)


def fx_vars_links(out):
  # DesignCraft represents every inline object (variable instance, page number, footnote, anchor...)
  # as one private-use character = 3 UTF-8 bytes; text.select takes UTF-8 byte offsets.
  OBJ = "\ue000"
  p1 = "Buy the " + OBJ + " today. Visit our website for details. This is page " + OBJ + " of " + OBJ + ". Write to us by email."
  def rng(word):
    a = len(p1[:p1.index(word)].encode("utf-8"))
    return {"story": 8, "anchor": a, "focus": a + len(word.encode("utf-8"))}
  return new_doc() + [
    ("variables.define", {"name": "Product", "type": "custom", "text": "Widget Pro"}),
    ("variables.define", {"name": "Last Page", "type": "lastPageNumber"}),
    ("frame.create", {"rect": [72, 72, 540, 700], "content": "text", "text": "Buy the ", "caret": True}),  # frame 7 / story 8
    ("text.move", {"dir": "storyEnd"}),
    ("variables.insert", {"name": "Product"}),
    ("text.insert", {"text": " today. Visit our website for details. This is page "}),
    ("text.insert", {"text": "\ue000", "raw": True}),   # current page number -> <?ACE 18?>
    ("text.insert", {"text": " of "}),
    ("variables.insert", {"name": "Last Page"}),
    ("text.insert", {"text": ". Write to us by email.\nSecond paragraph: the cross-reference target.\nThird paragraph refers to "}),
    ("xref.insert", {"paragraph": "the cross-reference target", "format": "Full Paragraph"}),
    ("text.insert", {"text": " for details."}),
    ("text.select", rng("our website")),
    ("hyperlink.create", {"url": "https://example.com/", "name": "Site link"}),
    ("text.select", rng("by email")),
    ("hyperlink.create", {"email": "info@example.com", "name": "Mail link"}),
    ("hyperlink.list", {}),
    ("variables.list", {}),
    ("xref.list", {}),
  ] + export(out)


def fx_master_caps(out):
  # The body frame and the "folio" frame are created on the page; the folio frame is moved to the
  # parent (master) spread by patch_master_caps (the CLI cannot target parent spreads).
  return new_doc(pages=2) + [
    ("style.paragraph.create", {"name": "Kicker Caps", "chars": {"capitalization": "allCaps"}}),
    ("style.paragraph.create", {"name": "Small Caps Head", "chars": {"capitalization": "smallCaps"}}),
    ("frame.create", {"rect": [36, 740, 576, 770], "content": "text", "text": "Running head \u00b7 Page ", "caret": True}),
    ("text.move", {"dir": "storyEnd"}),
    ("text.insert", {"text": "\ue000 \u00b7 Section \ue001", "raw": True}),
    ("frame.create", {"rect": [72, 72, 540, 700], "content": "text", "text": "kicker in all caps style", "caret": True}),
    ("style.paragraph.apply", {"name": "Kicker Caps"}),
    ("text.move", {"dir": "storyEnd"}),
    ("text.insert", {"text": "\nsmall caps heading"}),
    ("style.paragraph.apply", {"name": "Small Caps Head"}),
    ("text.insert", {"text": "\n"}),
    ("style.paragraph.apply", {"name": "[Basic Paragraph]"}),
    ("text.insert", {"text": SPECIALS + "\nLocal all caps override on a run.", "raw": True}),
    *[WORD_LEFT] * 6,                                                       # -> start of "all"
    *[("text.move", {"dir": "right", "word": True, "extend": True})] * 3,   # "all caps override"
    ("type.allCaps", {}),                                                   # local Capitalization override on a CSR
    ("document.inspect", {}),
  ] + export(out)


# ---------------------------------------------------------------- byte-preserving zip patching

def rewrite_zip(src, dst, edits):
  """Copy zip `src` to `dst`, replacing entries in `edits` {name: bytes}; new names are appended.
  Entry order, compression type and all untouched entry bytes are preserved."""
  zin = zipfile.ZipFile(src)
  tmp = Path(str(dst) + ".tmp")
  with zipfile.ZipFile(tmp, "w") as zout:
    for info in zin.infolist():
      data = edits.pop(info.filename, None)
      if data is None:
        data = zin.read(info.filename)
      ni = zipfile.ZipInfo(info.filename, date_time=info.date_time)
      ni.compress_type = info.compress_type
      ni.external_attr = info.external_attr
      ni.create_system = info.create_system
      zout.writestr(ni, data)
    for name, data in edits.items():
      ni = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
      ni.compress_type = zipfile.ZIP_DEFLATED
      zout.writestr(ni, data)
  zin.close()
  os.replace(tmp, dst)


def ser(root):
  # Same declaration bytes as InDesign/DesignCraft write (double quotes), then the tree.
  return b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' + etree.tostring(root, encoding="UTF-8")


def patch_master_caps(path):
  """Move the folio TextFrame (the one whose story contains <?ACE 18?>) from the page spread into the
  MasterSpread, keeping its ItemTransform (single-page, non-facing docs share the page transform:
  both Page elements use ItemTransform "1 0 0 1 -306 -396"). The CLI has no way to target a parent
  spread with frame.create (`spread` only indexes document spreads)."""
  z = zipfile.ZipFile(path)
  names = z.namelist()
  story_with_folio = None
  for n in names:
    if n.startswith("Stories/") and b"<?ACE 18?>" in z.read(n) and b"Running head" in z.read(n):
      story_with_folio = etree.fromstring(z.read(n)).find("Story").get("Self")
  assert story_with_folio, "folio story not found"
  master_name = next(n for n in names if n.startswith("MasterSpreads/"))
  master = etree.fromstring(z.read(master_name))
  edits = {}
  moved = None
  for n in names:
    if not n.startswith("Spreads/"):
      continue
    sp = etree.fromstring(z.read(n))
    for tf in sp.iter("TextFrame"):
      if tf.get("ParentStory") == story_with_folio:
        moved = tf
        tf.getparent().remove(tf)
        edits[n] = ser(sp)
        break
    if moved is not None:
      break
  assert moved is not None, "folio frame not found on a spread"
  ms = master.find("MasterSpread")
  page_tf = None
  for pg in ms.findall("Page"):
    page_tf = pg.get("ItemTransform")
  ms.append(moved)
  edits[master_name] = ser(master)
  z.close()
  rewrite_zip(path, path, edits)
  return {"moved_frame": moved.get("Self"), "story": story_with_folio, "master": master_name, "master_page_transform": page_tf}


def patch_nested(path):
  """Replace the inline-anchored <Rectangle> in the main story with the sidebar <TextFrame> (removed
  from the spread), giving it the Rectangle's AnchoredObjectSetting. Result: an anchored text frame
  inside a story whose ParentStory is a separate Stories/*.xml file (InDesign's anchored-frame shape)."""
  z = zipfile.ZipFile(path)
  names = z.namelist()
  edits = {}
  spread_name = next(n for n in names if n.startswith("Spreads/"))
  sp = etree.fromstring(z.read(spread_name))
  side_story = None
  for n in names:
    if n.startswith("Stories/") and b"Sidebar:" in z.read(n):
      side_story = etree.fromstring(z.read(n)).find("Story").get("Self")
  tf = next(t for t in sp.iter("TextFrame") if t.get("ParentStory") == side_story)
  tf.getparent().remove(tf)
  edits[spread_name] = ser(sp)
  for n in names:
    if not n.startswith("Stories/"):
      continue
    st = etree.fromstring(z.read(n))
    rect = next((r for r in st.iter("Rectangle") if r.getparent().tag == "CharacterStyleRange"), None)
    if rect is None:
      continue
    aos = rect.find("AnchoredObjectSetting")
    new = copy.deepcopy(tf)
    new.tail = rect.tail
    if aos is not None:
      new.append(copy.deepcopy(aos))
    rect.getparent().replace(rect, new)
    edits[n] = ser(st)
    host = st.find("Story").get("Self")
  z.close()
  rewrite_zip(path, path, edits)
  return {"anchored_frame": tf.get("Self"), "anchored_story": side_story, "host_story": host}


def patch_vars_links(path):
  """DesignCraft 0.6.0's IDML export (a) writes text-variable instances as its internal private-use
  characters (U+E1xx) inside <Content> and drops the custom TextVariable definitions, and (b) drops
  URL/email hyperlinks entirely. Rebuild paragraph 1 the way InDesign writes it:
    designmap: <TextVariable VariableType="CustomTextType"><CustomTextVariablePreference Contents=.../>,
               <TextVariable VariableType="LastPageNumberType">, <HyperlinkURLDestination>, <Hyperlink>
    story:     <TextVariableInstance .../> between <Content> siblings, <HyperlinkTextSource> wrapping a CSR.
  The <?ACE 18?> page-number PI and the cross-reference (CrossReferenceSource) are kept as exported."""
  z = zipfile.ZipFile(path)
  names = z.namelist()
  story_name = next(n for n in names if n.startswith("Stories/") and "\ue107".encode() in z.read(n))
  st = etree.fromstring(z.read(story_name))
  dm = etree.fromstring(z.read("designmap.xml"))
  content = next(c for c in st.iter("Content") if c.text and "\ue107" in c.text)
  csr = content.getparent()
  psr = csr.getparent()
  attrs = dict(csr.attrib)

  def CSR(*children):
    e = etree.Element("CharacterStyleRange", attrs)
    for ch in children:
      e.append(ch)
    return e

  def C(text, pi=None, tail=None):
    e = etree.Element("Content")
    e.text = text
    if pi is not None:
      p = etree.ProcessingInstruction(*pi)
      p.tail = tail
      e.append(p)
    return e

  def TVI(self_id, name, result, var_self):
    return etree.Element("TextVariableInstance", {"Self": self_id, "Name": name, "ResultText": result,
                                                  "AssociatedTextVariable": var_self})

  def HTS(self_id, name, text):
    e = etree.Element("HyperlinkTextSource", {"Self": self_id, "Name": name, "Hidden": "false",
                                              "AppliedCharacterStyle": "n"})
    e.append(CSR(C(text)))
    return e

  v_prod = "dTextVariablenProduct"
  v_last = "dTextVariablenLast Page Number"
  br = etree.Element("Br")
  new_nodes = [
    CSR(C("Buy the "), TVI("uf001", "Product", "Widget Pro", v_prod), C(" today. Visit ")),
    HTS("uf002", "Site link", "our website"),
    CSR(C(" for details. This is page ", pi=("ACE", "18"), tail=" of "),
        TVI("uf003", "Last Page Number", "1", v_last), C(". Write to us ")),
    HTS("uf004", "Mail link", "by email"),
    CSR(C("."), br),
  ]
  idx = list(psr).index(csr)
  tail = csr.tail
  psr.remove(csr)
  for k, n in enumerate(new_nodes):
    n.tail = tail
    psr.insert(idx + k, n)

  # designmap: variables after the last TextVariable, hyperlinks before the first Hyperlink
  doc = dm
  tvs = doc.findall("TextVariable")
  anchor = tvs[-1]
  tv1 = etree.Element("TextVariable", {"Self": v_prod, "Name": "Product", "VariableType": "CustomTextType"})
  etree.SubElement(tv1, "CustomTextVariablePreference", {"Contents": "Widget Pro"})
  tv2 = etree.Element("TextVariable", {"Self": v_last, "Name": "Last Page Number", "VariableType": "LastPageNumberType"})
  etree.SubElement(tv2, "PageNumberVariablePreference", {"NumberingStyle": "Current", "Scope": "DocumentScope",
                                                         "TextBefore": "", "TextAfter": ""})
  for e in (tv2, tv1):
    e.tail = anchor.tail
    anchor.addnext(e)
  first_h = doc.find("Hyperlink")
  dests = [("uf010", "https://example.com/", "uf002", "Site link", "uf011"),
           ("uf012", "mailto:info@example.com", "uf004", "Mail link", "uf013")]
  for dkey, url, src, name, hself in dests:
    d = etree.Element("HyperlinkURLDestination", {"Self": f"HyperlinkURLDestination/{dkey}", "DestinationURL": url,
                                                  "Name": url, "Hidden": "false", "DestinationUniqueKey": dkey[2:]})
    h = etree.Element("Hyperlink", {"Self": hself, "Name": name, "Source": src, "Visible": "false",
                                    "Highlight": "None", "Width": "Thin", "BorderStyle": "Solid",
                                    "Hidden": "false", "DestinationUniqueKey": hself[2:]})
    props = etree.SubElement(h, "Properties")
    de = etree.SubElement(props, "Destination", {"type": "object"})
    de.text = f"HyperlinkURLDestination/{dkey}"
    for e in (d, h):
      e.tail = first_h.tail
      first_h.addprevious(e)
  # designmap carries the <?aid ...?> PI before the root: keep the original prolog bytes.
  raw = z.read("designmap.xml")
  prolog = raw[:raw.index(b"<Document")]
  z.close()
  rewrite_zip(path, path, {story_name: ser(st), "designmap.xml": prolog + etree.tostring(dm, encoding="UTF-8")})
  return {"story": story_name, "variables": [v_prod, v_last], "hyperlinks": ["Site link", "Mail link"]}


MISC = "Deleted words. Note anchor here. Conditional words here. Hidden condition text. Index term here. Tagged title text."


def fx_misc(out):
  def rng(w):
    a = len(MISC[:MISC.index(w)].encode("utf-8"))
    return {"story": 8, "anchor": a, "focus": a + len(w.encode("utf-8"))}
  return new_doc() + [
    ("frame.create", {"rect": [72, 72, 540, 300], "content": "text", "text": MISC, "caret": True}),  # frame 7 / story 8
    ("condition.new", {"name": "PrintOnly", "visible": True}),
    ("condition.new", {"name": "Hidden", "visible": False}),
    ("text.select", rng("Conditional words")), ("condition.apply", {"name": "PrintOnly"}),
    ("text.select", rng("Hidden condition text.")), ("condition.apply", {"name": "Hidden"}),
    ("text.select", rng("Tagged title")), ("type.bold", {}),       # isolates the run later wrapped in <XMLElement>
    ("text.select", rng("Deleted words.")), ("type.italic", {}),   # isolates the run later wrapped in <Change DeletedText>
    # last: the index marker inserts an object character (3 bytes) that would shift later offsets
    ("text.select", rng("Index term")), ("index.addReference", {"topic": "Terms > Index term"}),
    ("path.create", {"anchors": [{"p": [72, 500]}, {"p": [300, 450]}, {"p": [540, 500]}]}),  # id 9
    ("type.onPath", {"id": 9, "text": "Text on a path"}),
    ("frame.create", {"rect": [72, 600, 200, 700], "content": "graphic"}),
    ("index.list", {}), ("condition.list", {}),
  ] + export(out)


def patch_misc(path):
  """DesignCraft 0.6.0 exports conditions, index PageReference/Topic and TextPath, but drops notes,
  tracked changes (it flattens them: deleted text re-appears as plain text!), XML structure and alt
  text. Add InDesign-shaped versions of those (shapes from IDML spec knowledge, not InDesign-verified):
    <Change ChangeType="DeletedText">, <Change ChangeType="InsertedText"> (wrapping CSRs, Story TrackChanges="true"),
    <Note> inside a CSR, <XMLElement MarkupTag=...> wrapping a <Content> (+ XML/Tags.xml, XML/BackingStory.xml),
    <ObjectExportOption CustomAltText=...> on the graphic Rectangle."""
  z = zipfile.ZipFile(path)
  names = z.namelist()
  story_name = next(n for n in names if n.startswith("Stories/") and b"Deleted words." in z.read(n))
  st = etree.fromstring(z.read(story_name))
  story = st.find("Story")
  story.set("TrackChanges", "true")

  def content_with(text):
    return next(c for c in st.iter("Content") if c.text and text in c.text)

  # 1) tracked deletion: wrap the CSR holding "Deleted words." in <Change ChangeType="DeletedText">
  c = content_with("Deleted words.")
  csr = c.getparent()
  ch = etree.Element("Change", {"Self": "uf101", "ChangeType": "DeletedText", "UserName": "QA",
                                "Date": "2026-10-12T12:00:00", "AllowMerge": "true"})
  ch.tail = csr.tail
  csr.addprevious(ch)
  ch.append(csr)
  # 2) tracked insertion appended at the end of the last paragraph
  psr = story.findall("ParagraphStyleRange")[-1]
  last_csr = psr.findall("CharacterStyleRange")[-1]
  ins = etree.Element("Change", {"Self": "uf102", "ChangeType": "InsertedText", "UserName": "QA",
                                 "Date": "2026-10-12T12:01:00", "AllowMerge": "true"})
  ins_csr = etree.SubElement(ins, "CharacterStyleRange", {"AppliedCharacterStyle": last_csr.get("AppliedCharacterStyle")})
  etree.SubElement(ins_csr, "Content").text = " Inserted while tracking."
  ins.tail = last_csr.tail
  last_csr.addnext(ins)
  # 3) note after "Note anchor": split that Content and put <Note> between the halves
  c = content_with("Note anchor")
  before, after = c.text.split("Note anchor", 1)
  c.text = before + "Note anchor"
  note = etree.Element("Note", {"Collapsed": "false", "CreationDate": "2026-10-12T12:00:00",
                                "ModificationDate": "2026-10-12T12:00:00", "UserName": "QA", "AuthorColor": "Gold"})
  npsr = etree.SubElement(note, "ParagraphStyleRange", {"AppliedParagraphStyle": "ParagraphStyle/$ID/NormalParagraphStyle"})
  ncsr = etree.SubElement(npsr, "CharacterStyleRange", {"AppliedCharacterStyle": "CharacterStyle/$ID/[No character style]"})
  etree.SubElement(ncsr, "Content").text = "Reviewer note: check this wording."
  c2 = etree.Element("Content")
  c2.text = after
  c2.tail = c.tail
  c.addnext(note)
  note.addnext(c2)
  # 4) XML tag: wrap the "Tagged title" Content in <XMLElement>
  c = content_with("Tagged title")
  xe = etree.Element("XMLElement", {"Self": "di2i3", "MarkupTag": "XMLTag/title"})
  xe.tail = c.tail
  c.addprevious(xe)
  xe.append(c)
  edits = {story_name: ser(st)}
  # 5) alt text on the graphic frame
  spread_name = next(n for n in names if n.startswith("Spreads/"))
  sp = etree.fromstring(z.read(spread_name))
  rect = next(sp.iter("Rectangle"))
  oeo = etree.Element("ObjectExportOption", {"AltTextSourceType": "SourceCustom", "ActualTextSourceType": "SourceCustom",
                                             "CustomAltText": "Alt text: a placeholder graphic frame",
                                             "CustomActualText": "Actual text for the frame", "ApplyTagType": "TagFromStructure"})
  rect.append(oeo)
  edits[spread_name] = ser(sp)
  # XML structure parts + designmap references
  raw = z.read("designmap.xml")
  prolog = raw[:raw.index(b"<Document")]
  dm = etree.fromstring(raw)
  PKG = "http://ns.adobe.com/AdobeInDesign/idml/1.0/packaging"
  first_story = dm.find(f"{{{PKG}}}Story")
  tags = etree.Element(f"{{{PKG}}}Tags", {"src": "XML/Tags.xml"})
  backing = etree.Element(f"{{{PKG}}}BackingStory", {"src": "XML/BackingStory.xml"})
  pref = dm.find(f"{{{PKG}}}Preferences")
  tags.tail = pref.tail
  pref.addnext(tags)
  backing.tail = first_story.tail
  first_story.addprevious(backing)
  edits["designmap.xml"] = prolog + etree.tostring(dm, encoding="UTF-8")
  sid = story.get("Self")
  decl = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
  edits["XML/Tags.xml"] = (decl +
    f'<idPkg:Tags xmlns:idPkg="{PKG}" DOMVersion="16.0">\n'
    '\t<XMLTag Self="XMLTag/Root" Name="Root"><Properties><TagColor type="enumeration">LightBlue</TagColor></Properties></XMLTag>\n'
    '\t<XMLTag Self="XMLTag/title" Name="title"><Properties><TagColor type="enumeration">Red</TagColor></Properties></XMLTag>\n'
    '</idPkg:Tags>\n').encode("utf-8")
  edits["XML/BackingStory.xml"] = (decl +
    f'<idPkg:BackingStory xmlns:idPkg="{PKG}" DOMVersion="16.0">\n'
    '\t<XmlStory Self="ufb1" AppliedTOCStyle="n" TrackChanges="false" StoryTitle="$ID/" AppliedNamedGrid="n">\n'
    '\t\t<ParagraphStyleRange AppliedParagraphStyle="ParagraphStyle/$ID/NormalParagraphStyle">\n'
    '\t\t\t<CharacterStyleRange AppliedCharacterStyle="CharacterStyle/$ID/[No character style]">\n'
    f'\t\t\t\t<XMLElement Self="di2" MarkupTag="XMLTag/Root"><XMLElement Self="di2i3ref" MarkupTag="XMLTag/title" XMLContent="{sid}"/></XMLElement>\n'
    '\t\t\t</CharacterStyleRange>\n\t\t</ParagraphStyleRange>\n\t</XmlStory>\n</idPkg:BackingStory>\n').encode("utf-8")
  z.close()
  rewrite_zip(path, path, edits)
  return {"story": story_name, "added": ["Change(DeletedText)", "Change(InsertedText)", "Note", "XMLElement",
                                         "ObjectExportOption", "XML/Tags.xml", "XML/BackingStory.xml"]}


PATCHES = {"fx_master_caps": patch_master_caps, "fx_nested": patch_nested, "fx_vars_links": patch_vars_links, "fx_misc": patch_misc}

FIXTURES = {
  "fx_table": fx_table,
  "fx_footnote": fx_footnote,
  "fx_nested": fx_nested,
  "fx_vars_links": fx_vars_links,
  "fx_master_caps": fx_master_caps,
  "fx_misc": fx_misc,
}


def verify(path):
  r = run_dc([("document.inspect", {})], in_file=path)[0]
  stories = [{"id": s["id"], "frames": s["frames"], "overset": s["overset"], "preview": s["preview"][:70]} for s in r.get("stories", [])]
  return {"pageCount": r.get("pageCount"), "parents": r.get("parents"), "stories": stories,
          "warnings": r.get("warnings", [])}


def verify_open(path):
  r = run_dc([("file.openIdml", {"path": fwd(path)})])[0]
  return {"documentFonts": r.get("documentFonts"), "warnings": r.get("warnings")}


def main():
  report = {}
  for name, fn in FIXTURES.items():
    if ONLY and name != ONLY:
      continue
    out = HERE / f"{name}.idml"
    print(f"== {name}")
    res = run_dc(fn(out))
    info = {"build_last_results": res[-1]}
    if name in PATCHES:
      info["patch"] = PATCHES[name](out)
    info["inspect"] = verify(out)
    info["openIdml"] = verify_open(out)
    report[name] = info
    print(json.dumps(info, ensure_ascii=True)[:600])
  vf = HERE / "verify.json"
  old = json.loads(vf.read_text(encoding="utf-8")) if vf.exists() else {}
  old.update(report)
  vf.write_text(json.dumps(old, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
  main()
