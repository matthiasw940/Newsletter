#!/usr/bin/env python3
"""Newsletter v7 — Norm extraction, Rechtsgebiet color coding, VfGH expanded."""
import json, hashlib, re, traceback
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.parse import urlencode
from html import unescape

MAX = 25; DAYS = 60; DATA = Path(__file__).parent / "data.json"
NOW = datetime.now(timezone.utc)
RIS = "https://data.bka.gv.at/ris/api/v2.6"

def mid(s): return hashlib.md5(s.encode()).hexdigest()[:12]
def strip(t):
    if not t: return ""
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", "", str(t)))).strip()[:600]
def get_item(obj):
    """Extract string from RIS item field: {"item":"x"} or {"item":["x","y"]} or "x"."""
    if isinstance(obj, dict):
        v = obj.get("item", "")
        if isinstance(v, list): return v
        return [str(v)] if v else []
    if isinstance(obj, str): return [obj] if obj else []
    return []

def http_get(url, timeout=25):
    req = Request(url, headers={
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:120.0) Gecko/20100101 Firefox/120.0",
        "Accept": "application/json, text/html, */*",
        "Accept-Language": "de-AT,de;q=0.9,en;q=0.8"})
    with urlopen(req, timeout=timeout) as r: return r.read()

def http_xml(url, timeout=25):
    req = Request(url, headers={
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:120.0) Gecko/20100101 Firefox/120.0",
        "Accept": "application/rss+xml, application/xml, text/xml, */*",
        "Accept-Language": "de-AT,de;q=0.9,en;q=0.8"})
    with urlopen(req, timeout=timeout) as r: return r.read()

def pdate(s):
    if not s: return ""
    s = str(s).replace("GMT","+0000").replace("UTC","+0000").strip()
    for f in ["%a, %d %b %Y %H:%M:%S %z","%Y-%m-%dT%H:%M:%S%z","%Y-%m-%dT%H:%M:%SZ",
              "%Y-%m-%d %H:%M:%S","%Y-%m-%d","%d.%m.%Y"]:
        try: return datetime.strptime(s, f).isoformat()
        except: pass
    return ""

def trim(arts, max_n=MAX):
    cutoff = NOW - timedelta(days=DAYS)
    arts.sort(key=lambda a: a.get("date","") or "9999", reverse=True)
    out = []
    for a in arts:
        d = a.get("date","")
        if not d: out.append(a); continue
        try:
            dt = datetime.fromisoformat(d.replace("Z","+00:00"))
            if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
            if dt >= cutoff: out.append(a)
        except: out.append(a)
    return out[:max_n]

def merge(existing, new_arts):
    urls = {a["url"] for a in existing}
    arts = list(existing)
    for a in new_arts:
        if a["url"] not in urls: arts.append(a); urls.add(a["url"])
    return arts

# ═══════════════ RSS ═══════════════
def parse_rss(raw, src):
    try: root = ET.fromstring(raw)
    except: return []
    arts = []
    ns_dc = "{http://purl.org/dc/elements/1.1/}"
    ns_rdf = "{http://purl.org/rss/1.0/}"

    # RSS 2.0
    for item in root.findall(".//item"):
        t = (item.findtext("title") or "").strip()
        l = (item.findtext("link") or "").strip()
        if not t or not l: continue
        cat = item.findtext("category","") or item.findtext(f"{ns_dc}subject","") or src
        pub = item.findtext("pubDate","") or item.findtext(f"{ns_dc}date","")
        arts.append(dict(id=mid(l),title=t,url=l,category=cat,
            excerpt=strip(item.findtext("description","")),source=src,
            date=pdate(pub),featured=False))
    if arts: return arts

    # RSS 1.0 / RDF (used by ORF)
    for item in root.findall(f"{ns_rdf}item"):
        t = (item.findtext(f"{ns_rdf}title") or item.findtext("title") or "").strip()
        l = (item.findtext(f"{ns_rdf}link") or item.findtext("link") or "").strip()
        if not t or not l: continue
        cat = item.findtext(f"{ns_dc}subject","") or src
        pub = item.findtext(f"{ns_dc}date","")
        arts.append(dict(id=mid(l),title=t,url=l,category=cat,
            excerpt=strip(item.findtext(f"{ns_rdf}description","") or item.findtext("description","")),
            source=src,date=pdate(pub),featured=False))
    if arts: return arts

    # Atom
    ns = "{http://www.w3.org/2005/Atom}"
    for e in root.findall(f"{ns}entry"):
        t = (e.findtext(f"{ns}title") or "").strip()
        lk = e.find(f"{ns}link[@rel='alternate']") or e.find(f"{ns}link")
        l = lk.get("href","") if lk is not None else ""
        if not t or not l: continue
        arts.append(dict(id=mid(l),title=t,url=l,category=src,
            excerpt=strip(e.findtext(f"{ns}summary","") or e.findtext(f"{ns}content","")),
            source=src,date=pdate(e.findtext(f"{ns}updated","") or e.findtext(f"{ns}published","")),
            featured=False))
    return arts

def fetch_rss(feeds, name):
    arts = []
    for url, src in feeds:
        print(f"  [{name}] {src}")
        try:
            new = parse_rss(http_xml(url), src)
            arts.extend(new); print(f"    ✓ {len(new)} articles")
        except Exception as e: print(f"    ✗ {type(e).__name__}: {e}")
    return arts

# ═══════════════ RIS JUSTIZ (OGH) ═══════════════
def ris_justiz(gericht, label):
    print(f"  [{label}] RIS REST API v2.6...")
    params = {
        "Applikation": "Justiz",
        "Gericht": gericht,
        "ImRisSeit": "ZweiWochen",
        "DokumenteProSeite": "OneHundred",
        "Seitennummer": "1",
        "Dokumenttyp.SucheInRechtssaetzen": "true",
        "Dokumenttyp.SucheInEntscheidungstexten": "true",
    }
    url = f"{RIS}/Judikatur?{urlencode(params)}"
    arts = []
    try:
        data = json.loads(http_get(url))
        results = data.get("OgdSearchResult",{}).get("OgdDocumentResults",{})
        if isinstance(results, dict): results = results.get("OgdDocumentReference",[])
        if isinstance(results, dict): results = [results]
        if not isinstance(results, list): results = []

        for doc in results:
            d = doc.get("Data",{}).get("Metadaten",{})
            allg = d.get("Allgemein",{})
            jud = d.get("Judikatur",{})
            jmeta = jud.get("Justiz",{})

            gz = (get_item(jud.get("Geschaeftszahl",{})) or [""])[0].strip()
            datum = str(jud.get("Entscheidungsdatum","") or "").strip()
            doc_url = str(allg.get("DokumentUrl","") or "").strip()
            gesamt_url = str(jud.get("GesamteEntscheidungUrl","") or "").strip()
            kurz = strip(jud.get("Kurzinformation",""))
            rechtssatz_url = str(jud.get("RechtssatzUrl","") or "").strip()

            # Norm: array of cited laws
            normen = get_item(jud.get("Norm",{}))
            if gz and len(arts)<3: print(f"    DEBUG {gz}: norm={normen[:2]}, kurz={kurz[:80]}, rg={rechtsgebiet}")
            norm_str = "; ".join(normen[:4]) if normen else ""

            # Rechtsgebiet & Fachgebiet
            rechtsgebiet = (get_item(jmeta.get("Rechtsgebiete",{})) or [""])[0]
            fachgebiet = (get_item(jmeta.get("Fachgebiete",{})) or [""])[0]

            # Build rich excerpt
            parts = []
            if norm_str: parts.append(f"📜 {norm_str}")
            if kurz: parts.append(kurz)
            excerpt = " — " .join(parts) if parts else ""

            final_url = gesamt_url or doc_url
            if not final_url:
                final_url = f"https://www.ris.bka.gv.at/Ergebnis.wxe?Abfrage=Justiz&Gericht={gericht}&Geschaeftszahl={gz}"
            if not gz: continue

            arts.append(dict(
                id=mid(final_url), title=f"{label} {gz}", url=final_url,
                category=rechtsgebiet or fachgebiet or label,
                excerpt=excerpt[:600], source="RIS", featured=False,
                date=pdate(datum), rechtsgebiet=rechtsgebiet, fachgebiet=fachgebiet, norm=norm_str,
            ))
        print(f"    ✓ {len(arts)} decisions")
    except Exception as e: print(f"    ✗ {type(e).__name__}: {e}"); traceback.print_exc()
    return arts

# ═══════════════ RIS VfGH ═══════════════
def ris_vfgh():
    print(f"  [VfGH] RIS REST API v2.6...")
    params = {
        "Applikation": "Vfgh",
        "ImRisSeit": "DreiMonaten",
        "DokumenteProSeite": "OneHundred",
        "Seitennummer": "1",
    }
    url = f"{RIS}/Judikatur?{urlencode(params)}"
    arts = []
    try:
        data = json.loads(http_get(url))
        results = data.get("OgdSearchResult",{}).get("OgdDocumentResults",{})
        if isinstance(results, dict): results = results.get("OgdDocumentReference",[])
        if isinstance(results, dict): results = [results]
        if not isinstance(results, list): results = []

        for doc in results:
            d = doc.get("Data",{}).get("Metadaten",{})
            allg = d.get("Allgemein",{})
            jud = d.get("Judikatur",{})

            gz = (get_item(jud.get("Geschaeftszahl",{})) or [""])[0].strip()
            datum = str(jud.get("Entscheidungsdatum","") or "").strip()
            doc_url = str(allg.get("DokumentUrl","") or "").strip()
            kurz = strip(jud.get("Kurzinformation",""))
            normen = get_item(jud.get("Norm",{}))
            norm_str = "; ".join(normen[:4]) if normen else ""

            parts = []
            if norm_str: parts.append(f"📜 {norm_str}")
            if kurz: parts.append(kurz)
            excerpt = " — ".join(parts) if parts else ""

            if not gz: continue
            arts.append(dict(
                id=mid(doc_url or gz), title=f"VfGH {gz}", url=doc_url or "https://www.ris.bka.gv.at/Vfgh/",
                category="VfGH", excerpt=excerpt[:600], source="RIS",
                featured=False, date=pdate(datum), norm=norm_str,
            ))
        print(f"    ✓ {len(arts)} decisions")
    except Exception as e: print(f"    ✗ {type(e).__name__}: {e}"); traceback.print_exc()
    return arts

# ═══════════════ OGH.GV.AT ═══════════════
def fetch_ogh_website():
    print("  [OGH] ogh.gv.at...")
    try: from bs4 import BeautifulSoup
    except: print("    ✗ bs4 missing"); return []
    arts = []; seen = set()
    try:
        html = http_get("https://www.ogh.gv.at/entscheidungen/entscheidungen-ogh/").decode("utf-8","replace")
        soup = BeautifulSoup(html, "html.parser")
        for link in soup.find_all("a", href=True):
            href = link.get("href",""); text = link.get_text(" ", strip=True)
            if not text or len(text)<25: continue
            if "/entscheidungen-ogh/" not in href and "/entscheidungen/" not in href: continue
            if href.rstrip("/") in ("/entscheidungen","/entscheidungen/entscheidungen-ogh"): continue
            if not href.startswith("http"): href = "https://www.ogh.gv.at" + href
            if href in seen: continue; seen.add(href)
            parent = link.find_parent(["div","article","li","section","p","td"])
            gz = ""; date_str = ""
            if parent:
                ctx = parent.get_text(" ", strip=True)
                gz_m = re.search(r"(\d+\s*(?:Ob|Os|Nc|Fsc|ObA|ObS)\s*\d+/\d+\w?)", ctx)
                if gz_m: gz = gz_m.group(1).strip()
                date_m = re.search(r"(\d{2}\.\d{2}\.\d{4})", ctx)
                if date_m: date_str = date_m.group(1)
            title = f"OGH {gz}" if gz else text[:120]
            arts.append(dict(id=mid(href), title=title, url=href,
                category="OGH", excerpt=text[:600], source="ogh.gv.at",
                featured=False, date=pdate(date_str) or NOW.isoformat()))
        print(f"    ✓ {len(arts)} decisions")
    except Exception as e: print(f"    ✗ {type(e).__name__}: {e}")
    return arts

# ═══════════════ VFGH.GV.AT ═══════════════
def fetch_vfgh_website():
    print("  [VfGH] vfgh.gv.at...")
    try: from bs4 import BeautifulSoup
    except: print("    ✗ bs4 missing"); return []
    arts = []
    try:
        html = http_get("https://www.vfgh.gv.at/rechtsprechung/Ausgewaehlte_Entscheidungen.de.html").decode("utf-8","replace")
        soup = BeautifulSoup(html, "html.parser")
        for link in soup.find_all("a", href=True):
            href = link.get("href",""); text = link.get_text(strip=True)
            if not text or len(text)<20: continue
            if not re.search(r"VfGH|G \d+|E \d+|V \d+|Aufhebung|Abweisung|verfassungswidrig", text): continue
            if not href.startswith("http"): href = "https://www.vfgh.gv.at/" + href.lstrip("/")
            date_m = re.search(r"(\d{2}\.\d{2}\.\d{4})", text)
            arts.append(dict(id=mid(href), title=text[:200], url=href,
                category="VfGH", excerpt=text[:600], source="vfgh.gv.at",
                featured=False, date=pdate(date_m.group(1)) if date_m else NOW.isoformat()))
        print(f"    ✓ {len(arts)} decisions")
    except Exception as e: print(f"    ✗ {type(e).__name__}: {e}")
    return arts

# ═══════════════ EuGH ═══════════════
AT_KW = re.compile(r"Österreich|Austria|österreichisch|Austrian|Oberster Gerichtshof|"
    r"Landesgericht|BVwG|Verwaltungsgerichtshof|Verfassungsgerichtshof|"
    r"OGH|VfGH|VwGH|BMF|BMJ|österreichischen", re.IGNORECASE)

def fetch_eugh():
    arts = []; seen = set()
    for url, label in [
        ("http://curia.europa.eu/site/rss.jsp?lang=de&secondLang=en", "CURIA DE"),
        ("http://curia.europa.eu/site/rss.jsp?lang=en&secondLang=fr", "CURIA EN"),
    ]:
        print(f"  [EuGH] {label}")
        try:
            new = parse_rss(http_xml(url), "EuGH")
            for a in new:
                tk = re.sub(r"[^a-z0-9]","",a["title"].lower())[:50]
                if tk not in seen:
                    seen.add(tk)
                    if AT_KW.search(a["title"] + " " + a.get("excerpt","")):
                        a["category"] = "🇦🇹 EuGH (Österreich)"; a["featured"] = True
                    arts.append(a)
            print(f"    ✓ {len(new)} articles")
            if len(arts) >= 5: break
        except Exception as e: print(f"    ✗ {type(e).__name__}: {e}")
    return arts

# ═══════════════ GZ DEDUP ═══════════════
def dedup_gz(articles, pattern):
    gz_map = {}; no_gz = []
    web = {"ogh.gv.at","vfgh.gv.at"}
    for a in articles:
        m = re.search(pattern, a.get("title","") + " " + a.get("url",""))
        gz = m.group(1).strip() if m else ""
        if not gz: no_gz.append(a); continue
        if gz not in gz_map: gz_map[gz] = a
        else:
            ex = gz_map[gz]
            # Prefer RIS (has norm/rechtsgebiet) over website, unless website has longer excerpt
            if a["source"]=="RIS" and ex["source"] in web and a.get("norm"):
                # Merge: keep RIS metadata but add website excerpt if longer
                if len(ex.get("excerpt","")) > len(a.get("excerpt","")):
                    a["excerpt"] = ex["excerpt"]
                gz_map[gz] = a
            elif a["source"] in web and ex["source"]=="RIS" and ex.get("norm"):
                if len(a.get("excerpt","")) > len(ex.get("excerpt","")):
                    ex["excerpt"] = a["excerpt"]
            elif a["source"] in web and ex["source"] not in web: gz_map[gz]=a
            elif len(a.get("excerpt",""))>len(ex.get("excerpt","")): gz_map[gz]=a
    return list(gz_map.values()) + no_gz

OGH_GZ = r"(\d+\s*(?:Ob|Os|Nc|Fsc|Bkv|ObA|ObS)\s*\d+/\d+\w?)"
VFGH_GZ = r"((?:G|E|V|W I|UA|SV)\s*\d+/\d+)"

# ═══════════════ FEEDS ═══════════════
FEEDS_AT_NEWS = [
    ("https://www.derstandard.at/rss/recht", "Der Standard Recht"),
    ("https://www.derstandard.at/rss/wirtschaft", "Der Standard Wirtschaft"),
]
FEEDS_INTL_LAW = [
    ("https://verfassungsblog.de/feed/", "Verfassungsblog"),
    ("https://www.ejiltalk.org/feed/", "EJIL:Talk!"),
    ("https://opiniojuris.org/feed/", "Opinio Juris"),
]
FEEDS_NATIONAL = [
    ("https://rss.orf.at/news.xml", "ORF"),
    ("https://www.derstandard.at/rss/inland", "Der Standard"),
    ("https://www.diepresse.com/rss/politik", "Die Presse"),
    ("https://kurier.at/xml/rssd", "Kurier"),
    ("https://www.wienerzeitung.at/rss/politik.xml", "Wiener Zeitung"),
    ("https://www.krone.at/nachrichten/rss/nachrichten", "Krone"),
    ("https://www.salzburg24.at/rss", "Salzburg24"),
]
FEEDS_INTERNATIONAL = [
    ("https://www.derstandard.at/rss/international", "Der Standard"),
    ("https://feeds.bbci.co.uk/news/world/rss.xml", "BBC World"),
    ("https://rss.nytimes.com/services/xml/rss/nyt/World.xml", "New York Times"),
    ("https://www.theguardian.com/world/rss", "The Guardian"),
    ("https://www.spiegel.de/international/index.rss", "Der Spiegel"),
    ("https://www.zeit.de/politik/ausland/index", "Die Zeit"),
    ("https://www.tagesschau.de/xml/rss2/", "Tagesschau"),
    ("https://www.nzz.ch/recent.rss", "NZZ"),
]

# ═══════════════ MAIN ═══════════════
def main():
    print(f"🗞️  Newsletter v7 — {NOW.strftime('%Y-%m-%d %H:%M UTC')}\n")
    ex = {}
    if DATA.exists():
        with open(DATA, "r", encoding="utf-8") as f: ex = json.load(f)
    r = {}

    print("══ OGH Urteile ══")
    ogh = ris_justiz("OGH", "OGH")
    ogh += fetch_ogh_website()
    ogh = merge(ex.get("recht_ogh",[]), ogh)
    r["recht_ogh"] = trim(dedup_gz(ogh, OGH_GZ))
    print(f"  → Total: {len(r['recht_ogh'])}\n")

    print("══ VfGH Urteile ══")
    vfgh = ris_vfgh()
    vfgh += fetch_vfgh_website()
    vfgh = merge(ex.get("recht_vfgh",[]), vfgh)
    r["recht_vfgh"] = trim(dedup_gz(vfgh, VFGH_GZ), 20)
    print(f"  → Total: {len(r['recht_vfgh'])}\n")

    print("══ EuGH Urteile ══")
    r["recht_eugh"] = trim(merge(ex.get("recht_eugh",[]), fetch_eugh()))
    print(f"  → Total: {len(r['recht_eugh'])}\n")

    for tab, feeds in [("recht_news",FEEDS_AT_NEWS),("recht_intl",FEEDS_INTL_LAW),
                       ("national",FEEDS_NATIONAL),("international",FEEDS_INTERNATIONAL)]:
        print(f"══ {tab} ══")
        r[tab] = trim(merge(ex.get(tab,[]), fetch_rss(feeds, tab)))
        print(f"  → Total: {len(r[tab])}\n")

    r["_meta"] = {"last_updated": NOW.isoformat()}
    with open(DATA, "w", encoding="utf-8") as f: json.dump(r, f, ensure_ascii=False, indent=2)
    total = sum(len(r[k]) for k in r if k != "_meta")
    print(f"✓ data.json — {total} articles total")

if __name__ == "__main__": main()
