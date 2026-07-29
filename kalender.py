#!/usr/bin/env python3
"""Phase 3 — Kalender-Engine: rollendes Fenster heute + N Tage.

Berechnet Geburtstage, Todestage, Gründungsjubiläen und Song-Jubiläen
aus den Stammdaten in kuenstler.db. Reine Berechnung, keine Recherche.

Ergebnis wird in die Tabelle `kalender_events` geschrieben (täglich
frisch berechnet) und als JSON für den Digest bereitgestellt.
"""

import json
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

from config import (
    DB_PATH,
    ERSTER_TODESTAG,
    HERVORHEBEN_TEILER,
    KALENDER_FENSTER_TAGE,
    RUND_TEILER,
    SONG_JUBILAEEN,
)

KALENDER_SCHEMA = """
CREATE TABLE IF NOT EXISTS kalender_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    datum           TEXT    NOT NULL,
    kuenstler_id    INTEGER REFERENCES kuenstler(id),
    titel_id        INTEGER REFERENCES titel(id),
    typ             TEXT    NOT NULL,
    jahre           INTEGER,
    text            TEXT    NOT NULL,
    quellen         TEXT,
    verifiziert     INTEGER DEFAULT 0,
    hervorgehoben   INTEGER DEFAULT 0,
    berechnet_am    TEXT    NOT NULL
);
"""


def init_kalender(conn: sqlite3.Connection):
    conn.executescript(KALENDER_SCHEMA)
    conn.commit()


def _is_round(n: int) -> bool:
    return n > 0 and n % RUND_TEILER == 0


def _is_highlight(n: int) -> bool:
    return n > 0 and n % HERVORHEBEN_TEILER == 0


def _parse_date(d: str | None) -> date | None:
    if not d:
        return None
    try:
        parts = d.split("-")
        return date(int(parts[0]), int(parts[1]), int(parts[2]))
    except (ValueError, IndexError):
        return None


def berechne_events(conn: sqlite3.Connection, start: date, tage: int) -> list[dict]:
    """Berechnet alle Kalender-Events im Fenster [start, start+tage]."""
    events = []
    end = start + timedelta(days=tage)

    conn.row_factory = sqlite3.Row
    kuenstler = conn.execute(
        """SELECT id, name, typ, geburtsdatum, todesdatum, gruendungsjahr,
                  quellen, verifiziert
           FROM kuenstler"""
    ).fetchall()

    for k in kuenstler:
        quellen = k["quellen"] or "[]"
        verif = k["verifiziert"] or 0

        geb = _parse_date(k["geburtsdatum"])
        tod = _parse_date(k["todesdatum"])
        gruendung = k["gruendungsjahr"]

        # --- Geburtstage ---
        if geb and k["typ"] == "Person":
            for day_offset in range(tage + 1):
                check = start + timedelta(days=day_offset)
                if check.month == geb.month and check.day == geb.day:
                    alter = check.year - geb.year

                    if tod is None:
                        if _is_round(alter):
                            events.append({
                                "datum": check.isoformat(),
                                "kuenstler_id": k["id"],
                                "typ": "geburtstag",
                                "jahre": alter,
                                "text": f"{k['name']} wird {alter} Jahre alt",
                                "quellen": quellen,
                                "verifiziert": verif,
                                "hervorgehoben": 1 if _is_highlight(alter) else 0,
                            })
                    else:
                        if _is_round(alter):
                            events.append({
                                "datum": check.isoformat(),
                                "kuenstler_id": k["id"],
                                "typ": "waere_geburtstag",
                                "jahre": alter,
                                "text": f"{k['name']} wäre {alter} Jahre alt geworden",
                                "quellen": quellen,
                                "verifiziert": verif,
                                "hervorgehoben": 1 if _is_highlight(alter) else 0,
                            })

        # --- Todestage ---
        if tod and k["typ"] == "Person":
            for day_offset in range(tage + 1):
                check = start + timedelta(days=day_offset)
                if check.month == tod.month and check.day == tod.day:
                    tod_jahre = check.year - tod.year
                    if tod_jahre < 1:
                        continue

                    show = False
                    if ERSTER_TODESTAG and tod_jahre == 1:
                        show = True
                    if _is_round(tod_jahre):
                        show = True

                    if show:
                        if tod_jahre == 1:
                            text = f"1. Todestag von {k['name']}"
                        else:
                            text = f"{tod_jahre}. Todestag von {k['name']}"
                        events.append({
                            "datum": check.isoformat(),
                            "kuenstler_id": k["id"],
                            "typ": "todestag",
                            "jahre": tod_jahre,
                            "text": text,
                            "quellen": quellen,
                            "verifiziert": verif,
                            "hervorgehoben": 1 if _is_highlight(tod_jahre) or tod_jahre == 1 else 0,
                        })

        # --- Gründungsjubiläen ---
        if gruendung and k["typ"] == "Band":
            for day_offset in range(tage + 1):
                check = start + timedelta(days=day_offset)
                if check.month == 1 and check.day == 1:
                    alter = check.year - gruendung
                    if _is_round(alter):
                        events.append({
                            "datum": check.isoformat(),
                            "kuenstler_id": k["id"],
                            "typ": "gruendung",
                            "jahre": alter,
                            "text": f"{k['name']}: {alter} Jahre seit Gründung ({gruendung})",
                            "quellen": quellen,
                            "verifiziert": verif,
                            "hervorgehoben": 1 if _is_highlight(alter) else 0,
                        })

    # --- Song-Jubiläen ---
    titel = conn.execute(
        """SELECT t.id, t.titel, t.voe_monat, t.voe_jahr,
                  k.id AS kid, k.name
           FROM titel t
           JOIN kuenstler k ON t.kuenstler_id = k.id
           WHERE t.voe_jahr IS NOT NULL"""
    ).fetchall()

    for t in titel:
        voe_jahr = t["voe_jahr"]
        voe_monat = t["voe_monat"]

        for day_offset in range(tage + 1):
            check = start + timedelta(days=day_offset)
            alter = check.year - voe_jahr
            if alter not in SONG_JUBILAEEN:
                continue

            if voe_monat:
                if check.month == voe_monat and check.day == 1:
                    events.append({
                        "datum": check.isoformat(),
                        "kuenstler_id": t["kid"],
                        "titel_id": t["id"],
                        "typ": "song_jubilaeum",
                        "jahre": alter,
                        "text": (f"„{t['titel']}\" von {t['name']} erschien "
                                 f"im {_monat_name(voe_monat)} vor {alter} Jahren"),
                        "quellen": "[]",
                        "verifiziert": 0,
                        "hervorgehoben": 1 if alter >= 50 else 0,
                    })
            else:
                if check.month == 1 and check.day == 1:
                    events.append({
                        "datum": check.isoformat(),
                        "kuenstler_id": t["kid"],
                        "titel_id": t["id"],
                        "typ": "song_jubilaeum",
                        "jahre": alter,
                        "text": (f"„{t['titel']}\" von {t['name']} erschien "
                                 f"vor {alter} Jahren ({voe_jahr})"),
                        "quellen": "[]",
                        "verifiziert": 0,
                        "hervorgehoben": 1 if alter >= 50 else 0,
                    })

    events.sort(key=lambda e: (e["datum"], -e.get("hervorgehoben", 0), e["text"]))
    return events


MONATSNAMEN = [
    "", "Januar", "Februar", "März", "April", "Mai", "Juni",
    "Juli", "August", "September", "Oktober", "November", "Dezember",
]


def _monat_name(m: int) -> str:
    return MONATSNAMEN[m] if 1 <= m <= 12 else str(m)


def persist_events(conn: sqlite3.Connection, events: list[dict], berechnet_am: str):
    """Schreibt Events in die DB (ersetzt vorherige Berechnung)."""
    init_kalender(conn)
    conn.execute("DELETE FROM kalender_events WHERE berechnet_am < ?", (berechnet_am,))
    for e in events:
        conn.execute(
            """INSERT INTO kalender_events
               (datum, kuenstler_id, titel_id, typ, jahre, text, quellen,
                verifiziert, hervorgehoben, berechnet_am)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                e["datum"],
                e.get("kuenstler_id"),
                e.get("titel_id"),
                e["typ"],
                e.get("jahre"),
                e["text"],
                e.get("quellen", "[]"),
                e.get("verifiziert", 0),
                e.get("hervorgehoben", 0),
                berechnet_am,
            ),
        )
    conn.commit()


def run():
    conn = sqlite3.connect(DB_PATH)
    heute = date.today()

    events = berechne_events(conn, heute, KALENDER_FENSTER_TAGE)
    persist_events(conn, events, heute.isoformat())
    conn.close()

    print(f"Kalender: {len(events)} Events für {heute} + {KALENDER_FENSTER_TAGE} Tage")
    for e in events:
        flag = "⚠" if not e.get("verifiziert") else "✓"
        star = "★" if e.get("hervorgehoben") else " "
        print(f"  {e['datum']} {star} [{flag}] {e['text']}")


if __name__ == "__main__":
    run()
