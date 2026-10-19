#!/bin/sh
set -e
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
W=$(mktemp -d)
PORT=${E2E_PORT:-8099}
mkdir -p "$W/dash-data/lapwatch" "$W/logs" "$W/srv"
cat > "$W/srv/season_def.json" <<EOF
{"game_type":"GameModeType_HOTLAP","game_config":{"practice_duration":7200},"event":{"track":"Monza","layout":"GP","event_name":"GP Time Attack","track_length":5793}}
EOF
echo '{"server_name":"E2E","max_players":16}' > "$W/srv/server_config.json"
echo '{"cars":[]}' > "$W/srv/cars.json"
cat > "$W/logs/server.log" <<EOF
[2026-01-01 00:00:01.000] [server] [info] Listening to UDP port 9600
[2026-01-01 00:00:02.000] [server] [info] connecting gamecar 4057390c195fb408-03e3fe3e4dc69d85 (Test Driver | 76561198000000001)
[2026-01-01 00:00:03.000] [gameplay] [info] 76561198000000001 connected (true) on car ks_porsche_992_gt3_r_rennsport, with new carId 4057390c195fb408-03e3fe3e4dc69d85
EOF
cd "$ROOT"
python3 lapwatch/lapwatch.py --pcap tests/fixtures/session.pcap --serve --speed "${E2E_SPEED:-8}" \
  --out "$W/dash-data/lapwatch" --season "$W/srv/season_def.json" > "$W/lapwatch.log" 2>&1 &
LW_PID=$!
sleep 1
PORT=$PORT REFRESH_S=0.5 ACE_API=http://127.0.0.1:1/ ACE_LOG="$W/logs/server.log" ACE_CONFIG="$W/srv/server_config.json" \
  ACE_SEASON="$W/srv/season_def.json" ACE_CARS="$W/srv/cars.json" ACE_DB="$W/dash-data/laptimes.json" \
  ACE_HISTORY="$W/dash-data/laps_history.jsonl" ACE_LAPWATCH_DIR="$W/dash-data/lapwatch" \
  ACE_BLOCKED="$W/dash-data/blocked.json" ACE_REMOVED="$W/dash-data/removed.json" \
  python3 dashboard/app.py > "$W/dash.log" 2>&1 &
DASH_PID=$!
trap 'kill $LW_PID $DASH_PID 2>/dev/null; rm -rf "$W"' EXIT
sleep 2
set +e
E2E_PORT=$PORT python3 tests/e2e/e2e_client.py
RC=$?
echo "--- lapwatch.log"; tail -5 "$W/lapwatch.log"
echo "--- dashboard.log"; tail -20 "$W/dash.log"
exit $RC
