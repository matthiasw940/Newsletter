#!/usr/bin/env python3
"""Newsletter v8 — Fixed norm extraction, Falter, title-dedup."""
import json,hashlib,re,traceback,xml.etree.ElementTree as ET
from datetime import datetime,timedelta,timezone
from pathlib import Path
from urllib.request import urlopen,Request
from urllib.parse import urlencode
from html import unescape

MAX=25;DAYS=60;DATA=Path(__file__).parent/"data.json";NOW=datetime.now(timezone.utc)
RIS="https://data.bka.gv.at/ris/api/v2.6"

def mid(s):return hashlib.md5(s.encode()).hexdigest()[:12]
def strip(t):
    if not t:return ""
    return re.sub(r"\s+"," ",unescape(re.sub(r"<[^>]+>","",str(t)))).strip()[:800]
def get_item(obj):
    if isinstance(obj,dict):
        v=obj.get("item","")
        return v if isinstance(v,list) else([str(v)] if v else [])
    return [obj] if isinstance(obj,str) and obj else []
def http_get(url,timeout=25):
    req=Request(url,headers={"User-Agent":"Mozilla/5.0 (X11; Linux x86_64; rv:120.0) Gecko/20100101 Firefox/120.0","Accept":"application/json, text/html, */*","Accept-Language":"de-AT,de;q=0.9,en;q=0.8"})
    with urlopen(req,timeout=timeout) as r:return r.read()
def http_xml(url,timeout=25):
    req=Request(url,headers={"User-Agent":"Mozilla/5.0 (X11; Linux x86_64; rv:120.0) Gecko/20100101 Firefox/120.0","Accept":"application/rss+xml, application/xml, text/xml, */*","Accept-Language":"de-AT,de;q=0.9,en;q=0.8"})
    with urlopen(req,timeout=timeout) as r:return r.read()
def pdate(s):
    if not s:return ""
    s=str(s).replace("GMT","+0000").replace("UTC","+0000").strip()
    for f in ["%a, %d %b %Y %H:%M:%S %z","%Y-%m-%dT%H:%M:%S%z","%Y-%m-%dT%H:%M:%SZ","%Y-%m-%d %H:%M:%S","%Y-%m-%d","%d.%m.%Y"]:
        try:return datetime.strptime(s,f).isoformat()
        except:pass
    return ""
def trim(arts,max_n=MAX):
    cutoff=NOW-timedelta(days=DAYS);arts.sort(key=lambda a:a.get("date","") or "9999",reverse=True)
    out=[]
    for a in arts:
        d=a.get("date","")
        if not d:out.append(a);continue
        try:
            dt=datetime.fromisoformat(d.replace("Z","+00:00"))
            if dt.tzinfo is None:dt=dt.replace(tzinfo=timezone.utc)
            if dt>=cutoff:out.append(a)
        except:out.append(a)
    return out[:max_n]
def merge(existing,new_arts):
    urls={a["url"] for a in existing};arts=list(existing)
    for a in new_arts:
        if a["url"] not in urls:arts.append(a);urls.add(a["url"])
    return arts
def title_dedup(articles):
    seen={};out=[]
    for a in articles:
        key=re.sub(r"[^a-zaeoeue0-9 ]","",a["title"].lower())[:40].strip()
        key=re.sub(r"\b(der|die|das|und|in|von|fuer|mit|auf|zu|im|am|ist|ein|eine|nach|vor|ueber|wird|hat|bei|als|den|dem|des|sich|nicht|auch|noch|wie|aus)\b","",key).strip()
        key=re.sub(r"\s+"," ",key)[:30]
        if key and key in seen:
            if len(a.get("excerpt",""))>len(seen[key].get("excerpt","")):
                out=[x for x in out if x is not seen[key]];out.append(a);seen[key]=a
        else:seen[key]=a;out.append(a)
    return out

# ═══════ RSS ═══════
def parse_rss(raw,src):
    try:root=ET.fromstring(raw)
    except:return []
    arts=[];dc="{http://purl.org/dc/elements/1.1/}";rdf="{http://purl.org/rss/1.0/}"
    for item in root.findall(".//item"):
        t=(item.findtext("title") or "").strip();l=(item.findtext("link") or "").strip()
        if not t or not l:continue
        cat=item.findtext("category","") or item.findtext(f"{dc}subject","") or src
        pub=item.findtext("pubDate","") or item.findtext(f"{dc}date","")
        arts.append(dict(id=mid(l),title=t,url=l,category=cat,excerpt=strip(item.findtext("description","")),source=src,date=pdate(pub),featured=False))
    if arts:return arts
    for item in root.findall(f"{rdf}item"):
        t=(item.findtext(f"{rdf}title") or item.findtext("title") or "").strip()
        l=(item.findtext(f"{rdf}link") or item.findtext("link") or "").strip()
        if not t or not l:continue
        arts.append(dict(id=mid(l),title=t,url=l,category=item.findtext(f"{dc}subject","") or src,excerpt=strip(item.findtext(f"{rdf}description","") or item.findtext("description","")),source=src,date=pdate(item.findtext(f"{dc}date","")),featured=False))
    if arts:return arts
    ns="{http://www.w3.org/2005/Atom}"
    for e in root.findall(f"{ns}entry"):
        t=(e.findtext(f"{ns}title") or "").strip();lk=e.find(f"{ns}link[@rel='alternate']") or e.find(f"{ns}link")
        l=lk.get("href","") if lk is not None else ""
        if not t or not l:continue
        arts.append(dict(id=mid(l),title=t,url=l,category=src,excerpt=strip(e.findtext(f"{ns}summary","") or e.findtext(f"{ns}content","")),source=src,date=pdate(e.findtext(f"{ns}updated","") or e.findtext(f"{ns}published","")),featured=False))
    return arts
def fetch_rss(feeds,name):
    arts=[]
    for url,src in feeds:
        print(f"  [{name}] {src}")
        try:new=parse_rss(http_xml(url),src);arts.extend(new);print(f"    \u2713 {len(new)} articles")
        except Exception as e:print(f"    \u2717 {type(e).__name__}: {e}")
    return arts

# ═══════ RIS JUSTIZ (OGH) — FIXED variable order ═══════
def ris_justiz(gericht,label):
    print(f"  [{label}] RIS REST API v2.6...")
    params={"Applikation":"Justiz","Gericht":gericht,"ImRisSeit":"ZweiWochen","DokumenteProSeite":"OneHundred","Seitennummer":"1","Dokumenttyp.SucheInRechtssaetzen":"true","Dokumenttyp.SucheInEntscheidungstexten":"true"}
    url=f"{RIS}/Judikatur?{urlencode(params)}";arts=[]
    try:
        data=json.loads(http_get(url))
        results=data.get("OgdSearchResult",{}).get("OgdDocumentResults",{})
        if isinstance(results,dict):results=results.get("OgdDocumentReference",[])
        if isinstance(results,dict):results=[results]
        if not isinstance(results,list):results=[]
        for doc in results:
            d=doc.get("Data",{}).get("Metadaten",{});allg=d.get("Allgemein",{});jud=d.get("Judikatur",{});jmeta=jud.get("Justiz",{})
            # 1. GZ
            gz=(get_item(jud.get("Geschaeftszahl",{})) or [""])[0].strip()
            if not gz:continue
            # 2. Dates & URLs
            datum=str(jud.get("Entscheidungsdatum","") or "").strip()
            doc_url=str(allg.get("DokumentUrl","") or "").strip()
            gesamt_url=str(jud.get("GesamteEntscheidungUrl","") or "").strip()
            # 3. Normen FIRST
            normen=get_item(jud.get("Norm",{}))
            norm_str="; ".join(normen[:4]) if normen else ""
            # 4. Rechtsgebiet AFTER normen
            rechtsgebiet=(get_item(jmeta.get("Rechtsgebiete",{})) or [""])[0]
            fachgebiet=(get_item(jmeta.get("Fachgebiete",{})) or [""])[0]
            # 5. Kurzinformation
            kurz=strip(jud.get("Kurzinformation",""))
            # 6. Build excerpt
            parts=[]
            if norm_str:parts.append(norm_str)
            if kurz:parts.append(kurz)
            excerpt=" \u2014 ".join(parts) if parts else ""
            final_url=gesamt_url or doc_url or f"https://www.ris.bka.gv.at/Ergebnis.wxe?Abfrage=Justiz&Gericht={gericht}&Geschaeftszahl={gz}"
            arts.append(dict(id=mid(final_url),title=f"{label} {gz}",url=final_url,category=rechtsgebiet or fachgebiet or label,excerpt=excerpt[:800],source="RIS",featured=False,date=pdate(datum),rechtsgebiet=rechtsgebiet,fachgebiet=fachgebiet,norm=norm_str))
        print(f"    \u2713 {len(arts)} decisions")
    except Exception as e:print(f"    \u2717 {type(e).__name__}: {e}");traceback.print_exc()
    return arts

# ═══════ RIS VfGH ═══════
def ris_vfgh():
    print(f"  [VfGH] RIS REST API v2.6...")
    params={"Applikation":"Vfgh","ImRisSeit":"DreiMonaten","DokumenteProSeite":"OneHundred","Seitennummer":"1"}
    url=f"{RIS}/Judikatur?{urlencode(params)}";arts=[]
    try:
        data=json.loads(http_get(url))
        results=data.get("OgdSearchResult",{}).get("OgdDocumentResults",{})
        if isinstance(results,dict):results=results.get("OgdDocumentReference",[])
        if isinstance(results,dict):results=[results]
        if not isinstance(results,list):results=[]
        for doc in results:
            d=doc.get("Data",{}).get("Metadaten",{});allg=d.get("Allgemein",{});jud=d.get("Judikatur",{})
            gz=(get_item(jud.get("Geschaeftszahl",{})) or [""])[0].strip()
            if not gz:continue
            datum=str(jud.get("Entscheidungsdatum","") or "").strip()
            doc_url=str(allg.get("DokumentUrl","") or "").strip()
            kurz=strip(jud.get("Kurzinformation",""))
            normen=get_item(jud.get("Norm",{}));norm_str="; ".join(normen[:4]) if normen else ""
            parts=[]
            if norm_str:parts.append(norm_str)
            if kurz:parts.append(kurz)
            excerpt=" \u2014 ".join(parts) if parts else ""
            arts.append(dict(id=mid(doc_url or gz),title=f"VfGH {gz}",url=doc_url or "https://www.ris.bka.gv.at/Vfgh/",category="VfGH",excerpt=excerpt[:800],source="RIS",featured=False,date=pdate(datum),norm=norm_str))
        print(f"    \u2713 {len(arts)} decisions")
    except Exception as e:print(f"    \u2717 {type(e).__name__}: {e}");traceback.print_exc()
    return arts

# ═══════ OGH.GV.AT ═══════
def fetch_ogh_website():
    print("  [OGH] ogh.gv.at...")
    try:from bs4 import BeautifulSoup
    except:print("    \u2717 bs4 missing");return []
    arts=[];seen=set()
    try:
        html=http_get("https://www.ogh.gv.at/entscheidungen/entscheidungen-ogh/").decode("utf-8","replace")
        soup=BeautifulSoup(html,"html.parser")
        for link in soup.find_all("a",href=True):
            href=link.get("href","");text=link.get_text(" ",strip=True)
            if not text or len(text)<25:continue
            if "/entscheidungen-ogh/" not in href and "/entscheidungen/" not in href:continue
            if href.rstrip("/") in ("/entscheidungen","/entscheidungen/entscheidungen-ogh"):continue
            if not href.startswith("http"):href="https://www.ogh.gv.at"+href
            if href in seen:continue
            seen.add(href)
            parent=link.find_parent(["div","article","li","section","p","td"])
            gz="";date_str=""
            if parent:
                ctx=parent.get_text(" ",strip=True)
                gz_m=re.search(r"(\d+\s*(?:Ob|Os|Nc|Fsc|ObA|ObS)\s*\d+/\d+\w?)",ctx)
                if gz_m:gz=gz_m.group(1).strip()
                date_m=re.search(r"(\d{2}\.\d{2}\.\d{4})",ctx)
                if date_m:date_str=date_m.group(1)
            title=f"OGH {gz}" if gz else text[:120]
            arts.append(dict(id=mid(href),title=title,url=href,category="OGH",excerpt=text[:800],source="ogh.gv.at",featured=False,date=pdate(date_str) or NOW.isoformat()))
        print(f"    \u2713 {len(arts)} decisions")
    except Exception as e:print(f"    \u2717 {type(e).__name__}: {e}")
    return arts

# ═══════ VFGH.GV.AT ═══════
def fetch_vfgh_website():
    print("  [VfGH] vfgh.gv.at...")
    try:from bs4 import BeautifulSoup
    except:print("    \u2717 bs4 missing");return []
    arts=[]
    try:
        html=http_get("https://www.vfgh.gv.at/rechtsprechung/Ausgewaehlte_Entscheidungen.de.html").decode("utf-8","replace")
        soup=BeautifulSoup(html,"html.parser")
        for link in soup.find_all("a",href=True):
            href=link.get("href","");text=link.get_text(strip=True)
            if not text or len(text)<20:continue
            if not re.search(r"VfGH|G \d+|E \d+|V \d+|Aufhebung|Abweisung|verfassungswidrig",text):continue
            if not href.startswith("http"):href="https://www.vfgh.gv.at/"+href.lstrip("/")
            date_m=re.search(r"(\d{2}\.\d{2}\.\d{4})",text)
            arts.append(dict(id=mid(href),title=text[:200],url=href,category="VfGH",excerpt=text[:800],source="vfgh.gv.at",featured=False,date=pdate(date_m.group(1)) if date_m else NOW.isoformat()))
        print(f"    \u2713 {len(arts)} decisions")
    except Exception as e:print(f"    \u2717 {type(e).__name__}: {e}")
    return arts

# ═══════ EuGH ═══════
AT_KW=re.compile(r"Oesterreich|Austria|oesterreichisch|Austrian|Oberster Gerichtshof|Landesgericht|BVwG|Verwaltungsgerichtshof|Verfassungsgerichtshof|OGH|VfGH|VwGH|BMF|BMJ",re.IGNORECASE)
def fetch_eugh():
    arts=[];seen=set()
    for url,label in [("http://curia.europa.eu/site/rss.jsp?lang=de&secondLang=en","CURIA DE"),("http://curia.europa.eu/site/rss.jsp?lang=en&secondLang=fr","CURIA EN")]:
        print(f"  [EuGH] {label}")
        try:
            new=parse_rss(http_xml(url),"EuGH")
            for a in new:
                tk=re.sub(r"[^a-z0-9]","",a["title"].lower())[:50]
                if tk not in seen:
                    seen.add(tk)
                    if AT_KW.search(a["title"]+" "+a.get("excerpt","")):a["category"]="\U0001f1e6\U0001f1f9 EuGH (\u00d6sterreich)";a["featured"]=True
                    arts.append(a)
            print(f"    \u2713 {len(new)} articles")
            if len(arts)>=5:break
        except Exception as e:print(f"    \u2717 {type(e).__name__}: {e}")
    return arts

# ═══════ GZ DEDUP ═══════
def dedup_gz(articles,pattern):
    gz_map={};no_gz=[];web={"ogh.gv.at","vfgh.gv.at"}
    for a in articles:
        m=re.search(pattern,a.get("title","")+" "+a.get("url",""))
        gz=m.group(1).strip() if m else ""
        if not gz:no_gz.append(a);continue
        if gz not in gz_map:gz_map[gz]=a
        else:
            ex=gz_map[gz]
            if a["source"]=="RIS" and ex["source"] in web and a.get("norm"):
                if len(ex.get("excerpt",""))>len(a.get("excerpt","")):a["excerpt"]=ex["excerpt"]
                gz_map[gz]=a
            elif a["source"] in web and ex["source"]=="RIS" and ex.get("norm"):
                if len(a.get("excerpt",""))>len(ex.get("excerpt","")):ex["excerpt"]=a["excerpt"]
            elif a["source"] in web and ex["source"] not in web:gz_map[gz]=a
            elif len(a.get("excerpt",""))>len(ex.get("excerpt","")):gz_map[gz]=a
    return list(gz_map.values())+no_gz

OGH_GZ=r"(\d+\s*(?:Ob|Os|Nc|Fsc|Bkv|ObA|ObS)\s*\d+/\d+\w?)"
VFGH_GZ=r"((?:G|E|V|W I|UA|SV)\s*\d+/\d+)"

# ═══════ FEEDS ═══════
FEEDS_AT_NEWS=[("https://www.derstandard.at/rss/recht","Der Standard Recht"),("https://www.derstandard.at/rss/wirtschaft","Der Standard Wirtschaft")]
FEEDS_INTL_LAW=[("https://verfassungsblog.de/feed/","Verfassungsblog"),("https://www.ejiltalk.org/feed/","EJIL:Talk!"),("https://opiniojuris.org/feed/","Opinio Juris")]
FEEDS_NATIONAL=[("https://rss.orf.at/news.xml","ORF"),("https://www.derstandard.at/rss/inland","Der Standard"),("https://www.diepresse.com/rss/politik","Die Presse"),("https://kurier.at/xml/rssd","Kurier"),("https://www.falter.at/falter/feed","Falter")]
FEEDS_INTERNATIONAL=[("https://www.derstandard.at/rss/international","Der Standard"),("https://feeds.bbci.co.uk/news/world/rss.xml","BBC World"),("https://rss.nytimes.com/services/xml/rss/nyt/World.xml","New York Times"),("https://www.theguardian.com/world/rss","The Guardian"),("https://www.spiegel.de/international/index.rss","Der Spiegel"),("https://www.tagesschau.de/xml/rss2/","Tagesschau"),("https://www.nzz.ch/recent.rss","NZZ")]

# ═══════ MAIN ═══════
def main():
    print(f"\U0001f4f0  Newsletter v8 \u2014 {NOW.strftime('%Y-%m-%d %H:%M UTC')}\n")
    ex={}
    if DATA.exists():
        with open(DATA,"r",encoding="utf-8") as f:ex=json.load(f)
    r={}
    print("\u2550\u2550 OGH Urteile \u2550\u2550")
    ogh=ris_justiz("OGH","OGH");ogh+=fetch_ogh_website();ogh=merge(ex.get("recht_ogh",[]),ogh)
    r["recht_ogh"]=trim(dedup_gz(ogh,OGH_GZ));print(f"  \u2192 Total: {len(r['recht_ogh'])}\n")
    print("\u2550\u2550 VfGH Urteile \u2550\u2550")
    vfgh=ris_vfgh();vfgh+=fetch_vfgh_website();vfgh=merge(ex.get("recht_vfgh",[]),vfgh)
    r["recht_vfgh"]=trim(dedup_gz(vfgh,VFGH_GZ),20);print(f"  \u2192 Total: {len(r['recht_vfgh'])}\n")
    print("\u2550\u2550 EuGH Urteile \u2550\u2550")
    r["recht_eugh"]=trim(merge(ex.get("recht_eugh",[]),fetch_eugh()));print(f"  \u2192 Total: {len(r['recht_eugh'])}\n")
    for tab,feeds in [("recht_news",FEEDS_AT_NEWS),("recht_intl",FEEDS_INTL_LAW),("national",FEEDS_NATIONAL),("international",FEEDS_INTERNATIONAL)]:
        print(f"\u2550\u2550 {tab} \u2550\u2550");new_arts=fetch_rss(feeds,tab);merged=merge(ex.get(tab,[]),new_arts)
        r[tab]=trim(title_dedup(merged));print(f"  \u2192 Total: {len(r[tab])}\n")
    r["_meta"]={"last_updated":NOW.isoformat()}
    with open(DATA,"w",encoding="utf-8") as f:json.dump(r,f,ensure_ascii=False,indent=2)
    total=sum(len(r[k]) for k in r if k!="_meta");print(f"\u2713 data.json \u2014 {total} articles total")

if __name__=="__main__":main()
