import json, subprocess, sys, os
from pathlib import Path
import fitz

DC = r"C:\Program Files\DesignCraft\designcraft-cli.exe"
HERE = Path(__file__).parent
VAR = HERE / "var"
PDF = HERE / "pdf"; PDF.mkdir(exist_ok=True)
PNG = HERE / "hpng"; PNG.mkdir(exist_ok=True)


def run(idml, *args):
  p = subprocess.run([DC, "run", "--in", str(idml), *args], capture_output=True, text=True, encoding="utf-8")
  return p.returncode, [json.loads(l) for l in p.stdout.splitlines() if l.startswith(("{", "["))], p.stderr


def lines_in_frame(pdf, page_no, rect):
  doc = fitz.open(pdf)
  pg = doc[page_no]
  out = []
  d = pg.get_text("dict", clip=fitz.Rect(*rect))
  for b in d["blocks"]:
    for l in b.get("lines", []):
      t = "".join(s["text"] for s in l["spans"])
      fonts = sorted({s["font"] for s in l["spans"]})
      out.append((round(l["bbox"][1], 1), t, fonts))
  out.sort()
  return out


rows = []
for f in sorted(VAR.glob("hy_*.idml")):
  pdf = PDF / (f.stem + ".pdf")
  rc, res, err = run(f, "--cmd", 'story.get={"story":9}', "--cmd",
                     "file.exportPdf=" + json.dumps({"path": pdf.as_posix(), "pages": [2]}),
                     "--page", "1", "--export", (PNG / (f.stem + ".png")).as_posix())
  st = res[0]
  # frame u1f now [42,182,162,520] on page 2 (page-relative == spread-relative for left page)
  lines = lines_in_frame(pdf, 0, (40, 178, 166, 524))
  hy = [t for _, t, _ in lines if t.rstrip().endswith(("-", "\u00ad", "\u2010"))]
  rows.append((f.stem, st["lines"], len(hy), [t for _, t, _ in lines]))
  print(f"{f.stem:22s} lines={st['lines']:2d} hyphenated_lines={len(hy)}  overset={st.get('overset')} err={err.strip()[:80]}")
json.dump(rows, open(HERE / "hyph_results.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
