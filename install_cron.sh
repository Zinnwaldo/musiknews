#!/bin/bash
# Richtet die Cron-Jobs für das Musiknews-Tool ein (idempotent).
# Aufruf: ./install_cron.sh

set -eu
DIR="$(cd "$(dirname "$0")" && pwd)"

chmod +x "$DIR/run_daily.sh" "$DIR/run_weekly.sh"

MARKER="# musiknews-tool"
DAILY="15 5 * * * $DIR/run_daily.sh $MARKER"
WEEKLY="0 9 * * 1 $DIR/run_weekly.sh $MARKER"

# Bestehende musiknews-Einträge entfernen, neue anhängen
( crontab -l 2>/dev/null | grep -v "$MARKER" || true
  echo "$DAILY"
  echo "$WEEKLY"
) | crontab -

echo "Cron-Jobs installiert:"
crontab -l | grep "$MARKER"
echo
echo "Täglich  5:15 Uhr → Kalender, Recherche, Digest"
echo "Montags  9:00 Uhr → Hitlisten-Import (aus ~/Downloads) + Stammdaten-Nachpflege"
echo "Logs: $DIR/logs/"
