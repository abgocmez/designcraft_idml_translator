"""Build IDML test variants of the sample (scratchpad only)."""
import sys, zipfile, re
from pathlib import Path
from lxml import etree

SRC = Path(r"C:/Programming/craft-studio/idml-demo/sample_en.idml")
OUT = Path(__file__).parent / "var"
OUT.mkdir(exist_ok=True)

TEXT = {
  "EN": "Internationalization responsibilities notwithstanding, telecommunications infrastructure demonstrates extraordinary characteristics; incomprehensibilities multiply uncharacteristically.",
  "DE": "Donaudampfschifffahrtsgesellschaft Rechtsschutzversicherungsgesellschaften Geschwindigkeitsbegrenzung Arbeitsunfähigkeitsbescheinigung Lebensmittelunverträglichkeit Straßenverkehrsordnung.",
  "TR": "Çekoslovakyalılaştıramadıklarımızdanmışsınız Afyonkarahisarlılaştıramadıklarımızdan kullanılabilirlik değerlendirmelerinin uygulanabilirliği öğretmenlerimizden şikâyetçiyiz.",
}
LANG = {"EN": "$ID/English: USA", "DE": "$ID/German: 2006 Reform", "TR": "$ID/Turkish", "NONE": "$ID/[No Language]"}
LANG_EL = {
  "DE": '<Language Self="Language/$ID/German%3a 2006 Reform" Name="$ID/German: 2006 Reform" SingleQuotes="&#8218;&#8216;" DoubleQuotes="&#8222;&#8220;" PrimaryLanguageName="$ID/German" SublanguageName="$ID/2006 Reform" Id="1797" HyphenationVendor="Hunspell" SpellingVendor="Hunspell"/>',
  "TR": '<Language Self="Language/$ID/Turkish" Name="$ID/Turkish" SingleQuotes="&#8216;&#8217;" DoubleQuotes="&#8220;&#8221;" PrimaryLanguageName="$ID/Turkish" SublanguageName="$ID/" Id="287" HyphenationVendor="Hunspell" SpellingVendor="Hunspell"/>',
}
GLYPHS = "ğĞşŞıİçÇöÖüÜ ßẞäöüÄÖÜ „“‚‘ «» 漢字ก"


def rewrite(out, edits):
  """Byte-preserving rewrite: unchanged entries copied with original ZipInfo; mimetype stays first+stored."""
  with zipfile.ZipFile(SRC) as zin, zipfile.ZipFile(out, "w") as zout:
    for info in zin.infolist():
      data = zin.read(info.filename)
      if info.filename in edits:
        data = edits[info.filename](data)
      zout.writestr(info, data, compress_type=info.compress_type)


def story_text(text, lang, hyph, just="LeftJustified"):
  def f(data):
    root = etree.fromstring(data)
    psr = root.find(".//ParagraphStyleRange")
    psr.set("Justification", just)
    psr.set("Hyphenation", "true" if hyph else "false")
    csr = psr.find("CharacterStyleRange")
    if lang:
      csr.set("AppliedLanguage", lang)
    csr.find("Content").text = text
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
  return f


def narrow_frame(data):
  # frame u1f (story u20 / DC story 9): make it 120pt wide and tall
  s = data.decode("utf-8")
  i = s.index('Self="u1f"'); j = s.index("</TextFrame>", i)
  blk = s[i:j]
  blk2 = blk.replace("492 182", "162 182").replace("492 240", "162 520").replace("42 240", "42 520")
  return (s[:i] + blk2 + s[j:]).encode("utf-8")


def add_lang(code):
  def f(data):
    s = data.decode("utf-8")
    k = s.index('<Language Self="Language/$ID/English%3a USA"')
    return (s[:k] + LANG_EL[code] + "\n\t" + s[k:]).encode("utf-8")
  return f


def build():
  made = []
  for code in ("EN", "DE", "TR"):
    for lang_src in ("own", "en", "none"):          # which AppliedLanguage to set
      lang = {"own": LANG[code], "en": LANG["EN"], "none": LANG["NONE"]}[lang_src]
      for hyph in (True, False):
        for decl in ((False, True) if code != "EN" and lang_src == "own" else (False,)):
          name = f"hy_{code}_{lang_src}_{'h' if hyph else 'n'}{'_decl' if decl else ''}.idml"
          edits = {"Stories/Story_u20.xml": story_text(TEXT[code], lang, hyph),
                   "Spreads/Spread_ub.xml": narrow_frame}
          if decl:
            edits["designmap.xml"] = add_lang(code)
          rewrite(OUT / name, edits)
          made.append(name)
  # glyph test: caption story u24 (DC story 10), single line frame
  for font in (None, "Source Sans 3", "Arial", "Courier New"):
    def g(data, font=font):
      root = etree.fromstring(data)
      csr = root.find(".//CharacterStyleRange")
      if font:
        csr.set("AppliedFont", font)
      csr.find("Content").text = GLYPHS
      return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
    name = f"gl_{(font or 'default').replace(' ', '')}.idml"
    rewrite(OUT / name, {"Stories/Story_u24.xml": g})
    made.append(name)
  # language without designmap element on the whole doc + undeclared unknown language
  rewrite(OUT / "warn_undeclared_tr.idml", {"Stories/Story_u20.xml": story_text(TEXT["TR"], LANG["TR"], True)})
  rewrite(OUT / "warn_bogus_lang.idml", {"Stories/Story_u20.xml": story_text(TEXT["EN"], "$ID/Klingon: Bogus", True)})
  # story order test: shuffle StoryList and the idPkg:Story order independently
  def shuffle(data):
    s = data.decode("utf-8")
    m = re.search(r'StoryList="([^"]*)"', s)
    ids = m.group(1).split()
    s = s.replace(m.group(0), 'StoryList="%s"' % " ".join(reversed(ids)))
    return s.encode("utf-8")
  rewrite(OUT / "order_storylist_reversed.idml", {"designmap.xml": shuffle})
  def shuffle_pkg(data):
    s = data.decode("utf-8")
    refs = re.findall(r'\s*<idPkg:Story src="[^"]*"/>', s)
    blob = "".join(refs)
    return s.replace(blob, "".join(reversed(refs))).encode("utf-8")
  rewrite(OUT / "order_pkg_reversed.idml", {"designmap.xml": shuffle_pkg})
  return made


if __name__ == "__main__":
  for m in build():
    print(m)
