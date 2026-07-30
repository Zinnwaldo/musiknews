#!/usr/bin/env python3
"""Phase 5 — Digest-Generator: baut die statische Webseite.

Erzeugt docs/index.html (Heute + 10-Tage-Vorschau) und archiviert
den Tages-Digest unter docs/JJJJ-MM-TT.html.

Optional: StatiCrypt-Verschlüsselung und Git-Push ins Pages-Repo.
"""

import argparse
import html
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

from config import (
    DB_PATH,
    DOCS_DIR,
    KALENDER_FENSTER_TAGE,
    PAGES_PAT_ENV,
    PAGES_REPO_ENV,
    STATICRYPT_PASSWORD_ENV,
)

DOCS_DIR.mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# Daten laden
# ---------------------------------------------------------------------------

def load_kalender_events(conn: sqlite3.Connection, heute: str) -> list[dict]:
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """SELECT datum, typ, jahre, text, quellen, verifiziert, hervorgehoben
           FROM kalender_events
           WHERE berechnet_am = ?
           ORDER BY datum, -hervorgehoben, text""",
        (heute,),
    ).fetchall()
    return [dict(r) for r in rows]


def load_news(conn: sqlite3.Connection, heute: str, lookback_days: int = 3) -> list[dict]:
    """Lädt alle relevanten News:

    - frisch gefunden (letzte lookback_days Tage), egal wann das Ereignis ist
    - ODER Ereignis steht noch bevor (Konzert, VÖ-Termin …) — bleibt
      sichtbar, bis es vorbei ist
    """
    conn.row_factory = sqlite3.Row
    heute_dt = date.fromisoformat(heute)
    cutoff = (heute_dt - timedelta(days=lookback_days)).isoformat()
    rows = conn.execute(
        """SELECT n.typ, n.ereignis_datum, n.text, n.quellen,
                  n.verifiziert, n.gefunden_am, k.name AS kuenstler
           FROM news n
           JOIN kuenstler k ON n.kuenstler_id = k.id
           WHERE n.gefunden_am >= ?
              OR (n.ereignis_datum IS NOT NULL AND n.ereignis_datum >= ?)
           ORDER BY n.gefunden_am DESC, k.name""",
        (cutoff, heute),
    ).fetchall()
    return [dict(r) for r in rows]


def load_verbrauch(conn: sqlite3.Connection, heute: str) -> dict | None:
    """Summiert den Abo-Verbrauch des letzten Recherche-Laufs."""
    try:
        row = conn.execute(
            """SELECT COUNT(*) AS n, SUM(input_tokens + output_tokens) AS tokens,
                      SUM(web_suchen) AS suchen, SUM(kosten_usd) AS kosten
               FROM verbrauch
               WHERE datum = (SELECT MAX(datum) FROM verbrauch)""",
        ).fetchone()
    except sqlite3.OperationalError:
        return None
    if not row or not row[0]:
        return None
    return {"recherchen": row[0], "tokens": row[1] or 0,
            "suchen": row[2] or 0, "kosten": row[3] or 0.0}


# ---------------------------------------------------------------------------
# HTML-Rendering
# ---------------------------------------------------------------------------

TYP_LABELS = {
    "geburtstag": "🎂 Geburtstag",
    "waere_geburtstag": "🕯 Wäre … geworden",
    "todestag": "✝ Todestag",
    "gruendung": "🎸 Gründungsjubiläum",
    "song_jubilaeum": "🎵 Song-Jubiläum",
    "album": "💿 Album",
    "single": "🎤 Single",
    "tour": "🎪 Tour/Konzert",
    "tv": "📺 TV-Auftritt",
    "news": "📰 Nachricht",
}

WOCHENTAGE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag",
              "Freitag", "Samstag", "Sonntag"]

MONATE = ["", "Januar", "Februar", "März", "April", "Mai", "Juni",
          "Juli", "August", "September", "Oktober", "November", "Dezember"]


def _format_datum(d: str) -> str:
    try:
        dt = date.fromisoformat(d)
        wt = WOCHENTAGE[dt.weekday()]
        return f"{wt}, {dt.day}. {MONATE[dt.month]} {dt.year}"
    except (ValueError, IndexError):
        return d


def _quellen_links(quellen_json: str) -> str:
    try:
        urls = json.loads(quellen_json)
    except (json.JSONDecodeError, TypeError):
        return ""
    if not urls:
        return ""
    links = []
    for i, url in enumerate(urls, 1):
        safe = html.escape(url)
        links.append(f'<a href="{safe}" target="_blank" rel="noopener">[{i}]</a>')
    return " ".join(links)


def _render_event(e: dict) -> str:
    typ_label = TYP_LABELS.get(e["typ"], e["typ"])
    verif = "" if e.get("verifiziert") else ' <span class="unverified">⚠ unverifiziert</span>'
    quellen = _quellen_links(e.get("quellen", "[]"))
    css_class = "event highlight" if e.get("hervorgehoben") else "event"

    text = html.escape(e["text"])
    return (f'<div class="{css_class}" data-kind="kalender" '
            f'data-verif="{1 if e.get("verifiziert") else 0}">'
            f'<span class="typ">{typ_label}</span> '
            f'{text}{verif}'
            f'{" " + quellen if quellen else ""}'
            f'</div>')


def _render_news_item(n: dict, heute: str) -> str:
    typ_label = TYP_LABELS.get(n["typ"], n["typ"])
    verif = "" if n.get("verifiziert") else ' <span class="unverified">⚠ unverifiziert</span>'
    quellen = _quellen_links(n.get("quellen", "[]"))
    kuenstler = html.escape(n.get("kuenstler", ""))
    text = html.escape(n["text"])
    datum = ""
    if n.get("ereignis_datum"):
        datum = f' <span class="datum">({n["ereignis_datum"]})</span>'
    neu = ' <span class="neu">NEU</span>' if n.get("gefunden_am") == heute else ""

    return (f'<div class="news-item" data-kind="news" '
            f'data-verif="{1 if n.get("verifiziert") else 0}">'
            f'<span class="typ">{typ_label}</span>{neu} '
            f'<strong>{kuenstler}</strong>: {text}{datum}{verif}'
            f'{" " + quellen if quellen else ""}'
            f'</div>')


def render_page(heute: str, events: list[dict], news: list[dict],
                verbrauch: dict | None = None) -> str:
    """Rendert die komplette HTML-Seite."""
    heute_dt = date.fromisoformat(heute)

    events_by_date: dict[str, list[dict]] = {}
    for e in events:
        events_by_date.setdefault(e["datum"], []).append(e)

    sections = []

    today_events = events_by_date.pop(heute, [])
    if today_events or news:
        sections.append(f'<h2>📅 Heute — {_format_datum(heute)}</h2>')
        for e in today_events:
            sections.append(_render_event(e))
        if not today_events:
            sections.append('<p class="empty">Keine Kalender-Ereignisse heute.</p>')

    if news:
        sections.append('<h3>🔍 Aktuelle News</h3>')
        for n in news:
            sections.append(_render_news_item(n, heute))

    dates = sorted(events_by_date.keys())
    if dates:
        sections.append(f'<h2>📆 Vorschau ({KALENDER_FENSTER_TAGE} Tage)</h2>')
        for d in dates:
            sections.append(f'<h3>{_format_datum(d)}</h3>')
            for e in events_by_date[d]:
                sections.append(_render_event(e))

    if not sections:
        sections.append(f'<h2>📅 {_format_datum(heute)}</h2>')
        sections.append(
            '<p class="empty">Keine runden Jubiläen und keine News im aktuellen '
            f'Fenster (heute + {KALENDER_FENSTER_TAGE} Tage). '
            'Das Tool läuft — es gibt schlicht nichts zu melden.</p>')

    content = "\n".join(sections)

    verbrauch_html = ""
    if verbrauch:
        mio = verbrauch["tokens"] / 1e6
        verbrauch_html = (
            f'<p>Abo-Verbrauch letzter Recherche-Lauf: '
            f'{verbrauch["recherchen"]} Recherchen · '
            f'{verbrauch["suchen"]} Websuchen · '
            f'{mio:.2f} Mio. Tokens · '
            f'≈ ${verbrauch["kosten"]:.2f} API-Gegenwert</p>')

    return f"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>Musiknews — NDR 1 Radio MV</title>
<style>
:root {{
  --bg: #f8f9fa; --fg: #212529; --card: #fff; --border: #dee2e6;
  --accent: #0d6efd; --warn: #dc3545; --highlight-bg: #fff3cd;
}}
@media (prefers-color-scheme: dark) {{
  :root {{
    --bg: #1a1a2e; --fg: #e0e0e0; --card: #16213e; --border: #333;
    --accent: #4dabf7; --warn: #ff6b6b; --highlight-bg: #3d3100;
  }}
}}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  background: var(--bg); color: var(--fg);
  max-width: 800px; margin: 0 auto; padding: 1rem;
  line-height: 1.6;
}}
h1 {{ margin-bottom: 0.25rem; }}
.meta {{ color: #6c757d; margin-bottom: 1.5rem; font-size: 0.9rem; }}
h2 {{ margin: 1.5rem 0 0.75rem; border-bottom: 2px solid var(--border); padding-bottom: 0.25rem; }}
h3 {{ margin: 1rem 0 0.5rem; color: var(--accent); }}
.event, .news-item {{
  background: var(--card); border: 1px solid var(--border);
  border-radius: 6px; padding: 0.6rem 0.8rem; margin: 0.4rem 0;
}}
.event.highlight {{ background: var(--highlight-bg); border-color: #ffc107; }}
.typ {{ font-weight: 600; }}
.unverified {{ color: var(--warn); font-weight: 600; }}
.neu {{ background: var(--accent); color: #fff; font-size: 0.7rem; font-weight: 700;
        padding: 0.1rem 0.4rem; border-radius: 4px; vertical-align: middle; }}
.datum {{ color: #6c757d; }}
.empty {{ color: #6c757d; font-style: italic; }}
a {{ color: var(--accent); }}
footer {{ margin-top: 2rem; padding-top: 1rem; border-top: 1px solid var(--border);
          font-size: 0.8rem; color: #6c757d; }}
.controls {{ position: sticky; top: 0; background: var(--bg); padding: 0.5rem 0;
             margin-bottom: 0.5rem; z-index: 10; border-bottom: 1px solid var(--border); }}
.controls input[type="search"] {{
  width: 100%; padding: 0.5rem 0.75rem; font-size: 1rem;
  border: 1px solid var(--border); border-radius: 6px;
  background: var(--card); color: var(--fg); margin-bottom: 0.5rem;
}}
.chips {{ display: flex; flex-wrap: wrap; gap: 0.4rem; }}
.chip {{ border: 1px solid var(--border); background: var(--card); color: var(--fg);
         border-radius: 999px; padding: 0.25rem 0.8rem; font-size: 0.85rem;
         cursor: pointer; }}
.chip.active {{ background: var(--accent); color: #fff; border-color: var(--accent); }}
.count {{ margin-left: auto; align-self: center; font-size: 0.85rem; color: #6c757d; }}
.hidden {{ display: none !important; }}
</style>
</head>
<body>
<h1>Musiknews — NDR 1 Radio MV</h1>
<p class="meta">Generiert: {_format_datum(heute)} · Rechercheansätze mit Belegen, keine sendefertigen Fakten</p>
<div class="controls">
  <input type="search" id="suche" placeholder="Suchen … (Künstler, Titel, Ort)" autocomplete="off">
  <div class="chips">
    <button class="chip active" data-filter="kind" data-value="">Alles</button>
    <button class="chip" data-filter="kind" data-value="kalender">📅 Jubiläen</button>
    <button class="chip" data-filter="kind" data-value="news">🔍 News</button>
    <button class="chip" data-filter="verif" data-value="1">✓ verifiziert</button>
    <button class="chip" data-filter="verif" data-value="0">⚠ unverifiziert</button>
    <span class="count" id="count"></span>
  </div>
</div>
{content}
<footer>
  <p>⚠ = unverifiziert (weniger als zwei unabhängige Quellen).
  Alle Angaben sind Rechercheansätze und müssen redaktionell geprüft werden.</p>
  {verbrauch_html}
  <p>Generiert am {heute} · Musiknews-Tool v1.0</p>
</footer>
<script>
(function () {{
  var suche = document.getElementById('suche');
  var chips = Array.prototype.slice.call(document.querySelectorAll('.chip'));
  var items = Array.prototype.slice.call(document.querySelectorAll('[data-kind]'));
  var countEl = document.getElementById('count');
  var aktiv = {{ kind: '', verif: '' }};

  function anwenden() {{
    var q = suche.value.trim().toLowerCase();
    var sichtbar = 0;
    items.forEach(function (el) {{
      var passt = true;
      if (aktiv.kind && el.dataset.kind !== aktiv.kind) passt = false;
      if (aktiv.verif !== '' && el.dataset.verif !== aktiv.verif) passt = false;
      if (q && el.textContent.toLowerCase().indexOf(q) === -1) passt = false;
      el.classList.toggle('hidden', !passt);
      if (passt) sichtbar++;
    }});
    // Datums-Überschriften ohne sichtbare Einträge ausblenden
    Array.prototype.slice.call(document.querySelectorAll('h2, h3')).forEach(function (h) {{
      var el = h.nextElementSibling, hatSichtbares = false;
      while (el && !/^H[23]$/.test(el.tagName)) {{
        if (el.dataset && el.dataset.kind && !el.classList.contains('hidden')) {{
          hatSichtbares = true; break;
        }}
        el = el.nextElementSibling;
      }}
      var gefiltert = aktiv.kind || aktiv.verif !== '' || q;
      h.classList.toggle('hidden', Boolean(gefiltert) && !hatSichtbares);
    }});
    countEl.textContent = (aktiv.kind || aktiv.verif !== '' || q)
      ? sichtbar + ' Treffer' : '';
  }}

  chips.forEach(function (chip) {{
    chip.addEventListener('click', function () {{
      var f = chip.dataset.filter, v = chip.dataset.value;
      if (f === 'kind') {{
        aktiv.kind = (aktiv.kind === v) ? '' : v;
        if (v === '') aktiv.kind = '';
      }}
      if (f === 'verif') aktiv.verif = (aktiv.verif === v) ? '' : v;
      chips.forEach(function (c) {{
        if (c.dataset.filter === 'kind')
          c.classList.toggle('active', c.dataset.value === aktiv.kind ||
                                       (aktiv.kind === '' && c.dataset.value === ''));
        if (c.dataset.filter === 'verif')
          c.classList.toggle('active', c.dataset.value === aktiv.verif);
      }});
      anwenden();
    }});
  }});
  suche.addEventListener('input', anwenden);
}})();
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Verschlüsselung & Deploy
# ---------------------------------------------------------------------------

def encrypt_file(html_path: Path, password: str) -> bool:
    """Verschlüsselt eine HTML-Datei mit StatiCrypt (v3-CLI) in-place."""
    if not shutil.which("staticrypt"):
        if shutil.which("npx"):
            cmd = ["npx", "--yes", "staticrypt"]
        else:
            print("WARNUNG: staticrypt nicht gefunden, Seite bleibt unverschlüsselt.",
                  file=sys.stderr)
            return False
    else:
        cmd = ["staticrypt"]

    with tempfile.TemporaryDirectory() as tmp:
        try:
            subprocess.run(
                [*cmd, str(html_path),
                 "-p", password,
                 "-d", tmp,
                 "--remember", "7",
                 "--short",
                 "--template-title", "Musiknews — NDR 1 Radio MV",
                 "--template-button", "Öffnen",
                 "--template-placeholder", "Passwort",
                 "--template-error", "Falsches Passwort",
                 "--template-remember", "Angemeldet bleiben",
                 "--template-instructions", "Interner Bereich — bitte Redaktions-Passwort eingeben."],
                check=True, capture_output=True, text=True,
                cwd=html_path.parent,
            )
        except subprocess.CalledProcessError as e:
            print(f"WARNUNG: StatiCrypt-Fehler: {e.stderr}", file=sys.stderr)
            return False

        # StatiCrypt legt die Datei unter <tmp>/<name> ab (ggf. verschachtelt)
        candidates = list(Path(tmp).rglob(html_path.name))
        if not candidates:
            print("WARNUNG: StatiCrypt hat keine Ausgabedatei erzeugt.", file=sys.stderr)
            return False

        encrypted = candidates[0].read_text(encoding="utf-8")
        if "staticrypt" not in encrypted.lower():
            print("WARNUNG: StatiCrypt-Ausgabe sieht nicht verschlüsselt aus.", file=sys.stderr)
            return False

        html_path.write_text(encrypted, encoding="utf-8")
        return True


def deploy_pages(docs_dir: Path):
    """Pusht docs/ ins GitHub-Pages-Repo."""
    repo = os.environ.get(PAGES_REPO_ENV)
    pat = os.environ.get(PAGES_PAT_ENV)
    if not repo or not pat:
        print("HINWEIS: Kein Pages-Repo/PAT konfiguriert, kein Deploy.")
        return

    try:
        subprocess.run(
            ["git", "add", "."],
            cwd=docs_dir, check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "commit", "-m", f"Digest {date.today().isoformat()}"],
            cwd=docs_dir, check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "push"],
            cwd=docs_dir, check=True, capture_output=True,
        )
        print("Deploy erfolgreich.")
    except subprocess.CalledProcessError as e:
        print(f"Deploy-Fehler: {e.stderr}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Hauptlogik
# ---------------------------------------------------------------------------

def run(no_encrypt: bool = False, no_deploy: bool = False):
    if (Path(__file__).parent / "PAUSE").exists():
        print("PAUSE-Datei vorhanden — Digest übersprungen.")
        return
    conn = sqlite3.connect(DB_PATH)
    heute = date.today().isoformat()

    events = load_kalender_events(conn, heute)
    news = load_news(conn, heute)
    verbrauch = load_verbrauch(conn, heute)
    conn.close()

    page = render_page(heute, events, news, verbrauch)

    index_path = DOCS_DIR / "index.html"
    index_path.write_text(page, encoding="utf-8")
    print(f"Digest geschrieben: {index_path}")

    archive_path = DOCS_DIR / f"{heute}.html"
    archive_path.write_text(page, encoding="utf-8")
    print(f"Archiv: {archive_path}")

    if not no_encrypt:
        password = os.environ.get(STATICRYPT_PASSWORD_ENV)
        if password:
            if encrypt_file(index_path, password):
                print("index.html verschlüsselt.")
            if encrypt_file(archive_path, password):
                print(f"{heute}.html verschlüsselt.")
        else:
            print(f"HINWEIS: {STATICRYPT_PASSWORD_ENV} nicht gesetzt, keine Verschlüsselung.")

    if not no_deploy:
        deploy_pages(DOCS_DIR)

    print(f"Digest abgeschlossen: {len(events)} Kalender-Events, {len(news)} News")


def main():
    parser = argparse.ArgumentParser(description="Tages-Digest generieren")
    parser.add_argument("--no-encrypt", action="store_true",
                        help="Keine StatiCrypt-Verschlüsselung")
    parser.add_argument("--no-deploy", action="store_true",
                        help="Kein Git-Push ins Pages-Repo")
    args = parser.parse_args()
    run(no_encrypt=args.no_encrypt, no_deploy=args.no_deploy)


if __name__ == "__main__":
    main()
