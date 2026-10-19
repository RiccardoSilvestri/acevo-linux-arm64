#!/bin/bash
set -e

log() { echo "[SERVER] $*"; }

SERVER_DIR="${SERVER_DIR:-/data/server}"
LOG_DIR="${LOG_DIR:-/data/logs}"
TEMPLATE_DIR="${TEMPLATE_DIR:-/config}"
WINEPREFIX="${WINEPREFIX:-/wine}"
ACE_EXE_NAME="${ACE_EXE_NAME:-AssettoCorsaEVOServer.exe}"
CONFIG_JSON_PATH="$SERVER_DIR/server_config.json"
SEASON_JSON_PATH="$SERVER_DIR/season_def.json"

json_escape() { printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g'; }
sed_escape() { printf '%s' "$1" | sed -e 's/[\/&|]/\\&/g'; }

install_template() {
    local name="$1" dest="$2" src=""
    [ -f "$dest" ] && return 0
    for cand in "$TEMPLATE_DIR/$name.json" "$TEMPLATE_DIR/$name.example.json"; do
        [ -f "$cand" ] && src="$cand" && break
    done
    if [ -z "$src" ]; then
        log "ERROR: $dest is missing and no template was found in $TEMPLATE_DIR"
        exit 1
    fi
    log "Creating $dest from $src"
    sed -e "s|__SERVER_NAME__|$(sed_escape "$(json_escape "${ACE_SERVER_NAME:-ACE Server}")")|" \
        -e "s|__DRIVER_PASSWORD__|$(sed_escape "$(json_escape "${ACE_DRIVER_PASSWORD:-}")")|" \
        -e "s|__ADMIN_PASSWORD__|$(sed_escape "$(json_escape "${ACE_ADMIN_PASSWORD:-}")")|" \
        -e "s|__SPECTATOR_PASSWORD__|$(sed_escape "$(json_escape "${ACE_SPECTATOR_PASSWORD:-}")")|" \
        -e "s|\"__MAX_PLAYERS__\"|${ACE_MAX_PLAYERS:-16}|" \
        -e "s|\"__GAME_PORT__\"|${ACE_PORT:-9600}|g" \
        -e "s|\"__HTTP_PORT__\"|${ACE_HTTP_PORT:-8000}|" \
        "$src" > "$dest"
    [ -n "${CONFIG_OWNER:-}" ] && chown "$CONFIG_OWNER" "$dest" || true
}

SERVER_EXE=$(find "$SERVER_DIR" -iname "$ACE_EXE_NAME" -type f 2>/dev/null | head -1)
if [ -z "$SERVER_EXE" ]; then
    log "ERROR: $ACE_EXE_NAME not found in $SERVER_DIR. Run with ACE_MODE=download to fetch it again."
    exit 1
fi

install_template server_config "$CONFIG_JSON_PATH"
install_template season_def "$SEASON_JSON_PATH"

log "Executable: $SERVER_EXE"
log "Wine prefix: $WINEPREFIX · game port: ${ACE_PORT:-9600}"

cd "$(dirname "$SERVER_EXE")"

mkdir -p "$LOG_DIR"
[ -f "$LOG_DIR/server.log" ] && mv -f "$LOG_DIR/server.log" "$LOG_DIR/server.log.old"
exec > >(tee -a "$LOG_DIR/server.log") 2>&1

export WINEESYNC="${WINEESYNC:-1}"
export WINEDEBUG="${WINEDEBUG:--all}"
export WINEDLLOVERRIDES="${WINEDLLOVERRIDES:-explorer.exe=d}"
export BOX64_DYNAREC_STRONGMEM="${BOX64_DYNAREC_STRONGMEM:-3}"
export BOX64_LOG="${BOX64_LOG:-0}"

to_wine_path() { printf 'Z:%s' "$1" | sed 's|/|\\|g'; }

exec wine "$(basename "$SERVER_EXE")" \
  -configjson "$(to_wine_path "$CONFIG_JSON_PATH")" \
  -seasonjson "$(to_wine_path "$SEASON_JSON_PATH")" \
  ${ACE_EXTRA_ARGS:-}
