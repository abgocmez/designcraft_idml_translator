"""DesignCraft verification prototype for idml-translate (research snippet, not production code).

DesignCraft is used ONLY to verify an IDML (never to write text). Findings this encodes:
  * `designcraft-cli run` prints one JSON value per --cmd on stdout (not wrapped in {"result":..});
    "wrote X (...)" export notices and errors ("designcraft-cli: no such page") go to stderr.
  * `--page N` is a 0-based page index (page *position*, across spreads). An out-of-range index aborts
    the whole invocation with exit code 1 -> the old prototype's `--page 1..4` exported pages 2,3,4 only.
  * DC story ids are renumbered; they follow the order of <idPkg:Story src=...> in designmap.xml
    (NOT StoryList), and may skip numbers. Frame bounds in document.inspect are spread coordinates
    with the spread's leftmost page top-left at (0,0) -> structural mapping via geometry.
  * Parent (master) spread items are not listed in document.inspect -> rank fallback for those stories.
  * preflight.run reports kind="missingGlyphs" ("Missing glyphs in <Family> <Style>: c c c"),
    kind="missingFont", kind="overset" (item = DC frame id, page = 0-based page index).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

from lxml import etree

DESIGNCRAFT = os.environ.get("DESIGNCRAFT_CLI", r"C:\Program Files\DesignCraft\designcraft-cli.exe")
ENV = {**os.environ, "PYTHONIOENCODING": "utf-8"}


class DCError(RuntimeError):
  pass


# ── CLI wrapper ─────────────────────────────────────────────────────────────

def _fwd(p) -> str:
  """Paths inside --cmd JSON must use forward slashes on Windows."""
  return str(Path(p).resolve()).replace("\\", "/")


def dc_raw(args: list[str]) -> tuple[list, list[str], int]:
  p = subprocess.run([DESIGNCRAFT, *args], capture_output=True, text=True, encoding="utf-8", env=ENV)
  out = []
  for line in p.stdout.splitlines():
    line = line.strip()
    if line:
      try:
        out.append(json.loads(line))
      except json.JSONDecodeError:  # e.g. `--version` text; never seen for --cmd results
        out.append({"_text": line})
  return out, p.stderr.splitlines(), p.returncode


def dc_run(idml, cmds: list[str]) -> list:
  """Run commands (each 'id' or 'id=JSON') against one IDML; returns one JSON value per command."""
  args = ["run", "--in", str(idml)]
  for c in cmds:
    args += ["--cmd", c]
  out, err, rc = dc_raw(args)
  if rc != 0 or len(out) != len(cmds):
    raise DCError(f"designcraft rc={rc} got {len(out)}/{len(cmds)} results; stderr={err}")
  return out


def cmd(cid: str, params: dict | None = None) -> str:
  return cid if params is None else f"{cid}={json.dumps(params, ensure_ascii=False)}"


def inspect(idml) -> dict:
  return dc_run(idml, ["document.inspect"])[0]


# ── geometry / overset ─────────────────────────────────────────────────────

def _page_of(bounds, pages):
  cx, cy = (bounds[0] + bounds[2]) / 2, (bounds[1] + bounds[3]) / 2
  for pg in pages:
    b = pg["bounds"]
    if b[0] <= cx <= b[2] and b[1] <= cy <= b[3]:
      return pg["index"]
  return None  # pasteboard


def geometry(insp: dict, ndigits: int = 3) -> list[dict]:
  """Text-independent layout fingerprint: every page item's id/kind/bounds/spread/page (+columns, story)."""
  items = []
  for sp in insp["spreads"]:
    for it in sp.get("items", []):
      items.append({
        "id": it["id"], "kind": it["kind"], "spread": sp["index"],
        "page": _page_of(it["bounds"], sp["pages"]),
        "bounds": [round(v, ndigits) for v in it["bounds"]],
        "columns": it.get("columns"), "story": it.get("story"),
        "rotation": it.get("rotation"),  # not emitted by DC 0.6.0 (always None)
      })
  return items


def geometry_diff(a: dict, b: dict, tol: float = 0.01) -> list[str]:
  ga = {g["id"]: g for g in geometry(a)}
  gb = {g["id"]: g for g in geometry(b)}
  diffs = [f"item {i} missing in output" for i in ga.keys() - gb.keys()]
  diffs += [f"item {i} new in output" for i in gb.keys() - ga.keys()]
  for i in ga.keys() & gb.keys():
    x, y = ga[i], gb[i]
    for k in ("kind", "spread", "page", "columns", "story"):
      if x[k] != y[k]:
        diffs.append(f"item {i} {k}: {x[k]} -> {y[k]}")
    if any(abs(p - q) > tol for p, q in zip(x["bounds"], y["bounds"])):
      diffs.append(f"item {i} bounds: {x['bounds']} -> {y['bounds']}")
  if len(a["spreads"]) != len(b["spreads"]) or a["pageCount"] != b["pageCount"]:
    diffs.append(f"pages/spreads changed: {a['pageCount']}/{len(a['spreads'])} -> {b['pageCount']}/{len(b['spreads'])}")
  return diffs


def overset(insp: dict) -> list[int]:
  """DC story ids that are overset. NB: story.get returns overset=null; use document.inspect."""
  return [s["id"] for s in insp["stories"] if s.get("overset")]


# ── story mapping: DC story id -> Stories/Story_uXX.xml ─────────────────────

def _mat(s):
  a, b, c, d, e, f = map(float, s.split())
  return (a, b, c, d, e, f)


def _mul(m, n):  # apply m then n (IDML row-vector convention)
  a, b, c, d, e, f = m
  A, B, C, D, E, F = n
  return (a * A + b * C, a * B + b * D, c * A + d * C, c * B + d * D, e * A + f * C + E, e * B + f * D + F)


def _apply(m, x, y):
  a, b, c, d, e, f = m
  return (a * x + c * y + e, b * x + d * y + f)


def _frames_in_spread(root):
  """Yield (Self, ParentStory, bbox) for every TextFrame (recursing into groups), in spread coords."""
  ident = (1, 0, 0, 1, 0, 0)

  def walk(el, m):
    for ch in el:
      if not isinstance(ch.tag, str):
        continue
      mm = _mul(_mat(ch.get("ItemTransform")), m) if ch.get("ItemTransform") else m
      if ch.tag == "TextFrame":
        pts = [tuple(map(float, p.get("Anchor").split())) for p in ch.iter("PathPointType")]
        tp = [_apply(mm, x, y) for x, y in pts]
        xs, ys = [p[0] for p in tp], [p[1] for p in tp]
        yield ch.get("Self"), ch.get("ParentStory"), (min(xs), min(ys), max(xs), max(ys))
      if ch.tag in ("Group", "TextFrame", "Rectangle", "Oval", "Polygon"):
        yield from walk(ch, mm)  # groups; frames with anchored content are not page items in DC

  sp = root.find("Spread")
  if sp is None:
    sp = root.find("MasterSpread")
  sm = _mat(sp.get("ItemTransform", "1 0 0 1 0 0"))
  # page offset: top-left of the left-most/top-most page
  tl = []
  for pg in sp.findall("Page"):
    gb = list(map(float, pg.get("GeometricBounds").split()))  # top left bottom right
    pm = _mul(_mat(pg.get("ItemTransform")), sm)
    tl.append(_apply(pm, gb[1], gb[0]))
  ox, oy = min(p[0] for p in tl), min(p[1] for p in tl)
  for self_, story, (x0, y0, x1, y1) in walk(sp, sm):
    yield self_, story, (x0 - ox, y0 - oy, x1 - ox, y1 - oy)


def story_map(idml_path, insp: dict, tol: float = 0.5) -> dict[int, str]:
  """Map DC story ids -> 'Stories/Story_uXX.xml'.

  1. Structural/geometric (primary): the i-th designmap <idPkg:Spread> is DC spread i; a DC text frame
     whose bounds match an IDML TextFrame within `tol` pt gives DC story -> ParentStory.
  2. Rank fallback (parent-page stories, anything not on a page): DC numbers stories in the order of
     <idPkg:Story src> in designmap; sorted DC ids are zipped with that order. The fallback is only
     used if it agrees with every geometric match (otherwise it raises).
  Works on translated output (no text involved).
  """
  with zipfile.ZipFile(idml_path) as z:
    dm = etree.fromstring(z.read("designmap.xml"))
    ns = {"idPkg": "http://ns.adobe.com/AdobeInDesign/idml/1.0/packaging"}
    spread_srcs = [e.get("src") for e in dm.findall("idPkg:Spread", ns)]
    story_srcs = [e.get("src") for e in dm.findall("idPkg:Story", ns)]
    self_to_src = {}
    for src in story_srcs:
      st = etree.fromstring(z.read(src)).find("Story")
      self_to_src[st.get("Self")] = src
    frames_by_spread = [list(_frames_in_spread(etree.fromstring(z.read(s)))) for s in spread_srcs]

  geo: dict[int, str] = {}
  conflicts = []
  for sp in insp["spreads"]:
    cands = frames_by_spread[sp["index"]] if sp["index"] < len(frames_by_spread) else []
    for it in sp["items"]:
      if it.get("story") is None:
        continue
      hit = [c for c in cands if all(abs(a - b) <= tol for a, b in zip(c[2], it["bounds"]))]
      if len(hit) != 1:
        continue
      src = self_to_src.get(hit[0][1])
      if geo.get(it["story"], src) != src:
        conflicts.append((it["story"], geo[it["story"]], src))
      geo[it["story"]] = src
  if conflicts:
    raise DCError(f"story_map geometric conflicts: {conflicts}")

  dc_ids = sorted(s["id"] for s in insp["stories"])
  rank = dict(zip(dc_ids, story_srcs)) if len(dc_ids) == len(story_srcs) else {}
  bad = [(k, v, rank.get(k)) for k, v in geo.items() if rank and rank.get(k) != v]
  if bad:
    raise DCError(f"rank order disagrees with geometry: {bad}")
  result = dict(rank)
  result.update(geo)
  missing = [i for i in dc_ids if i not in result]
  if missing:
    raise DCError(f"unmapped DC stories {missing} (story count {len(dc_ids)} vs designmap {len(story_srcs)})")
  story_map.last_methods = {k: ("geometry" if k in geo else "rank") for k in result}
  return result


# ── page export ─────────────────────────────────────────────────────────────

_WROTE = re.compile(r"wrote (.+?) \((\d+)×(\d+), ([\d.]+) ms, (\d+) glyphs\)")


def export_pngs(idml, out_prefix, page_count: int, scale: float | None = None) -> list[dict]:
  """One PNG per page: --page is a 0-based index. Files are named <prefix>_p<1-based>.png."""
  args = ["run", "--in", str(idml)]
  if scale:
    args += ["--scale", str(scale)]
  paths = []
  for i in range(page_count):
    p = f"{out_prefix}_p{i + 1}.png"
    paths.append(p)
    args += ["--page", str(i), "--export", p]
  _, err, rc = dc_raw(args)
  wrote = [m.groups() for m in map(_WROTE.search, err) if m]
  if rc != 0 or len(wrote) != page_count:
    raise DCError(f"export rc={rc}, wrote {len(wrote)}/{page_count}: {err}")
  return [{"path": p, "w": int(w), "h": int(h), "ms": float(ms), "glyphs": int(g)}
          for p, (_, w, h, ms, g) in zip(paths, wrote)]


def export_pdf(idml, pdf_path, pages=None) -> dict:
  params = {"path": _fwd(pdf_path)}
  if pages:
    params["pages"] = pages  # 1-based here (unlike --page)
  return dc_run(idml, [cmd("file.exportPdf", params)])[0]


# ── preflight / fonts / glyphs ──────────────────────────────────────────────

def preflight(idml) -> dict:
  """{'preflight': {errors, warnings, issues:[...]}, 'fonts': [...]} in one invocation."""
  pf, fonts = dc_run(idml, ["preflight.run", "font.list"])
  return {"preflight": pf, "fonts": fonts}


_MG = re.compile(r"^Missing glyphs in (.+?): (.*)$")


def missing_glyphs(pf: dict) -> dict[str, set[str]]:
  """Parse preflight missingGlyphs issues -> {'Family Style': {chars}}. Also lists fonts that are
  missing locally (their glyph coverage cannot be verified) under key '!unverifiable'."""
  res: dict[str, set[str]] = {}
  p = pf.get("preflight", pf)
  for iss in p["issues"]:
    if iss["kind"] == "missingGlyphs":
      m = _MG.match(iss["message"])
      if m:
        res.setdefault(m.group(1), set()).update(m.group(2).split())
  for f in pf.get("fonts", []):
    if f.get("missing") or f.get("styleMissing"):
      res.setdefault("!unverifiable", set()).add(f"{f['family']} {f['style']}")
  return res


def _issue_key(iss: dict):
  msg = re.sub(r"\d+", "#", iss.get("message", ""))
  if iss["kind"] == "missingGlyphs":
    msg = iss["message"].split(":")[0]
  return (iss["kind"], iss.get("item"), iss.get("page"), msg)


def new_issues(before: dict, after: dict) -> list[dict]:
  """Issues present in `after` but not in `before` (keyed on kind/item/page/message-without-numbers);
  for missingGlyphs, only newly missing characters count."""
  b = before.get("preflight", before)["issues"]
  a = after.get("preflight", after)["issues"]
  bkeys = {_issue_key(i) for i in b}
  out = [i for i in a if _issue_key(i) not in bkeys and i["kind"] != "missingGlyphs"]
  mb, ma = missing_glyphs(before), missing_glyphs(after)
  for font, chars in ma.items():
    extra = chars - mb.get(font, set())
    if extra:
      out.append({"kind": "missingGlyphs" if font != "!unverifiable" else "missingFont",
                  "font": font, "chars": sorted(extra), "severity": "error"})
  return out


# ── self-test ───────────────────────────────────────────────────────────────

def _timed(fn, *a, n=3):
  ts = []
  for _ in range(n):
    t = time.perf_counter(); r = fn(*a); ts.append(time.perf_counter() - t)
  return r, min(ts), sum(ts) / n


if __name__ == "__main__":
  sys.stdout.reconfigure(encoding="utf-8")
  DEMO = Path(r"C:\Programming\craft-studio\idml-demo")
  sample = DEMO / "sample_en.idml"
  outs = {"tr": DEMO / "out" / "sample_tr.idml", "de": DEMO / "out" / "sample_de.idml"}
  tmp = Path(tempfile.mkdtemp(prefix="dcverify_"))

  print("== inspect / determinism")
  base, tmin, tavg = _timed(inspect, sample)
  print(f"sample: pageCount={base['pageCount']} spreads={len(base['spreads'])} stories={len(base['stories'])} "
        f"inspect {tmin*1000:.0f} ms (min of 3)")
  again = inspect(sample)
  print("inspect deterministic across runs:", json.dumps(base, sort_keys=True) == json.dumps(again, sort_keys=True))

  print("\n== story_map (geometry + rank fallback)")
  smap = story_map(sample, base)
  for k in sorted(smap):
    print(f"  dc {k:2d} -> {smap[k]:24s} via {story_map.last_methods[k]}")
  # verify against story text for the sample
  with zipfile.ZipFile(sample) as z:
    def txt(src):
      # skips <?ACE?> PIs; story.get text omits table cells (U+E009 anchor) and footnotes (U+E00A anchor)
      root = etree.fromstring(z.read(src))
      return "".join(root.xpath("//Content[not(ancestor::Table) and not(ancestor::Footnote)]/descendant::text()"))
    got = dc_run(sample, [cmd("story.get", {"story": k}) for k in sorted(smap)])
    norm = lambda t: re.sub(r"[\s\ue000-\uf8ff\u2028\u2029]+", "", t)
    bad = [(g["id"], g["text"][:40], txt(smap[g["id"]])[:40]) for g in got
           if norm(g["text"]) != norm(txt(smap[g["id"]]))]
    print(f"  text check on sample: {len(got) - len(bad)}/{len(got)} stories identical; mismatches: {bad}")

  # rank fallback robustness: reverse the <idPkg:Story> order in a copy (DC renumbers accordingly)
  rev = tmp / "pkg_reversed.idml"
  with zipfile.ZipFile(sample) as zin, zipfile.ZipFile(rev, "w") as zout:
    for info in zin.infolist():
      data = zin.read(info.filename)
      if info.filename == "designmap.xml":
        d = data.decode("utf-8")
        refs = re.findall(r'\s*<idPkg:Story src="[^"]*"/>', d)
        data = d.replace("".join(refs), "".join(reversed(refs))).encode("utf-8")
      zout.writestr(info, data, compress_type=info.compress_type)
  rins = inspect(rev)
  rmap = story_map(rev, rins)
  f2s = lambda ins, m: {f: m[s["id"]] for s in ins["stories"] for f in s["frames"]}  # DC frame ids are stable
  print("  reversed <idPkg:Story> order: DC ids", sorted(rmap)[:4], "...; frame->file mapping identical to sample:",
        f2s(rins, rmap) == f2s(base, smap), "; methods:",
        {m: list(story_map.last_methods.values()).count(m) for m in ("geometry", "rank")})

  for lang, p in outs.items():
    ins = inspect(p)
    m = story_map(p, ins)
    print(f"\n== {lang.upper()} output {p.name}")
    print("  story_map identical to sample:", m == smap)
    gd = geometry_diff(base, ins)
    print("  geometry diffs vs sample:", gd or "none")
    ov = overset(ins)
    print("  overset DC stories:", ov, "->", [m[i] for i in ov])
    pf_b, pf_a = preflight(sample), preflight(p)
    print("  preflight:", json.dumps(pf_a["preflight"], ensure_ascii=False))
    print("  new issues vs source:", json.dumps(new_issues(pf_b, pf_a), ensure_ascii=False))
    print("  missing glyphs:", missing_glyphs(pf_a) or "none")

  print("\n== export_pngs (4 pages, 0-based --page)")
  t = time.perf_counter()
  res = export_pngs(sample, str(tmp / "sample"), base["pageCount"])
  wall = time.perf_counter() - t
  for r in res:
    print(f"  {Path(r['path']).name}: {r['w']}x{r['h']} render {r['ms']} ms, {r['glyphs']} glyphs")
  print(f"  wall for all 4: {wall*1000:.0f} ms")

  print("\n== timings (wall, min of 3 runs, includes process start)")
  def t_cmds(cmds):
    return _timed(dc_run, sample, cmds)[1]
  rows = {
    "document.inspect": t_cmds(["document.inspect"]),
    "preflight.run": t_cmds(["preflight.run"]),
    "font.list": t_cmds(["font.list"]),
    "story.get (1 story)": t_cmds([cmd("story.get", {"story": 11})]),
    "18x story.get in one run": t_cmds([cmd("story.get", {"story": k}) for k in sorted(smap)]),
    "inspect+preflight+font.list in one run": t_cmds(["document.inspect", "preflight.run", "font.list"]),
    "file.exportPdf (4 pages)": _timed(export_pdf, sample, tmp / "s.pdf")[1],
    "export_pngs (4 pages)": _timed(export_pngs, sample, str(tmp / "t"), 4)[1],
    "no-op open (version)": _timed(dc_raw, ["--version"])[1],
  }
  for k, v in rows.items():
    print(f"  {k:42s} {v*1000:7.0f} ms")

  print("\n== missing-glyph check on a synthetic preflight result")
  fake = {"issues": [{"kind": "missingGlyphs", "message": "Missing glyphs in Bell MT Regular: ğ Ğ ş Ş İ ẞ", "severity": "error"}]}
  print("  ", missing_glyphs(fake))
  print("\nOK")
