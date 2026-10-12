"""IDML translation demo: local Hy-MT2 (Ollama) + DesignCraft verification.

Only <Content> text nodes in Stories/*.xml are rewritten (plus an AppliedLanguage
attribute on CharacterStyleRange). Every other byte of the package is copied as is.

usage: python -I demo_translate.py <in.idml> <out.idml> <target: tr|de>
"""
import difflib
import hashlib
import json
import re
import sqlite3
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

from lxml import etree

OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
MODEL = "hf.co/tencent/Hy-MT2-7B-GGUF:Q4_K_M"
# Recommended sampling for Hy-MT2 1.8B/7B (model card).
OPTIONS = {"temperature": 0.7, "top_p": 0.6, "top_k": 20, "repeat_penalty": 1.05, "num_predict": 2048}
DESIGNCRAFT = r"C:\Program Files\DesignCraft\designcraft-cli.exe"

LANGS = {
  "tr": {"name": "Turkish", "idml": "$ID/Turkish"},
  "de": {"name": "German", "idml": "$ID/German: 2006 Reform"},
}
# Elements whose text forms its own segments, separate from the surrounding paragraph.
NESTED = {"Cell", "Footnote", "Note", "TextFrame", "Table", "Row", "Column"}
TAG_RE = re.compile(r"</?g\d+>")
MAX_TRIES = 3


# ── Segmentation ──

HAS_LETTER = re.compile(r"[^\W\d_]")


class Slot:
  """One run of text: a <Content>'s .text, or the .tail of a processing instruction inside it
  (<?ACE 4?> footnote numbers, special characters). The PIs themselves are never touched."""
  def __init__(self, el, attr, content):
    self.el, self.attr, self.content = el, attr, content

  @property
  def text(self):
    return getattr(self.el, self.attr) or ""

  @text.setter
  def text(self, value):
    setattr(self.el, self.attr, value)


def content_slots(content):
  slots = [Slot(content, "text", content)]
  slots += [Slot(child, "tail", content) for child in content]
  return slots


class Segment:
  def __init__(self, story, slots):
    self.story = story
    # Only runs with letters go to the model; whitespace/number/empty runs stay as they are.
    self.nodes = [s for s in slots if HAS_LETTER.search(s.text)]

  @property
  def source(self):
    if len(self.nodes) == 1:
      return self.nodes[0].text
    return "".join(f"<g{i}>{n.text}</g{i}>" for i, n in enumerate(self.nodes))

  def translatable(self):
    return bool(self.nodes)


def segment_story(story_name, root):
  segments = []

  def walk(container):
    current = []
    def flush():
      if current:
        segments.append(Segment(story_name, list(current)))
        current.clear()
    def visit(el):
      for child in el:
        tag = child.tag if isinstance(child.tag, str) else None
        if tag is None:
          continue  # processing instructions / comments: left untouched
        if tag == "Content":
          current.extend(content_slots(child))
        elif tag == "Br":
          flush()
        elif tag in NESTED:
          walk_nested(child)
        else:
          visit(child)
    visit(container)
    flush()

  def walk_nested(el):
    if el.tag in ("Row", "Column"):
      return
    if el.tag == "Table":
      for cell in el.findall("Cell"):
        walk(cell)
      return
    walk(el)

  walk(root)
  return segments


# ── Translation ──

def prompt_for(seg_src, lang_name, concise):
  if "<g" in seg_src:
    style = " Keep it concise." if concise else ""
    return (
      "### Task\n"
      f"Translate the user-facing text within the following XML data into {lang_name}.{style}\n\n"
      "### Strict Rules\n"
      "1. **Structure Preservation:** You MUST keep every tag (<g0>, </g0>, <g1>, …) exactly once, "
      "in the same order, wrapping the words that correspond to the original.\n"
      "2. **Selective Translation:** Translate ONLY the text between the tags.\n"
      "3. **Strict Non-Translation:** NEVER translate, rename, add or remove tags.\n"
      "Output ONLY the translated XML.\n\n"
      f"### Source Data\n{seg_src}"
    )
  if concise:
    return (f"Please translate the following text into {lang_name}. Note that the translation style "
            f"must strictly conform to [**concise: as short as possible while keeping the full meaning**]:\n\n{seg_src}")
  return (f"Translate the following text into {lang_name}. Note that you should **only output the "
          f"translated result without any additional explanation**:\n\n{seg_src}")


def ollama(prompt, temperature=None):
  opts = dict(OPTIONS)
  if temperature is not None:
    opts["temperature"] = temperature
  body = json.dumps({"model": MODEL, "stream": False, "options": opts,
                     "messages": [{"role": "user", "content": prompt}]}).encode()
  req = urllib.request.Request(OLLAMA_URL, body, {"Content-Type": "application/json"})
  with urllib.request.urlopen(req, timeout=600) as r:
    return json.load(r)["message"]["content"].strip()


def split_tagged(out, n):
  """Return the n run texts if the tag structure is intact, else None."""
  if TAG_RE.findall(out) != [t for i in range(n) for t in (f"<g{i}>", f"</g{i}>")]:
    return None
  parts = re.findall(r"<g(\d+)>(.*?)</g\1>", out, re.S)
  if [int(i) for i, _ in parts] != list(range(n)):
    return None
  if TAG_RE.sub("", re.sub(r"<g(\d+)>.*?</g\1>", "", out, flags=re.S)).strip():
    return None  # text outside the tags would be lost
  return [t for _, t in parts]


def keep_edges(src, dst):
  """Keep the source run's leading/trailing whitespace (spacing between runs)."""
  lead = src[: len(src) - len(src.lstrip())]
  trail = src[len(src.rstrip()):]
  return lead + dst.strip() + trail


class Translator:
  def __init__(self, lang, db_path):
    self.lang = lang
    self.db = sqlite3.connect(db_path)
    self.db.execute("CREATE TABLE IF NOT EXISTS tm (key TEXT PRIMARY KEY, src TEXT, dst TEXT, lang TEXT, concise INT)")
    self.stats = {"model_calls": 0, "tm_hits": 0, "retries": 0}

  def translate(self, seg, concise=False):
    """→ list of run texts, or None if the tag structure could not be preserved."""
    src = seg.source
    key = hashlib.sha1(f"{self.lang}|{int(concise)}|{src}".encode()).hexdigest()
    row = self.db.execute("SELECT dst FROM tm WHERE key=?", (key,)).fetchone()
    if row:
      self.stats["tm_hits"] += 1
      return json.loads(row[0])
    n = len(seg.nodes)
    runs = None
    for attempt in range(MAX_TRIES):
      self.stats["model_calls"] += 1
      if attempt:
        self.stats["retries"] += 1
      out = ollama(prompt_for(src, LANGS[self.lang]["name"], concise), temperature=0.7 if attempt == 0 else 0.2)
      runs = [out] if n == 1 else split_tagged(out, n)
      if runs is not None:
        break
    if runs is None:
      return None
    runs = [keep_edges(node.text or "", r) for node, r in zip(seg.nodes, runs)]
    self.db.execute("INSERT OR REPLACE INTO tm VALUES (?,?,?,?,?)", (key, src, json.dumps(runs), self.lang, int(concise)))
    self.db.commit()
    return runs


# ── DesignCraft verification ──

def dc_run(idml, cmd):
  out = subprocess.run([DESIGNCRAFT, "run", "--in", str(idml), "--cmd", cmd],
                       capture_output=True, text=True, encoding="utf-8").stdout
  data = json.loads(out.splitlines()[0])
  return data.get("result", data) if isinstance(data, dict) else data


def dc_inspect(idml):
  return dc_run(idml, "document.inspect")


def story_files_for(idml, story_ids, trees):
  """DesignCraft renumbers stories on import: match each one to its IDML file by text."""
  norm = lambda s: re.sub(r"\s+", "", s)
  texts = {name: norm("".join(c.text or "" for c in t.iter("Content"))) for name, t in trees.items()}
  files = set()
  for sid in story_ids:
    text = norm(dc_run(idml, "story.get=" + json.dumps({"story": sid})).get("text", ""))
    best = max(texts, key=lambda n: difflib.SequenceMatcher(None, texts[n], text).quick_ratio())
    files.add(best)
  return files


def geometry(inspect):
  """Every page item's id/kind/bounds, independent of text content."""
  items = []
  for sp in inspect["spreads"]:
    for it in sp.get("items", []):
      items.append({k: it.get(k) for k in ("id", "kind", "bounds", "rotation", "page") if k in it})
  return items


def overset_stories(inspect):
  return [s["id"] for s in inspect["stories"] if s.get("overset")]


def export_pages(idml, prefix, pages):
  args = [DESIGNCRAFT, "run", "--in", str(idml)]
  for p in range(1, pages + 1):
    args += ["--page", str(p), "--export", f"{prefix}_p{p}.png"]
  subprocess.run(args, capture_output=True, text=True)


# ── Package I/O ──

def write_package(src_idml, out_idml, story_trees):
  with zipfile.ZipFile(src_idml) as zin, zipfile.ZipFile(out_idml, "w") as zout:
    for info in zin.infolist():
      data = zin.read(info.filename)
      if info.filename in story_trees:
        data = etree.tostring(story_trees[info.filename], xml_declaration=True, encoding="UTF-8", standalone=True)
      # IDML requires 'mimetype' first and stored uncompressed; keep each entry's original compression.
      zout.writestr(info, data, compress_type=info.compress_type)


def main():
  src_idml, out_idml, lang = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
  work = out_idml.with_suffix("")
  t0 = time.time()

  parser = etree.XMLParser(remove_blank_text=False, strip_cdata=False, resolve_entities=False)
  trees, segments = {}, []
  with zipfile.ZipFile(src_idml) as z:
    for name in z.namelist():
      if name.startswith("Stories/") and name.endswith(".xml"):
        tree = etree.fromstring(z.read(name), parser)
        trees[name] = tree
        segments += segment_story(name, tree.find("Story"))

  todo = [s for s in segments if s.translatable()]
  tagged = sum(1 for s in todo if len(s.nodes) > 1)
  print(f"{len(trees)} stories, {len(segments)} segments, {len(todo)} to translate ({tagged} with inline tags)")

  tr = Translator(lang, work.parent / f"tm_{lang}.sqlite")
  failed = []

  def apply(seg, concise=False):
    runs = tr.translate(seg, concise)
    if runs is None:
      failed.append(seg)
      return
    for node, text in zip(seg.nodes, runs):
      node.text = text
      csr = node.content.getparent()
      if csr.tag == "CharacterStyleRange":
        csr.set("AppliedLanguage", LANGS[lang]["idml"])

  for i, seg in enumerate(todo, 1):
    apply(seg)
    print(f"\r  translated {i}/{len(todo)}", end="", flush=True)
  print()
  write_package(src_idml, out_idml, trees)

  # Verify with DesignCraft; for overset stories, ask for concise translations once.
  before = dc_inspect(src_idml)
  after = dc_inspect(out_idml)
  over = overset_stories(after)
  if over:
    print(f"overset stories {over} → retranslating concisely")
    story_files = story_files_for(out_idml, over, trees)
    for seg in todo:
      if seg.story in story_files and seg not in failed:
        apply(seg, concise=True)
    write_package(src_idml, out_idml, trees)
    after = dc_inspect(out_idml)
    over = overset_stories(after)

  geo_same = geometry(before) == geometry(after)
  pages = after["pageCount"]
  export_pages(src_idml, str(work) + "_src", pages)
  export_pages(out_idml, str(work), pages)

  report = {
    "input": str(src_idml), "output": str(out_idml), "target": lang, "seconds": round(time.time() - t0, 1),
    "segments": len(todo), "with_inline_tags": tagged, **tr.stats,
    "tag_failures_kept_in_source_language": [s.source for s in failed],
    "geometry_identical": geo_same,
    "overset_stories_remaining": over,
    "overset_stories_in_source": overset_stories(before),
  }
  Path(str(work) + "_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
  print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
  main()
