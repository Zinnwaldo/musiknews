#!/bin/bash
# Einmaliges Komplett-Setup für das Musiknews-Tool auf dem Mac Mini.
#
# Aufruf:  ./setup.sh
#
# Macht alles in einem Rutsch:
#   1. venv + Abhängigkeiten
#   2. neuesten Hitlisten-Export aus ~/Downloads importieren
#   3. Prioritäten setzen
#   4. Stammdaten von Wikidata/MusicBrainz holen (~15 Min)
#   5. Kalender + Digest erzeugen und im Browser öffnen
#   6. Cron-Automatik einrichten
#
# Danach ist kein Terminal mehr nötig: neue Hitliste einfach in
# ~/Downloads legen, alles Weitere passiert automatisch.

set -u
cd "$(dirname "$0")"

WATCH_DIR="${MUSIKNEWS_WATCH_DIR:-$HOME/Downloads}"

echo "════════════════════════════════════════════════"
echo " Musiknews-Tool — Komplett-Setup"
echo "════════════════════════════════════════════════"

# --- 1. venv + Abhängigkeiten ---
echo
echo "[1/6] Python-Umgebung …"
if [ ! -x venv/bin/python3 ]; then
  python3 -m venv venv || { echo "FEHLER: venv konnte nicht erstellt werden."; exit 1; }
fi
venv/bin/pip install -q -r requirements.txt || { echo "FEHLER: pip install fehlgeschlagen."; exit 1; }
PY="venv/bin/python3"
echo "      OK"

# --- 2. Hitliste importieren ---
echo
echo "[2/6] Hitlisten-Import …"
NEWEST=$(ls -t "$WATCH_DIR"/SenderHitliste*.xlsx 2>/dev/null | head -1)
if [ -z "$NEWEST" ]; then
  if [ -f kuenstler.db ]; then
    echo "      Kein Export in $WATCH_DIR gefunden — nutze vorhandene Datenbank."
  else
    echo "FEHLER: Keine SenderHitliste*.xlsx in $WATCH_DIR und keine Datenbank vorhanden."
    echo "Bitte den Export nach $WATCH_DIR legen und setup.sh erneut starten."
    exit 1
  fi
else
  echo "      Importiere: $NEWEST"
  "$PY" import_hitliste.py "$NEWEST" || exit 1
  STAMP=$(stat -c "%n %Y" "$NEWEST" 2>/dev/null || stat -f "%N %m" "$NEWEST")
  grep -qxF "$STAMP" .imported 2>/dev/null || echo "$STAMP" >> .imported
fi

# --- 3. Prioritäten ---
echo
echo "[3/6] Prioritäten setzen …"
"$PY" set_priorities.py || exit 1

# --- 4. Stammdaten ---
echo
echo "[4/6] Stammdaten von Wikidata + MusicBrainz (dauert ~15 Min) …"
"$PY" stammdaten.py || echo "      WARNUNG: Stammdaten-Lauf mit Fehlern — Details oben."

# --- 5. Kalender + Digest ---
echo
echo "[5/6] Kalender + Digest …"
"$PY" kalender.py || exit 1
"$PY" digest.py --no-encrypt --no-deploy || exit 1

# --- 6. Cron ---
echo
echo "[6/6] Cron-Automatik einrichten …"
./install_cron.sh

echo
echo "════════════════════════════════════════════════"
echo " Setup abgeschlossen!"
echo "════════════════════════════════════════════════"
echo
echo " Ab jetzt läuft alles automatisch:"
echo "   • Täglich 5:15 Uhr: Kalender, Recherche, Digest"
echo "   • Montags 9:00 Uhr: neuer Export aus $WATCH_DIR"
echo
echo " Dein wöchentlicher Handgriff: Hitlisten-Export nach"
echo " $WATCH_DIR herunterladen — mehr nicht."
echo
echo " Bitte noch prüfen (öffnet sich gleich):"
echo "   • Digest (docs/index.html)"
echo "   • review/stammdaten_konflikte.md  — Konflikte entscheiden"
echo "   • review/mitglieder_vorschlag.md  — Frontleute ankreuzen"

# Ergebnisse öffnen (nur auf macOS)
if command -v open >/dev/null 2>&1; then
  open docs/index.html 2>/dev/null
  [ -f review/stammdaten_konflikte.md ] && open review/stammdaten_konflikte.md 2>/dev/null
  [ -f review/mitglieder_vorschlag.md ] && open review/mitglieder_vorschlag.md 2>/dev/null
fi
