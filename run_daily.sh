#!/bin/bash
# Täglicher Lauf: Kalender → Recherche → Digest
# Wird per Cron um 5:15 Uhr gestartet (siehe install_cron.sh).

set -u
cd "$(dirname "$0")"

mkdir -p logs
LOG="logs/daily_$(date +%Y-%m-%d).log"

# Homebrew-Pfade für claude/staticrypt/npx (Cron hat minimalen PATH)
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

PY="venv/bin/python3"
[ -x "$PY" ] || PY="python3"

{
  echo "=== Täglicher Lauf $(date '+%Y-%m-%d %H:%M:%S') ==="
  "$PY" kalender.py    && echo "--- kalender OK"   || echo "!!! kalender FEHLER"
  "$PY" recherche.py   && echo "--- recherche OK"  || echo "!!! recherche FEHLER"
  "$PY" digest.py      && echo "--- digest OK"     || echo "!!! digest FEHLER"
  echo "=== Ende $(date '+%H:%M:%S') ==="
} >> "$LOG" 2>&1

# Logs älter als 30 Tage löschen
find logs -name "daily_*.log" -mtime +30 -delete 2>/dev/null
