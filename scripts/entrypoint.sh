#!/bin/bash
set -e

ACE_MODE="${ACE_MODE:-auto}"
SERVER_DIR="${SERVER_DIR:-/data/server}"
MARKER="$SERVER_DIR/.downloaded"

log() { echo "[ACE] $*"; }

log "Assetto Corsa EVO dedicated server · ARM64 via Box64 + Wine · mode: $ACE_MODE"

case "$ACE_MODE" in
  download)
    /scripts/download-server.sh
    ;;
  start)
    /scripts/start-server.sh
    ;;
  auto)
    if [ ! -f "$MARKER" ]; then
      log "Server files not found, downloading..."
      /scripts/download-server.sh
    else
      log "Server files present ($(cat "$MARKER"))"
    fi
    /scripts/start-server.sh
    ;;
  *)
    log "ERROR: invalid ACE_MODE='$ACE_MODE'. Use: download | start | auto"
    exit 1
    ;;
esac
