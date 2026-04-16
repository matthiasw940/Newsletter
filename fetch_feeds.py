#!/usr/bin/env python3
"""Newsletter Feed Fetcher v4.
Primary strategy: website scraping + RSS (reliable).
Secondary: RIS SOAP API (may fail, handled gracefully).
"""
import json, hashlib, re, sys, traceback
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.parse import quote
from html import unescape

MAX = 25; DAYS = 14; DATA = Path(__file__).parent / "data.json"
NOW = datetime.now(timezone.utc)

def mid(s): return hashlib.md5(s.encode()).hexdigest()[:12]
def strip(t):
    if not t: return ""
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", "", t))).strip()[:500]

def http(url, timeout=20, data=None, headers=None, method=None):
    h = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:120.0) Gecko/20100101 Firefox/120.0",
         "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
         "Accept-Language": "de-AT,de;q=0.9,en;q=0.8"}
    if headers: h.update(headers)
    if method is None: method = "POST" if data else "GET"
    req = Request(url, data=data, headers=h, method=method)
    with urlopen(req, timeout=timeout) as r: return r.read()

def pdate(s):
    if not s: return NOW.isoformat()
    s = s.replace("GMT","+0000").replace("UTC","+0000").strip()
    for f in ["%a, %d %b %Y %H:%M:%S %z","%Y-%m-%dT%H:%M:%S%z","%Y-%m-%dT%H:%M:%SZ",
              "%Y-%m-%d %H:%M:%S","%Y-%m-%d","%d.%m.%Y"]:
        try: return datetime.strptime(s, f).isoformat()
        except: pass
    return NOW.isoformat()

def trim(arts):
    cutoff = NOW - timedelta(days=DAYS)
    arts.sort(key=lambda a: a.get("date",""), reverse=True)
    out = []
    for a in arts:
        try:
            d = datetime.fromisoformat(a["date"].replace("Z","+00:00"))
            if d.tzinfo is None: d = d.replace(tzinfo=timezone.utc)
            if d >= cutoff: out.append(a)
        except: out.append(a)
    return out[:MAX]

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
        print(f"  [{name}] {src}: {url[:80]}...")
        try:
            new = parse_rss(http(url), src)
            arts.extend(new); print(f"    ✓ {len(new)} articles")
        except Exception as e: print(f"    ✗ {type(e).__name__}: {e}")
    return arts

# ═══════════════ OGH — PRIMARY: ogh.gv.at website ═══════════════
def fetch_ogh_website():
    """Scrape ogh.gv.at — this is the most reliable source with good summaries."""
    print("  [OGH] ogh.gv.at (primary source)...")
    try: from bs4 import BeautifulSoup
    except: print("    ✗ bs4 missing"); return []
    arts = []; seen = set()
    try:
        html = http("https://www.ogh.gv.at/entscheidungen/entscheidungen-ogh/").decode("utf-8","replace")
        soup = BeautifulSoup(html, "html.parser")
        for link in soup.find_all("a", href=True):
            href = link.get("href",""); text = link.get_text(strip=True)
            if not text or len(text) < 20: continue
            if "/entscheidungen/" not in href: continue
            if href.rstrip("/").endswith(("/entscheidungen","/entscheidungen-ogh")): continue
            if not href.startswith("http"): href = "https://www.ogh.gv.at" + href
            if href in seen: continue; seen.add(href)
            parent = link.find_parent(["div","article","li","section","p"])
            excerpt = text; date_str = ""; gz = ""
            if parent:
                full = parent.get_text(" ", strip=True)
                gz_m = re.search(r"OGH\s*\|\s*([^|]+?)\s*\|", full)
                if gz_m: gz = gz_m.group(1).strip()
                date_m = re.search(r"(\d{2}\.\d{2}\.\d{4})", full)
                if date_m: date_str = date_m.group(1)
            title = f"OGH {gz}" if gz else text[:100]
            arts.append(dict(id=mid(href), title=title, url=href,
                category="OGH", excerpt=excerpt, source="ogh.gv.at",
                featured=False, date=pdate(date_str)))
        print(f"    ✓ {len(arts)} decisions with summaries")
    except Exception as e: print(f"    ✗ {type(e).__name__}: {e}")
    return arts

# ═══════════════ OGH — SECONDARY: RIS SOAP API ═══════════════
def fetch_ogh_ris():
    """Try RIS OGD SOAP API v1.3 (the documented, working one)."""
    print("  [OGH] RIS SOAP API (secondary)...")
    soap = b"""<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"
  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
  xmlns:xsd="http://www.w3.org/2001/XMLSchema">
<soap:Body>
  <request xmlns="http://ogd.bka.gv.at/">
    <application>Justiz</application>
    <query>&lt;OGDSearchRequest xmlns="http://ris.bka.gv.at/Search/1.3/OGD"&gt;&lt;Justiz&gt;&lt;Gericht&gt;OGH&lt;/Gericht&gt;&lt;SucheNachRechtssatz&gt;True&lt;/SucheNachRechtssatz&gt;&lt;SucheNachText&gt;True&lt;/SucheNachText&gt;&lt;/Justiz&gt;&lt;ImRisSeit&gt;EinerWoche&lt;/ImRisSeit&gt;&lt;DokumenteProSeite&gt;Zwanzig&lt;/DokumenteProSeite&gt;&lt;Seitennummer&gt;1&lt;/Seitennummer&gt;&lt;/OGDSearchRequest&gt;</query>
  </request>
</soap:Body></soap:Envelope>"""
    arts = []
    try:
        raw = http("https://data.bka.gv.at/ris/OGDService.asmx",
            data=soap, headers={"Content-Type":"text/xml; charset=utf-8",
            "SOAPAction":'"http://ogd.bka.gv.at/request"'}).decode("utf-8","replace")
        m = re.search(r"<requestResult>(.*?)</requestResult>", raw, re.DOTALL)
        if not m: print("    ✗ No requestResult found"); print(f"    Response preview: {raw[:300]}"); return []
        inner = unescape(m.group(1))
        root = ET.fromstring(inner)
        ns = "http://ris.bka.gv.at/Search/1.3/OGD"
        for doc in root.iter(f"{{{ns}}}OGDDocumentReference"):
            gz = (doc.findtext(f"{{{ns}}}Geschaeftszahl") or "").strip()
            kurz = strip(doc.findtext(f"{{{ns}}}Kurzinformation") or "")
            url = (doc.findtext(f"{{{ns}}}DokumentUrl") or "").strip()
            datum = (doc.findtext(f"{{{ns}}}Entscheidungsdatum") or "").strip()
            if not gz and not kurz: continue
            arts.append(dict(id=mid(url or gz), title=f"OGH {gz}" if gz else "OGH",
                url=url or f"https://www.ris.bka.gv.at/Jus/", category="OGH",
                excerpt=kurz, source="RIS", featured=False, date=pdate(datum)))
        print(f"    ✓ {len(arts)} from RIS SOAP")
    except Exception as e:
        print(f"    ✗ {type(e).__name__}: {e}")
        traceback.print_exc()
    return arts

# ═══════════════ VfGH ═══════════════
def fetch_vfgh_website():
    print("  [VfGH] vfgh.gv.at (primary)...")
    try: from bs4 import BeautifulSoup
    except: print("    ✗ bs4 missing"); return []
    arts = []
    for url in ["https://www.vfgh.gv.at/medien/Pressemitteilungen.de.html",
                "https://www.vfgh.gv.at/rechtsprechung/Ausgewaehlte_Entscheidungen.de.html"]:
        try:
            html = http(url).decode("utf-8","replace")
            soup = BeautifulSoup(html, "html.parser")
            for link in soup.find_all("a", href=True):
                href = link.get("href",""); text = link.get_text(strip=True)
                if not text or len(text)<20: continue
                if not re.search(r"VfGH|G \d+|E \d+|V \d+|Aufhebung|Abweisung|Zurückweisung|verfassungswidrig", text): continue
                if not href.startswith("http"): href = "https://www.vfgh.gv.at/" + href.lstrip("/")
                date_m = re.search(r"(\d{2}\.\d{2}\.\d{4})", text)
                arts.append(dict(id=mid(href), title=text[:200], url=href,
                    category="VfGH", excerpt=text[:500], source="vfgh.gv.at",
                    featured=False, date=pdate(date_m.group(1)) if date_m else NOW.isoformat()))
            print(f"    ✓ {len(arts)} from {url.split('/')[-1]}")
        except Exception as e: print(f"    ✗ {type(e).__name__}: {e}")
    return arts

def fetch_vfgh_ris():
    print("  [VfGH] RIS SOAP API...")
    soap = b"""<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"
  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
  xmlns:xsd="http://www.w3.org/2001/XMLSchema">
<soap:Body>
  <request xmlns="http://ogd.bka.gv.at/">
    <application>Vfgh</application>
    <query>&lt;OGDSearchRequest xmlns="http://ris.bka.gv.at/Search/1.3/OGD"&gt;&lt;ImRisSeit&gt;EinerWoche&lt;/ImRisSeit&gt;&lt;DokumenteProSeite&gt;Zwanzig&lt;/DokumenteProSeite&gt;&lt;Seitennummer&gt;1&lt;/Seitennummer&gt;&lt;/OGDSearchRequest&gt;</query>
  </request>
</soap:Body></soap:Envelope>"""
    arts = []
    try:
        raw = http("https://data.bka.gv.at/ris/OGDService.asmx",
            data=soap, headers={"Content-Type":"text/xml; charset=utf-8",
            "SOAPAction":'"http://ogd.bka.gv.at/request"'}).decode("utf-8","replace")
        m = re.search(r"<requestResult>(.*?)</requestResult>", raw, re.DOTALL)
        if not m: print("    ✗ No requestResult"); return []
        inner = unescape(m.group(1))
        root = ET.fromstring(inner)
        ns = "http://ris.bka.gv.at/Search/1.3/OGD"
        for doc in root.iter(f"{{{ns}}}OGDDocumentReference"):
            gz = (doc.findtext(f"{{{ns}}}Geschaeftszahl") or "").strip()
            kurz = strip(doc.findtext(f"{{{ns}}}Kurzinformation") or "")
            url = (doc.findtext(f"{{{ns}}}DokumentUrl") or "").strip()
            datum = (doc.findtext(f"{{{ns}}}Entscheidungsdatum") or "").strip()
            if not gz and not kurz: continue
            arts.append(dict(id=mid(url or gz), title=f"VfGH {gz}" if gz else "VfGH",
                url=url or "https://www.ris.bka.gv.at/Vfgh/", category="VfGH",
                excerpt=kurz, source="RIS", featured=False, date=pdate(datum)))
        print(f"    ✓ {len(arts)} from RIS SOAP")
    except Exception as e: print(f"    ✗ {type(e).__name__}: {e}")
    return arts

# ═══════════════ EuGH — multiple fallback URLs ═══════════════
AT_KW = re.compile(r"Österreich|Austria|österreichisch|Austrian|Oberster Gerichtshof|"
    r"Landesgericht|Bezirksgericht|BVwG|Verwaltungsgerichtshof|Verfassungsgerichtshof|"
    r"Wien|Graz|Linz|Salzburg|Innsbruck|OGH|VfGH|VwGH|BMF|BMJ|"
    r"österreichischen|Austrian law|Austrian court", re.IGNORECASE)

def fetch_eugh():
    arts = []; seen = set()
    # Try multiple CURIA RSS URLs (old and new formats)
    curia_urls = [
        ("https://curia.europa.eu/jcms/upload/docs/application/rss+xml/cp_de.xml", "CURIA DE"),
        ("https://curia.europa.eu/jcms/upload/docs/application/rss+xml/cp_en.xml", "CURIA EN"),
        ("http://curia.europa.eu/site/rss.jsp?lang=de&secondLang=en", "CURIA old DE"),
        ("http://curia.europa.eu/site/rss.jsp?lang=en&secondLang=fr", "CURIA old EN"),
    ]
    for url, label in curia_urls:
        print(f"  [EuGH] {label}: {url[:70]}...")
        try:
            new = parse_rss(http(url), "EuGH")
            for a in new:
                tk = re.sub(r"[^a-z0-9]","",a["title"].lower())[:50]
                if tk not in seen:
                    seen.add(tk)
                    txt = a["title"] + " " + a.get("excerpt","")
                    if AT_KW.search(txt):
                        a["category"] = "🇦🇹 EuGH (Österreich)"
                        a["featured"] = True
                    arts.append(a)
            print(f"    ✓ {len(new)} articles")
            if len(arts) >= 5: break  # got enough, skip remaining URLs
        except Exception as e: print(f"    ✗ {type(e).__name__}: {e}")

    # Fallback: EUR-Lex recent case law RSS
    if len(arts) == 0:
        print("  [EuGH] Fallback: EUR-Lex RSS...")
        try:
            eurlex_url = "https://eur-lex.europa.eu/EN/display-feed.html?rssId=47&language=de"
            new = parse_rss(http(eurlex_url), "EUR-Lex")
            for a in new:
                tk = re.sub(r"[^a-z0-9]","",a["title"].lower())[:50]
                if tk not in seen:
                    seen.add(tk)
                    txt = a["title"] + " " + a.get("excerpt","")
                    if AT_KW.search(txt):
                        a["category"] = "🇦🇹 EuGH (Österreich)"
                        a["featured"] = True
                    else:
                        a["category"] = "EuGH"
                    arts.append(a)
            print(f"    ✓ {len(new)} from EUR-Lex")
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
    ("https://www.vfgh.gv.at/medien/VfGH_Entscheidungen_und_Pressemitteilungen.rss", "VfGH Presse"),
    ("https://www.parlament.gv.at/Filter/api/filter/rss?NRBR=NR&GP=XXVIII&LISTE=Alle&listeId=110&FBEZ=FP_010", "Parlament"),
    ("https://rss.orf.at/news.xml", "ORF"),
]
FEEDS_INTL_LAW = [
    ("https://verfassungsblog.de/feed/", "Verfassungsblog"),
    ("https://www.lawfaremedia.org/feed", "Lawfare"),
    ("https://www.ejiltalk.org/feed/", "EJIL:Talk!"),
    ("https://opiniojuris.org/feed/", "Opinio Juris"),
]
FEEDS_NATIONAL = [
    ("https://rss.orf.at/news.xml", "ORF"),
    ("https://www.derstandard.at/rss/inland", "Der Standard"),
    ("https://www.parlament.gv.at/Filter/api/filter/rss?NRBR=NR&GP=XXVIII&LISTE=Alle&listeId=110&FBEZ=FP_010", "Parlament"),
]
FEEDS_INTERNATIONAL = [
    ("https://www.derstandard.at/rss/international", "Der Standard"),
    ("https://feeds.bbci.co.uk/news/world/rss.xml", "BBC World"),
]

# ═══════════════ MAIN ═══════════════
def main():
    print(f"🗞️  Newsletter v4 — {NOW.strftime('%Y-%m-%d %H:%M UTC')}\n")
    ex = {}
    if DATA.exists():
        with open(DATA, "r", encoding="utf-8") as f: ex = json.load(f)
    r = {}

    print("══ OGH Urteile ══")
    ogh = fetch_ogh_website()  # primary
    ogh += fetch_ogh_ris()      # secondary
    ogh = merge(ex.get("recht_ogh",[]), ogh)
    r["recht_ogh"] = trim(dedup_gz(ogh, OGH_GZ))
    print(f"  → Total: {len(r['recht_ogh'])}\n")

    print("══ VfGH Urteile ══")
    vfgh = fetch_vfgh_website()
    vfgh += fetch_vfgh_ris()
    vfgh += fetch_rss([("https://www.vfgh.gv.at/medien/VfGH_Entscheidungen_und_Pressemitteilungen.rss","VfGH")],"VfGH RSS")
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
    print(f"✓ data.json updated — {total} articles total")

if __name__ == "__main__": main()
