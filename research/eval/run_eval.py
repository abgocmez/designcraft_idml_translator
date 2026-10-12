"""R3 evaluation harness: Hy-MT2-7B prompt templates for idml-translate.

Stdlib only; talks to Ollama at 127.0.0.1:11434 and nothing else.

usage:
  python research/eval/run_eval.py                 # run every stage from scratch, then report
  python research/eval/run_eval.py --resume        # reuse calls already in results/raw.jsonl
  python research/eval/run_eval.py --stages main,caps --resume
  python research/eval/run_eval.py --report-only   # recompute metrics/tables from raw.jsonl

Stages: main, caps, concise, sampling, multipara, retry, bleed, batching, throughput, options.
Outputs (research/eval/results/): raw.jsonl (every model call), metrics.jsonl (per call metrics),
summary.json, summary.md (tables pasted into research/prompts.md).
"""
import argparse
import collections
import hashlib
import json
import os
import re
import statistics
import sys
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
RES = HERE / "results"
OLLAMA = "http://127.0.0.1:11434"
MODEL = "hf.co/tencent/Hy-MT2-7B-GGUF:Q4_K_M"
SAMPLING = {"temperature": 0.7, "top_p": 0.6, "top_k": 20, "repeat_penalty": 1.05}
LANG = {"tr": "Turkish", "de": "German", "en": "English"}
SEED = 42
KEEP_ALIVE = "30m"
SYNOPSIS = ("Spring issue of a design magazine, 'Quarterly'; feature article about layout grids "
            "and typography.")
ROLE_DESC = {
  "headline": "headline", "kicker": "kicker (short section label above a headline)",
  "folio": "folio (page footer with page number and magazine name)", "table-header": "table column header",
  "table-cell": "table cell", "caption": "image caption", "body": "body text paragraph",
  "footnote": "footnote", "pullquote": "pull quote",
}

# ───────────────────────── templates ─────────────────────────

def t_v1(src, lang, **_):  # prototype default
  return (f"Translate the following text into {LANG[lang]}. Note that you should **only output the "
          f"translated result without any additional explanation**:\n\n{src}")


def t_v1b(src, lang, **_):  # Hy-MT model card, XX<=>XX default
  return f"Translate the following segment into {LANG[lang]}, without additional explanation.\n\n{src}"


def terms_block(item, lang):
  lines = [f"{s} translates to {t}" for s, t in item.get("glossary", {}).get(lang, [])]
  lines += [f"{d} translates to {d}" for d in item.get("dnt", [])]
  return lines


def t_v2(src, lang, item, **_):  # Terminology (+ DNT as identity terms) + default
  lines = terms_block(item, lang)
  if not lines:
    return t_v1b(src, lang)
  return ("Refer to the following translation:\n" + "\n".join(lines) + "\n\n" + t_v1b(src, lang))


def context_block(item):
  out = [f"Document: {SYNOPSIS}", f"Paragraph style: {item['style']}",
         f"Segment role: {ROLE_DESC.get(item['role'], item['role'])}"]
  if item.get("prev"):
    out.append(f"Previous paragraph: {clip(item['prev'])}")
  if item.get("next"):
    out.append(f"Next paragraph: {clip(item['next'])}")
  return "\n".join(out)


def clip(s, n=300):
  s = re.sub(r"<[^>]+>", "", s)
  return s if len(s) <= n else s[:n].rsplit(" ", 1)[0] + " …"


def t_v4(src, lang, item, glossary=False, **_):  # Structured Data 2 / contextual (background)
  head = ""
  if glossary:
    lines = terms_block(item, lang)
    if lines:
      head = "Refer to the following translation:\n" + "\n".join(lines) + "\n\n"
  return (head + context_block(item) + "\n\n"
          f"Refer to the information above and translate the following text into {LANG[lang]}. Note that "
          f"you do not need to translate the information above, and do not add any explanation:\n\n{src}")


MARKER_RE = re.compile(r"</?g\d+>|<x\d+/>|⟦\d+⟧|\{\d+\}|\[\[\d+\]\]")


def t_v3(src, lang, item=None, glossary=False, context=False, concise=False, **_):  # Structured Data 1
  markers = MARKER_RE.findall(src)
  if any(m.startswith("<g") or m.startswith("</g") for m in markers):
    what = "tag (<g0>, </g0>, <g1>, …)"
    rule1 = ("1. **Structure Preservation:** You MUST keep every tag (<g0>, </g0>, <g1>, …) exactly once, "
             "in the same order, wrapping the words that correspond to the original.\n")
  else:
    what = "placeholder (" + ", ".join(dict.fromkeys(markers)) + ")"
    rule1 = (f"1. **Structure Preservation:** You MUST keep every {what} exactly once, in the same order, "
             "at the position that corresponds to the original.\n")
  style = " Keep it concise." if concise else ""
  head = ""
  if glossary and item is not None:
    lines = terms_block(item, lang)
    if lines:
      head = "### Terminology\n" + "\n".join(lines) + "\n\n"
  ctx = ("### Context (do not translate)\n" + context_block(item) + "\n\n") if context else ""
  return (
    "### Task\n"
    f"Translate the user-facing text within the following XML data into {LANG[lang]}.{style}\n\n"
    + head + ctx +
    "### Strict Rules\n" + rule1 +
    "2. **Selective Translation:** Translate ONLY the text between the tags.\n"
    "3. **Strict Non-Translation:** NEVER translate, rename, add or remove tags.\n"
    "Output ONLY the translated XML.\n\n"
    f"### Source Data\n{src}"
  )


def t_v3b(src, lang, **_):  # Hunyuan-MT (v1) "formatted translation" template, English rendering
  return (f"Translate the text between <source></source> into {LANG[lang]}. Only output the translated "
          "result without any additional explanation. The <gN></gN> tags in the source mark text that "
          "carries formatting; keep each tag at the corresponding position in the translation. Output "
          f"format: <target>str</target>\n\n<source>{src}</source>")


def t_v5a(src, lang, **_):  # prototype concise (Style)
  return (f"Please translate the following text into {LANG[lang]}. Note that the translation style "
          f"must strictly conform to [**concise: as short as possible while keeping the full meaning**]:\n\n{src}")


def t_v5b(src, lang, **_):  # Style "concise", keeping every statement
  return (f"Please translate the following text into {LANG[lang]}. Note that the translation style must "
          f"strictly conform to [**concise**]. Keep every statement, name and number of the original; "
          f"shorten only the wording:\n\n{src}")


VARIANTS = {
  "V1": t_v1, "V1b": t_v1b, "V2": t_v2,
  "V4": t_v4, "V4g": lambda s, l, item, **k: t_v4(s, l, item, glossary=True),
  "V3": t_v3, "V3g": lambda s, l, item, **k: t_v3(s, l, item, glossary=True),
  "V3cg": lambda s, l, item, **k: t_v3(s, l, item, glossary=True, context=True),
  "V3b": t_v3b, "V5a": t_v5a, "V5b": t_v5b,
}
PLAIN_VARIANTS = ["V1", "V1b", "V2", "V4", "V4g"]
MARKUP_VARIANTS = ["V3", "V3g", "V3cg", "V3b"]

# ───────────────────────── ollama ─────────────────────────

_raw_lock = threading.Lock()
CACHE = {}
RAW_FH = None


def call_key(**kw):
  return hashlib.sha1(json.dumps(kw, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def ollama(prompt, options=None, tag=None, seed=SEED, use_cache=True):
  """→ record dict with output and timings. tag = metadata for raw.jsonl."""
  opts = dict(SAMPLING)
  opts["num_predict"] = 1024
  if options:
    opts.update(options)
  if seed is not None:
    opts["seed"] = seed
  key = call_key(prompt=prompt, options=opts, tag={k: v for k, v in (tag or {}).items() if k in ("rep",)},
                 stage=(tag or {}).get("stage"))
  if use_cache and key in CACHE:
    return CACHE[key]
  body = json.dumps({"model": MODEL, "stream": False, "keep_alive": KEEP_ALIVE, "options": opts,
                     "messages": [{"role": "user", "content": prompt}]}).encode("utf-8")
  req = urllib.request.Request(OLLAMA + "/api/chat", body, {"Content-Type": "application/json"})
  t0 = time.perf_counter()
  with urllib.request.urlopen(req, timeout=600) as r:
    data = json.loads(r.read().decode("utf-8"))
  wall = time.perf_counter() - t0
  rec = {"key": key, **(tag or {}), "prompt": prompt, "options": opts,
         "raw_output": data["message"]["content"], "output": data["message"]["content"].strip(),
         "wall_s": round(wall, 3), "done_reason": data.get("done_reason"),
         "prompt_tokens": data.get("prompt_eval_count"), "eval_tokens": data.get("eval_count"),
         "eval_s": round((data.get("eval_duration") or 0) / 1e9, 3),
         "load_s": round((data.get("load_duration") or 0) / 1e9, 3), "ts": time.time()}
  with _raw_lock:
    CACHE[key] = rec
    RAW_FH.write(json.dumps(rec, ensure_ascii=False) + "\n")
    RAW_FH.flush()
  return rec


# ───────────────────────── metrics ─────────────────────────

TAG_RE = re.compile(r"</?g\d+>")
PH_RE = {"uni": re.compile(r"⟦\d+⟧"), "brace": re.compile(r"\{\d+\}"), "xml": re.compile(r"<x\d+/>"),
         "dbl": re.compile(r"\[\[\d+\]\]")}
NUM_RE = re.compile(r"\d+(?:[.,]\d+)*")
STRIP_MARK = re.compile(r"</?g\d+>|<x\d+/>|⟦\d+⟧|\{\d+\}|\[\[\d+\]\]")
EN_STOP = set("""a an the and or but if of to in on at by for with from as is are was were be been being it its
this that these those there here what which who whom when where why how all any each every no not only own same so
than too very can will just should now one ones their them they his her him he she we our you your i me my into over
under out up down off again further then once also more most other some such do does did doing have has had having
about between through during before after above below while until because must let lets per""".split())
EXPLAIN_RE = re.compile(r"^\s*(here is|here's|sure|certainly|translation|translated|the translation|"
                        r"übersetzung|çeviri|türkçe|deutsch|german|turkish)\b", re.I)
NOTE_RE = re.compile(r"\((note|hinweis|not|anmerkung)\b|\bnote:|hinweis:|anmerkung:|açıklama:", re.I)
LEAK_RE = re.compile(r"paragraph style|previous paragraph|next paragraph|segment role|document:|"
                     r"paragraf stili|önceki paragraf|sonraki paragraf|belge:|absatzformat:|vorheriger absatz|"
                     r"nächster absatz|dokument:|### |terminology|refer to", re.I)
QUOTES = "\"'“”„«»‚‘’"


def lower(s, lang):
  if lang == "tr":
    s = s.replace("İ", "i").replace("I", "ı")
  return s.lower()


def upper(s, lang):
  if lang == "tr":
    s = s.replace("i", "İ").replace("ı", "I")
  return s.upper()


def sentence_case(s):
  low = s.lower()
  return re.sub(r"[^\W\d_]", lambda m: m.group(0).upper(), low, count=1)


def tag_nesting_ok(s):
  stack = []
  for t in TAG_RE.findall(s):
    if t.startswith("</"):
      if not stack or stack[-1] != t[2:-1]:
        return False
      stack.pop()
    else:
      stack.append(t[1:-1])
  return not stack


def numbers(s):
  return collections.Counter(re.sub(r"[.,]", "", n) for n in NUM_RE.findall(STRIP_MARK.sub(" ", s)))


def numbers_strict(s):
  return collections.Counter(NUM_RE.findall(STRIP_MARK.sub(" ", s)))


def content_words(s, dnt=()):
  s = STRIP_MARK.sub(" ", s)
  for d in dnt:
    s = s.replace(d, " ")
  return [w for w in re.findall(r"[^\W\d_]+", s.lower()) if len(w) >= 4 and w not in EN_STOP]


def code_like(src, dnt=()):
  """True when the source has no alphabetic run of >= 3 letters outside DNT terms (CMYK builds, codes)."""
  s = STRIP_MARK.sub(" ", src)
  for d in dnt:
    s = s.replace(d, " ")
  return not re.search(r"[^\W\d_]{3,}", s)


def ref_check(ref, out, lang):
  if not ref:
    return None
  o = lower(out, lang)
  ok = True
  if ref.get("any_of"):
    ok &= any(lower(x, lang) in o for x in ref["any_of"])
  if ref.get("all_of"):
    ok &= all(lower(x, lang) in o for x in ref["all_of"])
  if ref.get("must_not"):
    ok &= not any(lower(x, lang) in o for x in ref["must_not"])
  if ref.get("must_not_cs"):
    ok &= not any(x in out for x in ref["must_not_cs"])
  return bool(ok)


def evaluate(item, lang, out, src=None):
  src = src if src is not None else item["source"]
  m = {}
  st, ot = TAG_RE.findall(src), TAG_RE.findall(out)
  if st:
    m["tag_multiset"] = collections.Counter(st) == collections.Counter(ot)
    m["tag_order"] = st == ot
    m["tag_nesting"] = tag_nesting_ok(out)
    m["tag_ok"] = m["tag_order"] and m["tag_nesting"]
    # text outside the tags (lost on injection) when the source had none
    src_out = TAG_RE.sub("", re.sub(r"<g(\d+)>.*?</g\1>", "", src, flags=re.S)).strip()
    out_out = TAG_RE.sub("", re.sub(r"<g(\d+)>.*?</g\1>", "", out, flags=re.S)).strip()
    m["tag_text_outside"] = bool(out_out) and not src_out
  fmt = item.get("ph_format")
  if fmt:
    sp, op = PH_RE[fmt].findall(src), PH_RE[fmt].findall(out)
    m["ph_multiset"] = collections.Counter(sp) == collections.Counter(op)
    m["ph_order"] = sp == op
    m["ph_ok"] = m["ph_multiset"] and m["ph_order"]
    if fmt == "uni":  # look-alike brackets the model may substitute: ⟨1⟩ 〚1〛 〔1〕 [1]
      norm = re.sub(r"[⟨〚〔\[](\d+)[⟩〛〕\]]", r"⟦\1⟧", out)
      m["ph_multiset_norm"] = collections.Counter(sp) == collections.Counter(PH_RE[fmt].findall(norm))
    else:
      m["ph_multiset_norm"] = m["ph_multiset"]
  if "\n" in src:
    m["nl_ok"] = out.count("\n") == src.count("\n")
  sn = numbers(src)
  if sn:
    m["numbers_ok"] = sn == numbers(out)
    m["numbers_strict_ok"] = numbers_strict(src) == numbers_strict(out)
  if item.get("dnt"):
    m["dnt_ok"] = all(d in out for d in item["dnt"])
  same = re.sub(r"\s+", " ", out).strip().casefold() == re.sub(r"\s+", " ", src).strip().casefold()
  m["identical"] = same
  m["code_like"] = code_like(src, item.get("dnt", ()))
  m["untranslated"] = same and not m["code_like"]
  cw = [w for w in content_words(src, item.get("dnt", ()))]
  if len(cw) >= 3:
    ol = out.lower()
    frac = sum(1 for w in cw if re.search(r"\b" + re.escape(w) + r"\b", ol)) / len(cw)
    m["src_word_frac"] = round(frac, 2)
    m["mostly_source"] = frac >= 0.5
  added = bool(EXPLAIN_RE.search(out)) and not EXPLAIN_RE.search(src)
  sq = src.strip()[:1] in QUOTES and src.strip()[-1:] in QUOTES
  oq = out.strip()[:1] in QUOTES and out.strip()[-1:] in QUOTES and len(out.strip()) > 1
  m["added_quotes"] = oq and not sq
  m["added_note"] = bool(NOTE_RE.search(out)) and not NOTE_RE.search(src)
  m["extra_lines"] = out.count("\n") > src.count("\n")
  m["context_leak"] = bool(LEAK_RE.search(out)) and not LEAK_RE.search(src)
  m["added_any"] = added or m["added_quotes"] or m["added_note"] or m["extra_lines"] or m["context_leak"]
  ls = len(STRIP_MARK.sub("", src).strip())
  m["len_ratio"] = round(len(STRIP_MARK.sub("", out).strip()) / max(1, ls), 3)
  r = ref_check(item.get("ref", {}).get(lang), out, lang)
  if r is not None:
    m["ref_ok"] = r
  if item.get("case") == "upper" and not m["code_like"]:
    letters = [c for c in STRIP_MARK.sub("", out) if c.isalpha()]
    m["case_ok"] = bool(letters) and all(c.isupper() for c in letters)
  return m


# ───────────────────────── stages ─────────────────────────

def load_items():
  return [json.loads(l) for l in open(HERE / "eval_set.jsonl", encoding="utf-8")]


def is_markup(it):
  return bool(MARKER_RE.search(it["source"]))


def run_parallel(jobs, workers=1):
  if workers <= 1:
    return [j() for j in jobs]
  with ThreadPoolExecutor(workers) as ex:
    return list(ex.map(lambda j: j(), jobs))


def progress(stage, i, n):
  print(f"\r  [{stage}] {i}/{n}", end="", flush=True)


def stage_main(items):
  out = []
  jobs = []
  for lang in ("tr", "de"):
    for it in items:
      vs = list(PLAIN_VARIANTS)
      if is_markup(it):
        vs += ["V3", "V3g", "V3cg"] + (["V3b"] if TAG_RE.search(it["source"]) else [])
      for v in vs:
        jobs.append((lang, it, v))
  for i, (lang, it, v) in enumerate(jobs, 1):
    p = VARIANTS[v](it["source"], lang, item=it)
    rec = ollama(p, tag={"stage": "main", "variant": v, "lang": lang, "id": it["id"]})
    o = rec["output"]
    if v == "V3b":
      mm = re.search(r"<target>(.*?)</target>", o, re.S)
      o = mm.group(1).strip() if mm else o
    out.append({"stage": "main", "variant": v, "lang": lang, "id": it["id"], "category": it["category"],
                "short": it["short"], "output": o, "wall_s": rec["wall_s"], "eval_tokens": rec["eval_tokens"],
                "prompt_tokens": rec["prompt_tokens"], "done_reason": rec["done_reason"],
                "metrics": evaluate(it, lang, o)})
    progress("main", i, len(jobs))
  print()
  return out


def stage_caps(items):
  """ALL CAPS: as-is vs sentence-case before translation + locale-aware upper afterwards."""
  out = []
  caps = [it for it in items if it.get("case") == "upper" and not code_like(it["source"], it["dnt"])]
  for lang in ("tr", "de"):
    for it in caps:
      for v in ("V1b", "V2", "V4", "V4g"):
        for mode in ("asis", "fold"):
          src = it["source"] if mode == "asis" else sentence_case(it["source"])
          rec = ollama(VARIANTS[v](src, lang, item=it), tag={"stage": "caps", "variant": v, "lang": lang,
                                                            "id": it["id"], "mode": mode})
          o = rec["output"] if mode == "asis" else upper(rec["output"], lang)
          out.append({"stage": "caps", "variant": v, "mode": mode, "lang": lang, "id": it["id"],
                      "sent": src, "model_output": rec["output"], "output": o, "metrics": evaluate(it, lang, o)})
  return out


def stem(w):
  for suf in ("ing", "edly", "ed", "es", "ly", "s"):
    if len(w) > 4 + len(suf) - 1 and w.endswith(suf):
      return w[: -len(suf)]
  return w


def cw_set(s):
  return {stem(w) for w in re.findall(r"[^\W\d_]+", STRIP_MARK.sub(" ", s).lower()) if len(w) >= 3 and w not in EN_STOP}


def recall(ref, cand):
  a, b = cw_set(ref), cw_set(cand)
  return round(len(a & b) / max(1, len(a)), 3)


GREEDY = {"temperature": 0.0, "top_k": 1}


def precall(ref, cand, k=5, n=4):
  """Content-word recall with 5-letter prefix matching (tolerates inflection: 'arrives'/'arrival')."""
  ws = lambda s: {w[:k] for w in re.findall(r"[^\W\d_]+", STRIP_MARK.sub(" ", s).lower()) if len(w) >= n and w not in EN_STOP}
  a, b = ws(ref), ws(cand)
  return round(len(a & b) / max(1, len(a)), 3)


def truncations(text):
  """Deliberate omissions built from a full translation: drop one sentence / drop one clause."""
  sents = re.split(r"(?<=[.!?])\s+", text.strip())
  out = []
  if len(sents) >= 2:
    k = max(range(1, len(sents)), key=lambda i: len(sents[i]))  # drop the longest non-first sentence
    out.append(("drop_sentence", " ".join(s for i, s in enumerate(sents) if i != k)))
  # drop the last comma/colon/dash clause of the longest sentence
  k = max(range(len(sents)), key=lambda i: len(sents[i]))
  s = sents[k]
  parts = re.split(r"(,\s+|:\s+|\s+[—–-]\s+)", s)
  if len(parts) >= 3:
    end = s[-1] if s[-1] in ".!?" else ""
    cut = "".join(parts[:-2]).rstrip(",;: ") + end
    out.append(("drop_clause", " ".join(cut if i == k else x for i, x in enumerate(sents))))
  return out


def stage_concise(items, main_rows):
  ids = ["r_cover_deck", "r_deck", "r_caption_hills", "r_body_1", "r_body_2", "r_body_3", "r_body_4",
         "r_body_5", "r_footnote", "t_two_runs"]
  by = {it["id"]: it for it in items}
  normal = {(r["lang"], r["id"]): r["output"] for r in main_rows if r["variant"] == "V1b"}
  out = []
  for lang in ("tr", "de"):
    for iid in ids:
      it = dict(by[iid])
      src = TAG_RE.sub("", it["source"]).strip()
      it["source"] = src
      norm = normal.get((lang, iid))
      if norm is None or TAG_RE.search(norm):
        norm = ollama(t_v1b(src, lang), tag={"stage": "concise", "kind": "normal", "lang": lang, "id": iid})["output"]
      norm = TAG_RE.sub("", norm)
      bt_norm = ollama(t_v1b(norm, "en"), tag={"stage": "concise", "kind": "bt", "lang": lang, "id": iid})["output"]
      bt0_norm = ollama(t_v1b(norm, "en"), options=GREEDY, tag={"stage": "concise", "kind": "bt0", "lang": lang, "id": iid})["output"]
      cands = []
      for v in ("V5a", "V5b"):
        rec = ollama(VARIANTS[v](src, lang), tag={"stage": "concise", "variant": v, "lang": lang, "id": iid})
        cands.append((v, "real", rec["output"]))
      for kind, txt in truncations(norm):
        cands.append(("trunc", kind, txt))
      for v, kind, txt in cands:
        bt = ollama(t_v1b(txt, "en"), tag={"stage": "concise", "kind": "bt", "lang": lang, "id": iid})["output"]
        bt0 = ollama(t_v1b(txt, "en"), options=GREEDY, tag={"stage": "concise", "kind": "bt0", "lang": lang, "id": iid})["output"]
        out.append({"stage": "concise", "variant": v, "kind": kind, "lang": lang, "id": iid, "output": txt,
                    "normal": norm, "bt": bt, "bt_normal": bt_norm,
                    "len_vs_normal": round(len(txt) / max(1, len(norm)), 3),
                    "recall_src": recall(src, bt), "recall_normal_bt": recall(bt_norm, bt),
                    "recall_src_of_normal_bt": recall(src, bt_norm),
                    "bt0": bt0, "bt0_normal": bt0_norm, "p_src0": precall(src, bt0),
                    "p_src0_normal": precall(src, bt0_norm),
                    "p_delta0": round(precall(src, bt0) - precall(src, bt0_norm), 3),
                    "p_bt0_vs_bt0": precall(bt0_norm, bt0),
                    "numbers_ok": numbers(src) == numbers(txt), "metrics": evaluate(it, lang, txt, src)})
  return out


FAILURE_PRONE = ["r_headline_grid", "r_kicker_feature", "r_td_pullquotes", "r_folio_quarterly", "r_kicker_next",
                 "r_th_build", "r_td_kickers_rules", "r_td_bg_heads", "r_th_swatch", "c_feature"]


def stage_sampling(items):
  by = {it["id"]: it for it in items}
  out = []
  for lang in ("tr", "de"):
    for iid in FAILURE_PRONE:
      it = by[iid]
      for v in ("V1b", "V2", "V4", "V4g"):
        for temp in (0.7, 0.2):
          for rep in range(3):
            rec = ollama(VARIANTS[v](it["source"], lang, item=it), options={"temperature": temp}, seed=None,
                         tag={"stage": "sampling", "variant": v, "lang": lang, "id": iid, "temp": temp, "rep": rep})
            out.append({"stage": "sampling", "variant": v, "lang": lang, "id": iid, "temp": temp, "rep": rep,
                        "output": rec["output"], "metrics": evaluate(it, lang, rec["output"])})
    # fixed seed determinism check
    for iid in FAILURE_PRONE[:3]:
      it = by[iid]
      for rep in range(3):
        rec = ollama(t_v4(it["source"], lang, it), tag={"stage": "sampling", "variant": "V4-seed42", "lang": lang,
                                                         "id": iid, "rep": rep})
        out.append({"stage": "sampling", "variant": "V4-seed42", "lang": lang, "id": iid, "temp": 0.7, "rep": rep,
                    "output": rec["output"], "metrics": evaluate(it, lang, rec["output"])})
  return out


def stage_multipara(items):
  ids = ["ph_br_uni", "ph_br_brace", "ph_br_xml", "ph_br_dbl", "nl_br", "t_cover_pair"]
  by = {it["id"]: it for it in items}
  out = []
  for lang in ("tr", "de"):
    for iid in ids:
      it = dict(by[iid])
      it["prev"] = "THE SPRING ISSUE  ·  NO. 01"
      it["next"] = "Grids, type and color: how great pages are made — and the tools that make them."
      for v in ("V4", "V3cg", "V3"):
        for rep in range(3):
          rec = ollama(VARIANTS[v](it["source"], lang, item=it), seed=None,
                       tag={"stage": "multipara", "variant": v, "lang": lang, "id": iid, "rep": rep})
          out.append({"stage": "multipara", "variant": v, "lang": lang, "id": iid, "rep": rep,
                      "output": rec["output"], "metrics": evaluate(it, lang, rec["output"])})
  return out


def ngrams(s, n=3):
  w = re.findall(r"[^\W\d_]+", STRIP_MARK.sub(" ", s).lower())
  return {tuple(w[i:i + n]) for i in range(len(w) - n + 1)}


def stage_bleed(items, main_rows):
  """Context bleed: the model translates the background synopsis into the output. Detector: the output shares a
  word 3-gram with the synopsis' own translation (translated once per document and language) that the source does not
  explain. No-context variants (V1/V1b/V2/V3/V3g/V3b) serve as the control."""
  by = {it["id"]: it for it in items}
  syn = {lang: ollama(t_v1b(SYNOPSIS, lang), options=GREEDY, tag={"stage": "bleed", "kind": "synopsis", "lang": lang})["output"]
         for lang in ("tr", "de")}
  out = []
  for r in main_rows:
    g = ngrams(r["output"]) & ngrams(syn[r["lang"]])
    ctx = r["variant"] in ("V4", "V4g", "V3cg")
    out.append({"stage": "bleed", "variant": r["variant"], "lang": r["lang"], "id": r["id"], "context": ctx,
                "has_neighbours": bool(by[r["id"]].get("prev") or by[r["id"]].get("next")),
                "echo": sorted(" ".join(x) for x in g), "flag": bool(g), "output": r["output"], "synopsis_tr": syn[r["lang"]]})
  return out


def stage_retry(items, main_rows):
  """Validator failures from the main grid, retried once with the strict template at T=0.2."""
  by = {it["id"]: it for it in items}
  out = []
  for r in main_rows:
    m = evaluate(by[r["id"]], r["lang"], r["output"])
    reasons = [k for k in ("tag_ok", "ph_multiset", "nl_ok", "numbers_ok", "dnt_ok") if m.get(k) is False]
    if m.get("untranslated"):
      reasons.append("untranslated")
    if not reasons:
      continue
    it = by[r["id"]]
    v = "V3g" if is_markup(it) else "V4g"
    rec = ollama(VARIANTS[v](it["source"], r["lang"], item=it), options={"temperature": 0.2},
                 tag={"stage": "retry", "variant": v, "lang": r["lang"], "id": it["id"], "from": r["variant"]})
    out.append({"stage": "retry", "variant": v, "from": r["variant"], "lang": r["lang"], "id": it["id"],
                "reasons": reasons, "first": r["output"], "output": rec["output"]})
  return out


def retry_fixed(m):
  return all(m.get(k) is not False for k in ("tag_ok", "ph_multiset", "nl_ok", "numbers_ok", "dnt_ok")) and not m.get("untranslated")


def batch_items(items):
  sel = [it for it in items if not is_markup(it) and "\n" not in it["source"]]
  return sel[:50]


def batch_prompt(srcs, lang):
  lines = "\n".join(f"{i}. {s}" for i, s in enumerate(srcs, 1))
  return (f"Translate the following segments into {LANG[lang]}, without additional explanation. Each line is "
          f"one segment, prefixed with its number. Output exactly one translated line per segment, "
          f"keeping the same numbers.\n\n{lines}")


def stage_batching(items, main_rows):
  sel = batch_items(items)
  single = {(r["lang"], r["id"]): r for r in main_rows if r["variant"] == "V1b"}
  out = []
  for lang in ("tr", "de"):
    for size in (5, 10):
      for k in range(0, len(sel), size):
        chunk = sel[k:k + size]
        rec = ollama(batch_prompt([c["source"] for c in chunk], lang), options={"num_predict": 4096},
                     tag={"stage": "batching", "lang": lang, "size": size, "chunk": k})
        got = {}
        for line in rec["output"].splitlines():
          mm = re.match(r"\s*(\d+)[.)]\s*(.*)", line)
          if mm:
            got.setdefault(int(mm.group(1)), []).append(mm.group(2).strip())
        aligned = sorted(got) == list(range(1, len(chunk) + 1)) and all(len(v) == 1 for v in got.values())
        for i, c in enumerate(chunk, 1):
          o = got.get(i, [""])[0]
          s = single.get((lang, c["id"]))
          ratio_vs_single = round(len(o) / max(1, len(s["output"])), 2) if s else None
          out.append({"stage": "batching", "lang": lang, "size": size, "chunk": k, "id": c["id"],
                      "chunk_aligned": aligned, "output": o, "wall_s_chunk": rec["wall_s"], "n_chunk": len(chunk),
                      "ratio_vs_single": ratio_vs_single, "metrics": evaluate(c, lang, o) if o else {}})
  return out


def route(it):
  """Recommended routing used by the throughput stage."""
  if is_markup(it):
    return "V3cg" if it["short"] else "V3g"
  return "V4g" if it["short"] or it["role"] != "body" else "V2"


def stage_throughput(items):
  sel = [it for it in items if it["category"] != "placeholder"][:50]
  out = []
  for lang in ("tr", "de"):
    # warm-up
    ollama(t_v1b("Warm-up.", lang), tag={"stage": "throughput", "kind": "warmup", "lang": lang}, use_cache=False)
    for workers in (1, 2):
      t0 = time.perf_counter()
      def job(it, workers=workers):
        v = route(it)
        rec = ollama(VARIANTS[v](it["source"], lang, item=it), use_cache=False,
                     tag={"stage": "throughput", "lang": lang, "id": it["id"], "variant": v, "workers": workers})
        return it, v, rec
      res = run_parallel([lambda it=it: job(it) for it in sel], workers)
      total = time.perf_counter() - t0
      for it, v, rec in res:
        out.append({"stage": "throughput", "lang": lang, "workers": workers, "id": it["id"], "variant": v,
                    "output": rec["output"], "wall_s": rec["wall_s"], "eval_tokens": rec["eval_tokens"],
                    "prompt_tokens": rec["prompt_tokens"], "total_s": round(total, 2),
                    "metrics": evaluate(it, lang, rec["output"])})
  return out


def stage_options(items):
  """Stop tokens / num_predict cap / keep_alive."""
  out = {}
  rec = ollama(t_v1b(items[9]["source"], "de"), options={"num_predict": 8},
               tag={"stage": "options", "kind": "cap8"}, use_cache=False)
  out["cap8"] = {"done_reason": rec["done_reason"], "eval_tokens": rec["eval_tokens"], "output": rec["output"]}
  rec = ollama(t_v1b("Notes on the Grid", "de"), tag={"stage": "options", "kind": "stop"}, use_cache=False)
  out["stop"] = {"done_reason": rec["done_reason"], "eval_tokens": rec["eval_tokens"], "output": rec["output"],
                 "has_special": "<|" in rec["raw_output"]}
  req = urllib.request.Request(OLLAMA + "/api/ps")
  with urllib.request.urlopen(req, timeout=30) as r:
    out["ps"] = json.loads(r.read().decode("utf-8"))
  return out


# ───────────────────────── report ─────────────────────────

def pct(xs):
  xs = [x for x in xs if x is not None]
  if not xs:
    return "–"
  return f"{100 * sum(1 for x in xs if x) / len(xs):.0f}% ({sum(1 for x in xs if x)}/{len(xs)})"


def quant(xs, q):
  xs = sorted(xs)
  if not xs:
    return None
  i = (len(xs) - 1) * q
  lo, hi = int(i), min(int(i) + 1, len(xs) - 1)
  return round(xs[lo] + (xs[hi] - xs[lo]) * (i - lo), 2)


def table(headers, rows):
  s = "| " + " | ".join(headers) + " |\n|" + "|".join("---" for _ in headers) + "|\n"
  for r in rows:
    s += "| " + " | ".join(str(c) for c in r) + " |\n"
  return s


def rescore(results, by):
  """Recompute metrics from stored outputs so reference/metric changes apply without new model calls."""
  for r in results:
    if r["stage"] in ("main", "sampling", "multipara", "throughput", "caps", "retry") or (r["stage"] == "batching" and r["output"]):
      r["metrics"] = evaluate(by[r["id"]], r["lang"], r["output"])


def report(results, items):
  by = {it["id"]: it for it in items}
  rescore(results, by)
  md = []
  summ = {}
  main = [r for r in results if r["stage"] == "main"]

  # 1. main metrics per variant x lang
  metrics = ["ref_ok", "case_ok", "tag_ok", "ph_ok", "nl_ok", "numbers_ok", "dnt_ok", "untranslated",
             "mostly_source", "added_any", "context_leak"]
  rows = []
  for v in PLAIN_VARIANTS + MARKUP_VARIANTS:
    for lang in ("tr", "de"):
      rs = [r for r in main if r["variant"] == v and r["lang"] == lang]
      if not rs:
        continue
      row = [v, lang, len(rs)]
      for k in metrics:
        row.append(pct([r["metrics"].get(k) for r in rs]))
      lat = [r["wall_s"] for r in rs]
      row.append(f"{statistics.median(lat):.2f}")
      rows.append(row)
  md.append("### Main grid: metric pass rates per variant × language (all items the variant ran on)\n\n" +
            table(["variant", "lang", "n"] + metrics + ["median s"], rows))

  # same restricted to the comparable subsets
  def sub(name, pred, vs, ms):
    rows = []
    for v in vs:
      for lang in ("tr", "de"):
        rs = [r for r in main if r["variant"] == v and r["lang"] == lang and pred(by[r["id"]])]
        if rs:
          rows.append([v, lang, len(rs)] + [pct([r["metrics"].get(k) for r in rs]) for k in ms])
    md.append(f"### {name}\n\n" + table(["variant", "lang", "n"] + ms, rows))
  sub("Short / ambiguous items (≤ 6 words, no markup) with references", lambda it: it["short"] and not is_markup(it) and it["ref"],
      PLAIN_VARIANTS, ["ref_ok", "case_ok", "untranslated", "added_any"])
  sub("Tagged items (<gN>)", lambda it: bool(TAG_RE.search(it["source"])), PLAIN_VARIANTS + MARKUP_VARIANTS,
      ["tag_ok", "tag_multiset", "tag_order", "tag_nesting", "tag_text_outside", "ref_ok", "added_any"])
  sub("Numbers / DNT items", lambda it: it["category"] in ("numbers", "dnt"), PLAIN_VARIANTS + ["V3g"],
      ["numbers_ok", "numbers_strict_ok", "dnt_ok", "ref_ok", "added_any"])
  sub("Typographic-term items", lambda it: it["category"] == "typo", PLAIN_VARIANTS, ["ref_ok", "added_any"])
  sub("Body paragraphs (real)", lambda it: it["role"] in ("body", "footnote", "caption") and not it["short"] and not is_markup(it),
      PLAIN_VARIANTS, ["ref_ok", "mostly_source", "added_any", "context_leak"])

  # placeholder formats
  rows = []
  for fmt in ("uni", "brace", "xml", "dbl"):
    for v in ("V1b", "V2", "V4", "V4g", "V3", "V3g", "V3cg"):
      rs = [r for r in main if by[r["id"]].get("ph_format") == fmt and r["variant"] == v]
      if rs:
        rows.append([fmt, v, len(rs), pct([r["metrics"].get("ph_ok") for r in rs]),
                     pct([r["metrics"].get("ph_multiset") for r in rs]), pct([r["metrics"].get("ph_multiset_norm") for r in rs]),
                     pct([r["metrics"].get("ref_ok") for r in rs])])
  for fmt in ("uni", "brace", "xml", "dbl"):
    rs = [r for r in main if by[r["id"]].get("ph_format") == fmt]
    rows.append([fmt, "**all**", len(rs), pct([r["metrics"].get("ph_ok") for r in rs]),
                 pct([r["metrics"].get("ph_multiset") for r in rs]), pct([r["metrics"].get("ph_multiset_norm") for r in rs]),
                 pct([r["metrics"].get("ref_ok") for r in rs])])
  md.append("### Placeholder formats (TR+DE pooled)\n\n" + table(["format", "variant", "n", "ph_ok (multiset+order)", "ph multiset",
                                                                  "ph multiset after look-alike normalisation", "ref_ok"], rows))
  # title-case initial lost (e.g. glossary term pasted lowercase at start: "ızgara Üzerine Notlar")
  rows = []
  for v in PLAIN_VARIANTS:
    for lang in ("tr", "de"):
      rs = [r for r in main if r["variant"] == v and r["lang"] == lang]
      cand = [r for r in rs if re.match(r"[^\w]*[A-Z]", by[r["id"]]["source"])]
      bad = [r for r in cand if re.match(r"[^\w]*[^\W\d_]", r["output"]) and re.match(r"[^\w]*([^\W\d_])", r["output"]).group(1).islower()]
      rows.append([v, lang, len(cand), len(bad), "; ".join(f"`{r['output'][:40]}`" for r in bad[:4])])
  md.append("### Lost initial capital (source starts uppercase, output starts lowercase)\n\n" + table(["variant", "lang", "n", "lost", "examples"], rows))

  # L3 strings verbatim
  l3 = ["r_headline_grid", "r_folio_quarterly", "c_folio_2", "r_kicker_feature", "c_feature", "r_td_pullquotes",
        "r_kicker_next", "r_th_build", "r_th_swatch", "r_td_kickers_rules", "r_td_bg_heads", "r_cover_title_1",
        "r_cover_title_2", "y_pullquote"]
  rows = []
  for iid in l3:
    for lang in ("tr", "de"):
      cells = [f"`{by[iid]['source']}`", lang]
      for v in PLAIN_VARIANTS:
        r = next((r for r in main if r["id"] == iid and r["lang"] == lang and r["variant"] == v), None)
        if r:
          mark = "" if r["metrics"].get("ref_ok") is None else (" ✓" if r["metrics"]["ref_ok"] else " ✗")
          cells.append(r["output"].replace("|", "\\|").replace("\n", "⏎") + mark)
      rows.append(cells)
  md.append("### L3 strings, verbatim outputs (✓/✗ = reference check)\n\n" + table(["source", "lang"] + PLAIN_VARIANTS, rows))

  # length ratio bounds
  rows = []
  summ["len_ratio"] = {}
  for lang in ("tr", "de"):
    for cls, pred in (("all (V2/V4g)", lambda it: True), ("body ≥ 7 words", lambda it: not it["short"]),
                      ("short ≤ 6 words", lambda it: it["short"])):
      xs = [r["metrics"]["len_ratio"] for r in main if r["lang"] == lang and r["variant"] in ("V2", "V4g")
            and pred(by[r["id"]]) and not r["metrics"].get("code_like") and not r["metrics"].get("added_any")]
      q = [quant(xs, p) for p in (0.0, 0.05, 0.5, 0.95, 1.0)]
      summ["len_ratio"][f"{lang}:{cls}"] = q
      rows.append([lang, cls, len(xs)] + q)
  md.append("### Length ratio target/source (chars, markers stripped)\n\n" + table(["lang", "class", "n", "min", "p5", "p50", "p95", "max"], rows))

  # untranslated heuristic
  ident = [r for r in main if r["metrics"].get("identical")]
  rows = collections.Counter((r["id"], r["lang"], r["metrics"]["code_like"], r["output"]) for r in ident)
  md.append("### Identity outputs (output == source) and the code-like exemption\n\n" + table(
    ["id", "lang", "code_like (exempt)", "output", "count (variants)"],
    [[a, b, c, f"`{d}`", n] for (a, b, c, d), n in sorted(rows.items())]))

  # caps
  caps = [r for r in results if r["stage"] == "caps"]
  if caps:
    rows = []
    for v in ("V1b", "V2", "V4", "V4g"):
      for mode in ("asis", "fold"):
        for lang in ("tr", "de"):
          rs = [r for r in caps if r["variant"] == v and r["mode"] == mode and r["lang"] == lang]
          rows.append([v, mode, lang, len(rs), pct([r["metrics"].get("ref_ok") for r in rs]),
                       pct([r["metrics"].get("case_ok") for r in rs]), pct([r["metrics"].get("added_any") for r in rs])])
    md.append("### ALL CAPS: as-is vs sentence-case + locale upper (case_ok measured after restoring)\n\n" +
              table(["variant", "mode", "lang", "n", "ref_ok", "case_ok", "added_any"], rows))
    rows = []
    for r in caps:
      if r["variant"] == "V4g":
        rows.append([r["id"], r["lang"], r["mode"], f"`{r['sent']}`", r["model_output"], r["output"],
                     "" if r["metrics"].get("ref_ok") is None else ("✓" if r["metrics"]["ref_ok"] else "✗")])
    md.append("#### ALL CAPS outputs (V4g)\n\n" + table(["id", "lang", "mode", "sent", "model output", "final", "ref"], rows))

  # concise / back-translation
  con = [r for r in results if r["stage"] == "concise"]
  if con:
    real = [r for r in con if r["kind"] == "real"]
    trunc = [r for r in con if r["variant"] == "trunc"]
    rows = []
    for v in ("V5a", "V5b"):
      for lang in ("tr", "de"):
        rs = [r for r in real if r["variant"] == v and r["lang"] == lang]
        rows.append([v, lang, len(rs), quant([r["len_vs_normal"] for r in rs], 0.5),
                     min(r["len_vs_normal"] for r in rs), quant([r["recall_src"] for r in rs], 0.5),
                     min(r["recall_src"] for r in rs), quant([r["recall_normal_bt"] for r in rs], 0.5),
                     pct([r["numbers_ok"] for r in rs if numbers(by[r["id"]]["source"])])])
    for kind in ("drop_sentence", "drop_clause"):
      for lang in ("tr", "de"):
        rs = [r for r in trunc if r["kind"] == kind and r["lang"] == lang]
        if rs:
          rows.append([kind, lang, len(rs), quant([r["len_vs_normal"] for r in rs], 0.5),
                       min(r["len_vs_normal"] for r in rs), quant([r["recall_src"] for r in rs], 0.5),
                       min(r["recall_src"] for r in rs), quant([r["recall_normal_bt"] for r in rs], 0.5), "–"])
    nb = [r["recall_src_of_normal_bt"] for r in con if r["kind"] in ("real",)]
    md.append("### Concise candidates and deliberate truncations (back-translation recall)\n\n" + table(
      ["candidate", "lang", "n", "len/normal p50", "len/normal min", "recall_src p50", "recall_src min",
       "recall_vs_normalBT p50", "numbers kept"], rows) +
      f"\nReference: content-word recall of the *normal* translation's back-translation vs source: "
      f"p5={quant(nb, 0.05)}, p50={quant(nb, 0.5)}, min={min(nb) if nb else None}.\n")
    # threshold sweep: flag = recall_src < t_r OR len_vs_normal < t_l
    sweep = []
    for tr_ in (0.6, 0.65, 0.7, 0.75, 0.8, 0.85):
      for tl in (0.0, 0.6, 0.7, 0.75, 0.8):
        det = [r["recall_src"] < tr_ or r["len_vs_normal"] < tl for r in trunc]
        fp = [r["recall_src"] < tr_ or r["len_vs_normal"] < tl for r in real]
        detc = [r["recall_src"] < tr_ or r["len_vs_normal"] < tl for r in trunc if r["kind"] == "drop_clause"]
        sweep.append([tr_, tl, pct(det), pct(detc), pct(fp)])
    md.append("#### Detector sweep: flag if recall_src < R or len/normal < L\n\n" + table(
      ["R", "L", "detected (all truncations)", "detected (clause drops)", "flagged real concise (FP-or-true)"], sweep))
    sweep = []
    for tr_ in (0.6, 0.65, 0.7, 0.75, 0.8, 0.85):
      det = [r["recall_normal_bt"] < tr_ for r in trunc]
      fp = [r["recall_normal_bt"] < tr_ for r in real]
      sweep.append([tr_, pct(det), pct([r["recall_normal_bt"] < tr_ for r in trunc if r["kind"] == "drop_clause"]), pct(fp)])
    md.append("#### Alternative: recall of the normal translation's back-translation (BT-vs-BT)\n\n" + table(
      ["R", "detected (all)", "detected (clause)", "flagged real concise"], sweep))
    if "p_delta0" in con[0]:
      sweep = []
      for tl in (0.7, 0.75, 0.8):
        for dd in (None, -0.25, -0.2, -0.15, -0.1):
          f = lambda r: r["len_vs_normal"] < tl or (dd is not None and r["p_delta0"] < dd)
          sweep.append([tl, "–" if dd is None else dd, pct([f(r) for r in trunc]),
                        pct([f(r) for r in trunc if r["kind"] == "drop_sentence"]),
                        pct([f(r) for r in trunc if r["kind"] == "drop_clause"]), pct([f(r) for r in real])])
      md.append("#### Recommended detector family: greedy (T=0) back-translation, relative recall\n\n"
                "Flag if len(candidate)/len(normal) < L **or** Δ < D, where Δ = prefix-recall(source, BT0(candidate)) − "
                "prefix-recall(source, BT0(normal translation)).\n\n" + table(
        ["L", "D", "detected (all truncations)", "detected (sentence drops)", "detected (clause drops)", "flagged real concise"], sweep))
      rows = [[k, quant([r["p_src0"] for r in rs], 0.5), quant([r["p_delta0"] for r in rs], 0.5), min(r["p_delta0"] for r in rs),
               quant([r["p_bt0_vs_bt0"] for r in rs], 0.5)]
              for k, rs in (("real concise", real), ("drop_sentence", [r for r in trunc if r["kind"] == "drop_sentence"]),
                            ("drop_clause", [r for r in trunc if r["kind"] == "drop_clause"]))]
      nb0 = [r["p_src0_normal"] for r in real]
      md.append(table(["candidates", "p_src0 p50", "Δ p50", "Δ min", "BT0-vs-BT0 p50"], rows) +
                f"\nGreedy BT of the normal translation vs source (prefix recall): p5={quant(nb0, 0.05)}, p50={quant(nb0, 0.5)}.\n")
    rows = [[r["id"], r["lang"], r["variant"], r["len_vs_normal"], r["recall_src"], r["recall_normal_bt"],
             r["output"][:160].replace("|", "\\|") + ("…" if len(r["output"]) > 160 else "")] for r in real]
    md.append("#### Real concise outputs\n\n" + table(["id", "lang", "variant", "len/normal", "recall_src", "recall_vs_nBT", "output"], rows))

  # sampling
  smp = [r for r in results if r["stage"] == "sampling"]
  if smp:
    rows = []
    for v in ("V1b", "V4", "V4g", "V4-seed42"):
      for temp in (0.7, 0.2):
        for lang in ("tr", "de"):
          rs = [r for r in smp if r["variant"] == v and r["temp"] == temp and r["lang"] == lang]
          if not rs:
            continue
          groups = collections.defaultdict(set)
          for r in rs:
            groups[r["id"]].add(r["output"])
          uniq = statistics.mean(len(g) for g in groups.values())
          det = sum(1 for g in groups.values() if len(g) == 1) / len(groups)
          rows.append([v, temp, lang, len(rs), pct([r["metrics"].get("ref_ok") for r in rs]),
                       pct([r["metrics"].get("case_ok") for r in rs]), f"{uniq:.2f}", f"{100 * det:.0f}%"])
    md.append("### Sampling: failure-prone items, 3 runs each (random seed unless noted)\n\n" + table(
      ["variant", "temp", "lang", "n", "ref_ok", "case_ok", "mean distinct outputs /3", "items fully deterministic"], rows))

  # multipara
  mp = [r for r in results if r["stage"] == "multipara"]
  if mp:
    rows = []
    for iid in ("ph_br_uni", "ph_br_brace", "ph_br_xml", "ph_br_dbl", "nl_br", "t_cover_pair"):
      for v in ("V4", "V3cg", "V3"):
        for lang in ("tr", "de"):
          rs = [r for r in mp if r["id"] == iid and r["variant"] == v and r["lang"] == lang]
          if not rs:
            continue
          key = "ph_ok" if "ph_ok" in rs[0]["metrics"] else ("nl_ok" if "nl_ok" in rs[0]["metrics"] else "tag_ok")
          rows.append([iid, v, lang, pct([r["metrics"].get(key) for r in rs]), pct([r["metrics"].get("ref_ok") for r in rs]),
                       " ‖ ".join(sorted(set(r["output"].replace("\n", "⏎").replace("|", "\\|") for r in rs)))])
    md.append("### Multi-paragraph headline (\"The Quiet\" + \"Art of Layout\"), 3 runs each\n\n" + table(
      ["form", "variant", "lang", "boundary kept", "ref_ok", "distinct outputs"], rows))

  # context bleed
  bl = [r for r in results if r["stage"] == "bleed"]
  if bl:
    rows = []
    for v in PLAIN_VARIANTS + MARKUP_VARIANTS:
      for nb in (True, False):
        rs = [r for r in bl if r["variant"] == v and r["has_neighbours"] == nb]
        if rs:
          rows.append([v, "yes" if nb else "no", len(rs), pct([r["flag"] for r in rs])])
    md.append("### Context bleed (synopsis echoed into the output): 3-gram echo detector\n\n"
              f"Synopsis translations: TR `{next(r['synopsis_tr'] for r in bl if r['lang'] == 'tr')}` · "
              f"DE `{next(r['synopsis_tr'] for r in bl if r['lang'] == 'de')}`\n\n" +
              table(["variant", "item has prev/next", "n", "flagged"], rows))
    rows = [[r["variant"], r["lang"], r["id"], ", ".join(r["echo"]), r["output"][:110].replace("|", "\\|").replace("\n", "⏎")]
            for r in bl if r["flag"]]
    md.append("#### Flagged outputs\n\n" + table(["variant", "lang", "id", "echoed 3-grams", "output"], rows))

  # retry
  rt = [r for r in results if r["stage"] == "retry"]
  if rt:
    rows = [[r["from"], r["lang"], r["id"], ",".join(r["reasons"]), r["variant"], "✓" if retry_fixed(r["metrics"]) else "✗",
             r["first"][:70].replace("|", "\\|").replace("\n", "⏎"), r["output"][:70].replace("|", "\\|").replace("\n", "⏎")] for r in rt]
    md.append(f"### Retry (strict template, T=0.2) on main-grid validator failures: fixed {sum(1 for r in rt if retry_fixed(r['metrics']))}/{len(rt)}\n\n" +
              table(["first variant", "lang", "id", "failed", "retry template", "fixed", "first output", "retry output"], rows))

  # batching
  bt = [r for r in results if r["stage"] == "batching"]
  if bt:
    rows = []
    for size in (5, 10):
      for lang in ("tr", "de"):
        rs = [r for r in bt if r["size"] == size and r["lang"] == lang]
        chunks = {r["chunk"]: (r["chunk_aligned"], r["wall_s_chunk"], r["n_chunk"]) for r in rs}
        al = sum(1 for c in chunks.values() if c[0]) / len(chunks)
        secs = sum(c[1] for c in chunks.values())
        sus = [r for r in rs if r["ratio_vs_single"] is not None and not (0.5 <= r["ratio_vs_single"] <= 2.0)]
        rows.append([size, lang, len(chunks), f"{100 * al:.0f}%", f"{len(rs) / secs:.2f}", len(sus),
                     pct([r["metrics"].get("ref_ok") for r in rs]), pct([r["metrics"].get("case_ok") for r in rs])])
    seq = [r for r in main if r["variant"] == "V1b" and r["id"] in {it["id"] for it in batch_items(items)}]
    for lang in ("tr", "de"):
      rs = [r for r in seq if r["lang"] == lang]
      rows.append(["1 (sequential V1b)", lang, len(rs), "100%", f"{len(rs) / sum(r['wall_s'] for r in rs):.2f}", "–",
                   pct([r["metrics"].get("ref_ok") for r in rs]), pct([r["metrics"].get("case_ok") for r in rs])])
    md.append("### Batching (numbered lines in one prompt)\n\n" + table(
      ["batch size", "lang", "chunks", "chunks aligned", "segments/s", "segments with length off 0.5–2× vs single", "ref_ok", "case_ok"], rows))

  # throughput
  tp = [r for r in results if r["stage"] == "throughput"]
  if tp:
    rows = []
    for lang in ("tr", "de"):
      for w in (1, 2):
        rs = [r for r in tp if r["lang"] == lang and r["workers"] == w]
        if not rs:
          continue
        tot = rs[0]["total_s"]
        rows.append([lang, w, len(rs), tot, f"{len(rs) / tot:.2f}", quant([r["wall_s"] for r in rs], 0.5),
                     quant([r["wall_s"] for r in rs], 0.95), max(r["prompt_tokens"] or 0 for r in rs),
                     pct([r["metrics"].get("ref_ok") for r in rs]), pct([r["metrics"].get("added_any") for r in rs])])
    md.append("### Throughput (routed templates, warm model, 50 segments)\n\n" + table(
      ["lang", "parallel requests", "segments", "total s", "segments/s", "p50 s/seg", "p95 s/seg", "max prompt tokens",
       "ref_ok", "added_any"], rows))
    rows = [[r["id"], r["lang"], r["variant"], r["output"].replace("\n", "⏎").replace("|", "\\|")[:140]]
            for r in tp if r["workers"] == 1 and by[r["id"]]["short"]]
    md.append("#### Routed outputs for short segments (workers=1)\n\n" + table(["id", "lang", "template", "output"], rows))

  # token stats for num_predict / num_ctx
  allcalls = [r for r in main]
  ratios = [r["eval_tokens"] / max(1, len(STRIP_MARK.sub("", by[r["id"]]["source"]))) for r in allcalls if r["eval_tokens"]]
  summ["eval_tokens_per_src_char"] = {"p50": quant(ratios, 0.5), "p95": quant(ratios, 0.95), "p99": quant(ratios, 0.99), "max": max(ratios)}
  summ["max_prompt_tokens"] = max(r["prompt_tokens"] or 0 for r in allcalls)
  summ["done_reasons"] = dict(collections.Counter(r["done_reason"] for r in allcalls))
  md.append(f"### Token statistics (main grid)\n\noutput tokens per source character: {summ['eval_tokens_per_src_char']}; "
            f"max prompt tokens: {summ['max_prompt_tokens']}; done_reason counts: {summ['done_reasons']}\n")
  return "\n".join(md), summ


# ───────────────────────── main ─────────────────────────

def main():
  global RAW_FH
  sys.stdout.reconfigure(line_buffering=True, encoding="utf-8")
  ap = argparse.ArgumentParser()
  ap.add_argument("--resume", action="store_true")
  ap.add_argument("--report-only", action="store_true")
  ap.add_argument("--stages", default="main,caps,concise,sampling,multipara,retry,bleed,batching,throughput,options")
  a = ap.parse_args()
  RES.mkdir(exist_ok=True)
  raw = RES / "raw.jsonl"
  if (a.resume or a.report_only) and raw.exists():
    for l in open(raw, encoding="utf-8"):
      r = json.loads(l)
      CACHE[r["key"]] = r
  elif raw.exists():
    raw.unlink()
  RAW_FH = open(raw, "a", encoding="utf-8")
  items = load_items()
  stages = a.stages.split(",")
  results_path = RES / "metrics.jsonl"
  results = []
  extra = {}
  t0 = time.time()
  if a.report_only:
    results = [json.loads(l) for l in open(results_path, encoding="utf-8")]
    if (RES / "options.json").exists():
      extra = json.loads((RES / "options.json").read_text(encoding="utf-8"))
  else:
    prev = []
    if a.resume and results_path.exists():
      prev = [json.loads(l) for l in open(results_path, encoding="utf-8")]
    keep = [r for r in prev if r["stage"] not in stages]
    results = list(keep)
    main_rows = [r for r in results if r["stage"] == "main"]
    if "main" in stages:
      print("main grid"); main_rows = stage_main(items); results += main_rows
    if "caps" in stages:
      print("caps"); results += stage_caps(items)
    if "concise" in stages:
      print("concise"); results += stage_concise(items, main_rows)
    if "sampling" in stages:
      print("sampling"); results += stage_sampling(items)
    if "multipara" in stages:
      print("multipara"); results += stage_multipara(items)
    if "retry" in stages:
      print("retry"); results += stage_retry(items, main_rows)
    if "bleed" in stages:
      print("bleed"); results += stage_bleed(items, main_rows)
    if "batching" in stages:
      print("batching"); results += stage_batching(items, main_rows)
    if "throughput" in stages:
      print("throughput"); results += stage_throughput(items)
    if "options" in stages:
      print("options"); extra = stage_options(items)
      (RES / "options.json").write_text(json.dumps(extra, ensure_ascii=False, indent=2), encoding="utf-8")
    with open(results_path, "w", encoding="utf-8") as f:
      for r in results:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")
  md, summ = report(results, items)
  summ["options"] = extra
  summ["elapsed_s"] = round(time.time() - t0, 1)
  (RES / "summary.md").write_text(md, encoding="utf-8")
  (RES / "summary.json").write_text(json.dumps(summ, ensure_ascii=False, indent=2), encoding="utf-8")
  print(f"done in {summ['elapsed_s']} s → {RES / 'summary.md'}")


if __name__ == "__main__":
  main()
