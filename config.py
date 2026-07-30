"""Zentrale Konfiguration für das Musiknews-Tool."""

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "kuenstler.db"
REVIEW_DIR = BASE_DIR / "review"
DOCS_DIR = BASE_DIR / "docs"

# --- Kalender-Engine (Phase 3) ---
KALENDER_FENSTER_TAGE = 10

# Lebende Personen: nur runde Geburtstage (teilbar durch RUND_TEILER)
RUND_TEILER = 5
# 10er-Jubiläen hervorheben
HERVORHEBEN_TEILER = 10
# Verstorbene: 1. Todestag immer anzeigen
ERSTER_TODESTAG = True
# Song-Jubiläen: welche runden Jahre anzeigen
SONG_JUBILAEEN = [25, 30, 40, 50, 60, 75]

# --- Recherche-Agent (Phase 4) ---
TIER_A_TAEGLICH = True
TIER_B_PRO_TAG = 55

# Tourtermine in MV und Umgebung werden im Digest hervorgehoben
MV_STAEDTE = [
    "Rostock", "Schwerin", "Neubrandenburg", "Stralsund",
    "Greifswald", "Hamburg", "Lübeck", "Berlin",
]

# Claude Code CLI (läuft über Max-Abo, kein API-Key nötig)
CLAUDE_CMD = "claude"
CLAUDE_TIMEOUT = 300  # Sekunden pro Künstler (Websuche braucht Zeit)
RECHERCHE_WORKERS = 3  # parallele Recherchen (mehr = schneller, aber mehr Abo-Last)

# Modell-Steuerung: A-Stars bekommen das starke Modell, B/C das sparsame.
# Schont das Max-Abo erheblich — Haiku verbraucht nur einen Bruchteil.
RECHERCHE_MODEL_A = "claude-sonnet-5"
RECHERCHE_MODEL_BC = "claude-haiku-4-5-20251001"

# --- MusicBrainz (Phase 2) ---
MUSICBRAINZ_USER_AGENT = "MusikNewsTool/1.0 (stotco@googlemail.com)"
MUSICBRAINZ_RATE_LIMIT = 1.0  # Sekunden zwischen Requests

# --- StatiCrypt (Phase 5) ---
STATICRYPT_PASSWORD_ENV = "MUSIKNEWS_PASSWORD"  # Umgebungsvariable

# --- GitHub Pages Deploy ---
PAGES_REPO_ENV = "MUSIKNEWS_PAGES_REPO"  # z.B. "user/musiknews-site"
PAGES_PAT_ENV = "MUSIKNEWS_PAT"
