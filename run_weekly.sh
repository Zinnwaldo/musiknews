#!/bin/bash
# Wöchentlicher Lauf: neuesten Hitlisten-Export importieren + Stammdaten-Nachpflege
# Wird per Cron montags 9:00 Uhr gestartet (siehe install_cron.sh).
#
# Sucht die neueste Datei "SenderHitliste*.xlsx" im Download-Ordner.
# Bereits importierte Dateien werden übersprungen (Merkliste .imported).

set -u
cd "$(dirname "$0")"

WATCH_DIR="${MUSIKNEWS_WATCH_DIR:-$HOME/Downloads}"

mkdir -p logs
LOG="logs/weekly_$(date +%Y-%m-%d).log"

export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

PY="venv/bin/python3"
[ -x "$PY" ] || PY="python3"

{
  echo "=== Wöchentlicher Lauf $(date '+%Y-%m-%d %H:%M:%S') ==="
  # Code-Updates automatisch holen (nur fast-forward, gefahrlos)
  git pull -q --ff-only 2>/dev/null && echo "--- git pull OK" || echo "--- git pull übersprungen"

  if [ -f PAUSE ]; then
    echo "PAUSE-Datei vorhanden — Lauf übersprungen."
    exit 0
  fi

  # Neueste SenderHitliste-Datei finden (nach Änderungsdatum)
  NEWEST=$(ls -t "$WATCH_DIR"/SenderHitliste*.xlsx 2>/dev/null | head -1)

  if [ -z "$NEWEST" ]; then
    echo "Keine SenderHitliste*.xlsx in $WATCH_DIR gefunden — Import übersprungen."
  else
    # Schon importiert? (Dateiname + Änderungszeit als Kennung)
    STAMP=$(stat -c "%n %Y" "$NEWEST" 2>/dev/null || stat -f "%N %m" "$NEWEST")
    if grep -qxF "$STAMP" .imported 2>/dev/null; then
      echo "Bereits importiert: $NEWEST — übersprungen."
    else
      echo "Importiere: $NEWEST"
      if "$PY" import_hitliste.py "$NEWEST"; then
        echo "$STAMP" >> .imported
        echo "--- Import OK"
      else
        echo "!!! Import FEHLER"
      fi
    fi
  fi

  # Stammdaten-Nachpflege (neue Künstler der Woche)
  "$PY" stammdaten.py --nachpflege && echo "--- Nachpflege OK" || echo "!!! Nachpflege FEHLER"

  echo "=== Ende $(date '+%H:%M:%S') ==="
} >> "$LOG" 2>&1

find logs -name "weekly_*.log" -mtime +90 -delete 2>/dev/null
