#!/bin/bash
# Richtet die Cron-Jobs für das Musiknews-Tool ein (idempotent).
# Aufruf: ./install_cron.sh

set -eu
DIR="$(cd "$(dirname "$0")" && pwd)"

chmod +x "$DIR/run_daily.sh" "$DIR/run_digest.sh" "$DIR/run_weekly.sh"

MARKER="# musiknews-tool"
NIGHTLY="15 0 * * * $DIR/run_daily.sh $MARKER"
DIGEST="15 5 * * * $DIR/run_digest.sh $MARKER"
WEEKLY="0 9 * * 1 $DIR/run_weekly.sh $MARKER"

# Bestehende musiknews-Einträge entfernen, neue anhängen
( crontab -l 2>/dev/null | grep -v "$MARKER" || true
  echo "$NIGHTLY"
  echo "$DIGEST"
  echo "$WEEKLY"
) | crontab -

echo "Cron-Jobs installiert:"
crontab -l | grep "$MARKER"
echo
echo "Nachts   0:15 Uhr → Kalender + Recherche (dauert mehrere Stunden)"
echo "Morgens  5:15 Uhr → Digest bauen und veröffentlichen"
echo "Montags  9:00 Uhr → Hitlisten-Import (aus ~/Downloads) + Stammdaten-Nachpflege"
echo "Logs: $DIR/logs/"
