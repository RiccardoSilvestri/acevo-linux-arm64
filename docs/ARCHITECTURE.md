# Architecture

```
 drivers ── TCP/UDP 9600 ──▶ ┌────────────────────────────┐
                             │ ace-server                 │  Windows x86_64 server
                             │ Wine → Box64 → ARM64 Linux │  stdout → server.log
                             └──────┬──────────────┬──────┘
          host network, read-only   │              │ HTTP :8000 (internal)
          copy of the game traffic  ▼              │
                             ┌──────────────┐      │
                             │ lapwatch     │      │
                             │ AF_PACKET+BPF│      │
                             └──────┬───────┘      │
              Unix socket, NDJSON   ▼              ▼
 browsers ── HTTP/WS 8090 ─▶ ┌────────────────────────────┐
                             │ dashboard (app.py)         │  log parser, leaderboards,
                             │ REST + WebSocket hub       │  WebSocket push
                             └──────┬─────────────────────┘
                                    │ REST + shared files
 Discord ◀── gateway ──────▶ ┌────────────────────────────┐
                             │ discord-bot                │  commands, board, announcements,
                             │ docker.sock (restarts)     │  config edits
                             └────────────────────────────┘
```

## Game server on ARM64

The dedicated server only exists as a Windows x86_64 executable. The image runs it with a standalone amd64
build of Wine, which is itself an x86_64 program executed by Box64's dynamic recompiler. Box64 forwards most
library calls to native ARM64 libraries; `libstdc++` and `libgcc_s` are not wrapped, which is why their x86_64
versions are copied into the image. DepotDownloader has a native ARM64 build, so the game files are fetched
without SteamCMD (which would also need Box86).

`start-server.sh` keeps Wine as PID 1 (`exec`) and duplicates its output into `server-data/logs/server.log`
with a process substitution: `docker stop` reaches the game directly, and the dashboard reads the log as a file
without access to Docker. The log is rotated to `server.log.old` on every start.

`BOX64_DYNAREC_STRONGMEM=3` (plus the settings in `box64.box64rc`) avoids crashes in the server's threading code
during TLS initialisation.

## lapwatch

The game log reports finished laps, but not whether they were valid, nor where the cars are. `lapwatch` gets
that from the network:

1. A raw `AF_PACKET` socket with an in-kernel BPF filter receives only IPv4 TCP/UDP packets of the game port.
   The container runs on the host network with `NET_RAW` only, read-only, without new privileges.
2. TCP streams are reassembled per client and direction (duplicates and reordering handled), then cut into
   game frames and decoded with `schema.json`, a protobuf schema inferred from observing the network traffic. See [PROTOCOL.md](PROTOCOL.md).
3. The 63-byte UDP packets each client sends many times per second give position, velocity, gear, rpm, pedals
   and steering.
4. Events go out as newline-delimited JSON on a Unix socket: positions at 10 Hz, splits, laps, cuts, resets,
   diagnostics at most once per second per car, and a `hello` snapshot for each new subscriber.
5. Laps and incidents are appended to `laps.jsonl` and `incidents.jsonl`. The fastest valid lap of a track
   becomes its reference trace (`traces/<track>.json`: x, z, altitude, elapsed time). It draws the map, gives
   every car its progress along the lap, and gives the live delta.

lapwatch never sends anything to the game server or to the clients.

## Dashboard

`app.py` uses the Python standard library only.

- An updater thread rebuilds the public status every `REFRESH_S` seconds from the game log (who is connected,
  which car, pit/track state, race control, session classification), the game's HTTP API (client count) and
  the leaderboards, and pushes it to browsers only when something changed (plus a heartbeat).
- A second thread subscribes to lapwatch and forwards positions, diagnostics, splits and incidents to every
  browser over a hand-written RFC 6455 WebSocket hub with per-client bounded queues.
- A lap reported by lapwatch becomes a public record once the driver's name is known from the log. A valid lap
  inside the configured limits updates `laptimes.json` (one entry per driver and car per track, atomic writes)
  and the record history.
- Static pages are plain HTML/CSS/JS without frameworks or external resources. The pages get the branding
  through server-side placeholders and a JSON block, so the CSP can stay `script-src 'self'`.

Privacy and hardening: SteamIDs and IP addresses are used only as internal keys and are scrubbed from every
outgoing text. Responses carry CSP, `nosniff`, `X-Frame-Options: DENY` and `no-referrer`. WebSocket upgrades
from other origins are refused. The container runs as an unprivileged user on a read-only filesystem.

## Discord bot

The bot reads the dashboard API and the shared data files. It edits `season_def.json` / `server_config.json`
in place, because they may be bind-mounted as single files and an atomic rename would break the mount. It
restarts the game container through the Docker socket with plain HTTP over a Unix socket (no Docker CLI in the
image). Its state (board message id, pinned records, last seen lap) lives in `dashboard-data/bot_state.json`, so
a restart never duplicates announcements.

## Data files (`dashboard-data/`)

| File | Writer | Content |
|---|---|---|
| `laptimes.json` | dashboard | leaderboards per track and car, record history |
| `laps_history.jsonl` | dashboard | every lap with validity, sectors, cuts |
| `blocked.json`, `removed.json` | bot / admin | moderation |
| `bot_state.json`, `challenge_mode.json` | bot | bot state |
| `lapwatch/laps.jsonl`, `lapwatch/incidents.jsonl` | lapwatch | raw events |
| `lapwatch/traces/*.json` | lapwatch | reference lap per track |
| `lapwatch/live.json` | lapwatch | 1 Hz snapshot and health |
| `lapwatch/live.sock` | lapwatch | live event stream |
