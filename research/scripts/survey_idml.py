"""Read-only survey of an IDML package: where text lives and what surrounds <Content>.

usage: python research/scripts/survey_idml.py <file.idml> [--json out.json]

Reads the zip directly (never extracts or writes into it). Reports:
  - zip entry list / compression
  - every distinct element / PI appearing inside <Content> or as a sibling of <Content>
  - all PI targets and values (anywhere in stories)
  - non-ASCII / control characters in Content text, with code points and counts
  - stories placed on master spreads vs. normal spreads (TextFrame ParentStory)
  - table / footnote / note / anchored-frame / variable / hyperlink structures
  - paragraph & character styles with Capitalization, AppliedLanguage everywhere
  - text-bearing attributes in designmap / styles (CustomText, Contents, Name, alt text)
"""
import collections
import json
import sys
import unicodedata
import zipfile

from lxml import etree

PKG = "{http://ns.adobe.com/AdobeInDesign/idml/1.0/packaging}"


def local(tag):
  if not isinstance(tag, str):
    return None
  return tag.split("}", 1)[-1]


def node_label(n):
  if isinstance(n, etree._ProcessingInstruction):
    return f"<?{n.target} {n.text}?>"
  if isinstance(n, etree._Comment):
    return "<!--comment-->"
  return local(n.tag)


def char_name(c):
  try:
    return unicodedata.name(c)
  except ValueError:
    return {"\t": "TAB", "\n": "LF", "\r": "CR"}.get(c, "<unnamed>")


def survey(path):
  z = zipfile.ZipFile(path)
  rep = collections.OrderedDict()
  rep["entries"] = [(i.filename, "stored" if i.compress_type == 0 else "deflated") for i in z.infolist()]

  def parse(name):
    return etree.fromstring(z.read(name))

  # ---- spreads: which story is on master vs page; anchored frames are inside stories
  story_place = collections.defaultdict(set)
  spread_items = collections.Counter()
  textpaths = []
  for name in z.namelist():
    if not (name.startswith("MasterSpreads/") or name.startswith("Spreads/")):
      continue
    root = parse(name)
    kind = "master" if name.startswith("MasterSpreads/") else "spread"
    for el in root.iter():
      t = local(el.tag)
      if t in ("TextFrame", "Rectangle", "Oval", "Polygon", "GraphicLine", "Group", "Image", "PDF", "EPS", "TextPath", "Button", "MultiStateObject", "EPSText"):
        spread_items[f"{kind}:{t}"] += 1
      if t == "TextFrame":
        story_place[el.get("ParentStory")].add(f"{kind}:{name}")
      if t == "TextPath":
        textpaths.append((name, el.get("Self"), el.get("ParentStory")))
        story_place[el.get("ParentStory")].add(f"{kind}-textpath:{name}")
      if t in ("ObjectExportOption",):
        for a in ("CustomAltText", "CustomActualText", "AltTextSourceType", "ActualTextSourceType"):
          if el.get(a) not in (None, "", "$ID/"):
            rep.setdefault("alt_text", []).append((name, a, el.get(a)))
  rep["spread_items"] = dict(spread_items)
  rep["textpaths"] = textpaths

  # ---- stories
  inside_content = collections.Counter()
  content_siblings = collections.Counter()
  content_parents = collections.Counter()
  content_paths = collections.Counter()
  pis = collections.Counter()
  chars = collections.Counter()
  elements = collections.Counter()
  psr_without_csr = 0
  csr_lang = collections.Counter()
  story_attrs = collections.Counter()
  tables = []
  footnotes = []
  notes = []
  anchored = []
  hyperlink_sources = []
  tv_instances = []
  changes = []
  conditions = collections.Counter()
  content_count = 0
  per_story = {}
  attr_text = collections.Counter()

  for name in sorted(n for n in z.namelist() if n.startswith("Stories/")):
    root = parse(name)
    st = root.find("Story")
    sid = st.get("Self")
    for a in ("TrackChanges", "AppliedTOCStyle", "StoryTitle", "IsEndnoteStory"):
      if st.get(a) is not None:
        story_attrs[f"{a}={st.get(a)}"] += 1
    n_content = 0
    for el in root.iter():
      if isinstance(el, etree._ProcessingInstruction):
        pis[f"{el.target} {el.text}"] += 1
        continue
      if not isinstance(el.tag, str):
        continue
      t = local(el.tag)
      elements[t] += 1
      if t == "Content":
        content_count += 1
        n_content += 1
        content_parents[local(el.getparent().tag)] += 1
        chain, a = [], el.getparent()
        while a is not None and local(a.tag) != "Story":
          chain.append(local(a.tag))
          a = a.getparent()
        content_paths["/".join(reversed(chain))] += 1
        for ch in el:
          inside_content[node_label(ch)] += 1
        for sib in el.getparent():
          if sib is not el:
            content_siblings[node_label(sib) if not isinstance(sib, etree._ProcessingInstruction) else f"PI:{sib.target} {sib.text}"] += 1
        texts = [el.text or ""] + [(c.tail or "") for c in el]
        for s in texts:
          for c in s:
            if ord(c) > 0x7E or ord(c) < 0x20:
              chars[c] += 1
      elif t == "ParagraphStyleRange":
        if el.find("CharacterStyleRange") is None:
          psr_without_csr += 1
      elif t == "CharacterStyleRange":
        csr_lang[el.get("AppliedLanguage", "(inherit)")] += 1
        if el.get("AppliedConditions"):
          conditions[el.get("AppliedConditions")] += 1
      elif t == "Table":
        rows = el.findall("Row")
        cols = el.findall("Column")
        cells = el.findall("Cell")
        tables.append({
          "story": sid, "Self": el.get("Self"), "HeaderRowCount": el.get("HeaderRowCount"),
          "BodyRowCount": el.get("BodyRowCount"), "FooterRowCount": el.get("FooterRowCount"),
          "ColumnCount": el.get("ColumnCount"), "rows": len(rows), "cols": len(cols), "cells": len(cells),
          "cell_names": [c.get("Name") for c in cells][:12],
          "cell_child_tags": sorted({local(x.tag) for c in cells for x in c if isinstance(x.tag, str)}),
          "cell_csr_counts": [len(c.findall(".//CharacterStyleRange")) for c in cells],
          "parent": local(el.getparent().tag),
        })
      elif t == "Footnote":
        footnotes.append({
          "story": sid, "Self": el.get("Self"), "parent": local(el.getparent().tag),
          "children": [node_label(x) for x in el],
          "text": "".join(el.itertext())[:80],
          "pis_inside": [f"{p.target} {p.text}" for p in el.iter(etree.ProcessingInstruction)],
          "csr_count": len(el.findall(".//CharacterStyleRange")),
        })
      elif t == "Note":
        notes.append({"story": sid, "text": "".join(el.itertext())[:80]})
      elif t in ("TextFrame", "Rectangle", "Group", "Oval", "Polygon") and el.getparent() is not None and local(el.getparent().tag) == "CharacterStyleRange":
        anchored.append({"story": sid, "kind": t, "Self": el.get("Self"), "ParentStory": el.get("ParentStory")})
        if t == "TextFrame":
          story_place[el.get("ParentStory")].add(f"anchored-in:{sid}")
      elif t == "HyperlinkTextSource":
        hyperlink_sources.append({"story": sid, "Self": el.get("Self"), "Name": el.get("Name"), "text": "".join(el.itertext())[:60]})
      elif t == "TextVariableInstance":
        tv_instances.append({"story": sid, **{k: el.get(k) for k in ("Self", "Name", "ResultText", "AssociatedTextVariable")}})
      elif t == "Change":
        changes.append({"story": sid, "ChangeType": el.get("ChangeType"), "text": "".join(el.itertext())[:60]})
      for a in ("Name", "ResultText", "CustomText", "Contents"):
        if el.get(a) is not None and t != "Content":
          attr_text[f"{t}@{a}"] += 1
    per_story[sid] = {"file": name, "content_elements": n_content, "placed": sorted(story_place.get(sid, []))}

  for sid in per_story:
    per_story[sid]["placed"] = sorted(story_place.get(sid, []))

  rep["story_attrs"] = dict(story_attrs)
  rep["elements_in_stories"] = dict(elements)
  rep["content_count"] = content_count
  rep["content_parents"] = dict(content_parents)
  rep["content_ancestor_paths"] = dict(content_paths)
  rep["children_inside_content"] = dict(inside_content)
  rep["siblings_of_content"] = dict(content_siblings)
  rep["processing_instructions"] = dict(pis)
  rep["special_chars"] = [(f"U+{ord(c):04X}", char_name(c), n) for c, n in sorted(chars.items(), key=lambda x: ord(x[0]))]
  rep["psr_without_csr"] = psr_without_csr
  rep["csr_AppliedLanguage"] = dict(csr_lang)
  rep["csr_AppliedConditions"] = dict(conditions)
  rep["stories"] = per_story
  rep["master_stories"] = sorted(s for s, p in story_place.items() if any(x.startswith("master:") for x in p))
  rep["unplaced_stories"] = sorted(s for s in per_story if not story_place.get(s))
  rep["tables"] = tables
  rep["footnotes"] = footnotes
  rep["notes"] = notes
  rep["anchored_objects"] = anchored
  rep["hyperlink_text_sources"] = hyperlink_sources
  rep["text_variable_instances"] = tv_instances
  rep["changes"] = changes
  rep["text_bearing_attrs_in_stories"] = dict(attr_text)

  # ---- styles
  sty = parse("Resources/Styles.xml")
  caps, langs = [], collections.Counter()
  for el in sty.iter():
    if not isinstance(el.tag, str):
      continue
    t = local(el.tag)
    if el.get("Capitalization") not in (None, "Normal"):
      caps.append((t, el.get("Self"), el.get("Capitalization")))
    if el.get("AppliedLanguage") is not None:
      langs[f"{t}: {el.get('AppliedLanguage')}"] += 1
    if t == "TOCStyle":
      rep.setdefault("toc_styles", []).append((el.get("Self"), el.get("Title")))
    for a in ("BulletChar", "NumberingExpression"):
      if el.get(a) not in (None, "", "^#.^t"):
        rep.setdefault("list_text_in_styles", []).append((t, el.get("Self"), a, el.get(a)))
  # BulletsAndNumbering / properties children
  for el in sty.iter():
    if isinstance(el.tag, str) and local(el.tag) in ("BulletChar",):
      rep.setdefault("bullet_chars", []).append((el.getparent().getparent().get("Self"), dict(el.attrib)))
  rep["capitalization_styles"] = caps
  rep["style_AppliedLanguage"] = dict(langs)

  # ---- designmap
  dm = parse("designmap.xml")
  dmi = collections.defaultdict(list)
  for el in dm.iter():
    if not isinstance(el.tag, str):
      continue
    t = local(el.tag)
    if t == "TextVariable":
      pref = el.find("CustomTextVariablePreference")
      dmi["TextVariable"].append((el.get("Name"), el.get("VariableType"), pref.get("Contents") if pref is not None else None))
    elif t == "BuildingBlock" and el.get("BlockType") == "CustomStringBuildingBlock":
      dmi["XrefCustomText"].append(el.get("CustomText"))
    elif t in ("Hyperlink", "HyperlinkURLDestination", "HyperlinkPageDestination", "HyperlinkTextDestination", "Bookmark", "Topic", "Index", "Condition", "ConditionSet", "Language", "XMLTag", "ItemLink", "StoryLink", "Section"):
      dmi[t].append({k: v for k, v in el.attrib.items() if k in ("Self", "Name", "DestinationURL", "Visible", "Marker", "SectionPrefix", "Source", "Destination", "SortOrder")})
    if el.get("StoryList"):
      dmi["StoryList"] = el.get("StoryList").split()
  rep["designmap"] = dict(dmi)
  pref = parse("Resources/Preferences.xml")
  for el in pref.iter():
    if isinstance(el.tag, str) and local(el.tag) in ("TextDefault", "StoryPreference", "FootnoteOption", "DictionaryPreference"):
      keep = {k: v for k, v in el.attrib.items() if k in ("AppliedLanguage", "Capitalization", "Separator", "Prefix", "Suffix", "ShowPrefixSuffix", "FootnoteNumberingStyle")}
      if keep:
        rep.setdefault("preferences", []).append((local(el.tag), keep))
  # XML structure / BackingStory
  for n in z.namelist():
    if n.startswith("XML/"):
      rep.setdefault("xml_parts", []).append(n)
  return rep


def main():
  args = sys.argv[1:]
  rep = survey(args[0])
  out = json.dumps(rep, ensure_ascii=False, indent=1, default=list)
  if "--json" in args:
    with open(args[args.index("--json") + 1], "w", encoding="utf-8") as f:
      f.write(out)
  else:
    sys.stdout.write(out + "\n")


if __name__ == "__main__":
  main()
