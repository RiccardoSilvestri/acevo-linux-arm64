#!/bin/sh
set -e
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
W=${DEMO_DIR:-$(mktemp -d)}
PORT=${DEMO_PORT:-8099}
mkdir -p "$W/dash-data/lapwatch" "$W/logs" "$W/srv"
cat > "$W/srv/season_def.json" <<EOF
{"game_type":"GameModeType_HOTLAP","game_config":{"practice_duration":7200},"event":{"track":"Monza","layout":"GP","event_name":"GP Time Attack","track_length":5793}}
EOF
echo '{"server_name":"Demo server","max_players":16}' > "$W/srv/server_config.json"
echo '{"cars":[]}' > "$W/srv/cars.json"
NOW=$(date -u +"%Y-%m-%d %H:%M:%S")
cat > "$W/logs/server.log" <<EOF
[$NOW.000] [server] [info] Listening to UDP port 9600
[$NOW.100] [server] [info] connecting gamecar 4057390c195fb408-03e3fe3e4dc69d85 (Demo Driver | 76561198000000001)
[$NOW.200] [gameplay] [info] 76561198000000001 connected (true) on car ks_porsche_992_gt3_r_rennsport, with new carId 4057390c195fb408-03e3fe3e4dc69d85
EOF
cd "$ROOT"
python3 lapwatch/lapwatch.py --pcap tests/fixtures/session.pcap --serve --loop --speed "${DEMO_SPEED:-1}" \
  --out "$W/dash-data/lapwatch" --season "$W/srv/season_def.json" > "$W/lapwatch.log" 2>&1 &
sleep 1
echo "Demo running on http://127.0.0.1:$PORT (data in $W)"
PORT=$PORT REFRESH_S=0.5 ACE_API=http://127.0.0.1:1/ ACE_LOG="$W/logs/server.log" ACE_CONFIG="$W/srv/server_config.json" \
  ACE_SEASON="$W/srv/season_def.json" ACE_CARS="$W/srv/cars.json" ACE_DB="$W/dash-data/laptimes.json" \
  ACE_HISTORY="$W/dash-data/laps_history.jsonl" ACE_LAPWATCH_DIR="$W/dash-data/lapwatch" \
  ACE_BLOCKED="$W/dash-data/blocked.json" ACE_REMOVED="$W/dash-data/removed.json" \
  exec python3 dashboard/app.py
