#!/usr/bin/env python3
"""Morning Brief v15 — Finance+Sport tabs, improved summaries, better briefing."""
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
    if isinstance(obj,dict):v=obj.get("item","");return v if isinstance(v,list) else([str(v)] if v else [])
    return [obj] if isinstance(obj,str) and obj else []
def http_get(url,timeout=25):
    req=Request(url,headers={"User-Agent":"Mozilla/5.0 (X11; Linux x86_64; rv:120.0) Gecko/20100101 Firefox/120.0","Accept":"application/json, text/html, */*","Accept-Language":"de-AT,de;q=0.9,en;q=0.8"})
    with urlopen(req,timeout=timeout) as r:return r.read()
def http_xml(url,timeout=25):
    req=Request(url,headers={"User-Agent":"Mozilla/5.0 (X11; Linux x86_64; rv:120.0) Gecko/20100101 Firefox/120.0","Accept":"application/rss+xml, application/xml, text/xml, */*"})
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
def merge_smart(existing,new_arts):
    by_url={}
    for a in existing:by_url[a["url"]]=a
    for a in new_arts:
        old=by_url.get(a["url"])
        if old is None:by_url[a["url"]]=a
        else:
            if a.get("norm") and not old.get("norm"):by_url[a["url"]]=a
            elif a.get("rechtsgebiet") and not old.get("rechtsgebiet"):by_url[a["url"]]=a
            elif len(a.get("excerpt",""))>len(old.get("excerpt",""))+20:by_url[a["url"]]=a
            if by_url[a["url"]] is a and old.get("summary") and not a.get("summary"):a["summary"]=old["summary"]
    return list(by_url.values())
def title_dedup(articles):
    seen={};out=[]
    for a in articles:
        key=re.sub(r"[^a-z0-9 ]","",a["title"].lower())[:40].strip()
        key=re.sub(r"\b(der|die|das|und|in|von|mit|auf|zu|im|am|ist|ein|eine|nach|vor|wird|hat|bei|als|den|dem|des|sich|nicht|auch|noch|wie|aus)\b","",key).strip()
        key=re.sub(r"\s+"," ",key)[:30]
        if key and key in seen:
            if len(a.get("excerpt",""))>len(seen[key].get("excerpt","")):out=[x for x in out if x is not seen[key]];out.append(a);seen[key]=a
        else:seen[key]=a;out.append(a)
    return out

# ═══════ AI ═══════
def ai_call(prompt,max_tokens=400):
    if not API_KEY:return ""
    try:
        body=json.dumps({"model":"claude-haiku-4-5-20251001","max_tokens":max_tokens,"messages":[{"role":"user","content":prompt}]}).encode("utf-8")
        req=Request("https://api.anthropic.com/v1/messages",data=body,headers={"Content-Type":"application/json","x-api-key":API_KEY,"anthropic-version":"2023-06-01"})
        with urlopen(req,timeout=30) as r:resp=json.loads(r.read())
        text=""
        for block in resp.get("content",[]):
            if block.get("type")=="text":text+=block.get("text","")
        return text.strip()
    except Exception as e:
        err=""
        if hasattr(e,"read"):
            try:err=e.read().decode("utf-8","replace")[:200]
            except:pass
        print(f"      AI error: {type(e).__name__}: {e}")
        if err:print(f"      {err[:150]}")
        return ""

def fetch_decision_text(url):
    if not url:return ""
    try:
        from bs4 import BeautifulSoup
        html=http_get(url,timeout=20).decode("utf-8","replace")
        soup=BeautifulSoup(html,"html.parser")
        for sel in [".ContentBlock",".Zusammenfassung",".Content","#ContentBlock","article","main",".RISJudwordsContent"]:
            block=soup.select_one(sel)
            if block and len(block.get_text(strip=True))>100:return block.get_text(" ",strip=True)[:6000]
        paras=soup.find_all(["p","div"],class_=lambda c:c and ("text" in str(c).lower() or "content" in str(c).lower()))
        if paras:return " ".join(p.get_text(" ",strip=True) for p in paras)[:6000]
        body=soup.find("body")
        if body:return body.get_text(" ",strip=True)[:6000]
    except Exception as e:print(f"      Fetch error: {type(e).__name__}: {e}")
    return ""

BULLET_PROMPT="""Du bist ein oesterreichischer Jurist. Fasse diese Gerichtsentscheidung in 5 Stichpunkten zusammen. Verwende dabei moeglichst das Wording und die juristische Terminologie des OGH/Gerichts selbst. Die Laenge der einzelnen Punkte darf variieren — bei komplexen Rechtsfragen und der Entscheidungsbegruendung ausfuehrlicher formulieren.

Format:
\u2022 Normen: [betroffene Gesetze/Paragraphen]
\u2022 SV: [Sachverhalt]
\u2022 Rechtsfrage: [zentrale Frage — ausfuehrlich, 2-4 Saetze]
\u2022 Entscheidung: [rechtliche Begruendung und Ergebnis des Gerichts — ausfuehrlich, 3-5 Saetze, mit dem Wording des Gerichts]
\u2022 Bedeutung: [praktische Auswirkung]

Auf Deutsch. Keine kuenstliche Kuerzung — die Zusammenfassung soll die wesentlichen Erwaegungen des Gerichts wiedergeben.

Entscheidung: {title}
Rechtsgebiet: {rg}
Normen: {norm}

Entscheidungstext:
{text}"""

EUGH_PROMPT="""Erstelle genau 5 kurze Stichpunkte zu dieser EuGH-Entscheidung. Format:
\u2022 EU-Recht: [betroffene Richtlinien/Verordnungen]
\u2022 SV: [Sachverhalt in 1 Satz]
\u2022 Rechtsfrage: [zentrale Frage]
\u2022 Entscheidung: [Ergebnis]
\u2022 Bedeutung: [Auswirkung]

Jeder Punkt maximal 1-2 kurze Saetze. Auf Deutsch.

{title}
{excerpt}"""

def ai_summary_from_text(title,url,norm,rechtsgebiet):
    if not API_KEY:return ""
    print(f"      Fetching text...")
    text=fetch_decision_text(url)
    if not text or len(text)<200:print(f"      No text, skipping");return ""
    print(f"      {len(text)} chars, summarizing...")
    prompt=BULLET_PROMPT.format(title=title,rg=rechtsgebiet or "k.A.",norm=norm or "k.A.",text=text[:5000])
    return ai_call(prompt,1500)[:3000]

def ai_summary_from_excerpt(title,excerpt):
    if not API_KEY or not excerpt or len(excerpt)<50:return ""
    prompt=EUGH_PROMPT.format(title=title,excerpt=excerpt[:3000])
    return ai_call(prompt,600)[:1200]

def ai_sport_briefing(headlines):
    if not API_KEY or not headlines:return ""
    prompt=f"""Erstelle ein kurzes Sport-Briefing auf Deutsch. Pro Nachricht genau 1 Stichpunkt mit "\u2022 " am Anfang. Maximal 10 Stichpunkte. Nur Fakten, keine Spekulationen. Jeder Punkt 1 kurzer Satz.

Sport-Schlagzeilen:
{headlines}"""
    return ai_call(prompt,800)[:2000]

# ═══════ WEATHER ═══════
def fetch_weather_vienna():
    print("  [Wetter] Open-Meteo Wien...")
    try:
        url="https://api.open-meteo.com/v1/forecast?latitude=48.2082&longitude=16.3738&daily=temperature_2m_max,temperature_2m_min,precipitation_sum,weathercode&current=temperature_2m,weathercode,relative_humidity_2m,wind_speed_10m&hourly=temperature_2m,weathercode,precipitation_probability&timezone=Europe/Vienna&forecast_days=1"
        data=json.loads(http_get(url));current=data.get("current",{});daily=data.get("daily",{});hourly=data.get("hourly",{})
        wmo={0:"Klar",1:"\u00dcberwiegend klar",2:"Teilweise bew\u00f6lkt",3:"Bew\u00f6lkt",45:"Nebel",48:"Nebel mit Reif",51:"Leichter Nieselregen",53:"Nieselregen",55:"Starker Nieselregen",61:"Leichter Regen",63:"Regen",65:"Starker Regen",71:"Leichter Schneefall",73:"Schneefall",75:"Starker Schneefall",80:"Leichte Regenschauer",81:"Regenschauer",82:"Starke Regenschauer",85:"Schneeschauer",86:"Starke Schneeschauer",95:"Gewitter",96:"Gewitter mit Hagel",99:"Schweres Gewitter mit Hagel"}
        wmo_emoji={0:"\u2600\ufe0f",1:"\U0001f324\ufe0f",2:"\u26c5",3:"\u2601\ufe0f",45:"\U0001f32b\ufe0f",48:"\U0001f32b\ufe0f",51:"\U0001f326\ufe0f",53:"\U0001f327\ufe0f",55:"\U0001f327\ufe0f",61:"\U0001f326\ufe0f",63:"\U0001f327\ufe0f",65:"\U0001f327\ufe0f",71:"\U0001f328\ufe0f",73:"\U0001f328\ufe0f",75:"\U0001f328\ufe0f",80:"\U0001f326\ufe0f",81:"\U0001f327\ufe0f",82:"\U0001f327\ufe0f",85:"\U0001f328\ufe0f",86:"\U0001f328\ufe0f",95:"\u26c8\ufe0f",96:"\u26c8\ufe0f",99:"\u26c8\ufe0f"}
        code=current.get("weathercode",0)
        hours_forecast=[]
        h_times=hourly.get("time",[]);h_temps=hourly.get("temperature_2m",[]);h_codes=hourly.get("weathercode",[]);h_precip=hourly.get("precipitation_probability",[])
        for i,t in enumerate(h_times):
            hour=int(t.split("T")[1].split(":")[0]) if "T" in t else -1
            if hour in (6,8,10,12,14,16,18,20):
                hours_forecast.append({"hour":f"{hour:02d}:00","temp":h_temps[i] if i<len(h_temps) else None,"code":h_codes[i] if i<len(h_codes) else 0,"emoji":wmo_emoji.get(h_codes[i] if i<len(h_codes) else 0,""),"precip":h_precip[i] if i<len(h_precip) else 0})
        w={"temp_current":current.get("temperature_2m"),"humidity":current.get("relative_humidity_2m"),"wind":current.get("wind_speed_10m"),"temp_max":(daily.get("temperature_2m_max") or [None])[0],"temp_min":(daily.get("temperature_2m_min") or [None])[0],"precip":(daily.get("precipitation_sum") or [0])[0],"description":wmo.get(code,"Unbekannt"),"emoji":wmo_emoji.get(code,"\U0001f324\ufe0f"),"code":code,"hourly":hours_forecast}
        print(f"    \u2713 {w['temp_current']}\u00b0C, {w['description']}");return w
    except Exception as e:print(f"    \u2717 {type(e).__name__}: {e}");return None

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
        try:new=parse_rss(http_xml(url),src);arts.extend(new);print(f"    \u2713 {len(new)}")
        except Exception as e:print(f"    \u2717 {type(e).__name__}: {e}")
    return arts

# ═══════ RIS ═══════
def ris_justiz(gericht,label):
    print(f"  [{label}] RIS v2.6...")
    params={"Applikation":"Justiz","Gericht":gericht,"ImRisSeit":"ZweiWochen","DokumenteProSeite":"OneHundred","Seitennummer":"1","Dokumenttyp.SucheInRechtssaetzen":"true","Dokumenttyp.SucheInEntscheidungstexten":"true"}
    url=f"{RIS}/Judikatur?{urlencode(params)}";arts=[]
    try:
        data=json.loads(http_get(url));results=data.get("OgdSearchResult",{}).get("OgdDocumentResults",{})
        if isinstance(results,dict):results=results.get("OgdDocumentReference",[])
        if isinstance(results,dict):results=[results]
        if not isinstance(results,list):results=[]
        for doc in results:
            d=doc.get("Data",{}).get("Metadaten",{});allg=d.get("Allgemein",{});jud=d.get("Judikatur",{});jmeta=jud.get("Justiz",{})
            gz=(get_item(jud.get("Geschaeftszahl",{})) or [""])[0].strip()
            if not gz:continue
            if re.search(r"\d+\s*Ds\s*\d+",gz):continue
            datum=str(jud.get("Entscheidungsdatum","") or "").strip()
            et=jmeta.get("Entscheidungstexte",{});et_item=et.get("item",{}) if isinstance(et,dict) else {}
            if isinstance(et_item,list):et_item=et_item[0] if et_item else {}
            if not isinstance(et_item,dict):et_item={}
            doc_url=str(et_item.get("DokumentUrl","") or allg.get("DokumentUrl","") or "").strip()
            normen=get_item(jud.get("Normen",{}));norm_str="; ".join(normen[:5]) if normen else ""
            rechtsgebiet=(get_item(jmeta.get("Rechtsgebiete",{})) or [""])[0]
            schlagworte=strip(jud.get("Schlagworte",""));anmerkung=strip(jmeta.get("Anmerkung",""))
            parts=[];
            if schlagworte:parts.append(schlagworte)
            if anmerkung:parts.append(anmerkung)
            excerpt=". ".join(parts) if parts else ""
            final_url=doc_url or f"https://www.ris.bka.gv.at/Ergebnis.wxe?Abfrage=Justiz&Gericht={gericht}&Geschaeftszahl={gz}"
            arts.append(dict(id=mid(final_url),title=f"{label} {gz}",url=final_url,category=rechtsgebiet or label,excerpt=excerpt[:800],source="RIS",featured=False,date=pdate(datum),rechtsgebiet=rechtsgebiet,norm=norm_str,summary=""))
        print(f"    \u2713 {len(arts)}")
    except Exception as e:print(f"    \u2717 {type(e).__name__}: {e}");traceback.print_exc()
    return arts

def ris_vfgh():
    print(f"  [VfGH] RIS v2.6...")
    params={"Applikation":"Vfgh","ImRisSeit":"DreiMonaten","DokumenteProSeite":"OneHundred","Seitennummer":"1"}
    url=f"{RIS}/Judikatur?{urlencode(params)}";arts=[]
    try:
        data=json.loads(http_get(url));results=data.get("OgdSearchResult",{}).get("OgdDocumentResults",{})
        if isinstance(results,dict):results=results.get("OgdDocumentReference",[])
        if isinstance(results,dict):results=[results]
        if not isinstance(results,list):results=[]
        for doc in results:
            d=doc.get("Data",{}).get("Metadaten",{});allg=d.get("Allgemein",{});jud=d.get("Judikatur",{})
            gz=(get_item(jud.get("Geschaeftszahl",{})) or [""])[0].strip()
            if not gz:continue
            datum=str(jud.get("Entscheidungsdatum","") or "").strip()
            doc_url=str(allg.get("DokumentUrl","") or "").strip()
            normen=get_item(jud.get("Normen",{}));norm_str="; ".join(normen[:5]) if normen else ""
            schlagworte=strip(jud.get("Schlagworte",""));kurz=strip(jud.get("Kurzinformation",""))
            parts=[];
            if schlagworte:parts.append(schlagworte)
            if kurz:parts.append(kurz)
            excerpt=". ".join(parts) if parts else ""
            arts.append(dict(id=mid(doc_url or gz),title=f"VfGH {gz}",url=doc_url or "https://www.ris.bka.gv.at/Vfgh/",category="VfGH",excerpt=excerpt[:800],source="RIS",featured=False,date=pdate(datum),norm=norm_str,summary=""))
        print(f"    \u2713 {len(arts)}")
    except Exception as e:print(f"    \u2717 {type(e).__name__}: {e}");traceback.print_exc()
    return arts

def fetch_ogh_website():
    print("  [OGH] ogh.gv.at...")
    try:from bs4 import BeautifulSoup
    except:return []
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
            seen.add(href);parent=link.find_parent(["div","article","li","section","p","td"])
            gz="";date_str=""
            if parent:
                ctx=parent.get_text(" ",strip=True);gz_m=re.search(r"(\d+\s*(?:Ob|Os|Nc|Fsc|ObA|ObS)\s*\d+/\d+\w?)",ctx)
                if gz_m:gz=gz_m.group(1).strip()
                date_m=re.search(r"(\d{2}\.\d{2}\.\d{4})",ctx)
                if date_m:date_str=date_m.group(1)
            title=f"OGH {gz}" if gz else text[:120]
            arts.append(dict(id=mid(href),title=title,url=href,category="OGH",excerpt=text[:800],source="ogh.gv.at",featured=False,date=pdate(date_str) or NOW.isoformat()))
        print(f"    \u2713 {len(arts)}")
    except Exception as e:print(f"    \u2717 {type(e).__name__}: {e}")
    return arts

def fetch_vfgh_website():
    print("  [VfGH] vfgh.gv.at...")
    try:from bs4 import BeautifulSoup
    except:return []
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
        print(f"    \u2713 {len(arts)}")
    except Exception as e:print(f"    \u2717 {type(e).__name__}: {e}")
    return arts

AT_KW=re.compile(r"Oesterreich|Austria|oesterreichisch|Austrian|OGH|VfGH|VwGH|BMF|BMJ",re.IGNORECASE)
def fetch_eugh():
    arts=[];seen=set()
    for url,label in [("http://curia.europa.eu/site/rss.jsp?lang=de&secondLang=en","CURIA DE"),("http://curia.europa.eu/site/rss.jsp?lang=en&secondLang=fr","CURIA EN")]:
        print(f"  [EuGH] {label}")
        try:
            new=parse_rss(http_xml(url),"EuGH")
            for a in new:
                tk=re.sub(r"[^a-z0-9]","",a["title"].lower())[:50]
                if tk in seen:continue
                seen.add(tk)
                if AT_KW.search(a["title"]+" "+a.get("excerpt","")):a["category"]="\U0001f1e6\U0001f1f9 EuGH (\u00d6sterreich)";a["featured"]=True
                arts.append(a)
            print(f"    \u2713 {len(new)}")
            if len(arts)>=5:break
        except Exception as e:print(f"    \u2717 {type(e).__name__}: {e}")
    return arts

def dedup_gz(articles,pattern):
    gz_map={};no_gz=[]
    for a in articles:
        m=re.search(pattern,a.get("title","")+" "+a.get("url",""));gz=m.group(1).strip() if m else ""
        if not gz:no_gz.append(a);continue
        if gz not in gz_map:gz_map[gz]=a
        else:
            ex=gz_map[gz]
            if a.get("norm") and not ex.get("norm"):gz_map[gz]=a
            elif ex.get("norm") and not a.get("norm"):pass
            elif a["source"]=="RIS" and ex["source"]!="RIS":gz_map[gz]=a
            elif len(a.get("excerpt",""))>len(ex.get("excerpt","")):gz_map[gz]=a
            winner=gz_map[gz];loser=a if winner is ex else ex
            if not winner.get("summary") and loser.get("summary"):winner["summary"]=loser["summary"]
    return list(gz_map.values())+no_gz

OGH_GZ=r"(\d+\s*(?:Ob|Os|Nc|Fsc|Bkv|ObA|ObS)\s*\d+/\d+\w?)"
VFGH_GZ=r"((?:G|E|V|W I|UA|SV)\s*\d+/\d+)"

FEEDS_AT_NEWS=[("https://www.derstandard.at/rss/recht","Der Standard Recht"),("https://www.derstandard.at/rss/wirtschaft","Der Standard Wirtschaft")]
FEEDS_INTL_LAW=[("https://verfassungsblog.de/feed/","Verfassungsblog"),("https://www.ejiltalk.org/feed/","EJIL:Talk!"),("https://opiniojuris.org/feed/","Opinio Juris")]
FEEDS_NATIONAL=[("https://rss.orf.at/news.xml","ORF"),("https://www.derstandard.at/rss/inland","Der Standard"),("https://www.diepresse.com/rss/politik","Die Presse"),("https://kurier.at/xml/rssd","Kurier"),("https://www.falter.at/falter/feed","Falter")]
FEEDS_INTERNATIONAL=[("https://www.derstandard.at/rss/international","Der Standard"),("https://feeds.bbci.co.uk/news/world/rss.xml","BBC World"),("https://rss.nytimes.com/services/xml/rss/nyt/World.xml","New York Times"),("https://www.theguardian.com/world/rss","The Guardian"),("https://www.spiegel.de/international/index.rss","Der Spiegel"),("https://www.tagesschau.de/xml/rss2/","Tagesschau"),("https://www.nzz.ch/recent.rss","NZZ")]
FEEDS_FINANCE=[("https://www.coindesk.com/arc/outboundfeeds/rss/","CoinDesk"),("https://cointelegraph.com/rss","Cointelegraph"),("https://www.derstandard.at/rss/finanzen","Der Standard Finanzen"),("https://rss.nytimes.com/services/xml/rss/nyt/Business.xml","NYT Business"),("https://feeds.bbci.co.uk/news/business/rss.xml","BBC Business")]
FEEDS_SPORT=[("https://rss.orf.at/sport.xml","ORF Sport"),("https://www.derstandard.at/rss/sport","Der Standard Sport"),("https://feeds.bbci.co.uk/sport/rss.xml","BBC Sport"),("https://rss.nytimes.com/services/xml/rss/nyt/Sports.xml","NYT Sports")]

def fetch_btc_price():
    print("  [BTC] CoinGecko...")
    try:
        data=json.loads(http_get("https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,ethereum&vs_currencies=usd,eur&include_24hr_change=true"))
        btc=data.get("bitcoin",{});eth=data.get("ethereum",{})
        r={"btc_eur":btc.get("eur"),"btc_usd":btc.get("usd"),"btc_24h":btc.get("eur_24h_change"),"eth_eur":eth.get("eur"),"eth_usd":eth.get("usd"),"eth_24h":eth.get("eur_24h_change")}
        print(f"    \u2713 BTC: {r['btc_eur']}\u20ac");return r
    except Exception as e:print(f"    \u2717 {type(e).__name__}: {e}");return None

def fetch_apartments():
    """Scrape multiple sources for apartments in Wien Bezirke 1-9."""
    from bs4 import BeautifulSoup
    arts=[];seen=set()
    BEZ_FILTER=re.compile(r"\b10[0-9]{2}\b|\b1[1-9]\d{2}\b|\b[2-9]\d{3}\b")  # PLZ outside 1010-1090
    BEZ_OK=re.compile(r"\b10[1-9]0\b")  # 1010-1090
    # willhaben: each Bezirk 1-9
    for bez in range(1,10):
        bezstr=f"/{bez}-bezirk" if bez>1 else "/1-bezirk"
        url=f"https://www.willhaben.at/iad/immobilien/mietwohnungen/wien/wien-{bez}00-{['innere-stadt','leopoldstadt','landstrasse','wieden','margareten','mariahilf','neubau','josefstadt','alsergrund'][bez-1]}?PRICE_TO=1200&ESTATE_SIZE_FROM=50&NUMBER_OF_ROOMS_FROM=2&rows=20&sort=1"
        print(f"  [Wohnung] willhaben Bez.{bez}...")
        try:
            html=http_get(url,timeout=15).decode("utf-8","replace")
            soup=BeautifulSoup(html,"html.parser")
            for a in soup.find_all("a",href=True):
                href=a.get("href","")
                if "/iad/immobilien/d/mietwohnungen/" not in href:continue
                if not href.startswith("http"):href="https://www.willhaben.at"+href
                if href in seen:continue
                seen.add(href)
                text=a.get_text(" ",strip=True)
                if len(text)<15:continue
                price_m=re.search(r"(\d[\d.,]+)\s*\u20ac",text)
                size_m=re.search(r"(\d+)\s*m",text)
                rooms_m=re.search(r"(\d+)\s*Zimmer",text)
                excerpt_parts=[f"Bez. {bez}"]
                if price_m:excerpt_parts.append(f"{price_m.group(1)}\u20ac")
                if size_m:excerpt_parts.append(f"{size_m.group(1)}m\u00b2")
                if rooms_m:excerpt_parts.append(f"{rooms_m.group(1)} Zimmer")
                arts.append(dict(id=mid(href),title=text[:150],url=href,category=f"Wien {bez}. Bezirk",excerpt=" \u00b7 ".join(excerpt_parts),source="willhaben",date=NOW.isoformat(),featured=False))
                if len(arts)>=30:break
            print(f"    \u2713 {len(arts)} total")
        except Exception as e:print(f"    \u2717 {type(e).__name__}: {e}")
        if len(arts)>=30:break
    # ImmobilienScout24
    print(f"  [Wohnung] ImmobilienScout24...")
    try:
        is_url="https://www.immobilienscout24.at/regional/wien/wohnung-mieten?price=-1200&livingspace=50-&numberofrooms=2-&pagenumber=1"
        html=http_get(is_url,timeout=15).decode("utf-8","replace")
        soup=BeautifulSoup(html,"html.parser")
        for a in soup.find_all("a",href=True):
            href=a.get("href","")
            if "/expose/" not in href and "/regional/" not in href:continue
            if href in seen:continue
            if not href.startswith("http"):href="https://www.immobilienscout24.at"+href
            seen.add(href)
            text=a.get_text(" ",strip=True)
            if len(text)<15 or len(text)>300:continue
            # Filter: only Bezirke 1-9
            if BEZ_FILTER.search(text) and not BEZ_OK.search(text):continue
            arts.append(dict(id=mid(href),title=text[:150],url=href,category="Mietwohnung",excerpt="",source="ImmoScout24",date=NOW.isoformat(),featured=False))
            if len(arts)>=40:break
        print(f"    \u2713 {len(arts)} total")
    except Exception as e:print(f"    \u2717 {type(e).__name__}: {e}")
    print(f"  \u2192 {len(arts)} apartments total")
    return arts[:40]

def ai_briefing(r):
    nat="\n".join([f"- {a['title']} ({a['source']}) [{a['url']}]" for a in r.get("national",[])[:10]])
    intl="\n".join([f"- {a['title']} ({a['source']}) [{a['url']}]" for a in r.get("international",[])[:10]])
    # Include existing summaries for court decisions so briefing is more detailed
    ogh_lines=[]
    for a in r.get("recht_ogh",[])[:8]:
        if a.get("source")!="RIS":continue
        line=f"- {a['title']}: {a.get('norm','')}"
        if a.get("summary"):line+=f"\n  Zusammenfassung: {a['summary'][:300]}"
        line+=f" [{a['url']}]"
        ogh_lines.append(line)
    ogh="\n".join(ogh_lines)
    vfgh_lines=[]
    for a in r.get("recht_vfgh",[])[:6]:
        if a.get("source")!="RIS":continue
        line=f"- {a['title']}: {a.get('norm','')}"
        if a.get("summary"):line+=f"\n  Zusammenfassung: {a['summary'][:300]}"
        line+=f" [{a['url']}]"
        vfgh_lines.append(line)
    vfgh="\n".join(vfgh_lines)
    eugh="\n".join([f"- {a['title']} [{a['url']}]" for a in r.get("recht_eugh",[])[:4]])
    recht_news="\n".join([f"- {a['title']} ({a['source']}) [{a['url']}]" for a in r.get("recht_news",[])[:4]])
    intl_law="\n".join([f"- {a['title']} ({a['source']}) [{a['url']}]" for a in r.get("recht_intl",[])[:4]])
    prompt=f"""Erstelle ein ausfuehrliches deutsches Morgenbriefing. WICHTIG: Erfinde KEINE Fakten. Verwende NUR die unten angegebenen Informationen.

Format — verwende diese EXAKTE Struktur:

NACHRICHTEN

**Oesterreich:**
[Pro Nachricht: "\u2022 **Titel**" + Zeilenumbruch + "  \u2192 " + 2-3 Saetze Zusammenfassung + " [LINK:url]"]
[Leerzeile zwischen Nachrichten]

**International:**
[Gleiches Format]

RECHTSPRECHUNG

**OGH (neu veroeffentlicht):**
[Pro Entscheidung: "\u2022 **GZ**" + Kurzinfo zu Normen/Rechtsgebiet + Zeilenumbruch + "  \u2192 " + 2-3 Saetze die den Sachverhalt und die Entscheidung zusammenfassen + " [LINK:url]"]
[Leerzeile zwischen Entscheidungen]

**VfGH:**
[Gleiches Format]

**EuGH:**
[Gleiches Format]

**Recht News:**
[Gleiches Format]

**Intl. Recht:**
[Gleiches Format]

REGELN:
- KEINE erfundenen Details, Orte, Namen oder Personen
- Bei Gerichtsentscheidungen: die Zusammenfassungen unten verwenden falls vorhanden
- **Fett** fuer Ueberschriften und GZ-Nummern (mit **)
- Abschnittstitel in GROSSBUCHSTABEN
- Mindestens 8 Nachrichten, mindestens 5 Rechtsprechungs-Eintraege
- [LINK:url] am Ende jeder Zusammenfassung

Quellen:
Oesterreich: {nat}
International: {intl}
OGH: {ogh}
VfGH: {vfgh}
EuGH: {eugh}
Recht News: {recht_news}
Intl. Recht: {intl_law}"""
    return ai_call(prompt,2500)[:6000]

# ═══════ MAIN ═══════
def main():
    print(f"\U0001f4f0  Morning Brief v15 \u2014 {NOW.strftime('%Y-%m-%d %H:%M UTC')}")
    if API_KEY:print(f"  \U0001f916 AI enabled\n")
    else:print(f"  \u26a0\ufe0f  No API key\n")
    ex={}
    if DATA.exists():
        with open(DATA,"r",encoding="utf-8") as f:ex=json.load(f)
    r={}
    print("\u2550\u2550 Wetter \u2550\u2550")
    weather=fetch_weather_vienna()
    if weather:r["weather"]=weather
    print()
    print("\u2550\u2550 OGH \u2550\u2550")
    ogh=ris_justiz("OGH","OGH");ogh+=fetch_ogh_website();ogh=merge_smart(ex.get("recht_ogh",[]),ogh)
    r["recht_ogh"]=trim(dedup_gz(ogh,OGH_GZ));print(f"  \u2192 {len(r['recht_ogh'])}\n")
    print("\u2550\u2550 VfGH \u2550\u2550")
    vfgh=ris_vfgh();vfgh+=fetch_vfgh_website();vfgh=merge_smart(ex.get("recht_vfgh",[]),vfgh)
    r["recht_vfgh"]=trim(dedup_gz(vfgh,VFGH_GZ),20);print(f"  \u2192 {len(r['recht_vfgh'])}\n")
    print("\u2550\u2550 EuGH \u2550\u2550")
    r["recht_eugh"]=trim(merge_smart(ex.get("recht_eugh",[]),fetch_eugh()));print(f"  \u2192 {len(r['recht_eugh'])}\n")
    for tab,feeds in [("recht_news",FEEDS_AT_NEWS),("recht_intl",FEEDS_INTL_LAW),("national",FEEDS_NATIONAL),("international",FEEDS_INTERNATIONAL)]:
        print(f"\u2550\u2550 {tab} \u2550\u2550");new_arts=fetch_rss(feeds,tab);merged=merge_smart(ex.get(tab,[]),new_arts)
        r[tab]=trim(title_dedup(merged));print(f"  \u2192 {len(r[tab])}\n")
    # Finance
    print("\u2550\u2550 Finance \u2550\u2550")
    fin_arts=fetch_rss(FEEDS_FINANCE,"finance");r["finance"]=trim(title_dedup(merge_smart(ex.get("finance",[]),fin_arts)))
    print(f"  \u2192 {len(r['finance'])}\n")
    r["crypto"]=fetch_btc_price();print()
    # Sport
    print("\u2550\u2550 Sport \u2550\u2550")
    sport_arts=fetch_rss(FEEDS_SPORT,"sport");r["sport_articles"]=trim(title_dedup(merge_smart(ex.get("sport_articles",[]),sport_arts)),30)
    print(f"  \u2192 {len(r['sport_articles'])}\n")
    # Apartments
    print("\u2550\u2550 Wohnungen \u2550\u2550")
    r["apartments"]=fetch_apartments()
    print()

    # AI Summaries
    if API_KEY:
        print("\u2550\u2550 KI-Zusammenfassungen \u2550\u2550")
        for tab in ["recht_ogh","recht_vfgh"]:
            for a in r[tab]:
                if a.get("summary"):continue
                # Try any URL that has content (RIS or ogh.gv.at)
                url=a.get("url","")
                if not url:continue
                print(f"  \U0001f916 {a['title']}...")
                s=ai_summary_from_text(a["title"],url,a.get("norm",""),a.get("rechtsgebiet",""))
                if s:a["summary"]=s;print(f"    \u2713 {s[:60]}...")
                else:print(f"    - skipped")
        for a in r.get("recht_eugh",[]):
            if a.get("summary"):continue
            print(f"  \U0001f916 {a['title']}...")
            s=ai_summary_from_excerpt(a["title"],a.get("excerpt",""))
            if s:a["summary"]=s;print(f"    \u2713 {s[:60]}...")
        print()
        # Sport briefing
        print("\u2550\u2550 KI Sport-Briefing \u2550\u2550")
        sport_hl="\n".join([f"- {a['title']} ({a['source']})" for a in r.get("sport_articles",[])[:15]])
        sb=ai_sport_briefing(sport_hl)
        if sb:r["sport_briefing"]={"text":sb,"date":NOW.isoformat()};print(f"  \u2713 {len(sb)} chars")
        print()
        # Briefing
        print("\u2550\u2550 KI-Briefing \u2550\u2550")
        briefing=ai_briefing(r)
        if briefing:r["briefing"]={"text":briefing,"date":NOW.isoformat()};print(f"  \u2713 {len(briefing)} chars")
        else:r["briefing"]=ex.get("briefing",{});print(f"  \u2717 failed")
        print()

    r["_meta"]={"last_updated":NOW.isoformat()}
    with open(DATA,"w",encoding="utf-8") as f:json.dump(r,f,ensure_ascii=False,indent=2)
    total=sum(len(r[k]) for k in r if k not in ("_meta","weather","briefing","crypto","sport_briefing"))
    sums=sum(1 for k in r if k not in ("_meta","weather","briefing","crypto","sport_briefing") for a in r[k] if isinstance(a,dict) and a.get("summary"))
    print(f"\u2713 data.json \u2014 {total} articles, {sums} summaries")

if __name__=="__main__":main()
