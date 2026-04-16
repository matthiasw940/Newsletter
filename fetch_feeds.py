#!/usr/bin/env python3
"""Newsletter v11 — AI summaries via Anthropic API for court decisions."""
import json,hashlib,re,traceback,xml.etree.ElementTree as ET,os
from datetime import datetime,timedelta,timezone
from pathlib import Path
from urllib.request import urlopen,Request
from urllib.parse import urlencode
from html import unescape

MAX=25;DAYS=60;DATA=Path(__file__).parent/"data.json";NOW=datetime.now(timezone.utc)
RIS="https://data.bka.gv.at/ris/api/v2.6"
API_KEY=os.environ.get("ANTHROPIC_API_KEY","")

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
def merge_smart(existing, new_arts):
    by_url = {}
    for a in existing:
        by_url[a["url"]] = a
    for a in new_arts:
        old = by_url.get(a["url"])
        if old is None:
            by_url[a["url"]] = a
        else:
            if a.get("norm") and not old.get("norm"):
                by_url[a["url"]] = a
            elif a.get("rechtsgebiet") and not old.get("rechtsgebiet"):
                by_url[a["url"]] = a
            elif len(a.get("excerpt","")) > len(old.get("excerpt","")) + 20:
                by_url[a["url"]] = a
            # Keep existing summary if new doesn't have one
            if by_url[a["url"]] is a and old.get("summary") and not a.get("summary"):
                a["summary"] = old["summary"]
    return list(by_url.values())
def title_dedup(articles):
    seen={};out=[]
    for a in articles:
        key=re.sub(r"[^a-z0-9 ]","",a["title"].lower())[:40].strip()
        key=re.sub(r"\b(der|die|das|und|in|von|mit|auf|zu|im|am|ist|ein|eine|nach|vor|wird|hat|bei|als|den|dem|des|sich|nicht|auch|noch|wie|aus)\b","",key).strip()
        key=re.sub(r"\s+"," ",key)[:30]
        if key and key in seen:
            if len(a.get("excerpt",""))>len(seen[key].get("excerpt","")):
                out=[x for x in out if x is not seen[key]];out.append(a);seen[key]=a
        else:seen[key]=a;out.append(a)
    return out

# ═══════ AI SUMMARY ═══════
def ai_summary(title, norm, schlagworte, rechtsgebiet, anmerkung):
    """Generate a 2-3 sentence German summary of a court decision using Claude Haiku."""
    if not API_KEY:
        return ""
    # Build context from available data
    parts = []
    if norm: parts.append(f"Normen: {norm}")
    if schlagworte: parts.append(f"Schlagworte: {schlagworte}")
    if rechtsgebiet: parts.append(f"Rechtsgebiet: {rechtsgebiet}")
    if anmerkung: parts.append(f"Anmerkung: {anmerkung}")
    if not parts:
        return ""
    context = "\n".join(parts)
    prompt = f"""Du bist ein österreichischer Jurist. Fasse die folgende OGH/VfGH-Entscheidung in 2-3 kurzen, prägnanten Sätzen auf Deutsch zusammen. Erkläre worum es geht und was entschieden wurde, basierend auf den verfügbaren Metadaten. Antworte NUR mit der Zusammenfassung, ohne Einleitung.

Entscheidung: {title}
{context}"""
    try:
        body = json.dumps({
            "model": "claude-haiku-4-5-20251001",
            "max_tokens": 200,
            "messages": [{"role": "user", "content": prompt}]
        }).encode("utf-8")
        req = Request("https://api.anthropic.com/v1/messages", data=body, headers={
            "Content-Type": "application/json",
            "x-api-key": API_KEY,
            "anthropic-version": "2023-06-01"
        })
        with urlopen(req, timeout=30) as r:
            resp = json.loads(r.read())
        text = ""
        for block in resp.get("content", []):
            if block.get("type") == "text":
                text += block.get("text", "")
        return text.strip()[:500]
    except Exception as e:
        err_body = ""
        if hasattr(e, "read"):
            try: err_body = e.read().decode("utf-8","replace")[:300]
            except: pass
        print(f"      AI error: {type(e).__name__}: {e}")
        if err_body: print(f"      Response: {err_body}")
        return ""

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

# ═══════ RIS JUSTIZ (OGH) ═══════
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
            d=doc.get("Data",{}).get("Metadaten",{})
            allg=d.get("Allgemein",{})
            jud=d.get("Judikatur",{})
            jmeta=jud.get("Justiz",{})
            gz=(get_item(jud.get("Geschaeftszahl",{})) or [""])[0].strip()
            if not gz:continue
            datum=str(jud.get("Entscheidungsdatum","") or "").strip()
            et=jmeta.get("Entscheidungstexte",{})
            et_item=et.get("item",{}) if isinstance(et,dict) else {}
            if isinstance(et_item,list):et_item=et_item[0] if et_item else {}
            if not isinstance(et_item,dict):et_item={}
            doc_url=str(et_item.get("DokumentUrl","") or allg.get("DokumentUrl","") or "").strip()
            entsch_art=str(et_item.get("Entscheidungsart","") or "").strip()
            normen=get_item(jud.get("Normen",{}))
            norm_str="; ".join(normen[:5]) if normen else ""
            rechtsgebiet=(get_item(jmeta.get("Rechtsgebiete",{})) or [""])[0]
            schlagworte=strip(jud.get("Schlagworte",""))
            anmerkung=strip(jmeta.get("Anmerkung",""))
            # Build excerpt from Schlagworte + Anmerkung
            parts=[]
            if schlagworte:parts.append(schlagworte)
            if entsch_art:parts.append(entsch_art)
            if anmerkung:parts.append(anmerkung)
            excerpt=". ".join(parts) if parts else ""
            final_url=doc_url or f"https://www.ris.bka.gv.at/Ergebnis.wxe?Abfrage=Justiz&Gericht={gericht}&Geschaeftszahl={gz}"
            # AI Summary
            summary=""
            if norm_str or schlagworte:
                title_full=f"{label} {gz}"
                print(f"    \U0001f916 Summarizing {gz}...")
                summary=ai_summary(title_full, norm_str, schlagworte, rechtsgebiet, anmerkung)
                if summary:
                    print(f"      \u2713 {summary[:80]}...")
            arts.append(dict(
                id=mid(final_url),title=f"{label} {gz}",url=final_url,
                category=rechtsgebiet or label,
                excerpt=excerpt[:800],source="RIS",featured=False,
                date=pdate(datum),rechtsgebiet=rechtsgebiet,
                norm=norm_str,summary=summary
            ))
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
            normen=get_item(jud.get("Normen",{}))
            norm_str="; ".join(normen[:5]) if normen else ""
            schlagworte=strip(jud.get("Schlagworte",""))
            kurz=strip(jud.get("Kurzinformation",""))
            parts=[]
            if schlagworte:parts.append(schlagworte)
            if kurz:parts.append(kurz)
            excerpt=". ".join(parts) if parts else ""
            # AI Summary for VfGH too
            summary=""
            if norm_str or schlagworte or kurz:
                print(f"    \U0001f916 Summarizing VfGH {gz}...")
                summary=ai_summary(f"VfGH {gz}", norm_str, schlagworte or kurz, "", "")
                if summary:print(f"      \u2713 {summary[:80]}...")
            arts.append(dict(id=mid(doc_url or gz),title=f"VfGH {gz}",url=doc_url or "https://www.ris.bka.gv.at/Vfgh/",category="VfGH",excerpt=excerpt[:800],source="RIS",featured=False,date=pdate(datum),norm=norm_str,summary=summary))
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
    gz_map={};no_gz=[]
    for a in articles:
        m=re.search(pattern,a.get("title","")+" "+a.get("url",""))
        gz=m.group(1).strip() if m else ""
        if not gz:no_gz.append(a);continue
        if gz not in gz_map:
            gz_map[gz]=a
        else:
            ex=gz_map[gz]
            if a.get("norm") and not ex.get("norm"):
                gz_map[gz]=a
            elif ex.get("norm") and not a.get("norm"):
                pass
            elif a["source"]=="RIS" and ex["source"]!="RIS":
                gz_map[gz]=a
            elif len(a.get("excerpt",""))>len(ex.get("excerpt","")):
                gz_map[gz]=a
            # Preserve summary from winner
            winner=gz_map[gz]
            loser=a if winner is ex else ex
            if not winner.get("summary") and loser.get("summary"):
                winner["summary"]=loser["summary"]
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
    print(f"\U0001f4f0  Newsletter v11 \u2014 {NOW.strftime('%Y-%m-%d %H:%M UTC')}")
    if API_KEY:
        print(f"  \U0001f916 AI summaries enabled (Haiku)\n")
    else:
        print(f"  \u26a0\ufe0f  No ANTHROPIC_API_KEY — summaries disabled\n")
    ex={}
    if DATA.exists():
        with open(DATA,"r",encoding="utf-8") as f:ex=json.load(f)
    r={}

    print("\u2550\u2550 OGH Urteile \u2550\u2550")
    ogh=ris_justiz("OGH","OGH")
    ogh+=fetch_ogh_website()
    ogh=merge_smart(ex.get("recht_ogh",[]),ogh)
    r["recht_ogh"]=trim(dedup_gz(ogh,OGH_GZ))
    print(f"  \u2192 Total: {len(r['recht_ogh'])}\n")

    print("\u2550\u2550 VfGH Urteile \u2550\u2550")
    vfgh=ris_vfgh();vfgh+=fetch_vfgh_website()
    vfgh=merge_smart(ex.get("recht_vfgh",[]),vfgh)
    r["recht_vfgh"]=trim(dedup_gz(vfgh,VFGH_GZ),20)
    print(f"  \u2192 Total: {len(r['recht_vfgh'])}\n")

    print("\u2550\u2550 EuGH Urteile \u2550\u2550")
    eugh=fetch_eugh()
    r["recht_eugh"]=trim(merge_smart(ex.get("recht_eugh",[]),eugh))
    print(f"  \u2192 Total: {len(r['recht_eugh'])}\n")

    for tab,feeds in [("recht_news",FEEDS_AT_NEWS),("recht_intl",FEEDS_INTL_LAW),("national",FEEDS_NATIONAL),("international",FEEDS_INTERNATIONAL)]:
        print(f"\u2550\u2550 {tab} \u2550\u2550")
        new_arts=fetch_rss(feeds,tab)
        merged=merge_smart(ex.get(tab,[]),new_arts)
        r[tab]=trim(title_dedup(merged))
        print(f"  \u2192 Total: {len(r[tab])}\n")

    r["_meta"]={"last_updated":NOW.isoformat()}
    with open(DATA,"w",encoding="utf-8") as f:json.dump(r,f,ensure_ascii=False,indent=2)
    total=sum(len(r[k]) for k in r if k!="_meta")
    summaries=sum(1 for k in r if k!="_meta" for a in r[k] if a.get("summary"))
    print(f"\u2713 data.json \u2014 {total} articles, {summaries} with AI summary")

if __name__=="__main__":main()
