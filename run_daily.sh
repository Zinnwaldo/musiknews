#!/bin/bash
# Nächtlicher Lauf: Kalender → Recherche (dauert mehrere Stunden)
# Wird per Cron um 0:15 Uhr gestartet (siehe install_cron.sh).
# Der Digest wird separat um 5:15 Uhr von run_digest.sh gebaut.

set -u
cd "$(dirname "$0")"

mkdir -p logs
LOG="logs/daily_$(date +%Y-%m-%d).log"

# Homebrew-Pfade für claude/staticrypt/npx (Cron hat minimalen PATH)
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

PY="venv/bin/python3"
[ -x "$PY" ] || PY="python3"

{
  echo "=== Nächtlicher Lauf $(date '+%Y-%m-%d %H:%M:%S') ==="
  # Code-Updates automatisch holen (nur fast-forward, gefahrlos)
  git pull -q --ff-only 2>/dev/null && echo "--- git pull OK" || echo "--- git pull übersprungen"
  "$PY" kalender.py    && echo "--- kalender OK"   || echo "!!! kalender FEHLER"
  "$PY" recherche.py   && echo "--- recherche OK"  || echo "!!! recherche FEHLER"
  echo "=== Ende $(date '+%H:%M:%S') ==="
} >> "$LOG" 2>&1

# Logs älter als 30 Tage löschen
find logs -name "daily_*.log" -mtime +30 -delete 2>/dev/null
