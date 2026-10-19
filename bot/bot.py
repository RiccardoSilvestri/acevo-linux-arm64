import asyncio
import datetime
import http.client
import json
import os
import re
import socket
import time
import urllib.parse
import urllib.request

import discord
from discord import app_commands


def _env(name, default, cast=str):
    v = os.environ.get(name)
    return default if v is None or v.strip() == "" else cast(v.strip())


def _flag(name, default):
    return _env(name, "true" if default else "false").lower() in ("1", "true", "yes", "on")


def _color(name, default):
    return int(_env(name, default).lstrip("#"), 16)


TOKEN = _env("DISCORD_BOT_TOKEN", "")
CHANNEL_ID = _env("DISCORD_CHANNEL_ID", 0, int)
ADMIN_IDS = {int(x) for x in _env("DISCORD_ADMIN_IDS", "").replace(" ", "").split(",") if x.isdigit()}
ANNOUNCE_JOINS = _flag("DISCORD_ANNOUNCE_JOINS", False)
ANNOUNCE_INVALID = _flag("DISCORD_ANNOUNCE_INVALID", True)
ANNOUNCE_RECORDS = _flag("DISCORD_ANNOUNCE_RECORDS", True)
ANNOUNCE_TRACK_CHANGES = _flag("DISCORD_ANNOUNCE_TRACK_CHANGES", True)
PIN_RECORDS = _flag("DISCORD_PIN_RECORDS", True)
LIVE_BOARD = _flag("DISCORD_LIVE_BOARD", True)
OPEN_COMMANDS = _flag("DISCORD_OPEN_COMMANDS", False)
ANNOUNCE_PENALTIES = _flag("DISCORD_ANNOUNCE_PENALTIES", True)
ANNOUNCE_SESSIONS = _flag("DISCORD_ANNOUNCE_SESSIONS", True)
REQUIRE_FORCE = _flag("REQUIRE_FORCE_WITH_DRIVERS", True)

STATUS_URL = _env("ACE_STATUS_URL", "http://dashboard:8080/api/status")
SITE_URL = _env("ACE_SITE_URL", "").rstrip("/")
API_BASE = STATUS_URL.rsplit("/api/", 1)[0]
GAME_CONTAINER = _env("ACE_CONTAINER", "acevo-server")
DOCKER_SOCKET = _env("DOCKER_SOCKET", "/var/run/docker.sock")
RESTART_TIMEOUT_S = _env("RESTART_TIMEOUT_S", 35, int)

DATA_DIR = _env("BOT_DATA_DIR", "/dash-data")
GAME_CONFIG_DIR = _env("GAME_CONFIG_DIR", "/srv")
GAME_DIR = _env("GAME_DIR", "/game")
DB_FILE = os.path.join(DATA_DIR, "laptimes.json")
BLOCKED_FILE = os.path.join(DATA_DIR, "blocked.json")
STATE_FILE = os.path.join(DATA_DIR, "bot_state.json")
CHALLENGE_STATE_FILE = os.path.join(DATA_DIR, "challenge_mode.json")
SEASON_FILE = os.path.join(GAME_CONFIG_DIR, "season_def.json")
CONFIG_FILE = os.path.join(GAME_CONFIG_DIR, "server_config.json")
EVENTS_FILE = os.path.join(GAME_CONFIG_DIR, "events_practice.json")
EVENTS_RACE_FILE = os.path.join(GAME_CONFIG_DIR, "events_race_weekend.json")
MARKER_FILE = os.path.join(GAME_DIR, ".downloaded")
CHALLENGE_FILE = _env("CHALLENGE_FILE", "/config/challenge.json")
CARS_FILE = os.path.join(GAME_CONFIG_DIR, "cars.json")
CHALLENGE_CLASSES = [c.strip().upper() for c in _env("CHALLENGE_CLASSES", "").split(",") if c.strip()]

SERVER_BASE_NAME = _env("SERVER_BASE_NAME", "ACE Server")
SERVER_NAME_MAX = _env("SERVER_NAME_MAX", 60, int)
BOARD_INTERVAL_S = _env("BOARD_INTERVAL_S", 45, int)
PRESENCE_INTERVAL_S = _env("PRESENCE_INTERVAL_S", 60, int)
LAPFEED_INTERVAL_S = _env("LAPFEED_INTERVAL_S", 4, int)
ANNOUNCER_INTERVAL_S = _env("ANNOUNCER_INTERVAL_S", 5, int)
BOARD_MAX_DRIVERS = _env("BOARD_MAX_DRIVERS", 8, int)
BOARD_TOP = _env("BOARD_TOP", 5, int)
MIN_LAP_MS = _env("MIN_LAP_MS", 30000, int)
MAX_LAP_MS = _env("MAX_LAP_MS", 900000, int)
UPDATE_WAIT_MIN = _env("UPDATE_WAIT_MIN", 15, int)
MIN_SESSION_MIN = _env("MIN_SESSION_MIN", 10, int)
MAX_SESSION_MIN = _env("MAX_SESSION_MIN", 1440, int)
MAX_PLAYERS_LIMIT = _env("MAX_PLAYERS_LIMIT", 30, int)
AUTO_RESTART = _flag("AUTO_RESTART_ON_SESSION_END", True)
AUTO_RESTART_MODES = {m.strip().upper() for m in _env("AUTO_RESTART_MODES", "HOTLAP,PRACTICE,HOTSTINT").split(",") if m.strip()}
AUTO_RESTART_DELAY_S = _env("AUTO_RESTART_DELAY_S", 45, int)
AUTO_RESTART_CHECK_S = _env("AUTO_RESTART_CHECK_S", 20, int)

COLOR_OK = _color("BOT_COLOR_OK", "34a853")
COLOR_GOLD = _color("BOT_COLOR_GOLD", "d4af37")
COLOR_RED = _color("BOT_COLOR_RED", "d32f2f")
COLOR_INFO = _color("BOT_COLOR_INFO", "4a90d9")
COLOR_DARK = _color("BOT_COLOR_DARK", "2b2d31")

STATUS_TRACK = "track"

WEATHER = {
    "clear": "GameModeSelectionWeatherType_CLEAR",
    "scattered clouds": "GameModeSelectionWeatherType_SCATTERED_CLOUDS",
    "broken clouds": "GameModeSelectionWeatherType_BROKEN_CLOUDS",
    "overcast": "GameModeSelectionWeatherType_OVERCAST",
    "damp": "GameModeSelectionWeatherType_DAMP",
    "drizzle": "GameModeSelectionWeatherType_DRIZZLE",
    "rain": "GameModeSelectionWeatherType_RAIN",
    "heavy rain": "GameModeSelectionWeatherType_HEAVY_RAIN",
}
MODES = {
    "practice": "GameModeType_PRACTICE",
    "hotlap": "GameModeType_HOTLAP",
    "hotstint": "GameModeType_HOTSTINT",
    "race weekend": "GameModeType_RACE_WEEKEND",
}
MODE_NAMES = {v: k.title() for k, v in MODES.items()}

DEFAULT_CHALLENGE = {
    "default_class": "GT3",
    "classes": {},
    "names": {
        "hotlap_record": "{base} {label} | {time} {driver}",
        "hotlap_empty": "{base} {label} | Beat the clock",
        "race_winner": "{base} {label} Race | Champion: {winner}",
        "race_empty": "{base} {label} Race | Win to name the server",
    },
    "race_config": {
        "practice_duration": 900,
        "practice_time_of_day": {"hour": 10, "minute": 0, "time_multiplier": 1.0},
        "practice_overtime_waiting_next_session": 60,
        "practice_max_wait_to_box": 0,
        "qualify_duration": 600,
        "qualify_time_of_day": {"hour": 12, "minute": 0, "time_multiplier": 1.0},
        "qualify_overtime_waiting_next_session": 60,
        "qualify_max_wait_to_box": 0,
        "warmup_duration": 0,
        "race_duration": 10,
        "race_duration_type": "GameModeSelectionDuration_LAPS",
        "race_time_of_day": {"hour": 14, "minute": 0, "time_multiplier": 1.0},
        "race_overtime_waiting_next_session": 120,
        "race_max_wait_to_box": 0,
        "min_waiting_for_players": 0,
        "max_waiting_for_players": 60,
    },
}


def jread(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default


def jwrite(path, data):
    if os.path.abspath(path).startswith(os.path.abspath(GAME_CONFIG_DIR) + os.sep):
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
        return
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def challenge_def():
    custom = jread(CHALLENGE_FILE, {})
    merged = dict(DEFAULT_CHALLENGE)
    for k, v in custom.items():
        if isinstance(v, dict) and isinstance(merged.get(k), dict) and k not in ("cars", "classes"):
            merged[k] = {**merged[k], **v}
        else:
            merged[k] = v
    if custom.get("cars") and custom.get("label"):
        merged["classes"] = {**merged.get("classes", {}), custom["label"].upper(): {"cars": custom["cars"]}}
        merged.setdefault("default_class", custom["label"].upper())
    return merged


CAR_STOPWORDS = {"lms", "evo", "ii", "iii", "r", "the"}
CLASS_TOKENS = {"gt2", "gt3", "gt4", "cup"}


def _tokens(name):
    return re.findall(r"[a-z0-9]+", re.sub(r"\(.*?\)", " ", str(name).lower()))


def car_signature(name):
    toks = [t for t in _tokens(name) if t not in CAR_STOPWORDS]
    words = {t for t in toks if not t.isdigit()}
    return words if len(words) >= 2 else set(toks)


def same_car(signature, leaderboard_name):
    return bool(signature) and signature <= set(_tokens(leaderboard_name))


def game_car_index():
    out = {}
    for car in jread(CARS_FILE, {"cars": []}).get("cars", []):
        base, _, variant = str(car.get("display_name", "")).rpartition(" - ")
        out[car.get("name")] = {"base": (base or car.get("display_name", "?")).strip(), "variant": variant.strip(),
                                "pi": car.get("performance_indicator")}
    return out


def class_conf(cls):
    return (challenge_def().get("classes") or {}).get(cls.upper()) or {}


def class_label(cls):
    return class_conf(cls).get("label") or cls.upper()


def class_cars(cls):
    cls = cls.upper()
    conf = class_conf(cls)
    if conf.get("cars"):
        return dict(conf["cars"])
    index = game_car_index()
    out = {}
    if conf.get("presets"):
        for preset in conf["presets"]:
            if preset in index:
                out[preset] = index[preset]["base"]
    else:
        for preset, car in index.items():
            if car["variant"].upper() == cls and preset:
                out[preset] = car["base"]
    for preset, name in (conf.get("include") or {}).items():
        out[preset] = name
    for preset in conf.get("exclude") or []:
        out.pop(preset, None)
    return out


def challenge_classes():
    return CHALLENGE_CLASSES or [k.upper() for k in (challenge_def().get("classes") or {})] or ["GT3", "GT2", "GT4"]


def pi_range(presets):
    index = game_car_index()
    pis = [index[p]["pi"] for p in presets if p in index and index[p]["pi"]]
    return (min(pis), max(pis)) if pis else None


def class_choices():
    return [app_commands.Choice(name=class_label(c), value=c) for c in challenge_classes()][:25]


def fmt_ms(ms):
    return f"{ms // 60000}:{ms % 60000 // 1000:02d}.{ms % 1000:03d}"


def parse_ms(text):
    m = re.fullmatch(r"\s*(?:(\d+):)?(\d{1,2})(?:[.,](\d{1,3}))?\s*", text or "")
    if not m:
        return None
    mins, secs, frac = int(m.group(1) or 0), int(m.group(2)), (m.group(3) or "0").ljust(3, "0")
    return (mins * 60 + secs) * 1000 + int(frac) if secs < 60 else None


def plural(n, word):
    return f"{n} {word}" + ("" if n == 1 else "s")


def events_list(race=False):
    evs = jread(EVENTS_RACE_FILE if race else EVENTS_FILE, {}).get("events", [])
    return [{"key": f"{e['track']} {e['layout']}", **e} for e in evs]


def is_race_weekend(game_type):
    return str(game_type).endswith("RACE_WEEKEND")


def find_event(track, race=False):
    return next((e for e in events_list(race) if e["key"].lower() == track.lower()), None)


def event_block(ev):
    return {"track": ev["track"], "layout": ev["layout"], "event_name": ev["event_name"],
            "track_length": ev["track_length"], "max_pit_slot": ev["max_pit_slot"]}


def race_config_defaults():
    return dict(DEFAULT_CHALLENGE["race_config"])


def season():
    return jread(SEASON_FILE, {})


def config():
    return jread(CONFIG_FILE, {})


def current_track_key():
    ev = season().get("event", {})
    return f"{ev.get('track', '?')} {ev.get('layout', '')}".strip()


def blocked_list():
    return jread(BLOCKED_FILE, {"blocked": []}).get("blocked", [])


def bot_state():
    return jread(STATE_FILE, {"record_pins": {}, "board_message_id": 0})


def save_state(st):
    jwrite(STATE_FILE, st)


def track_records(track_key):
    td = jread(DB_FILE, {"tracks": {}}).get("tracks", {}).get(track_key, {})
    return sorted(
        ({**e, "car": c} for c, cd in td.get("cars", {}).items() for e in cd.get("entries", [])),
        key=lambda x: x["time_ms"])


def leaderboard_snapshot():
    db = jread(DB_FILE, {"tracks": {}})
    bests, overall = {}, {}
    for t, td in db.get("tracks", {}).items():
        for car, cd in td.get("cars", {}).items():
            entries = cd.get("entries", [])
            if entries:
                bests[(t, car)] = dict(entries[0])
                if t not in overall or entries[0]["time_ms"] < overall[t]["time_ms"]:
                    overall[t] = {**entries[0], "car": car}
    return bests, overall


async def _in_thread(fn):
    try:
        return await asyncio.get_running_loop().run_in_executor(None, fn)
    except Exception:
        return None


async def get_status():
    def fetch():
        with urllib.request.urlopen(STATUS_URL, timeout=5) as r:
            return json.loads(r.read())
    return await _in_thread(fetch)


async def api_get(path):
    def fetch():
        with urllib.request.urlopen(API_BASE + path, timeout=6) as r:
            return json.loads(r.read())
    return await _in_thread(fetch)


def sec_line(splits):
    return " · ".join(f"S{i + 1} {s / 1000:.3f}" for i, s in enumerate(splits[:3]))


class UnixHTTP(http.client.HTTPConnection):
    def __init__(self, path):
        super().__init__("localhost")
        self._path = path

    def connect(self):
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(RESTART_TIMEOUT_S + 25)
        s.connect(self._path)
        self.sock = s


async def _container_action(action):
    def do():
        c = UnixHTTP(DOCKER_SOCKET)
        c.request("POST", f"/containers/{GAME_CONTAINER}/{action}")
        return c.getresponse().status in (204, 304)
    return bool(await _in_thread(do))


async def restart_game_server():
    return await _container_action(f"restart?t={RESTART_TIMEOUT_S}")


async def stop_game_server():
    return await _container_action(f"stop?t={RESTART_TIMEOUT_S}")


async def start_game_server():
    return await _container_action("start")


async def game_server_logs(tail=120):
    def do():
        c = UnixHTTP(DOCKER_SOCKET)
        c.request("GET", f"/containers/{GAME_CONTAINER}/logs?stdout=1&stderr=1&tail={tail}")
        r = c.getresponse()
        return r.read().decode("utf-8", errors="replace") if r.status == 200 else ""
    return await _in_thread(do) or ""


async def game_server_started_at():
    def do():
        c = UnixHTTP(DOCKER_SOCKET)
        c.request("GET", f"/containers/{GAME_CONTAINER}/json")
        r = c.getresponse()
        if r.status != 200:
            return None
        started = json.loads(r.read()).get("State", {}).get("StartedAt", "")
        started = started.split(".")[0].rstrip("Z")
        return datetime.datetime.fromisoformat(started).replace(tzinfo=datetime.timezone.utc).timestamp()
    return await _in_thread(do)


async def game_server_logs_since(ts):
    def do():
        c = UnixHTTP(DOCKER_SOCKET)
        c.request("GET", f"/containers/{GAME_CONTAINER}/logs?stdout=1&stderr=1&since={int(ts)}")
        r = c.getresponse()
        return r.read().decode("utf-8", errors="replace") if r.status == 200 else ""
    return await _in_thread(do) or ""


def is_admin(inter: discord.Interaction):
    if OPEN_COMMANDS or inter.user.id in ADMIN_IDS:
        return True
    if not ADMIN_IDS and isinstance(inter.user, discord.Member):
        return inter.user.guild_permissions.administrator
    return False


FORCE_HELP = "Restart even if drivers are connected"


async def deny(inter):
    await inter.response.send_message("You don't have permission to use this command.", ephemeral=True)


def classification_rows(cls, limit):
    medals = ["🥇", "🥈", "🥉"]
    rows = []
    for i, d in enumerate(cls[:limit]):
        pre = medals[i] if i < 3 else f"`{i + 1}.`"
        best = f" · best {fmt_ms(d['best_ms'])}" if d.get("best_ms") else ""
        rows.append(f"{pre} **{d['driver']}** — {d['car']} · {plural(d['laps'], 'lap')}{best}")
    return rows


def podium_embed(cls):
    winner = cls[0]
    e = discord.Embed(
        title="🏆 CHEQUERED FLAG",
        description=f"**{winner['driver']}** wins in the {winner['car']} after {plural(winner['laps'], 'lap')}",
        color=COLOR_GOLD)
    e.add_field(name="Final classification", value="\n".join(classification_rows(cls, 10)), inline=False)
    if SITE_URL:
        e.url = SITE_URL
    e.timestamp = discord.utils.utcnow()
    return e


def challenge_state():
    return jread(CHALLENGE_STATE_FILE, {"active": False})


def challenge_best(track_key, cars, target=None):
    td = jread(DB_FILE, {"tracks": {}}).get("tracks", {}).get(track_key, {})
    sigs = [car_signature(c) for c in cars]
    best = None
    for car, cd in td.get("cars", {}).items():
        if not any(same_car(s, car) for s in sigs):
            continue
        for e in cd.get("entries", []):
            if best is None or e["time_ms"] < best["time_ms"]:
                best = {**e, "car": car}
    if target and target.get("time_ms") and (best is None or target["time_ms"] < best["time_ms"]):
        best = {"time_ms": target["time_ms"], "driver": target.get("driver") or "?", "car": None, "target": True}
    return best


def challenge_track_label(state):
    if state.get("title"):
        return state["title"]
    ev = find_event(state.get("track", "")) or {}
    return ev.get("layout") if ev.get("layout") and len(ev["layout"]) > 4 else state.get("track", "")


def challenge_server_name(state):
    ch = challenge_def()
    names = ch["names"]
    cls = state.get("class") or ch.get("default_class", "GT3")
    ctx = {"base": SERVER_BASE_NAME, "label": class_label(cls), "track": challenge_track_label(state)}
    if state.get("mode") == "race":
        w = state.get("last_winner")
        text = names["race_winner"].format(winner=w, **ctx) if w else names["race_empty"].format(**ctx)
    else:
        best = challenge_best(state.get("track", ""), state.get("cars") or list(class_cars(cls).values()),
                              state.get("target"))
        text = (names["hotlap_record"].format(time=fmt_ms(best["time_ms"]), driver=best["driver"], **ctx)
                if best else names["hotlap_empty"].format(**ctx))
    return text.strip()[:SERVER_NAME_MAX]


PHASE_TEXT = {
    "Waiting_For_Players": "waiting for drivers", "Waiting_For_Start": "waiting for the start",
    "Start_Spawn_On_Position": "cars on the grid", "Start_Countdown_No_Lights": "get ready",
    "Start_Countdown_Lights_On": "lights on", "Start_Countdown_Lights_Off": "lights out",
    "RollingStart_Start_Formation": "formation lap", "RollingStart_Change_Line": "formation lap",
    "RollingStart_Start_Green_Flag": "green flag", "RollingStart_End_Green_Flag": "green flag",
    "Session": "green flag", "Waiting_Last_Lap": "last lap", "Overtime_Waiting_For_Leader": "last lap for the leader",
    "Overtime_Waiting_For_Others": "chequered flag", "Waiting_For_Ai": "chequered flag",
    "Waiting_For_PitBox": "session over", "Ended": "session over", "Request_Quit": "session over",
}


def clock(sec):
    sec = max(0, int(sec))
    h, m, s = sec // 3600, sec % 3600 // 60, sec % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def session_line(st):
    race = (st or {}).get("race") or {}
    if not race.get("session"):
        return None
    text = f"**{race['session']}** · {PHASE_TEXT.get(race.get('phase'), str(race.get('phase', '')).replace('_', ' ').lower())}"
    weekend = (st or {}).get("weekend") or {}
    if race["session"] == "Race" and weekend.get("race_laps") and race.get("phase") in ("Session", "Overtime_Waiting_For_Leader"):
        lead = next((c for c in race.get("cars") or [] if c.get("pos") == 1), None)
        if lead and lead.get("laps") is not None:
            text += f" · lap {min(weekend['race_laps'], lead['laps'] + 1)}/{weekend['race_laps']}"
    elif race.get("phase_end"):
        text += f" · {clock(race['phase_end'] - time.time())} left"
    return text


def session_fastest(st):
    rows = [r for r in (((st or {}).get("timing") or {}).get("rows") or []) if r.get("best_ms")]
    return min(rows, key=lambda r: r["best_ms"]) if rows else None


def race_order(st):
    race = (st or {}).get("race") or {}
    if race.get("sort") != "Race":
        return []
    cars = [c for c in race.get("cars") or [] if c.get("pos") and c.get("name")]
    return sorted(cars, key=lambda c: c["pos"])


def gap_text(car, leader):
    if car is leader:
        return "Leader"
    if leader and car.get("laps") is not None and leader.get("laps") is not None and leader["laps"] > car["laps"]:
        return f"+{plural(leader['laps'] - car['laps'], 'lap')}"
    return f"+{car['gap_ms'] / 1000:.1f}s" if car.get("gap_ms") is not None else ""


async def drivers_guard(inter, force, what):
    if force or not REQUIRE_FORCE:
        return True
    st = await get_status()
    n = (st or {}).get("players") or 0
    if not n:
        return True
    await inter.response.send_message(
        f"⚠️ {plural(n, 'driver')} on the server: {what} would disconnect them. "
        f"Run the command again with `force: True`, or wait until the server is empty.", ephemeral=True)
    return False


def restart_suffix(ok):
    return {None: " · applied at the next restart",
            True: " · server restarted",
            False: " · restart failed, check the logs"}[ok]


intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)
_channel = None


async def announce_channel():
    global _channel
    if _channel or not CHANNEL_ID:
        return _channel
    try:
        _channel = client.get_channel(CHANNEL_ID) or await client.fetch_channel(CHANNEL_ID)
    except Exception:
        _channel = None
    return _channel


async def clean_pin_notices(channel):
    try:
        async for m in channel.history(limit=8):
            if m.type is discord.MessageType.pins_add:
                await m.delete()
    except Exception:
        pass


async def pin_record(track, message):
    if not PIN_RECORDS:
        return
    st = bot_state()
    old_id = st["record_pins"].get(track)
    if old_id:
        try:
            old = await message.channel.fetch_message(old_id)
            await old.unpin()
        except Exception:
            pass
    try:
        await message.pin(reason=f"Track record — {track}")
        st["record_pins"][track] = message.id
        save_state(st)
        await clean_pin_notices(message.channel)
    except Exception as ex:
        print(f"pin failed: {ex}", flush=True)


def board_embed(st, overall):
    track = st.get("track", "?") if st else "?"
    layout = st.get("layout", "") if st else ""
    tk = f"{track} {layout}".strip()
    online = bool(st and st.get("online"))
    e = discord.Embed(
        title=(st.get("server_name") if st else None) or SERVER_BASE_NAME,
        description=("🟢 **Online**" if online else "🔴 **Offline**")
                    + (f" · [Live timing]({SITE_URL})" if SITE_URL else ""),
        color=COLOR_OK if online else COLOR_RED)
    e.add_field(name="Track", value=tk or "?")
    e.add_field(name="Drivers", value=f"{st.get('players', 0)}/{st.get('max_players', '?')}" if st else "?")
    e.add_field(name="Mode", value=MODE_NAMES.get("GameModeType_" + (st.get("mode", "") if st else ""),
                                                  (st.get("mode", "?").title() if st else "?")))
    line = session_line(st)
    fast = session_fastest(st)
    if line or fast:
        e.add_field(name="Session", inline=False, value="\n".join(x for x in (
            line, f"⏱ fastest **{fmt_ms(fast['best_ms'])}** — {fast['name']}" if fast else None) if x))
    order = race_order(st)
    if order:
        lead = order[0]
        e.add_field(name="Race order", inline=False, value="\n".join(
            f"`P{c['pos']}` **{c['name']}** — {c.get('car') or '?'} · {gap_text(c, lead)}"
            + (f" · PIT {c['pits']}" if c.get("pits") else "") + (" · ⚠️ penalty" if c.get("pen") else "")
            for c in order[:BOARD_MAX_DRIVERS]))
    drivers = (st or {}).get("drivers", [])
    rows = {r["name"]: r for r in ((st or {}).get("timing") or {}).get("rows", [])}
    if drivers and not order:
        lines = []
        for d in drivers[:BOARD_MAX_DRIVERS]:
            r = rows.get(d["name"])
            tag = "🟢 on track" if d.get("status") == STATUS_TRACK else "⚪ pits"
            line = f"• **{d['name']}** — {d.get('car', '?')} ({tag})"
            if r and r.get("best_ms"):
                line += f"\n  ⏱ best **{fmt_ms(r['best_ms'])}**"
                if r.get("last_ms") and r["last_ms"] != r["best_ms"]:
                    line += f" · last {fmt_ms(r['last_ms'])} {'✅' if r.get('last_ok') else '❌'}"
                line += f" · {r['valid']}/{r['laps']} valid"
            elif r and r.get("last_ms") and not r.get("last_ok"):
                line += f"\n  ❌ last lap {fmt_ms(r['last_ms'])} invalidated"
            lines.append(line)
        e.add_field(name="On the server now", inline=False, value="\n".join(lines))
    rec = overall.get(tk)
    if rec:
        e.add_field(name="Track record", inline=False,
                    value=f"👑 **{fmt_ms(rec['time_ms'])}** — {rec['driver']} ({rec['car']}, {rec['date']})")
    laps = track_records(tk)[:BOARD_TOP]
    if laps:
        e.add_field(name=f"Top {BOARD_TOP}", inline=False, value="\n".join(
            f"`{i + 1}.` **{fmt_ms(l['time_ms'])}** {l['driver']} — {l['car']}" for i, l in enumerate(laps)))
    lw = (st or {}).get("lapwatch") or {}
    e.set_footer(text="Live board · only valid laps count" + (" · live map active" if lw.get("on") else ""))
    e.timestamp = discord.utils.utcnow()
    return e


async def board_loop():
    await client.wait_until_ready()
    while not client.is_closed():
        try:
            ch = await announce_channel()
            if ch and LIVE_BOARD:
                st_file = bot_state()
                status = await get_status()
                _, overall = leaderboard_snapshot()
                embed = board_embed(status, overall)
                msg = None
                if st_file.get("board_message_id"):
                    try:
                        msg = await ch.fetch_message(st_file["board_message_id"])
                    except Exception:
                        msg = None
                if msg:
                    await msg.edit(embed=embed)
                else:
                    msg = await ch.send(embed=embed)
                    try:
                        await msg.pin(reason="Live server board")
                        await clean_pin_notices(ch)
                    except Exception:
                        pass
                    st_file["board_message_id"] = msg.id
                    save_state(st_file)
        except Exception as ex:
            print(f"board: {ex}", flush=True)
        await asyncio.sleep(BOARD_INTERVAL_S)


async def presence_loop():
    await client.wait_until_ready()
    while not client.is_closed():
        try:
            st = await get_status()
            if st and st.get("online"):
                sess = ((st.get("race") or {}).get("session"))
                name = " · ".join(x for x in (st.get("track", "?"), sess, plural(st.get("players", 0), "driver")) if x)
                act = discord.Activity(type=discord.ActivityType.watching, name=name)
                await client.change_presence(status=discord.Status.online, activity=act)
            else:
                await client.change_presence(
                    status=discord.Status.dnd,
                    activity=discord.Activity(type=discord.ActivityType.watching, name="server offline"))
        except Exception:
            pass
        await asyncio.sleep(PRESENCE_INTERVAL_S)


async def incident_feed(ch, mem):
    d = await api_get("/api/incidents")
    since = mem.setdefault("since", time.time())
    seen = mem.setdefault("seen", set())
    for i in (d or {}).get("incidents") or []:
        if i.get("ts", 0) <= since or i.get("k") not in ("penalty", "rc"):
            continue
        key = (i.get("k"), i.get("cid"), round(i.get("ts", 0)), i.get("text") or i.get("pen"))
        if key in seen:
            continue
        seen.add(key)
        if i["k"] == "rc" and i.get("kind") == "penalty":
            continue
        name = i.get("name") or "Driver"
        if i["k"] == "penalty":
            why = str(i.get("why") or "").replace("_", " ").lower()
            desc = (f"⚠️ **{name}** — {str(i.get('pen') or 'penalty').replace('_', ' ')}"
                    + (f" {i['pen_ms'] / 1000:g} s" if i.get("pen_ms") else "") + (f" ({why})" if why else ""))
        else:
            desc = f"📢 **Race control** — {i.get('text')}" + (f" · {name}" if i.get("cid") else "")
        await ch.send(embed=discord.Embed(description=desc, color=COLOR_GOLD))
    if len(seen) > 500:
        seen.clear()
        mem["since"] = time.time()


async def lapfeed_loop():
    await client.wait_until_ready()
    st = bot_state()
    last = st.get("lapfeed_ts", time.time())
    seen = set()
    inc_mem = {}
    while not client.is_closed():
        try:
            if ANNOUNCE_PENALTIES:
                ch = await announce_channel()
                if ch:
                    await incident_feed(ch, inc_mem)
            if ANNOUNCE_INVALID:
                d = await api_get("/api/laps?limit=15")
                ch = await announce_channel()
                new = [l for l in reversed((d or {}).get("laps") or []) if l["ts"] > last and l["id"] not in seen]
                for l in new:
                    seen.add(l["id"])
                    last = max(last, l["ts"])
                    if l["valid"] or not (MIN_LAP_MS < l["ms"] < MAX_LAP_MS) or not ch:
                        continue
                    why = plural(l["cuts"], "track-limit warning") if l.get("cuts") else "off track"
                    e = discord.Embed(
                        description=f"❌ **{l['driver']}** — lap **{fmt_ms(l['ms'])}** invalidated ({why})",
                        color=COLOR_RED)
                    e.set_footer(text=f"{l['car']} · does not count for the leaderboards")
                    await ch.send(embed=e)
                st = bot_state()
                st["lapfeed_ts"] = last
                save_state(st)
        except Exception as ex:
            print(f"lapfeed: {ex}", flush=True)
        await asyncio.sleep(LAPFEED_INTERVAL_S)


async def announce_records(ch, bests, prev_bests, prev_overall):
    for key, rec in bests.items():
        t, car = key
        old = prev_bests.get(key)
        if old is not None and rec["time_ms"] >= old["time_ms"]:
            continue
        is_track_rec = t not in prev_overall or rec["time_ms"] < prev_overall[t]["time_ms"]
        first_ever = t not in prev_overall
        if is_track_rec:
            e = discord.Embed(
                title="🏁 FIRST TRACK RECORD" if first_ever else "👑 NEW TRACK RECORD",
                description=f"**{rec['driver']}** stops the clock at **{fmt_ms(rec['time_ms'])}**",
                color=COLOR_GOLD)
            e.add_field(name="Track", value=t)
            e.add_field(name="Car", value=car)
            if not first_ever:
                po = prev_overall[t]
                delta = (po["time_ms"] - rec["time_ms"]) / 1000
                e.add_field(name="Previous record", inline=False,
                            value=f"{fmt_ms(po['time_ms'])} by {po['driver']} (−{delta:.3f}s)")
        else:
            e = discord.Embed(title="New car record",
                              description=f"**{rec['driver']}** — **{fmt_ms(rec['time_ms'])}**", color=COLOR_OK)
            e.add_field(name="Track", value=t)
            e.add_field(name="Car", value=car)
            if old:
                delta = (old["time_ms"] - rec["time_ms"]) / 1000
                e.add_field(name="Previous", inline=False,
                            value=f"{fmt_ms(old['time_ms'])} by {old['driver']} (−{delta:.3f}s)")
        if SITE_URL:
            e.url = SITE_URL
        e.timestamp = discord.utils.utcnow()
        msg = await ch.send(embed=e)
        if is_track_rec:
            await pin_record(t, msg)



SESS = {"Practice": "Practice", "Qualifying": "Qualifying", "Race": "The race", "Warm-up": "Warm-up", "Hotlap": "Hotlap session"}
RACE_END_PHASES = ("Overtime_Waiting_For_Others", "Waiting_For_Ai", "Waiting_For_PitBox", "Ended")
RACE_GO_PHASES = ("Start_Countdown_Lights_Off", "RollingStart_Start_Green_Flag", "RollingStart_End_Green_Flag")


async def race_watch(ch, st, mem):
    race = st.get("race") or {}
    sess, ph = race.get("session"), race.get("phase")
    if not sess or not ph:
        return
    tk = f"{st.get('track', '?')} {st.get('layout', '')}".strip()
    prev = mem.get("key")
    mem["key"] = (sess, ph)
    start = race.get("session_start")
    prev_start, mem["start"] = mem.get("start"), start
    if (ch and ANNOUNCE_SESSIONS and prev is not None and prev[0] == sess and sess != "Race"
            and prev_start and start and abs(start - prev_start) > 30 and ph == "Session"):
        await ch.send(f"🔄 New **{sess}** session at **{tk}**")
        return
    if prev is None or prev == (sess, ph) or not ch:
        return
    if prev[0] != sess:
        mem["done"] = False
        if ph == "Session" or sess != "Race":
            if ANNOUNCE_SESSIONS:
                await ch.send(f"⏱ **{SESS.get(sess, sess)}** starts at **{tk}**")
            return
    if sess == "Race" and ph in RACE_GO_PHASES and prev[1] not in RACE_GO_PHASES:
        await ch.send(embed=discord.Embed(title="🚦 **Lights out, the race is on!**", description=f"Racing at **{tk}**", color=COLOR_OK))
    elif sess == "Race" and ph == "Session" and prev[1] not in RACE_GO_PHASES and prev[0] == sess and prev[1] != "Session":
        await ch.send(embed=discord.Embed(title="🚦 **Lights out, the race is on!**", description=f"Racing at **{tk}**", color=COLOR_OK))
    if sess == "Race" and ph in RACE_END_PHASES and not mem.get("done"):
        mem["done"] = True
        await asyncio.sleep(8)
        st2 = await get_status() or st
        cars = [c for c in ((st2.get("race") or {}).get("cars") or []) if c.get("name") and c.get("pos")]
        cars.sort(key=lambda c: c["pos"])
        if not cars:
            return
        w = cars[0]
        medals = ["🥇", "🥈", "🥉"]
        rows = []
        for i, c in enumerate(cars[:15]):
            pre = medals[i] if i < 3 else f"`{i + 1}.`"
            best = f" · best {fmt_ms(c['best_ms'])}" if c.get("best_ms") else ""
            tag = " · DSQ" if (c.get("flags") or 0) & 8 else " · DNF" if (c.get("flags") or 0) & 32 else ""
            rows.append(f"{pre} **{c['name']}** — {c.get('car') or '?'} · {c.get('laps') or 0} laps{best}{tag}")
        e = discord.Embed(title="🏁 CHEQUERED FLAG", description=f"**{w['name']}** wins in the {w['car']}", color=COLOR_GOLD)
        e.add_field(name="Final classification", value="\n".join(rows), inline=False)
        if SITE_URL:
            e.url = SITE_URL
        e.timestamp = discord.utils.utcnow()
        await ch.send(embed=e)

async def announcer():
    await client.wait_until_ready()
    prev_bests, prev_overall = leaderboard_snapshot()
    prev_track, prev_players = None, None
    prev_session_id, last_classification = None, []
    race_mem = {}
    rename_pending = False
    while not client.is_closed():
        try:
            ch = await announce_channel()
            bests, overall = leaderboard_snapshot()
            if ch and ANNOUNCE_RECORDS:
                await announce_records(ch, bests, prev_bests, prev_overall)
            prev_bests, prev_overall = bests, overall

            state = challenge_state()
            if state.get("active"):
                target = challenge_server_name(state)
                cfg = config()
                if cfg.get("server_name") != target:
                    cfg["server_name"] = target
                    jwrite(CONFIG_FILE, cfg)
                    rename_pending = True
                if rename_pending:
                    st_now = await get_status()
                    if st_now and st_now.get("players", 0) == 0 and await restart_game_server():
                        rename_pending = False
                        if ch:
                            await ch.send(embed=discord.Embed(title="⏱ Server name updated",
                                                              description=f"**{target}**", color=COLOR_GOLD))

            st = await get_status()
            if st:
                await race_watch(ch, st, race_mem)
                sess = st.get("session") or {}
                sid = sess.get("id")
                cls = sess.get("classification") or []
                if cls:
                    last_classification = cls
                if (ch and prev_session_id and sid and sid != prev_session_id and last_classification
                        and st.get("mode") == "RACE_WEEKEND" and not st.get("race")):
                    await ch.send(embed=podium_embed(last_classification))
                    m = challenge_state()
                    if m.get("active") and m.get("mode") == "race":
                        m["last_winner"] = last_classification[0]["driver"]
                        jwrite(CHALLENGE_STATE_FILE, m)
                    last_classification = []
                prev_session_id = sid or prev_session_id

                tk = st.get("track")
                if ch and ANNOUNCE_TRACK_CHANGES and prev_track and tk and tk != prev_track:
                    e = discord.Embed(title="🔀 Track change", description=f"Now racing at **{tk}**", color=COLOR_INFO)
                    laps = track_records(current_track_key())
                    if laps:
                        e.add_field(name="Record to beat",
                                    value=f"{fmt_ms(laps[0]['time_ms'])} — {laps[0]['driver']} ({laps[0]['car']})")
                    await ch.send(embed=e)
                prev_track = tk or prev_track
                names = {d["name"] for d in st.get("drivers", [])}
                if ch and ANNOUNCE_JOINS and prev_players is not None:
                    for n in sorted(names - prev_players):
                        await ch.send(f"🟢 **{n}** joined the server")
                    for n in sorted(prev_players - names):
                        await ch.send(f"⚪ **{n}** left the server")
                prev_players = names
        except Exception as ex:
            print(f"announcer: {ex}", flush=True)
        await asyncio.sleep(ANNOUNCER_INTERVAL_S)


async def session_end_watch():
    await client.wait_until_ready()
    pending = None
    while not client.is_closed():
        await asyncio.sleep(AUTO_RESTART_CHECK_S)
        try:
            mode = season().get("game_type", "").replace("GameModeType_", "").upper()
            if not AUTO_RESTART or mode not in AUTO_RESTART_MODES or config().get("cycle"):
                pending = None
                continue
            started = await game_server_started_at()
            if not started:
                continue
            logs = await game_server_logs_since(started)
            ended = logs.rfind("OnExitGamemode")
            if ended < 0 or logs.rfind("Restart Season") > ended:
                pending = None
                continue
            key = (started, ended)
            if pending is None or pending[0] != key:
                pending = (key, time.time())
                continue
            if time.time() - pending[1] < AUTO_RESTART_DELAY_S:
                continue
            pending = None
            print("session over: restarting the game server for a new session", flush=True)
            ok = await restart_game_server()
            ch = await announce_channel()
            if ch:
                await ch.send(embed=discord.Embed(
                    title="🔄 New session" if ok else "Session over, restart failed",
                    description=(f"The {mode.title()} session is over: a new one is starting at "
                                 f"**{current_track_key()}**." if ok else "Check the game server logs."),
                    color=COLOR_INFO if ok else COLOR_RED))
        except Exception as ex:
            print(f"session watch: {ex}", flush=True)


async def track_autocomplete(inter, current: str):
    return [app_commands.Choice(name=f"{e['key']} · {e['track_length'] / 1000:.1f} km", value=e["key"])
            for e in events_list() if current.lower() in e["key"].lower()][:25]


async def race_track_autocomplete(inter, current: str):
    return [app_commands.Choice(name=f"{e['key']} · {e['track_length'] / 1000:.1f} km", value=e["key"])
            for e in events_list(True) if current.lower() in e["key"].lower()][:25]


async def db_track_autocomplete(inter, current: str):
    tracks = list(jread(DB_FILE, {"tracks": {}}).get("tracks", {}).keys())
    return [app_commands.Choice(name=t, value=t) for t in tracks if current.lower() in t.lower()][:25]


async def car_autocomplete(inter, current: str):
    cars = set()
    for td in jread(DB_FILE, {"tracks": {}}).get("tracks", {}).values():
        cars.update(td.get("cars", {}).keys())
    return [app_commands.Choice(name=c, value=c) for c in sorted(cars) if current.lower() in c.lower()][:25]


async def unreachable(inter):
    await inter.response.send_message("The dashboard is not reachable.", ephemeral=True)


@tree.command(name="server", description="Server status, track and records")
async def cmd_server(inter: discord.Interaction):
    st = await get_status()
    if not st:
        return await unreachable(inter)
    _, overall = leaderboard_snapshot()
    e = board_embed(st, overall)
    e.set_footer(text="Snapshot requested with /server")
    await inter.response.send_message(embed=e)


@tree.command(name="drivers", description="Who is connected right now")
async def cmd_drivers(inter: discord.Interaction):
    st = await get_status()
    if not st:
        return await unreachable(inter)
    drivers = st.get("drivers", [])
    anon = st.get("anonymous_drivers", 0)
    if not drivers and not anon:
        await inter.response.send_message("Nobody is connected right now.")
        return
    lines = []
    for d in drivers:
        state = "🟢 on track" if d.get("status") == STATUS_TRACK else "🟡 pits"
        pb = f" · PB **{fmt_ms(d['pb'])}**" if d.get("pb") else ""
        lines.append(f"{state} **{d['name']}** — {d.get('car', '?')}{pb}")
    lines += ["⚪ *driver connecting…*"] * anon
    e = discord.Embed(title=f"Connected drivers · {st.get('players', 0)}", description="\n".join(lines),
                      color=COLOR_INFO)
    await inter.response.send_message(embed=e)


@tree.command(name="record", description="Record and top 5 of a track")
@app_commands.describe(track="Track (empty = current track)")
@app_commands.autocomplete(track=db_track_autocomplete)
async def cmd_record(inter: discord.Interaction, track: str = ""):
    t = track or current_track_key()
    laps = track_records(t)
    if not laps:
        await inter.response.send_message(f"No lap times recorded for **{t}**.")
        return
    best = laps[0]
    e = discord.Embed(title=f"Record — {t}",
                      description=f"👑 **{fmt_ms(best['time_ms'])}** — {best['driver']} ({best['car']}, {best['date']})",
                      color=COLOR_GOLD)
    rows = []
    for i, l in enumerate(laps[:5]):
        gap = "" if i == 0 else f" `+{(l['time_ms'] - best['time_ms']) / 1000:.3f}`"
        rows.append(f"`{i + 1}.` **{fmt_ms(l['time_ms'])}** {l['driver']} — {l['car']}{gap}")
    e.add_field(name="Top 5", value="\n".join(rows), inline=False)
    if SITE_URL:
        e.url = SITE_URL
    await inter.response.send_message(embed=e)


@tree.command(name="leaderboard", description="Leaderboard of one car")
@app_commands.describe(car="Car", track="Track (empty = current track)")
@app_commands.autocomplete(car=car_autocomplete, track=db_track_autocomplete)
async def cmd_leaderboard(inter: discord.Interaction, car: str, track: str = ""):
    t = track or current_track_key()
    cd = jread(DB_FILE, {"tracks": {}}).get("tracks", {}).get(t, {}).get("cars", {}).get(car)
    if not cd or not cd.get("entries"):
        await inter.response.send_message(f"No lap times for **{car}** at **{t}**.")
        return
    entries = cd["entries"]
    best = entries[0]["time_ms"]
    rows = []
    for i, en in enumerate(entries[:10]):
        gap = "" if i == 0 else f" `+{(en['time_ms'] - best) / 1000:.3f}`"
        rows.append(f"`{i + 1}.` **{fmt_ms(en['time_ms'])}** {en['driver']}{gap}")
    await inter.response.send_message(embed=discord.Embed(title=f"{car} — {t}", description="\n".join(rows),
                                                          color=COLOR_INFO))


@tree.command(name="tracks", description="All available tracks, with their records")
async def cmd_tracks(inter: discord.Interaction):
    evs = events_list()
    race_keys = {e["key"] for e in events_list(True)}
    cur = current_track_key()
    _, overall = leaderboard_snapshot()
    rows = []
    for ev in evs:
        mark = "▸ " if ev["key"] == cur else ""
        rec = overall.get(ev["key"])
        rec_s = f" · 👑 {fmt_ms(rec['time_ms'])}" if rec else ""
        no_race = "" if ev["key"] in race_keys else " · *no race*"
        rows.append(f"{mark}**{ev['key']}** — {ev['track_length'] / 1000:.1f} km{rec_s}{no_race}")
    half = (len(rows) + 1) // 2
    e = discord.Embed(title=f"Available tracks · {len(evs)}", color=COLOR_INFO)
    e.add_field(name="\u200b", value="\n".join(rows[:half]) or "—")
    e.add_field(name="\u200b", value="\n".join(rows[half:]) or "—")
    e.set_footer(text=f"Current track: {cur} · change it with /changetrack · race weekends: {len(race_keys)} tracks")
    await inter.response.send_message(embed=e)


@tree.command(name="changetrack", description="Change track, optionally weather, duration and mode (admin)")
@app_commands.describe(track="Destination track", weather="Weather of the new session (optional)",
                       duration="Session length in minutes (optional)", mode="Game mode (optional)", force=FORCE_HELP)
@app_commands.autocomplete(track=track_autocomplete)
@app_commands.choices(weather=[app_commands.Choice(name=k.title(), value=k) for k in WEATHER],
                      mode=[app_commands.Choice(name=k.title(), value=k) for k in MODES])
async def cmd_changetrack(inter: discord.Interaction, track: str,
                          weather: app_commands.Choice[str] = None,
                          duration: app_commands.Range[int, MIN_SESSION_MIN, MAX_SESSION_MIN] = None,
                          mode: app_commands.Choice[str] = None, force: bool = False):
    if not is_admin(inter):
        return await deny(inter)
    s = season()
    game_type = MODES[mode.value] if mode else s.get("game_type", "")
    race = is_race_weekend(game_type)
    ev = find_event(track, race)
    if not ev:
        hint = " Race weekends are not available on this layout." if race and find_event(track) else " Use /tracks for the list."
        await inter.response.send_message(f"Track `{track}` not found.{hint}", ephemeral=True)
        return
    if not await drivers_guard(inter, force, "changing track"):
        return
    await inter.response.defer()
    s["event"] = event_block(ev)
    extra = []
    if weather:
        s["weather_type"] = WEATHER[weather.value]
        extra.append(f"weather **{weather.name}**")
    if duration:
        s.setdefault("game_config", {})["practice_duration"] = duration * 60
        extra.append(f"duration **{duration} min**")
    if mode:
        s["game_type"] = game_type
        if race:
            s["game_config"] = {**race_config_defaults(), **{k: v for k, v in s.get("game_config", {}).items()
                                                            if k.startswith(("qualify_", "race_", "warmup_"))}}
        extra.append(f"mode **{mode.name}**")
    jwrite(SEASON_FILE, s)
    st = await get_status()
    n = st.get("players", 0) if st else 0
    ok = await restart_game_server()
    e = discord.Embed(title="🔀 Track changed" if ok else "Config written, restart failed",
                      description=f"Now racing at **{ev['key']}**" + (f"\nwith {', '.join(extra)}" if extra else ""),
                      color=COLOR_OK if ok else COLOR_RED)
    e.add_field(name="Length", value=f"{ev['track_length'] / 1000:.3f} km")
    e.add_field(name="Pit boxes", value=str(ev["max_pit_slot"]))
    laps = track_records(ev["key"])
    e.add_field(name="Record to beat", inline=False,
                value=(f"👑 {fmt_ms(laps[0]['time_ms'])} — {laps[0]['driver']} ({laps[0]['car']})" if laps
                       else "None yet: the first valid lap sets the record"))
    if n:
        e.set_footer(text=f"{plural(n, 'driver')} were connected and have been disconnected")
    await inter.followup.send(embed=e)


@tree.command(name="mode", description="Change the game mode (admin)")
@app_commands.choices(mode=[app_commands.Choice(name=k.title(), value=k) for k in MODES])
@app_commands.describe(restart="Restart the server now to apply", force=FORCE_HELP)
async def cmd_mode(inter: discord.Interaction, mode: app_commands.Choice[str], restart: bool = True, force: bool = False):
    if not is_admin(inter):
        return await deny(inter)
    s = season()
    game_type = MODES[mode.value]
    race = is_race_weekend(game_type)
    cur = current_track_key()
    ev = find_event(cur, race)
    if not ev:
        await inter.response.send_message(f"**{cur}** has no {'race weekend' if race else 'practice'} event: "
                                          f"use /changetrack with a mode.", ephemeral=True)
        return
    if restart and not await drivers_guard(inter, force, "changing the mode"):
        return
    await inter.response.defer()
    s["game_type"] = game_type
    s["event"] = event_block(ev)
    if race and "race_duration" not in s.get("game_config", {}):
        s["game_config"] = {**race_config_defaults(), **s.get("game_config", {})}
    jwrite(SEASON_FILE, s)
    ok = await restart_game_server() if restart else None
    await inter.followup.send(f"Mode set to **{mode.name}**{restart_suffix(ok)}")


@tree.command(name="raceweekend", description="Set up a race weekend: practice, qualifying and race (admin)")
@app_commands.describe(track="Track (empty = current track)", practice="Practice minutes (0 = none)",
                       qualifying="Qualifying minutes (0 = none)", race="Race length", race_type="Race length in laps or minutes",
                       mandatory_pit="Mandatory pit stop", tyre_change="The pit stop must change tyres",
                       refuel="The pit stop must refuel", weather="Weather (optional)", force=FORCE_HELP)
@app_commands.autocomplete(track=race_track_autocomplete)
@app_commands.choices(race_type=[app_commands.Choice(name="Laps", value="laps"), app_commands.Choice(name="Minutes", value="minutes")],
                      weather=[app_commands.Choice(name=k.title(), value=k) for k in WEATHER])
async def cmd_raceweekend(inter: discord.Interaction, track: str = "",
                          practice: app_commands.Range[int, 0, 240] = 15,
                          qualifying: app_commands.Range[int, 0, 120] = 10,
                          race: app_commands.Range[int, 1, 300] = 10,
                          race_type: app_commands.Choice[str] = None,
                          mandatory_pit: bool = False, tyre_change: bool = False, refuel: bool = False,
                          weather: app_commands.Choice[str] = None, force: bool = False):
    if not is_admin(inter):
        return await deny(inter)
    key = track or current_track_key()
    ev = find_event(key, True)
    if not ev:
        await inter.response.send_message(f"**{key}** has no race weekend event. Pick another track.", ephemeral=True)
        return
    if not await drivers_guard(inter, force, "starting a race weekend"):
        return
    await inter.response.defer()
    by_time = race_type is not None and race_type.value == "minutes"
    gc = race_config_defaults()
    gc.update({"practice_duration": practice * 60, "qualify_duration": qualifying * 60,
               "race_duration": race * 60 if by_time else race,
               "race_duration_type": "GameModeSelectionDuration_TIME" if by_time else "GameModeSelectionDuration_LAPS",
               "mandatory_pit_stop": mandatory_pit, "requires_tyre_change": tyre_change, "requires_refuelling": refuel})
    s = season()
    s["game_type"] = "GameModeType_RACE_WEEKEND"
    s["event"] = event_block(ev)
    s["game_config"] = gc
    if weather:
        s["weather_type"] = WEATHER[weather.value]
    jwrite(SEASON_FILE, s)
    ok = await restart_game_server()
    plan = [f"Practice **{practice}′**" if practice else None, f"Qualifying **{qualifying}′**" if qualifying else None,
            f"Race **{race}{'′' if by_time else ' laps'}**"]
    pit = [x for x, on in (("mandatory pit stop", mandatory_pit), ("tyre change", tyre_change), ("refuelling", refuel)) if on]
    e = discord.Embed(title="🏁 Race weekend ready" if ok else "Config written, restart failed",
                      description=f"**{ev['key']}** — " + " › ".join(x for x in plan if x),
                      color=COLOR_GOLD if ok else COLOR_RED)
    if pit:
        e.add_field(name="Pit rules", value=", ".join(pit).capitalize())
    if weather:
        e.add_field(name="Weather", value=weather.name)
    await inter.followup.send(embed=e)


@tree.command(name="duration", description="Session length in minutes (admin)")
@app_commands.describe(minutes=f"From {MIN_SESSION_MIN} to {MAX_SESSION_MIN}", restart="Restart now to apply", force=FORCE_HELP)
async def cmd_duration(inter: discord.Interaction,
                       minutes: app_commands.Range[int, MIN_SESSION_MIN, MAX_SESSION_MIN], restart: bool = True,
                       force: bool = False):
    if not is_admin(inter):
        return await deny(inter)
    if restart and not await drivers_guard(inter, force, "changing the session length"):
        return
    await inter.response.defer()
    s = season()
    s.setdefault("game_config", {})["practice_duration"] = minutes * 60
    jwrite(SEASON_FILE, s)
    ok = await restart_game_server() if restart else None
    await inter.followup.send(f"Session length: **{minutes} minutes**{restart_suffix(ok)}")


@tree.command(name="weather", description="Change the weather (admin)")
@app_commands.choices(weather=[app_commands.Choice(name=k.title(), value=k) for k in WEATHER])
@app_commands.describe(restart="Restart now to apply", force=FORCE_HELP)
async def cmd_weather(inter: discord.Interaction, weather: app_commands.Choice[str], restart: bool = True,
                      force: bool = False):
    if not is_admin(inter):
        return await deny(inter)
    if restart and not await drivers_guard(inter, force, "changing the weather"):
        return
    await inter.response.defer()
    s = season()
    s["weather_type"] = WEATHER[weather.value]
    jwrite(SEASON_FILE, s)
    ok = await restart_game_server() if restart else None
    await inter.followup.send(f"Weather set to **{weather.name}**{restart_suffix(ok)}")


@tree.command(name="maxdrivers", description="Maximum number of drivers (admin)")
@app_commands.describe(count=f"From 1 to {MAX_PLAYERS_LIMIT}", restart="Restart now to apply", force=FORCE_HELP)
async def cmd_maxdrivers(inter: discord.Interaction, count: app_commands.Range[int, 1, MAX_PLAYERS_LIMIT],
                         restart: bool = True, force: bool = False):
    if not is_admin(inter):
        return await deny(inter)
    if restart and not await drivers_guard(inter, force, "changing the driver limit"):
        return
    await inter.response.defer()
    c = config()
    c["max_players"] = count
    jwrite(CONFIG_FILE, c)
    ok = await restart_game_server() if restart else None
    await inter.followup.send(f"Maximum drivers: **{count}**{restart_suffix(ok)}")


@tree.command(name="password", description="Set or remove the server password (admin)")
@app_commands.describe(password="The password, or 'off' for an open server", restart="Restart now to apply", force=FORCE_HELP)
async def cmd_password(inter: discord.Interaction, password: str, restart: bool = True, force: bool = False):
    if not is_admin(inter):
        return await deny(inter)
    if restart and not await drivers_guard(inter, force, "changing the password"):
        return
    await inter.response.defer(ephemeral=True)
    c = config()
    open_srv = password.lower() in ("off", "no", "none", "")
    c["driver_password"] = "" if open_srv else password
    jwrite(CONFIG_FILE, c)
    ok = await restart_game_server() if restart else None
    msg = "Server **open to everyone**" if open_srv else "Password set"
    await inter.followup.send(msg + restart_suffix(ok), ephemeral=True)


@tree.command(name="servername", description="Rename the server (admin)")
@app_commands.describe(name="New name", restart="Restart now to apply", force=FORCE_HELP)
async def cmd_servername(inter: discord.Interaction, name: str, restart: bool = True, force: bool = False):
    if not is_admin(inter):
        return await deny(inter)
    if restart and not await drivers_guard(inter, force, "renaming the server"):
        return
    await inter.response.defer()
    c = config()
    c["server_name"] = name[:SERVER_NAME_MAX]
    jwrite(CONFIG_FILE, c)
    ok = await restart_game_server() if restart else None
    await inter.followup.send(f"Server name: **{name[:SERVER_NAME_MAX]}**{restart_suffix(ok)}")


@tree.command(name="cycle", description="Start a new session automatically when one ends (admin)")
@app_commands.describe(enabled="On: sessions loop by themselves", restart="Restart now to apply", force=FORCE_HELP)
async def cmd_cycle(inter: discord.Interaction, enabled: bool, restart: bool = True, force: bool = False):
    if not is_admin(inter):
        return await deny(inter)
    if restart and not await drivers_guard(inter, force, "changing session cycling"):
        return
    await inter.response.defer()
    c = config()
    c["cycle"] = enabled
    jwrite(CONFIG_FILE, c)
    ok = await restart_game_server() if restart else None
    await inter.followup.send(("🔁 Sessions now **loop by themselves**" if enabled
                               else "Sessions **stop** when they end" + (" (the bot restarts the server)" if AUTO_RESTART else ""))
                              + restart_suffix(ok))


@tree.command(name="settings", description="Current server and session settings (admin)")
async def cmd_settings(inter: discord.Interaction):
    if not is_admin(inter):
        return await deny(inter)
    c, s = config(), season()
    gc, ev = s.get("game_config", {}), s.get("event", {})
    mode = MODE_NAMES.get(s.get("game_type", ""), s.get("game_type", "?"))
    e = discord.Embed(title="Server settings", color=COLOR_DARK)
    e.add_field(name="Name", value=c.get("server_name", "?"), inline=False)
    e.add_field(name="Track", value=f"{ev.get('track', '?')} {ev.get('layout', '')}")
    e.add_field(name="Mode", value=mode)
    e.add_field(name="Weather", value=str(s.get("weather_type", "?")).replace("GameModeSelectionWeatherType_", "").title())
    if is_race_weekend(s.get("game_type", "")):
        laps = "LAPS" in str(gc.get("race_duration_type", ""))
        e.add_field(name="Weekend", inline=False, value=(
            f"Practice {gc.get('practice_duration', 0) // 60}′ · Qualifying {gc.get('qualify_duration', 0) // 60}′ · "
            f"Race {gc.get('race_duration', 0) if laps else gc.get('race_duration', 0) // 60}{' laps' if laps else '′'}"
            + (" · mandatory pit" if gc.get("mandatory_pit_stop") else "")))
    else:
        e.add_field(name="Session", value=f"{gc.get('practice_duration', 0) // 60} min")
    e.add_field(name="Max drivers", value=str(c.get("max_players", "?")))
    e.add_field(name="Password", value="set" if c.get("driver_password") else "none (open)")
    e.add_field(name="Cycle", value="on" if c.get("cycle") else "off")
    allowed = c.get("allowed_cars_list_full") or []
    ch = challenge_state()
    e.add_field(name="Cars", inline=False, value=(f"{len(allowed)} allowed" + (f" · {ch.get('class')} challenge" if ch.get("active") else ""))
                if allowed else "all cars")
    await inter.response.send_message(embed=e, ephemeral=True)


@tree.command(name="restart", description="Restart the game server (admin)")
@app_commands.describe(force=FORCE_HELP)
async def cmd_restart(inter: discord.Interaction, force: bool = False):
    if not is_admin(inter):
        return await deny(inter)
    if not await drivers_guard(inter, force, "restarting"):
        return
    await inter.response.defer()
    st = await get_status()
    n = st.get("players", 0) if st else 0
    ok = await restart_game_server()
    msg = "Server restarted." if ok else "Restart failed, check the logs."
    if n and ok:
        msg += f" ({plural(n, 'driver')} disconnected)"
    await inter.followup.send(msg)


@tree.command(name="challenge", description="Challenge mode: one car class or pack, record holder in the server name (admin)")
@app_commands.describe(track="Challenge track",
                       car_class="Car class or pack (see /packs)",
                       mode="Hotlap: single lap · Race: race weekend, the winner names the server",
                       weather="Weather (optional)",
                       duration="Hotlap: session minutes · Race: race laps (optional)",
                       title="Track name shown in the server name (optional, e.g. Nordschleife)",
                       target_time="Hotlap: time to beat until a real lap is faster, e.g. 6:48.734 (optional)",
                       target_driver="Name shown with the time to beat", force=FORCE_HELP)
@app_commands.autocomplete(track=track_autocomplete)
@app_commands.rename(car_class="class")
@app_commands.choices(car_class=class_choices(),
                      mode=[app_commands.Choice(name="Hotlap", value="hotlap"),
                            app_commands.Choice(name="Race", value="race")],
                      weather=[app_commands.Choice(name=k.title(), value=k) for k in WEATHER])
async def cmd_challenge(inter: discord.Interaction, track: str,
                        car_class: app_commands.Choice[str] = None,
                        mode: app_commands.Choice[str] = None,
                        weather: app_commands.Choice[str] = None,
                        duration: app_commands.Range[int, 3, MAX_SESSION_MIN] = None,
                        title: str = "", target_time: str = "", target_driver: str = "", force: bool = False):
    if not is_admin(inter):
        return await deny(inter)
    race = mode is not None and mode.value == "race"
    target_ms = parse_ms(target_time) if target_time else None
    if target_time and not target_ms:
        await inter.response.send_message(f"`{target_time}` is not a lap time: use m:ss.mmm, e.g. 6:48.734.",
                                          ephemeral=True)
        return
    ev = find_event(track, race)
    if not ev:
        hint = " Race weekends are not available on this layout." if race and find_event(track) else " Use /tracks."
        await inter.response.send_message(f"Track `{track}` not found.{hint}", ephemeral=True)
        return
    ch = challenge_def()
    cls = (car_class.value if car_class else ch.get("default_class", "GT3")).upper()
    cars = class_cars(cls)
    if not cars:
        await inter.response.send_message(f"No **{class_label(cls)}** cars in the server's car list.", ephemeral=True)
        return
    if not await drivers_guard(inter, force, "starting a challenge"):
        return
    await inter.response.defer()
    s = season()
    s["event"] = event_block(ev)
    if race:
        s["game_type"] = "GameModeType_RACE_WEEKEND"
        s["game_config"] = dict(ch["race_config"])
        if duration:
            s["game_config"]["race_duration"] = duration
    else:
        s["game_type"] = "GameModeType_PRACTICE"
        if duration:
            s.setdefault("game_config", {})["practice_duration"] = duration * 60
    if weather:
        s["weather_type"] = WEATHER[weather.value]
    jwrite(SEASON_FILE, s)
    prev = challenge_state()
    state = {"active": True, "track": ev["key"], "mode": "race" if race else "hotlap", "class": cls,
             "cars": list(cars.values()),
             "last_winner": prev.get("last_winner") if prev.get("class", cls) == cls else None}
    if title.strip():
        state["title"] = title.strip()
    if target_ms and not race:
        state["target"] = {"time_ms": target_ms, "driver": target_driver.strip() or "?"}
    jwrite(CHALLENGE_STATE_FILE, state)
    c = config()
    c["allowed_cars_list_full"] = [{"car_name": k, "ballast": 0, "restrictor": 0} for k in cars]
    c["server_name"] = challenge_server_name(state)
    jwrite(CONFIG_FILE, c)
    ok = await restart_game_server()
    label = class_label(cls).upper()
    title = (f"🏆 {label} RACE STARTED" if race else f"🏁 {label} HOTLAP STARTED") if ok \
        else "Config written, restart failed"
    desc = (f"Race weekend at **{ev['key']}** — practice, qualifying and a "
            f"**{plural(s['game_config'].get('race_duration', 0), 'lap')}** race: the winner names the server"
            if race else
            f"Single-lap challenge at **{ev['key']}** — the fastest time lives in the server name")
    e = discord.Embed(title=title, description=desc, color=COLOR_GOLD if ok else COLOR_RED)
    rng = pi_range(list(cars))
    e.add_field(name=f"Allowed cars · {len(cars)}" + (f" · PI {rng[0]:.1f}–{rng[1]:.1f}" if rng else ""), inline=False,
                value="\n".join(f"• {v}" for v in sorted(set(cars.values()))) or "—")
    if race:
        e.add_field(name="Reigning champion", inline=False,
                    value=state.get("last_winner") or "Vacant: decided by the first race")
    else:
        best = challenge_best(ev["key"], list(cars.values()), state.get("target"))
        e.add_field(name="Time to beat", inline=False,
                    value=(f"🎯 {fmt_ms(best['time_ms'])} — {best['driver']} (target: the first faster lap replaces it)"
                           if best and best.get("target") else
                           f"👑 {fmt_ms(best['time_ms'])} — {best['driver']} ({best['car']})" if best
                           else "None yet: the first valid lap takes the server name"))
    e.add_field(name="Server name", value=c["server_name"], inline=False)
    await inter.followup.send(embed=e)


@tree.command(name="packs", description="Car classes and packs available for challenges")
async def cmd_packs(inter: discord.Interaction):
    e = discord.Embed(title="Challenge classes and packs", color=COLOR_INFO,
                      description="Start one with `/challenge <track> class:<pack>` (admin).")
    for cls in challenge_classes()[:25]:
        cars = class_cars(cls)
        if not cars:
            continue
        rng = pi_range(list(cars))
        names = sorted(set(cars.values()))
        listed = ", ".join(names[:6]) + (f" +{len(names) - 6}" if len(names) > 6 else "")
        desc = class_conf(cls).get("description")
        e.add_field(name=f"{class_label(cls)} · {len(cars)} cars" + (f" · PI {rng[0]:.1f}–{rng[1]:.1f}" if rng else ""),
                    value=(f"*{desc}*\n" if desc else "") + listed, inline=False)
    st = challenge_state()
    if st.get("active"):
        e.set_footer(text=f"Active now: {class_label(st.get('class', 'GT3'))} at {st.get('track', '?')}")
    await inter.response.send_message(embed=e)


@tree.command(name="challengeoff", description="Turn off challenge mode (admin)")
@app_commands.describe(force=FORCE_HELP)
async def cmd_challengeoff(inter: discord.Interaction, force: bool = False):
    if not is_admin(inter):
        return await deny(inter)
    if not await drivers_guard(inter, force, "ending the challenge"):
        return
    await inter.response.defer()
    c = config()
    c.pop("allowed_cars_list_full", None)
    c["server_name"] = SERVER_BASE_NAME
    jwrite(CONFIG_FILE, c)
    jwrite(CHALLENGE_STATE_FILE, {"active": False})
    ok = await restart_game_server()
    await inter.followup.send(f"Challenge mode **off**: all cars allowed, name restored to **{SERVER_BASE_NAME}**"
                              + ("" if ok else " · restart failed"))


async def _reply(inter, text=None, embed=None):
    try:
        await inter.followup.send(text, embed=embed) if embed else await inter.followup.send(text)
    except Exception:
        ch = await announce_channel()
        if ch:
            await (ch.send(embed=embed) if embed else ch.send(text))


def car_classes(cars_doc):
    out = {}
    for c in cars_doc.get("cars", []):
        base, _, variant = str(c.get("display_name", "")).rpartition(" - ")
        out[c.get("name")] = (base or c.get("display_name", "?"), variant)
    return out


@tree.command(name="update", description="Update the game server from Steam and restart it (admin)")
@app_commands.describe(force=FORCE_HELP)
async def cmd_update(inter: discord.Interaction, force: bool = False):
    if not is_admin(inter):
        return await deny(inter)
    if not await drivers_guard(inter, force, "updating the game"):
        return
    await inter.response.defer()
    saved_config, saved_season = config(), season()
    cars_before = car_classes(jread(CARS_FILE, {"cars": []}))
    try:
        os.remove(MARKER_FILE)
    except FileNotFoundError:
        pass
    except Exception as ex:
        await inter.followup.send(f"Could not start the update: {ex}")
        return
    if not await restart_game_server():
        await inter.followup.send("Restart failed, check the logs.")
        return
    await inter.followup.send("⬇️ Update started: checking and downloading the game files from Steam…")
    guard_warned = False
    for _ in range(UPDATE_WAIT_MIN * 6):
        await asyncio.sleep(10)
        low = (await game_server_logs()).lower()
        if "listening to udp" in low:
            restored = []
            if config() != saved_config:
                jwrite(CONFIG_FILE, saved_config)
                restored.append("server_config.json")
            if season() != saved_season:
                jwrite(SEASON_FILE, saved_season)
                restored.append("season_def.json")
            if restored:
                await restart_game_server()
            cars_after = car_classes(jread(CARS_FILE, {"cars": []}))
            new = [cars_after[k] for k in cars_after if k not in cars_before]
            e = discord.Embed(title="✅ Server updated and online",
                              description="Steam download complete, the server is back in the lobby.", color=COLOR_OK)
            if new:
                e.add_field(name=f"New cars · {len(new)}", inline=False, value="\n".join(
                    f"• {base}" + (f" · **{variant}**" if variant.upper() in CHALLENGE_CLASSES else "")
                    for base, variant in sorted(new))[:1000])
            if restored:
                e.add_field(name="Settings restored", value=", ".join(restored), inline=False)
            await _reply(inter, embed=e)
            return
        if not guard_warned and any(k in low for k in ("auth code", "steam guard", "two-factor", "2fa")):
            guard_warned = True
            await _reply(inter, "🔐 **Steam Guard**: approve the sign-in in the Steam mobile app "
                                f"(or, for an email code, run `docker attach {GAME_CONTAINER}`, type the code and "
                                "detach with `Ctrl-P` `Ctrl-Q`). Still waiting.")
    await _reply(inter, f"⏳ After {UPDATE_WAIT_MIN} minutes the server is not online yet: the download is slow "
                        f"or stuck. Check with `docker compose logs -f ace-server`.")


@tree.command(name="stop", description="Stop the game server (admin)")
@app_commands.describe(force=FORCE_HELP)
async def cmd_stop(inter: discord.Interaction, force: bool = False):
    if not is_admin(inter):
        return await deny(inter)
    if not await drivers_guard(inter, force, "stopping the server"):
        return
    await inter.response.defer()
    st = await get_status()
    n = st.get("players", 0) if st else 0
    ok = await stop_game_server()
    msg = "🔴 Server **stopped**. Start it again with `/start`." if ok else "Stop failed, check the logs."
    if n and ok:
        msg += f" ({plural(n, 'driver')} disconnected)"
    await inter.followup.send(msg)


@tree.command(name="start", description="Start the game server (admin)")
async def cmd_start(inter: discord.Interaction):
    if not is_admin(inter):
        return await deny(inter)
    await inter.response.defer()
    if not await start_game_server():
        await inter.followup.send("Start failed, check the logs.")
        return
    for _ in range(24):
        await asyncio.sleep(5)
        st = await get_status()
        if st and st.get("online"):
            await inter.followup.send(f"🟢 Server **online** — {st.get('track', '?')} {st.get('layout', '')}, in the lobby.")
            return
    await inter.followup.send("Container started, but the server is not listening yet: check the logs.")


@tree.command(name="block", description="Exclude a driver from the leaderboards (admin)")
@app_commands.describe(name="Exact driver nickname")
async def cmd_block(inter: discord.Interaction, name: str):
    if not is_admin(inter):
        return await deny(inter)
    data = {"blocked": blocked_list()}
    if name.lower() in (b.lower() for b in data["blocked"]):
        await inter.response.send_message(f"**{name}** is already blocked.", ephemeral=True)
        return
    data["blocked"].append(name)
    jwrite(BLOCKED_FILE, data)
    await inter.response.send_message(f"🚫 **{name}** excluded from the leaderboards, effective immediately.")


@tree.command(name="unblock", description="Allow a driver back into the leaderboards (admin)")
@app_commands.describe(name="Driver nickname")
async def cmd_unblock(inter: discord.Interaction, name: str):
    if not is_admin(inter):
        return await deny(inter)
    jwrite(BLOCKED_FILE, {"blocked": [b for b in blocked_list() if b.lower() != name.lower()]})
    await inter.response.send_message(f"**{name}** is back in the leaderboards.")


@tree.command(name="blocked", description="Drivers excluded from the leaderboards (admin)")
async def cmd_blocked(inter: discord.Interaction):
    if not is_admin(inter):
        return await deny(inter)
    b = blocked_list()
    await inter.response.send_message("No blocked drivers." if not b else
                                      "Blocked drivers:\n" + "\n".join(f"• {x}" for x in b), ephemeral=True)


@tree.command(name="session", description="Live timing of the current session")
async def cmd_session(inter: discord.Interaction):
    st = await get_status()
    if not st:
        return await unreachable(inter)
    title = f"Timing · {st.get('track', '?')} {st.get('layout', '')}".strip()
    line = session_line(st)
    order = race_order(st)
    if order:
        lead = order[0]
        rows = {r.get("cid"): r for r in ((st.get("timing") or {}).get("rows") or [])}
        medals = ["🥇", "🥈", "🥉"]
        lines = []
        for c in order[:15]:
            r = rows.get(c["cid"]) or {}
            pre = medals[c["pos"] - 1] if c["pos"] <= 3 else f"`P{c['pos']}`"
            best = f" · best {fmt_ms(c['best_ms'])}" if c.get("best_ms") else ""
            tags = (" · PIT " + str(c["pits"]) if c.get("pits") else "") + (" · ⚠️ penalty" if c.get("pen") else "")
            lines.append(f"{pre} **{c['name']}** — {c.get('car') or r.get('car') or '?'} · {gap_text(c, lead)}{best}{tags}")
        e = discord.Embed(title=title, description=(line + "\n\n" if line else "") + "\n".join(lines), color=COLOR_INFO)
        e.set_footer(text="Race order from the server · gaps measured at the timing lines")
        await inter.response.send_message(embed=e)
        return
    timing = (st.get("timing") or {}).get("rows") or []
    if timing:
        medals = ["🥇", "🥈", "🥉"]
        lines = []
        for i, r in enumerate(timing[:15]):
            pre = medals[i] if i < 3 and r.get("best_ms") else f"`{i + 1}.`"
            best = fmt_ms(r["best_ms"]) if r.get("best_ms") else "—"
            gap = f" (+{r['gap_ms'] / 1000:.3f})" if r.get("gap_ms") else ""
            last = (f" · last {fmt_ms(r['last_ms'])} " + ("✅" if r.get("last_ok") else "❌")) if r.get("last_ms") else ""
            lines.append(f"{pre} **{r['name']}** — {r['car']}\n"
                         f"      ⏱ **{best}**{gap}{last} · {r['valid']}/{r['laps']} valid")
        sb = (st.get("timing") or {}).get("sector_best") or []
        e = discord.Embed(title=title, description=(line + "\n\n" if line else "") + "\n".join(lines), color=COLOR_INFO)
        if any(sb):
            e.add_field(name="Best sectors (track)", inline=False,
                        value=" · ".join(f"S{i + 1} {v / 1000:.3f}" for i, v in enumerate(sb) if v))
        e.set_footer(text="Only valid laps count for the best time")
        await inter.response.send_message(embed=e)
        return
    if line:
        await inter.response.send_message(embed=discord.Embed(title=title, description=line + "\n\nNo completed laps yet.",
                                                              color=COLOR_INFO))
        return
    await inter.response.send_message("No completed laps in this session yet.")


@tree.command(name="laps", description="Latest laps with validity and sectors")
@app_commands.describe(driver="Driver name (empty = everyone)")
async def cmd_laps(inter: discord.Interaction, driver: str = ""):
    d = await api_get("/api/laps?limit=12" + (("&driver=" + urllib.parse.quote(driver)) if driver else ""))
    laps = (d or {}).get("laps") or []
    if not laps:
        await inter.response.send_message("No laps recorded.", ephemeral=True)
        return
    rows = []
    for l in laps:
        mark = "✅" if l["valid"] else "❌"
        extra = "" if l["valid"] else (f" · {plural(l['cuts'], 'cut')}" if l.get("cuts") else " · invalid")
        rows.append(f"{mark} **{fmt_ms(l['ms'])}** — {l['driver']} ({l['car']}){extra}"
                    + (f"\n      {sec_line(l['splits'])}" if l.get("splits") else ""))
    e = discord.Embed(title="Latest laps" + (f" · {driver}" if driver else ""), description="\n".join(rows),
                      color=COLOR_INFO)
    e.set_footer(text="✅ valid · ❌ invalidated by the server")
    await inter.response.send_message(embed=e)


@tree.command(name="driver", description="Statistics of a driver")
@app_commands.describe(name="Driver name")
async def cmd_driver(inter: discord.Interaction, name: str):
    d = await api_get("/api/driver?name=" + urllib.parse.quote(name))
    if not d or d.get("error"):
        await inter.response.send_message("Driver not found.", ephemeral=True)
        return
    e = discord.Embed(title=f"🏁 {d['name']}", color=COLOR_INFO)
    e.add_field(name="Laps", value=f"{d['laps']} ({d['valid']} valid · {d['invalid']} invalidated)")
    if d.get("valid_rate") is not None:
        e.add_field(name="Clean laps", value=f"{d['valid_rate']}% valid")
    if d.get("consistency_ms") is not None:
        e.add_field(name="Consistency", value=f"±{d['consistency_ms'] / 1000:.2f} s")
    e.add_field(name="Cuts", value=str(d["cuts"]))
    recs = d.get("records") or []
    if recs:
        e.add_field(name="Personal records", inline=False, value="\n".join(
            f"`{r['pos']}/{r['of']}` **{fmt_ms(r['time_ms'])}** — {r['track']} · {r['car']}" for r in recs[:6]))
    if SITE_URL:
        e.url = f"{SITE_URL}/driver/{urllib.parse.quote(d['name'])}"
    await inter.response.send_message(embed=e)


@tree.command(name="map", description="Live map with car positions")
async def cmd_map(inter: discord.Interaction):
    if SITE_URL:
        await inter.response.send_message(f"🗺️ Live map and timing: {SITE_URL}")
    else:
        await inter.response.send_message("The website is not configured.", ephemeral=True)


@tree.command(name="site", description="Link to the live timing website")
async def cmd_site(inter: discord.Interaction):
    if SITE_URL:
        await inter.response.send_message(f"📊 Live timing: {SITE_URL}")
    else:
        await inter.response.send_message("The website is not configured.", ephemeral=True)


@tree.command(name="help", description="List of the bot commands")
async def cmd_help(inter: discord.Interaction):
    e = discord.Embed(title=f"{SERVER_BASE_NAME} · commands", color=COLOR_DARK)
    e.add_field(name="Everyone", inline=False, value=(
        "`/server` status, session and records\n"
        "`/drivers` who is connected\n"
        "`/session` live timing (race order and gaps during a race)\n"
        "`/record [track]` record and top 5\n"
        "`/leaderboard <car> [track]` leaderboard of a car\n"
        "`/tracks` available tracks with records\n"
        "`/laps [driver]` latest laps with validity and sectors\n"
        "`/driver <name>` driver statistics and records\n"
        "`/packs` car classes and packs for challenges\n"
        "`/map` `/site` live timing link"))
    e.add_field(name="Admin · sessions", inline=False, value=(
        "`/changetrack <track> [weather] [duration] [mode]` full setup in one command\n"
        "`/raceweekend [track] [practice] [qualifying] [race] [race_type] [mandatory_pit]…` race weekend\n"
        "`/challenge <track> [class]` class or pack challenge (`/packs`) · `/challengeoff`\n"
        "`/mode` `/duration` `/weather` single settings\n"
        "`/cycle <on|off>` loop sessions automatically"))
    e.add_field(name="Admin · server", inline=False, value=(
        "`/settings` current configuration\n"
        "`/maxdrivers` `/password` `/servername`\n"
        "`/restart` `/stop` `/start` `/update` (Steam)\n"
        "`/block` `/unblock` `/blocked` leaderboard moderation"))
    e.set_footer(text="Commands that restart the server ask for force: True while drivers are connected")
    await inter.response.send_message(embed=e, ephemeral=True)


@tree.error
async def on_command_error(inter: discord.Interaction, error: app_commands.AppCommandError):
    print(f"command {inter.command.name if inter.command else '?'}: {error}", flush=True)
    msg = "Something went wrong, please try again in a moment."
    try:
        if inter.response.is_done():
            await inter.followup.send(msg, ephemeral=True)
        else:
            await inter.response.send_message(msg, ephemeral=True)
    except Exception:
        pass


@client.event
async def on_ready():
    await tree.sync()
    for job in (announcer, board_loop, presence_loop, lapfeed_loop, session_end_watch):
        client.loop.create_task(job())
    print(f"Bot online as {client.user} — announcement channel: {CHANNEL_ID or 'not set'}", flush=True)


if __name__ == "__main__":
    if not TOKEN:
        print("DISCORD_BOT_TOKEN is not set: the bot is idle.", flush=True)
        while True:
            time.sleep(3600)
    client.run(TOKEN)
