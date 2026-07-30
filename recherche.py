#!/usr/bin/env python3
"""Phase 4 — Recherche-Agent: tägliche Newssuche per Claude Code CLI.

Läuft über das Max-Abo (kein API-Key nötig). Claude Code wird im
Headless-Modus aufgerufen (`claude -p "…" --output-format json`).

Tier A (Priorität A): täglich abfragen.
Tier B (Priorität B/C): wöchentlich rotierend (~55 pro Tag).

Gesucht wird: Albumankündigungen, Singles, Tourtermine, TV-Auftritte, News.
Tourtermine in MV/Umgebung werden im Digest nach oben gewichtet.

Ergebnisse → Tabelle `news` mit Dedupe über hash(kuenstler, typ, ereignis_datum).
"""

import argparse
import hashlib
import json
import signal
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from pathlib import Path

# Sauberes Verhalten bei abgeschnittener Pipe (z. B. `| head`)
signal.signal(signal.SIGPIPE, signal.SIG_DFL)

from config import (
    CLAUDE_CMD,
    CLAUDE_TIMEOUT,
    DB_PATH,
    MV_STAEDTE,
    RECHERCHE_WORKERS,
    TIER_A_TAEGLICH,
    TIER_B_PRO_TAG,
)


NEWS_SCHEMA = """
CREATE TABLE IF NOT EXISTS news (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    kuenstler_id    INTEGER NOT NULL REFERENCES kuenstler(id),
    typ             TEXT    NOT NULL,
    ereignis_datum  TEXT,
    text            TEXT    NOT NULL,
    quellen         TEXT,
    verifiziert     INTEGER DEFAULT 0,
    gefunden_am     TEXT    NOT NULL,
    hash            TEXT    NOT NULL UNIQUE
);
"""


def init_news_table(conn: sqlite3.Connection):
    conn.executescript(NEWS_SCHEMA)
    conn.commit()


def _make_hash(kuenstler_id: int, typ: str, ereignis_datum: str | None) -> str:
    raw = f"{kuenstler_id}:{typ}:{ereignis_datum or ''}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


MV_STAEDTE_LOWER = [s.lower() for s in MV_STAEDTE]


def _ist_mv_relevant(text: str) -> bool:
    text_lower = text.lower()
    return any(s in text_lower for s in MV_STAEDTE_LOWER)


def _build_prompt(name: str, heute: date, fenster_tage: int = 10) -> str:
    bis = heute + timedelta(days=fenster_tage)
    staedte = ", ".join(MV_STAEDTE)

    return f"""Recherchiere aktuelle Informationen über den Musiker/die Band "{name}".

Zeitfenster: {heute.isoformat()} bis {bis.isoformat()}, plus Neuankündigungen.

Gesucht:
1. Neue Alben oder Singles (angekündigt oder erschienen)
2. Tourtermine und Konzerte, besonders in: {staedte}
3. TV-Auftritte in Deutschland
4. Relevante Nachrichten (Preise, besondere Ereignisse)

WICHTIG:
- NUR belegbare Fakten mit konkreter Quell-URL.
- Keine Spekulationen, keine Gerüchte.
- Wenn du nichts Aktuelles findest, antworte mit einem leeren Array.

Antworte ausschließlich als JSON-Array. Jedes Element:
{{
  "typ": "album" | "single" | "tour" | "tv" | "news",
  "ereignis_datum": "YYYY-MM-DD" oder null,
  "text": "Kurze Beschreibung der Nachricht",
  "quellen": ["https://..."],
  "verifiziert": true nur wenn zwei unabhängige Quellen vorliegen
}}

Beispiel für eine leere Antwort: []"""


def recherche_kuenstler(name: str, heute: date) -> list[dict]:
    """Führt eine Claude-Code-CLI-Suche für einen Künstler durch."""
    prompt = _build_prompt(name, heute)

    try:
        result = subprocess.run(
            [CLAUDE_CMD, "-p", prompt,
             "--output-format", "json",
             "--allowedTools", "WebSearch", "WebFetch"],
            capture_output=True, text=True, timeout=CLAUDE_TIMEOUT,
        )
    except FileNotFoundError:
        print(f"\n    FEHLER: '{CLAUDE_CMD}' nicht gefunden. "
              "Claude Code CLI installieren: https://docs.anthropic.com/en/docs/claude-code",
              file=sys.stderr)
        sys.exit(1)
    except subprocess.TimeoutExpired:
        print(f"Timeout ({CLAUDE_TIMEOUT}s)", file=sys.stderr)
        return []

    if result.returncode != 0:
        stderr = result.stderr.strip()[:200] if result.stderr else ""
        print(f"CLI-Fehler (exit {result.returncode}): {stderr}", file=sys.stderr)
        return []

    try:
        cli_output = json.loads(result.stdout)
    except json.JSONDecodeError:
        cli_output = None

    if isinstance(cli_output, dict) and "result" in cli_output:
        full_text = cli_output["result"]
    elif isinstance(cli_output, str):
        full_text = cli_output
    else:
        full_text = result.stdout

    start = full_text.find("[")
    end = full_text.rfind("]")
    if start == -1 or end == -1:
        return []

    try:
        results = json.loads(full_text[start:end + 1])
        if not isinstance(results, list):
            return []
        return results
    except json.JSONDecodeError:
        print(f"JSON-Parse-Fehler", file=sys.stderr)
        return []


def get_tier_artists(conn: sqlite3.Connection, heute: date) -> list[dict]:
    """Bestimmt welche Künstler heute recherchiert werden."""
    conn.row_factory = sqlite3.Row
    artists = []

    if TIER_A_TAEGLICH:
        tier_a = conn.execute(
            "SELECT id, name FROM kuenstler WHERE prioritaet = 'A' ORDER BY name"
        ).fetchall()
        artists.extend([{"id": r["id"], "name": r["name"], "tier": "A"} for r in tier_a])

    tier_bc = conn.execute(
        "SELECT id, name FROM kuenstler WHERE prioritaet != 'A' ORDER BY name"
    ).fetchall()

    if tier_bc:
        day_of_year = heute.timetuple().tm_yday
        total = len(tier_bc)
        chunk_size = TIER_B_PRO_TAG
        start_idx = (day_of_year * chunk_size) % total
        indices = [(start_idx + i) % total for i in range(min(chunk_size, total))]
        for idx in indices:
            r = tier_bc[idx]
            artists.append({"id": r["id"], "name": r["name"], "tier": "B"})

    return artists


def run(limit: int | None = None, dry_run: bool = False):
    conn = sqlite3.connect(DB_PATH)
    init_news_table(conn)
    heute = date.today()

    artists = get_tier_artists(conn, heute)
    if limit:
        artists = artists[:limit]

    print(f"Recherche: {len(artists)} Künstler ({heute})")

    if dry_run:
        for a in artists:
            print(f"  [{a['tier']}] {a['name']}")
        conn.close()
        return

    stats = {"gesucht": 0, "gefunden": 0, "duplikate": 0, "fehler": 0}

    # Recherche parallel (nur die CLI-Aufrufe); DB-Schreiben im Hauptthread
    with ThreadPoolExecutor(max_workers=RECHERCHE_WORKERS) as pool:
        futures = {
            pool.submit(recherche_kuenstler, artist["name"], heute): artist
            for artist in artists
        }

        done = 0
        for future in as_completed(futures):
            artist = futures[future]
            done += 1
            stats["gesucht"] += 1

            try:
                results = future.result()
            except Exception as e:
                print(f"  [{done}/{len(artists)}] [{artist['tier']}] {artist['name']} … Fehler: {e}")
                stats["fehler"] += 1
                continue

            if not results:
                print(f"  [{done}/{len(artists)}] [{artist['tier']}] {artist['name']} … keine News")
                continue

            count = 0
            for item in results:
                if not isinstance(item, dict) or "typ" not in item or "text" not in item:
                    stats["fehler"] += 1
                    continue

                quellen = item.get("quellen", [])
                if not quellen:
                    continue

                h = _make_hash(artist["id"], item["typ"], item.get("ereignis_datum"))

                try:
                    conn.execute(
                        """INSERT INTO news
                           (kuenstler_id, typ, ereignis_datum, text, quellen,
                            verifiziert, gefunden_am, hash)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            artist["id"],
                            item["typ"],
                            item.get("ereignis_datum"),
                            item["text"],
                            json.dumps(quellen),
                            1 if item.get("verifiziert") else 0,
                            heute.isoformat(),
                            h,
                        ),
                    )
                    count += 1
                    stats["gefunden"] += 1
                except sqlite3.IntegrityError:
                    stats["duplikate"] += 1

            print(f"  [{done}/{len(artists)}] [{artist['tier']}] {artist['name']} … "
                  + (f"{count} neu" if count else "nur Duplikate"))
            conn.commit()

    conn.close()
    print(f"\nRecherche abgeschlossen: {stats['gesucht']} gesucht, "
          f"{stats['gefunden']} neu, {stats['duplikate']} Duplikate, "
          f"{stats['fehler']} Fehler")


def main():
    parser = argparse.ArgumentParser(description="Tägliche Künstler-Recherche")
    parser.add_argument("--limit", type=int, default=None,
                        help="Maximal N Künstler recherchieren")
    parser.add_argument("--dry-run", action="store_true",
                        help="Nur Liste der Künstler anzeigen")
    args = parser.parse_args()
    run(limit=args.limit, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
