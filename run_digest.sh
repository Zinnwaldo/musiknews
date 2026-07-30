#!/bin/bash
# Digest-Lauf: baut die Webseite aus den Ergebnissen der Nacht.
# Wird per Cron um 5:15 Uhr gestartet (siehe install_cron.sh).

set -u
cd "$(dirname "$0")"

mkdir -p logs
LOG="logs/daily_$(date +%Y-%m-%d).log"

export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

PY="venv/bin/python3"
[ -x "$PY" ] || PY="python3"

{
  echo "=== Digest-Lauf $(date '+%Y-%m-%d %H:%M:%S') ==="
  "$PY" digest.py && echo "--- digest OK" || echo "!!! digest FEHLER"
  echo "=== Ende $(date '+%H:%M:%S') ==="
} >> "$LOG" 2>&1
