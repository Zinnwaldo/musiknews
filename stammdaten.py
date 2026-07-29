#!/usr/bin/env python3
"""Phase 2 — Stammdaten aus Wikidata und MusicBrainz abgleichen.

Erstlauf: alle Künstler ohne wikidata_id.
Nachpflege (--nachpflege): nur Künstler mit last_seen in den letzten 7 Tagen
                           und fehlenden Stammdaten.

Konflikte → review/stammdaten_konflikte.md
Mitglieder-Vorschläge → review/mitglieder_vorschlag.md
"""

import argparse
import hashlib
import json
import re
import sqlite3
import sys
import time
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import quote

import requests

from config import (
    DB_PATH,
    MUSICBRAINZ_RATE_LIMIT,
    MUSICBRAINZ_USER_AGENT,
    REVIEW_DIR,
)

REVIEW_DIR.mkdir(exist_ok=True)

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": MUSICBRAINZ_USER_AGENT})

_last_mb_request = 0.0


# ---------------------------------------------------------------------------
# Wikidata
# ---------------------------------------------------------------------------

WIKIDATA_API = "https://www.wikidata.org/w/api.php"
WIKIDATA_ENTITY = "https://www.wikidata.org/wiki/Special:EntityData/{qid}.json"


def wikidata_search(name: str) -> list[dict]:
    """Sucht eine Wikidata-Entität per wbsearchentities."""
    resp = SESSION.get(WIKIDATA_API, params={
        "action": "wbsearchentities",
        "search": name,
        "language": "de",
        "uselang": "de",
        "type": "item",
        "limit": 5,
        "format": "json",
    }, timeout=15)
    resp.raise_for_status()
    return resp.json().get("search", [])


def wikidata_entity(qid: str) -> dict | None:
    """Holt die vollständigen Entity-Daten."""
    resp = SESSION.get(WIKIDATA_ENTITY.format(qid=qid), timeout=15)
    resp.raise_for_status()
    data = resp.json()
    entities = data.get("entities", {})
    return entities.get(qid)


def _claim_time_value(entity: dict, prop: str) -> str | None:
    """Extrahiert ein Datum aus einem Wikidata-Claim (P569, P570 etc.)."""
    claims = entity.get("claims", {})
    if prop not in claims:
        return None
    for claim in claims[prop]:
        snak = claim.get("mainsnak", {})
        dv = snak.get("datavalue", {})
        if dv.get("type") == "time":
            raw = dv["value"]["time"]
            m = re.match(r"\+?(\d{4}-\d{2}-\d{2})", raw)
            if m:
                return m.group(1)
    return None


def _claim_year(entity: dict, prop: str) -> int | None:
    """Extrahiert ein Jahr aus einem Wikidata-Claim."""
    d = _claim_time_value(entity, prop)
    if d:
        try:
            return int(d[:4])
        except ValueError:
            return None
    return None


def _is_human(entity: dict) -> bool:
    """Prüft ob P31 (instance of) Q5 (human) enthält."""
    claims = entity.get("claims", {})
    for claim in claims.get("P31", []):
        dv = claim.get("mainsnak", {}).get("datavalue", {})
        if dv.get("type") == "wikibase-entityid":
            if dv["value"].get("id") == "Q5":
                return True
    return False


def _get_members(entity: dict) -> list[str]:
    """Extrahiert Mitglieder-QIDs aus P527 (has part)."""
    claims = entity.get("claims", {})
    members = []
    for claim in claims.get("P527", []):
        dv = claim.get("mainsnak", {}).get("datavalue", {})
        if dv.get("type") == "wikibase-entityid":
            members.append(dv["value"]["id"])
    for claim in claims.get("P463", []):
        dv = claim.get("mainsnak", {}).get("datavalue", {})
        if dv.get("type") == "wikibase-entityid":
            members.append(dv["value"]["id"])
    return members


def _entity_label(entity: dict) -> str:
    """Gibt das deutsche oder englische Label zurück."""
    labels = entity.get("labels", {})
    for lang in ("de", "en"):
        if lang in labels:
            return labels[lang]["value"]
    return "?"


def _best_match(name: str, results: list[dict]) -> dict | None:
    """Wählt den besten Treffer: Musiker/Band bevorzugen."""
    if not results:
        return None
    name_lower = name.lower().strip()
    for r in results:
        if r.get("label", "").lower().strip() == name_lower:
            desc = (r.get("description") or "").lower()
            if any(k in desc for k in ("musik", "sänger", "singer", "band", "group",
                                        "rapper", "songwriter", "musician", "dj")):
                return r
    for r in results:
        if r.get("label", "").lower().strip() == name_lower:
            return r
    return results[0] if len(results) == 1 else None


def lookup_wikidata(name: str) -> dict:
    """Gibt ein Dict mit Wikidata-Daten zurück oder leeres Dict."""
    results = wikidata_search(name)
    match = _best_match(name, results)
    if not match:
        return {"ambiguous": len(results) > 1, "candidates": len(results)}

    qid = match["id"]
    entity = wikidata_entity(qid)
    if not entity:
        return {}

    is_person = _is_human(entity)
    data = {
        "qid": qid,
        "url": f"https://www.wikidata.org/wiki/{qid}",
        "typ": "Person" if is_person else "Band",
        "geburtsdatum": _claim_time_value(entity, "P569") if is_person else None,
        "todesdatum": _claim_time_value(entity, "P570") if is_person else None,
        "gruendungsjahr": _claim_year(entity, "P571") if not is_person else None,
        "members_qids": _get_members(entity) if not is_person else [],
        "label": _entity_label(entity),
    }
    return data


# ---------------------------------------------------------------------------
# MusicBrainz
# ---------------------------------------------------------------------------

MB_API = "https://musicbrainz.org/ws/2/artist"


def _mb_rate_limit():
    global _last_mb_request
    elapsed = time.monotonic() - _last_mb_request
    if elapsed < MUSICBRAINZ_RATE_LIMIT:
        time.sleep(MUSICBRAINZ_RATE_LIMIT - elapsed)
    _last_mb_request = time.monotonic()


def lookup_musicbrainz(name: str) -> dict:
    """Sucht den Künstler in MusicBrainz."""
    _mb_rate_limit()
    resp = SESSION.get(MB_API, params={
        "query": f'artist:"{name}"',
        "fmt": "json",
        "limit": 5,
    }, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    artists = data.get("artists", [])
    if not artists:
        return {}

    best = None
    name_lower = name.lower().strip()
    for a in artists:
        if a.get("name", "").lower().strip() == name_lower:
            best = a
            break
    if not best:
        if artists[0].get("score", 0) >= 90:
            best = artists[0]
        else:
            return {"ambiguous": True}

    ls = best.get("life-span", {})
    begin = ls.get("begin")
    end = ls.get("end") if not ls.get("ended") is False else None
    if ls.get("ended") and "end" in ls:
        end = ls["end"]

    typ = best.get("type", "")
    is_person = typ.lower() == "person" if typ else None

    result = {
        "mbid": best["id"],
        "url": f"https://musicbrainz.org/artist/{best['id']}",
        "typ": "Person" if is_person is True else ("Band" if is_person is False else None),
    }

    if is_person is True or is_person is None:
        result["geburtsdatum"] = begin
        result["todesdatum"] = end
    if is_person is False:
        if begin:
            m = re.match(r"(\d{4})", begin)
            result["gruendungsjahr"] = int(m.group(1)) if m else None
        else:
            result["gruendungsjahr"] = None

    return result


# ---------------------------------------------------------------------------
# Abgleich & Verifikation
# ---------------------------------------------------------------------------

def _dates_match(d1: str | None, d2: str | None) -> bool | None:
    """Vergleicht zwei Datumsstrings. None = keine Aussage."""
    if d1 is None or d2 is None:
        return None
    return d1[:10] == d2[:10]


def merge_and_verify(wd: dict, mb: dict) -> tuple[dict, list[str]]:
    """Führt Wikidata- und MusicBrainz-Daten zusammen.

    Returns (merged_data, list_of_conflicts).
    """
    merged = {}
    conflicts = []

    for field in ("typ", "geburtsdatum", "todesdatum", "gruendungsjahr"):
        wd_val = wd.get(field)
        mb_val = mb.get(field)

        if wd_val is not None and mb_val is not None:
            if field in ("geburtsdatum", "todesdatum"):
                match = _dates_match(wd_val, mb_val)
            else:
                match = (str(wd_val) == str(mb_val))

            if match:
                merged[field] = wd_val
            elif match is False:
                conflicts.append(
                    f"  - **{field}**: Wikidata=`{wd_val}` vs. MusicBrainz=`{mb_val}`"
                )
                merged[field] = wd_val
        elif wd_val is not None:
            merged[field] = wd_val
        elif mb_val is not None:
            merged[field] = mb_val

    merged["verifiziert"] = 1 if not conflicts and wd.get("qid") and mb.get("mbid") else 0
    merged["wikidata_id"] = wd.get("qid")
    merged["musicbrainz_id"] = mb.get("mbid")

    quellen = []
    if wd.get("url"):
        quellen.append(wd["url"])
    if mb.get("url"):
        quellen.append(mb["url"])
    merged["quellen"] = json.dumps(quellen)

    return merged, conflicts


# ---------------------------------------------------------------------------
# Member-Vorschläge
# ---------------------------------------------------------------------------

def fetch_member_names(qids: list[str], max_count: int = 3) -> list[dict]:
    """Holt Labels für Mitglieder-QIDs (max. max_count)."""
    members = []
    for qid in qids[:max_count * 2]:
        entity = wikidata_entity(qid)
        if entity and _is_human(entity):
            members.append({
                "qid": qid,
                "name": _entity_label(entity),
                "url": f"https://www.wikidata.org/wiki/{qid}",
            })
        if len(members) >= max_count:
            break
        time.sleep(0.2)
    return members


# ---------------------------------------------------------------------------
# Hauptlogik
# ---------------------------------------------------------------------------

def run(nachpflege: bool = False, limit: int | None = None):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    heute = date.today().isoformat()

    if nachpflege:
        cutoff = (date.today() - timedelta(days=7)).isoformat()
        rows = conn.execute(
            """SELECT id, name, prioritaet, wikidata_id, musicbrainz_id
               FROM kuenstler
               WHERE last_seen >= ?
                 AND (wikidata_id IS NULL OR musicbrainz_id IS NULL
                      OR geburtsdatum IS NULL)
               ORDER BY
                 CASE prioritaet WHEN 'A' THEN 1 WHEN 'B' THEN 2 ELSE 3 END,
                 name""",
            (cutoff,),
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT id, name, prioritaet, wikidata_id, musicbrainz_id
               FROM kuenstler
               WHERE wikidata_id IS NULL
               ORDER BY
                 CASE prioritaet WHEN 'A' THEN 1 WHEN 'B' THEN 2 ELSE 3 END,
                 name""",
        ).fetchall()

    if limit:
        rows = rows[:limit]

    conflict_lines = [
        "# Stammdaten-Konflikte\n",
        f"Generiert: {heute}\n",
        "Bitte manuell prüfen und in der DB korrigieren.\n\n",
    ]
    member_lines = [
        "# Mitglieder-Vorschläge\n",
        f"Generiert: {heute}\n",
        "Bitte kuratieren: gewünschte Zeilen mit [x] markieren, "
        "dann `stammdaten.py --import-mitglieder` ausführen.\n\n",
    ]
    has_conflicts = False
    has_members = False

    print(f"Verarbeite {len(rows)} Künstler …")

    for i, row in enumerate(rows):
        kid, name = row["id"], row["name"]
        print(f"  [{i+1}/{len(rows)}] {name} …", end=" ", flush=True)

        try:
            wd = lookup_wikidata(name)
        except Exception as e:
            print(f"Wikidata-Fehler: {e}")
            wd = {}

        if wd.get("ambiguous"):
            conflict_lines.append(f"### {name} (ID {kid})\n")
            conflict_lines.append(f"- Wikidata: mehrdeutig ({wd.get('candidates', '?')} Treffer)\n")
            conflict_lines.append(f"- Bitte manuell suchen: "
                                  f"https://www.wikidata.org/w/index.php?search={quote(name)}\n\n")
            has_conflicts = True
            print("mehrdeutig (Wikidata)")
            continue

        try:
            mb = lookup_musicbrainz(name)
        except Exception as e:
            print(f"MusicBrainz-Fehler: {e}")
            mb = {}

        if mb.get("ambiguous"):
            conflict_lines.append(f"### {name} (ID {kid})\n")
            conflict_lines.append(f"- MusicBrainz: mehrdeutig\n")
            if wd.get("qid"):
                conflict_lines.append(f"- Wikidata: [{wd['qid']}]({wd.get('url', '')})\n")
            conflict_lines.append(f"- Bitte manuell suchen: "
                                  f"https://musicbrainz.org/search?query={quote(name)}&type=artist\n\n")
            has_conflicts = True
            print("mehrdeutig (MusicBrainz)")
            continue

        merged, conflicts = merge_and_verify(wd, mb)

        if conflicts:
            has_conflicts = True
            conflict_lines.append(f"### {name} (ID {kid})\n")
            for c in conflicts:
                conflict_lines.append(c + "\n")
            if wd.get("url"):
                conflict_lines.append(f"  - Wikidata: {wd['url']}\n")
            if mb.get("url"):
                conflict_lines.append(f"  - MusicBrainz: {mb['url']}\n")
            conflict_lines.append("\n")

        conn.execute(
            """UPDATE kuenstler SET
                 typ = COALESCE(?, typ),
                 geburtsdatum = COALESCE(?, geburtsdatum),
                 todesdatum = COALESCE(?, todesdatum),
                 gruendungsjahr = COALESCE(?, gruendungsjahr),
                 wikidata_id = COALESCE(?, wikidata_id),
                 musicbrainz_id = COALESCE(?, musicbrainz_id),
                 quellen = ?,
                 verifiziert = CASE WHEN ? = 1 THEN 1 ELSE verifiziert END
               WHERE id = ?""",
            (
                merged.get("typ"),
                merged.get("geburtsdatum"),
                merged.get("todesdatum"),
                merged.get("gruendungsjahr"),
                merged.get("wikidata_id"),
                merged.get("musicbrainz_id"),
                merged.get("quellen"),
                merged.get("verifiziert", 0),
                kid,
            ),
        )

        if wd.get("members_qids"):
            try:
                members = fetch_member_names(wd["members_qids"])
            except Exception:
                members = []
            if members:
                has_members = True
                member_lines.append(f"### {name} (ID {kid})\n")
                for m in members:
                    member_lines.append(
                        f"- [ ] {m['name']} — [{m['qid']}]({m['url']})\n"
                    )
                member_lines.append("\n")

        status = "✓ verifiziert" if merged.get("verifiziert") else "teilweise"
        print(status)

    conn.commit()
    conn.close()

    if has_conflicts:
        conflict_path = REVIEW_DIR / "stammdaten_konflikte.md"
        conflict_path.write_text("".join(conflict_lines), encoding="utf-8")
        print(f"\nKonflikte: {conflict_path}")

    if has_members:
        member_path = REVIEW_DIR / "mitglieder_vorschlag.md"
        member_path.write_text("".join(member_lines), encoding="utf-8")
        print(f"Mitglieder-Vorschläge: {member_path}")

    print("Stammdaten-Abgleich abgeschlossen.")


def main():
    parser = argparse.ArgumentParser(description="Stammdaten aus Wikidata/MusicBrainz abgleichen")
    parser.add_argument("--nachpflege", action="store_true",
                        help="Nur neue/unvollständige Künstler der letzten 7 Tage")
    parser.add_argument("--limit", type=int, default=None,
                        help="Maximal N Künstler verarbeiten (für Tests)")
    args = parser.parse_args()
    run(nachpflege=args.nachpflege, limit=args.limit)


if __name__ == "__main__":
    main()
