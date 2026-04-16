#!/usr/bin/env python3
"""Newsletter v6 — RIS OGD v2.6 is a REST/JSON API (not SOAP!).
Correct URL pattern: https://data.bka.gv.at/ris/api/v2.6/{Controller}?Applikation={App}&params...
Response: JSON
"""
import json, hashlib, re, traceback
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.parse import urlencode
from html import unescape

MAX = 25; DAYS = 30; DATA = Path(__file__).parent / "data.json"
NOW = datetime.now(timezone.utc)
RIS = "https://data.bka.gv.at/ris/api/v2.6"

def mid(s): return hashlib.md5(s.encode()).hexdigest()[:12]
def strip(t):
    if not t: return ""
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", "", str(t)))).strip()[:500]

def http_get(url, timeout=25):
    req = Request(url, headers={
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:120.0) Gecko/20100101 Firefox/120.0",
        "Accept": "application/json, text/html, */*",
        "Accept-Language": "de-AT,de;q=0.9,en;q=0.8"})
    with urlopen(req, timeout=timeout) as r: return r.read()

def http_get_xml(url, timeout=25):
    req = Request(url, headers={
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:120.0) Gecko/20100101 Firefox/120.0",
        "Accept": "application/rss+xml, application/xml, text/xml, text/html, */*",
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

def trim(arts):
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
    return out[:MAX]

def merge(existing, new_arts):
    urls = {a["url"] for a in existing}
    arts = list(existing)
    for a in new_arts:
        if a["url"] not in urls: arts.append(a); urls.add(a["url"])
    return arts

# ═══════════════ RSS PARSER ═══════════════
def parse_rss(raw, src):
    try: root = ET.fromstring(raw)
    except: return []
    arts = []
    for item in root.findall(".//item"):
        t = (item.findtext("title") or "").strip()
        l = (item.findtext("link") or "").strip()
        if not t or not l: continue
        arts.append(dict(id=mid(l),title=t,url=l,category=item.findtext("category",src) or src,
            excerpt=strip(item.findtext("description","")),source=src,
            date=pdate(item.findtext("pubDate","")),featured=False))
    if arts: return arts
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
            new = parse_rss(http_get_xml(url), src)
            arts.extend(new); print(f"    ✓ {len(new)} articles")
        except Exception as e: print(f"    ✗ {type(e).__name__}: {e}")
    return arts

# ═══════════════ RIS REST API v2.6 (JSON!) ═══════════════

def ris_justiz(gericht, label):
    """Fetch from RIS REST API: GET /Judikatur?Applikation=Justiz&Gericht=OGH&..."""
    print(f"  [{label}] RIS REST API v2.6...")
    params = {
        "Applikation": "Justiz",
        "Gericht": gericht,
        "ImRisSeit": "EinerWoche",
        "DokumenteProSeite": "Twenty",
        "Seitennummer": "1",
        "Dokumenttyp.SucheInRechtssaetzen": "true",
        "Dokumenttyp.SucheInEntscheidungstexten": "true",
    }
    url = f"{RIS}/Judikatur?{urlencode(params)}"
    arts = []
    try:
        raw = http_get(url)
        data = json.loads(raw)
        results = data.get("OgdSearchResult", {}).get("OgdDocumentResults", [])
        if isinstance(results, dict): results = results.get("OgdDocumentReference", [])
        if isinstance(results, dict): results = [results]  # single result
        if not isinstance(results, list): results = []

        for doc in results:
            # Navigate the JSON structure
            meta = doc.get("Data", {}).get("Metadaten", {}).get("Justiz", {}).get("Justiz", {})
            if not meta and "Data" in doc:
                meta = doc["Data"].get("Metadaten", {})

            gz = str(meta.get("Geschaeftszahl", "") or doc.get("Geschaeftszahl", "") or "").strip()
            kurz = strip(meta.get("Kurzinformation", "") or doc.get("Kurzinformation", ""))
            datum = str(meta.get("Entscheidungsdatum", "") or doc.get("Entscheidungsdatum", "") or "").strip()

            # Get document URL from Dokumentliste
            doc_url = ""
            doklist = doc.get("Data", {}).get("Dokumentliste", {})
            if isinstance(doklist, dict):
                content_ref = doklist.get("ContentReference", {})
                if isinstance(content_ref, list) and content_ref:
                    content_ref = content_ref[0]
                urls_block = content_ref.get("Urls", {}) if isinstance(content_ref, dict) else {}
                if isinstance(urls_block, dict):
                    content_urls = urls_block.get("ContentUrl", [])
                    if isinstance(content_urls, dict): content_urls = [content_urls]
                    for cu in (content_urls if isinstance(content_urls, list) else []):
                        if isinstance(cu, dict) and cu.get("Url"):
                            doc_url = cu["Url"]; break

            if not doc_url:
                doc_url = f"https://www.ris.bka.gv.at/Ergebnis.wxe?Abfrage=Justiz&Gericht={gericht}&Geschaeftszahl={gz}"

            if not gz and not kurz: continue

            arts.append(dict(
                id=mid(doc_url or gz),
                title=f"{label} {gz}" if gz else f"{label} Entscheidung",
                url=doc_url, category=label,
                excerpt=kurz, source="RIS",
                featured=False, date=pdate(datum)
            ))

        print(f"    ✓ {len(arts)} decisions from RIS API")
    except Exception as e:
        print(f"    ✗ {type(e).__name__}: {e}")
        traceback.print_exc()
    return arts

def ris_vfgh():
    """Fetch VfGH from RIS REST API."""
    print(f"  [VfGH] RIS REST API v2.6...")
    params = {
        "Applikation": "Vfgh",
        "ImRisSeit": "EinerWoche",
        "DokumenteProSeite": "Twenty",
        "Seitennummer": "1",
    }
    url = f"{RIS}/Judikatur?{urlencode(params)}"
    arts = []
    try:
        raw = http_get(url)
        data = json.loads(raw)
        results = data.get("OgdSearchResult", {}).get("OgdDocumentResults", [])
        if isinstance(results, dict): results = results.get("OgdDocumentReference", [])
        if isinstance(results, dict): results = [results]
        if not isinstance(results, list): results = []

        for doc in results:
            meta = doc.get("Data", {}).get("Metadaten", {}).get("Vfgh", {}).get("Vfgh", {})
            if not meta: meta = doc.get("Data", {}).get("Metadaten", {})

            gz = str(meta.get("Geschaeftszahl", "") or doc.get("Geschaeftszahl", "") or "").strip()
            kurz = strip(meta.get("Kurzinformation", "") or doc.get("Kurzinformation", ""))
            datum = str(meta.get("Entscheidungsdatum", "") or "").strip()

            doc_url = ""
            doklist = doc.get("Data", {}).get("Dokumentliste", {})
            if isinstance(doklist, dict):
                cr = doklist.get("ContentReference", {})
                if isinstance(cr, list) and cr: cr = cr[0]
                urls_b = cr.get("Urls", {}) if isinstance(cr, dict) else {}
                if isinstance(urls_b, dict):
                    cus = urls_b.get("ContentUrl", [])
                    if isinstance(cus, dict): cus = [cus]
                    for cu in (cus if isinstance(cus, list) else []):
                        if isinstance(cu, dict) and cu.get("Url"):
                            doc_url = cu["Url"]; break

            if not doc_url: doc_url = f"https://www.ris.bka.gv.at/Vfgh/"
            if not gz and not kurz: continue

            arts.append(dict(id=mid(doc_url or gz),
                title=f"VfGH {gz}" if gz else "VfGH Entscheidung",
                url=doc_url, category="VfGH", excerpt=kurz,
                source="RIS", featured=False, date=pdate(datum)))

        print(f"    ✓ {len(arts)} from RIS API")
    except Exception as e:
        print(f"    ✗ {type(e).__name__}: {e}")
        traceback.print_exc()
    return arts

# ═══════════════ OGH.GV.AT WEBSITE ═══════════════
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
            if not text or len(text) < 25: continue
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
                category="OGH", excerpt=text[:500], source="ogh.gv.at",
                featured=False, date=pdate(date_str) or NOW.isoformat()))
        print(f"    ✓ {len(arts)} decisions")
    except Exception as e: print(f"    ✗ {type(e).__name__}: {e}")
    return arts

# ═══════════════ VFGH.GV.AT WEBSITE ═══════════════
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
                category="VfGH", excerpt=text[:500], source="vfgh.gv.at",
                featured=False, date=pdate(date_m.group(1)) if date_m else NOW.isoformat()))
        print(f"    ✓ {len(arts)} decisions")
    except Exception as e: print(f"    ✗ {type(e).__name__}: {e}")
    return arts

# ═══════════════ EuGH (CURIA old RSS — confirmed working) ═══════════════
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
            new = parse_rss(http_get_xml(url), "EuGH")
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
            if a["source"] in web and ex["source"] not in web: gz_map[gz]=a
            elif len(a.get("excerpt",""))>len(ex.get("excerpt","")) and ex["source"] not in web: gz_map[gz]=a
    return list(gz_map.values()) + no_gz

OGH_GZ = r"(\d+\s*(?:Ob|Os|Nc|Fsc|Bkv|ObA|ObS)\s*\d+/\d+\w?)"
VFGH_GZ = r"((?:G|E|V|W I|UA|SV)\s*\d+/\d+)"

# ═══════════════ FEEDS ═══════════════
FEEDS_AT_NEWS = [
    ("https://www.derstandard.at/rss/recht", "Der Standard Recht"),
]
FEEDS_INTL_LAW = [
    ("https://verfassungsblog.de/feed/", "Verfassungsblog"),
    ("https://www.ejiltalk.org/feed/", "EJIL:Talk!"),
    ("https://opiniojuris.org/feed/", "Opinio Juris"),
]
FEEDS_NATIONAL = [
    ("https://www.derstandard.at/rss/inland", "Der Standard"),
    ("https://www.derstandard.at/rss", "Der Standard Newsroom"),
]
FEEDS_INTERNATIONAL = [
    ("https://www.derstandard.at/rss/international", "Der Standard"),
    ("https://feeds.bbci.co.uk/news/world/rss.xml", "BBC World"),
]

# ═══════════════ MAIN ═══════════════
def main():
    print(f"🗞️  Newsletter v6 — {NOW.strftime('%Y-%m-%d %H:%M UTC')}\n")
    ex = {}
    if DATA.exists():
        with open(DATA, "r", encoding="utf-8") as f: ex = json.load(f)
    r = {}

    print("══ OGH Urteile ══")
    ogh = ris_justiz("OGH", "OGH")      # RIS REST API (JSON!)
    ogh += fetch_ogh_website()            # ogh.gv.at scraping
    ogh = merge(ex.get("recht_ogh",[]), ogh)
    r["recht_ogh"] = trim(dedup_gz(ogh, OGH_GZ))
    print(f"  → Total: {len(r['recht_ogh'])}\n")

    print("══ VfGH Urteile ══")
    vfgh = ris_vfgh()                     # RIS REST API (JSON!)
    vfgh += fetch_vfgh_website()          # vfgh.gv.at scraping
    vfgh = merge(ex.get("recht_vfgh",[]), vfgh)
    r["recht_vfgh"] = trim(dedup_gz(vfgh, VFGH_GZ))
    print(f"  → Total: {len(r['recht_vfgh'])}\n")

    print("══ EuGH Urteile ══")
    r["recht_eugh"] = trim(merge(ex.get("recht_eugh",[]), fetch_eugh()))
    print(f"  → Total: {len(r['recht_eugh'])}\n")

    print("══ AT Recht News ══")
    r["recht_news"] = trim(merge(ex.get("recht_news",[]), fetch_rss(FEEDS_AT_NEWS, "recht_news")))
    print(f"  → Total: {len(r['recht_news'])}\n")

    print("══ Intl. Recht ══")
    r["recht_intl"] = trim(merge(ex.get("recht_intl",[]), fetch_rss(FEEDS_INTL_LAW, "recht_intl")))
    print(f"  → Total: {len(r['recht_intl'])}\n")

    print("══ National ══")
    r["national"] = trim(merge(ex.get("national",[]), fetch_rss(FEEDS_NATIONAL, "national")))
    print(f"  → Total: {len(r['national'])}\n")

    print("══ International ══")
    r["international"] = trim(merge(ex.get("international",[]), fetch_rss(FEEDS_INTERNATIONAL, "international")))
    print(f"  → Total: {len(r['international'])}\n")

    r["_meta"] = {"last_updated": NOW.isoformat()}
    with open(DATA, "w", encoding="utf-8") as f: json.dump(r, f, ensure_ascii=False, indent=2)
    total = sum(len(r[k]) for k in r if k != "_meta")
    print(f"✓ data.json — {total} articles total")

if __name__ == "__main__": main()
