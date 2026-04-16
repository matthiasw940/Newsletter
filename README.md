# 🗞️ Lesezeichen — Persönlicher Newsletter

Automatisch aktualisierte Newsletter-Website mit Podcast-Player und täglichen News.

## Struktur

### 🎧 Podcasts
Morgenjournal um 8 → The Headlines (NYT) → Bloomberg Daybreak Europe

### ⚖️ AT Recht (4 Unter-Tabs)
| Tab | Quelle | Beschreibung |
|-----|--------|-------------|
| **OGH Urteile** | RIS OGD API | Neue OGH-Entscheidungen dieser Woche mit Rechtssätzen |
| **AT Recht News** | Der Standard/Recht, VfGH | Aktuelle rechtliche Diskussionen in Österreich |
| **Intl. Recht** | Verfassungsblog, Lawfare, EJIL:Talk!, Opinio Juris, European Law Blog | Internationale Rechtsentwicklungen |
| **EuGH Urteile** | CURIA RSS | Aktuelle EuGH-Pressemitteilungen zu Urteilen |

### 🇦🇹 National
ORF News, Der Standard Inland

### 🌍 International
Der Standard International, BBC World, Reuters

## 🚀 Setup (5 Minuten)

### 1. Repo erstellen
[github.com/new](https://github.com/new) → Name: `lesezeichen` → **Public** → Create

### 2. Dateien hochladen
Alle Dateien per Drag & Drop oder Git:
```bash
git clone https://github.com/DEIN-USERNAME/lesezeichen.git
cd lesezeichen
# Dateien hierhin kopieren
git add . && git commit -m "Initial" && git push
```

### 3. GitHub Pages aktivieren
**Settings → Pages** → Branch: `main`, Ordner: `/ (root)` → Save

### 4. Action testen
**Actions** → "Update Newsletter Feeds" → **Run workflow**

Seite: `https://DEIN-USERNAME.github.io/lesezeichen/`

## ⏰ Automatisch jeden Morgen um 06:00 Wiener Zeit

Die GitHub Action:
1. Ruft OGH-Urteile via RIS OGD API ab
2. Holt EuGH-Urteile von CURIA
3. Sammelt News aus allen RSS-Feeds
4. Aktualisiert `data.json`
5. GitHub Pages deployed automatisch

## 🔧 Feeds anpassen

In `fetch_feeds.py` — einfach URLs hinzufügen/entfernen:

```python
FEEDS_RECHT = {
    "at_news": [
        ("https://www.derstandard.at/rss/recht", "Der Standard"),
        # Neue Feeds hier...
    ],
}
```

Einstellungen: `MAX_ARTICLES_PER_TAB = 20`, `MAX_AGE_DAYS = 7`

## 📝 Lizenz
Persönliches Projekt. Feeds gehören den jeweiligen Quellen. RIS-Daten unter CC BY 4.0.
