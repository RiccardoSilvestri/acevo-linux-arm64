#!/bin/bash
set -e

log() { echo "[DOWNLOAD] $*"; }

STEAM_USER="${STEAM_USER:?STEAM_USER is not set in config/game.env}"
STEAM_PASS="${STEAM_PASS:?STEAM_PASS is not set in config/game.env}"
ACE_APP_ID="${ACE_APP_ID:-4564210}"
SERVER_DIR="${SERVER_DIR:-/data/server}"
DEPOT_DIR="${DEPOT_DIR:-/opt/depotdownloader}"

mkdir -p "$SERVER_DIR"

log "Downloading app $ACE_APP_ID with DepotDownloader as $STEAM_USER into $SERVER_DIR"
log "If Steam asks for a Steam Guard code, attach to the container and type it here."

"$DEPOT_DIR/DepotDownloader" \
    -app "$ACE_APP_ID" \
    -username "$STEAM_USER" \
    -password "$STEAM_PASS" \
    -dir "$SERVER_DIR" \
    -validate

echo "App:$ACE_APP_ID downloaded on $(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$SERVER_DIR/.downloaded"

log "Download complete. Executables found:"
find "$SERVER_DIR" -name "*.exe" 2>/dev/null | head -20
