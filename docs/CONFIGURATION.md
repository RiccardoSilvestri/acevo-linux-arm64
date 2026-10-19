# Configuration

Configuration is split per service so that changing one service never recreates another: Docker recreates a
container when its environment changes, and the game server should only restart when you mean it.

| File | Read by | Contains |
|---|---|---|
| `.env` | Docker Compose | names, ports, user ids |
| `config/game.env` | game server | Steam credentials, first-start server settings |
| `config/lapwatch.env` | lapwatch | detection thresholds |
| `config/dashboard.env` | website | branding, units, limits |
| `config/bot.env` | Discord bot | token, channel, admins, behaviour |
| `config/challenge.json` | Discord bot | challenge mode definition |
| `config/server_config.example.json`, `config/season_def.example.json` | game server | templates used once, on the first start |

`config/*.env` files hold secrets and are ignored by git; only the `*.env.example` files are versioned.

## `.env` (Compose)

| Variable | Default | Meaning |
|---|---|---|
| `STACK_NAME` | `acevo` | Prefix of container and image names (`acevo-server`, `acevo-dashboard`…) |
| `GAME_PORT` | `9600` | Game port, TCP and UDP |
| `WEB_PORT` | `8090` | Public port of the website |
| `WEB_BIND` | `0.0.0.0` | Interface the website is published on (`127.0.0.1` behind a reverse proxy) |
| `APP_UID` / `APP_GID` | `1000` | User of the website and bot containers; must own `dashboard-data/` |
| `DOCKER_GID` | `999` | Group id of the Docker socket on the host (lets the bot restart the game server) |
| `COMPOSE_PROFILES` | empty | Set to `https` to start the HTTPS reverse proxy |
| `SITE_DOMAIN` | `localhost` | Domain served by the proxy (`www.` redirects to it) |
| `TLS_CERT`, `TLS_KEY` | `./config/proxy/cert.pem`, `key.pem` | Certificate and key on the host (for example a Cloudflare Origin certificate) |
| `HTTP_PORT`, `HTTPS_PORT` | `80`, `443` | Public ports of the proxy |

### HTTPS

With `COMPOSE_PROFILES=https`, an nginx container terminates TLS for `SITE_DOMAIN` and forwards everything (WebSocket
included) to the dashboard; plain HTTP redirects to HTTPS. Behind Cloudflare, use an Origin certificate with the SSL
mode set to *Full (strict)*. Once the proxy is up you can set `WEB_BIND=127.0.0.1` so that port 8090 is no longer public.

## `config/game.env`

| Variable | Default | Meaning |
|---|---|---|
| `STEAM_USER`, `STEAM_PASS` | — | Steam account that owns the dedicated server |
| `ACE_APP_ID` | `4564210` | Steam app id of the dedicated server |
| `ACE_MODE` | `auto` | `auto` downloads when missing then starts, `download` only downloads, `start` only starts |
| `ACE_EXTRA_ARGS` | — | Extra command-line arguments for the server executable |
| `ACE_EXE_NAME` | `AssettoCorsaEVOServer.exe` | Executable to look for |
| `ACE_SERVER_NAME` | `ACE Server` | First-start value of `server_name` |
| `ACE_MAX_PLAYERS` | `16` | First-start value of `max_players` |
| `ACE_DRIVER_PASSWORD`, `ACE_ADMIN_PASSWORD`, `ACE_SPECTATOR_PASSWORD` | empty | First-start passwords |
| `ACE_HTTP_PORT` | `8000` | Port of the game's HTTP API (internal network only) |
| `BOX64_DYNAREC_STRONGMEM` | `3` | Box64 memory ordering; 3 is the stable value for this server |
| `WINEDEBUG`, `WINEESYNC`, `WINEDLLOVERRIDES` | `-all`, `1`, `explorer.exe=d` | Wine settings |

The `ACE_SERVER_NAME`/password/port values are written into `server_config.json` only when that file does not
exist yet. Afterwards edit `server-data/server/server_config.json` or use the bot.

## `config/dashboard.env`

**Branding and units**

| Variable | Default | Meaning |
|---|---|---|
| `SITE_NAME` | `ACE Live Timing` | Name in the header and page titles when the server name is not used |
| `SITE_NAME_FROM_SERVER` | `1` | Use the game server's current name (`server_name`) as the site name; it follows challenge renames live |
| `SITE_POWERED_BY` | `1` | Show the "Powered by" link to the project in the footer |
| `SITE_REPO_URL`, `SITE_REPO_LABEL` | this project | Target and text of the "Powered by" link |
| `SITE_DESCRIPTION` | generic text | `<meta name="description">` of the live page |
| `SITE_FOOTER` | generic text | Footer text of the live page |
| `SITE_ACCENT` | `#ff2e4d` (from CSS) | Accent colour, as `#rgb`, `#rrggbb` or a CSS colour name |
| `SITE_LOCALE` | `en-GB` | Locale for dates, times and numbers in the browser |
| `SPEED_UNIT` | `kmh` | `kmh` or `mph` |
| `HIDDEN_TEXT` | `[hidden]` | Replacement for any IP address or SteamID found in public text |
| `DEFAULT_TRACK`, `DEFAULT_SERVER_NAME`, `UNKNOWN_CAR`, `UNKNOWN_DRIVER` | `Track`, `ACE Server`, `Unknown car`, `Driver` | Fallback labels |

**Laps and leaderboards**

| Variable | Default | Meaning |
|---|---|---|
| `MIN_LAP_MS`, `MAX_LAP_MS` | `30000`, `900000` | Lap times outside this range are never saved |
| `MIN_SECTOR_MS`, `MAX_SECTOR_MS` | `5000`, `300000` | Plausible sector times read from the log |
| `MIN_SPLITS_TO_SAVE` | `1` | Minimum timed splits for a lap to enter a leaderboard |
| `BLOCKED_DRIVERS` | — | Comma-separated nicknames never saved (in addition to `blocked.json`) |
| `ACE_LOG_FALLBACK` | `0` | `1` saves laps from the game log when lapwatch is down (the log does not know lap validity) |
| `RECORD_HISTORY_KEEP` | `50` | Record-history entries kept per track |
| `CONSISTENCY_WINDOW`, `CONSISTENCY_LAPS` | `1.07`, `15` | Laps within 7% of the best, last 15, make the consistency figure |

**Server and limits**

| Variable | Default | Meaning |
|---|---|---|
| `BIND_HOST`, `PORT` | `0.0.0.0`, `8080` | Listening address inside the container |
| `REFRESH_S` | `1.5` | How often the status is recomputed from the log and the game API |
| `MAX_WS_CLIENTS`, `MAX_SSE_CLIENTS` | `150`, `25` | Connection caps |
| `WS_QUEUE`, `WS_PING_S`, `HEARTBEAT_S` | `300`, `20`, `5` | Per-client queue, ping and heartbeat |
| `HELLO_LAPS`, `HISTORY_SIZE`, `INCIDENTS_SIZE` | `60`, `3000`, `300` | In-memory history sizes |
| `PENDING_LAP_TTL_S` | `900` | How long a lap waits for its driver name before being dropped |
| `LOG_TAIL_BYTES` | `1048576` | Bytes of the game log parsed each cycle |
| `CHECK_ORIGIN` | `1` | Reject WebSocket connections from other origins |

**Paths** (inside the container; the defaults match the Compose file): `ACE_LAPWATCH_DIR`, `ACE_LAPWATCH_SOCK`
(Unix socket path or `tcp://host:port`), `ACE_HISTORY`, `ACE_DB`, `ACE_BLOCKED`, `ACE_REMOVED`, `ACE_LOG`,
`ACE_CONFIG`, `ACE_SEASON`, `ACE_CARS`, `ACE_API`.

## `config/lapwatch.env`

| Variable | Default | Meaning |
|---|---|---|
| `LW_IFACE` | all | Network interface to capture on |
| `LW_POS_HZ` | `10` | Rate of the live position stream |
| `LW_HITS` | `0` | `1` also records impacts as incidents (noisy) |
| `LW_MIN_IMPACT_MS` | `2.0` | Minimum impact speed (m/s) counted as a contact |
| `LW_FLOOR_NORMAL_Y` | `0.6` | Contacts with a more vertical normal are floor scrapes and ignored |
| `LW_PIT_REQUEST_WINDOW_S` | `15` | A teleport counts as a return to the pits only this soon after the driver asked for it |
| `LW_SLOW_RATIO`, `LW_SLOW_MIN_REF_KMH` | `0.4`, `80` | A car on track slower than 40% of the reference lap's speed at that point (where the reference is above 80 km/h) shows a yellow flag |
| `LW_SLOW_ABS_KMH` | `30` | Where the reference speed is unknown (off the racing line, no reference lap): below this speed on track. Never on the grid or in the pit lane |
| `LW_SLOW_CONFIRM_S`, `LW_SLOW_CLEAR_S` | `1.5`, `3` | Time slow before the yellow, time at normal speed before it clears |
| `LW_RESET_DEDUP_S` | `3` | Same teleport seen by several clients is counted once |
| `LW_TRACE_STEP_S` | `0.2` | Sampling period of the lap trace |
| `LW_TRACE_MAX_POINTS` | `6000` | Trace buffer per car |
| `LW_TRACE_MIN_POINTS`, `LW_TRACE_MIN_LAP_MS` | `50`, `20000` | Minimum lap to become the reference trace |
| `LW_REF_MATCH_M`, `LW_REF_LOST_M`, `LW_REF_SEARCH_WINDOW` | `35`, `150`, `90` | Matching of a car to the reference trace |
| `LW_DELTA_MIN_MS` | `3000` | Live delta is shown after this much of the lap |
| `LW_PIT_START_GAP_M` | `60` | A start line further than this from the finish line is drawn as a separate pit exit |
| `LW_CAR_STALE_S` | `15` | Cars without positions for this long leave the live map |
| `LW_STREAM_GAP_S` | `2` | A missing TCP segment is skipped after this long, so one lost packet never stalls a driver's data |
| `LW_HEAL_INTERVAL_S`, `LW_UNBOUND_RECENT_S` | `2`, `3` | How often clients sending positions without a known car are matched again, and how recent their packets must be. A client is re-bound only when exactly one connected car has no positions |
| `LW_DIAG_INTERVAL_S` | `1` | Minimum interval between diagnostics updates per car |
| `LW_RECENT_LAPS`, `LW_RECENT_INCIDENTS` | `300`, `200` | History sent to a dashboard that (re)connects |
| `LW_DEFAULT_TRACK` | `Track` | Track name when `season_def.json` cannot be read |
| `LW_PORT`, `LW_OUT`, `LW_SEASON`, `LW_SCHEMA`, `LW_SOCKET` | set by Compose | Game port and paths |

## `config/bot.env`

| Variable | Default | Meaning |
|---|---|---|
| `DISCORD_BOT_TOKEN` | — | Bot token; without it the bot stays idle |
| `DISCORD_CHANNEL_ID` | — | Channel for the board and the announcements |
| `DISCORD_ADMIN_IDS` | — | Comma-separated user ids allowed to use admin commands; empty = Discord administrators |
| `DISCORD_OPEN_COMMANDS` | `false` | Everyone may use admin commands (testing only) |
| `DISCORD_LIVE_BOARD` | `true` | Keep a pinned live board in the channel |
| `DISCORD_ANNOUNCE_RECORDS`, `DISCORD_PIN_RECORDS` | `true` | Announce records, pin track records |
| `DISCORD_ANNOUNCE_INVALID` | `true` | Short notice for every invalidated lap |
| `DISCORD_ANNOUNCE_TRACK_CHANGES` | `true` | Announce track changes with the record to beat |
| `DISCORD_ANNOUNCE_JOINS` | `false` | Announce joins and leaves |
| `DISCORD_ANNOUNCE_PENALTIES` | `true` | Post penalties and race-control messages |
| `DISCORD_ANNOUNCE_SESSIONS` | `true` | Post session starts and new looped sessions |
| `REQUIRE_FORCE_WITH_DRIVERS` | `true` | Commands that restart the game server need `force: True` while drivers are connected |
| `CHALLENGE_CLASSES` | empty | Classes offered by `/challenge`; empty = every entry of `config/challenge.json` |
| `ACE_SITE_URL` | — | Public URL of the website, used in links |
| `SERVER_BASE_NAME` | `ACE Server` | Server name restored when challenge mode ends; used in challenge names |
| `SERVER_NAME_MAX` | `60` | Maximum server name length |
| `BOARD_INTERVAL_S`, `PRESENCE_INTERVAL_S`, `LAPFEED_INTERVAL_S`, `ANNOUNCER_INTERVAL_S` | `45`, `60`, `4`, `5` | Loop periods |
| `BOARD_MAX_DRIVERS`, `BOARD_TOP` | `8`, `5` | Size of the live board |
| `MIN_SESSION_MIN`, `MAX_SESSION_MIN`, `MAX_PLAYERS_LIMIT` | `10`, `1440`, `30` | Limits of the admin commands |
| `RESTART_TIMEOUT_S`, `UPDATE_WAIT_MIN` | `35`, `15` | Grace period of restarts, wait for a Steam update |
| `AUTO_RESTART_ON_SESSION_END` | `true` | Fallback for servers with `"cycle": false`: restart the game server when a single-session mode ends. With `"cycle": true` in `server_config.json` (the default template) the server loops sessions itself and the bot never restarts it |
| `AUTO_RESTART_MODES` | `HOTLAP,PRACTICE,HOTSTINT` | Game modes covered (race weekends already loop on their own) |
| `AUTO_RESTART_DELAY_S`, `AUTO_RESTART_CHECK_S` | `45`, `20` | Wait after the end of the session before restarting; polling period |
| `BOT_COLOR_OK`, `BOT_COLOR_GOLD`, `BOT_COLOR_RED`, `BOT_COLOR_INFO`, `BOT_COLOR_DARK` | Discord-like palette | Embed colours (hex) |
| `ACE_CONTAINER`, `DOCKER_SOCKET`, `ACE_STATUS_URL`, `BOT_DATA_DIR`, `GAME_CONFIG_DIR`, `GAME_DIR`, `CHALLENGE_FILE` | set by Compose | Container name and paths |

## `config/challenge.json`

`/challenge <track> [class]` restricts the server to one car class and writes the class record holder (hotlap) or
the last race winner (race weekend) into the server name.

```json
{
  "default_class": "GT3",
  "classes": {
    "GT3": {"include": {}, "exclude": []},
    "GT2": {"include": {"preset_example_mech_1": "Example GT2"}, "exclude": ["preset_935_mech_1"]}
  },
  "names": {
    "hotlap_record": "{base} {label} | {time} {driver}",
    "hotlap_empty": "{base} {label} | Beat the clock",
    "race_winner": "{base} {label} Race | Champion: {winner}",
    "race_empty": "{base} {label} Race | Win to name the server"
  },
  "race_config": {"race_duration": 10, "race_duration_type": "GameModeSelectionDuration_LAPS"}
}
```

Besides classes, `classes` can hold **packs**: `{"label": "JDM", "description": "…", "presets": ["preset_nsxr_mech_1", …]}` lists the presets explicitly (see [DISCORD.md](DISCORD.md)). For the GT classes, the cars come from the server's own `cars.json`: every preset whose display name ends with
` - <CLASS>` (for example `Ferrari 296 GT3 - GT3`) belongs to that class, so cars added by a game update join their
class automatically after `/update`. `include` adds presets, `exclude` removes them, and a `cars` map replaces the
automatic list. The classes offered by the command are set with `CHALLENGE_CLASSES` (default `GT3,GT2,GT4`) in
`config/bot.env`. In the name templates `{label}` is the class, `{track}` the track (the `title` given to `/challenge`, else the layout or track name) and `{base}` is `SERVER_BASE_NAME`; `race_config` is
merged over the built-in race weekend settings.

## Moderation files (`dashboard-data/`)

- `blocked.json` — `{"blocked": ["nickname"]}`: never saved, managed with `/block` and `/unblock`.
- `removed.json` — `{"removed": [{"track": "Monza GP", "car": "…", "driver": "…", "time_ms": 104670}]}`: single laps
  removed from the leaderboards for good (`"track": "*"` matches every track).
