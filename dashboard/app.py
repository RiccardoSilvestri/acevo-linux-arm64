import base64
import calendar
import hashlib
import html
import json
import os
import re
import select
import socket
import statistics
import sys
import struct
import threading
import time
import urllib.parse
import urllib.request
from collections import deque
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn



def _env(name, default, cast=str):
    v = os.environ.get(name)
    return default if v is None or v == "" else cast(v)


def _flag(name, default):
    return _env(name, "1" if default else "0").lower() in ("1", "true", "yes", "on")


LW_DIR = _env("ACE_LAPWATCH_DIR", "/dash-data/lapwatch")
LW_SOCK = _env("ACE_LAPWATCH_SOCK", os.path.join(LW_DIR, "live.sock"))
HISTORY_FILE = _env("ACE_HISTORY", "/dash-data/laps_history.jsonl")
LOG_FALLBACK = _flag("ACE_LOG_FALLBACK", False)

ACE_API = _env("ACE_API", "http://ace-server:8000/")
LOG_FILE = _env("ACE_LOG", "/logs/server.log")
CONFIG_FILE = _env("ACE_CONFIG", "/srv-config/server_config.json")
SEASON_FILE = _env("ACE_SEASON", "/srv-config/season_def.json")
CARS_FILE = _env("ACE_CARS", "/srv-config/cars.json")
DB_FILE = _env("ACE_DB", "/dash-data/laptimes.json")
BIND_HOST = _env("BIND_HOST", "0.0.0.0")
PORT = _env("PORT", 8080, int)
REFRESH_S = _env("REFRESH_S", 1.5, float)

SITE_NAME = _env("SITE_NAME", "ACE Live Timing")
SITE_DESCRIPTION = _env("SITE_DESCRIPTION", "Live timing, track map and car telemetry for an Assetto Corsa EVO server")
SITE_FOOTER = _env("SITE_FOOTER", "Live data from the game server · invalid laps (track limits, cuts) never count towards leaderboards")
SITE_ACCENT = _env("SITE_ACCENT", "")
SITE_LOCALE = _env("SITE_LOCALE", "en-GB")
SITE_NAME_FROM_SERVER = _flag("SITE_NAME_FROM_SERVER", True)
SITE_POWERED_BY = _flag("SITE_POWERED_BY", True)
SITE_REPO_URL = _env("SITE_REPO_URL", "https://github.com/RiccardoSilvestri/acevo-linux-arm64")
SITE_REPO_LABEL = _env("SITE_REPO_LABEL", "acevo-linux-arm64")
SPEED_UNIT = _env("SPEED_UNIT", "kmh").lower()
HIDDEN_TEXT = _env("HIDDEN_TEXT", "[hidden]")
DEFAULT_TRACK = _env("DEFAULT_TRACK", "Track")
DEFAULT_SERVER_NAME = _env("DEFAULT_SERVER_NAME", "ACE Server")
UNKNOWN_CAR = _env("UNKNOWN_CAR", "Unknown car")
UNKNOWN_DRIVER = _env("UNKNOWN_DRIVER", "Driver")

MIN_LAP_MS = _env("MIN_LAP_MS", 30000, int)
MAX_LAP_MS = _env("MAX_LAP_MS", 900000, int)
MIN_SECTOR_MS = _env("MIN_SECTOR_MS", 5000, int)
MAX_SECTOR_MS = _env("MAX_SECTOR_MS", 300000, int)
MIN_SPLITS_TO_SAVE = _env("MIN_SPLITS_TO_SAVE", 1, int)
HISTORY_SIZE = _env("HISTORY_SIZE", 3000, int)
INCIDENTS_SIZE = _env("INCIDENTS_SIZE", 300, int)
PENDING_LAP_TTL_S = _env("PENDING_LAP_TTL_S", 900, int)
RECORD_HISTORY_KEEP = _env("RECORD_HISTORY_KEEP", 50, int)
CONSISTENCY_WINDOW = _env("CONSISTENCY_WINDOW", 1.07, float)
CONSISTENCY_LAPS = _env("CONSISTENCY_LAPS", 15, int)
LOG_TAIL_BYTES = _env("LOG_TAIL_BYTES", 1048576, int)
MAX_WS_CLIENTS = _env("MAX_WS_CLIENTS", 150, int)
MAX_SSE_CLIENTS = _env("MAX_SSE_CLIENTS", 25, int)
WS_QUEUE = _env("WS_QUEUE", 300, int)
WS_PING_S = _env("WS_PING_S", 20, float)
HEARTBEAT_S = _env("HEARTBEAT_S", 5, float)
HELLO_LAPS = _env("HELLO_LAPS", 60, int)
CHECK_ORIGIN = _flag("CHECK_ORIGIN", True)

STATUS_TRACK = "track"
STATUS_PIT = "pit"


_ENV_BLOCKED = {n.strip().lower()
                for n in os.environ.get("BLOCKED_DRIVERS", "").split(",")
                if n.strip()}
BLOCKED_FILE = _env("ACE_BLOCKED", "/dash-data/blocked.json")
REMOVED_FILE = _env("ACE_REMOVED", "/dash-data/removed.json")


def removed_laps():
    try:
        with open(REMOVED_FILE) as f:
            return {(r.get("track", "*"), r["car"], r["driver"].lower(),
                     r["time_ms"])
                    for r in json.load(f).get("removed", [])}
    except Exception:
        return set()


def blocked_drivers():
    extra = set()
    try:
        with open(BLOCKED_FILE) as f:
            extra = {str(n).lower() for n in json.load(f).get("blocked", [])}
    except Exception:
        pass
    return _ENV_BLOCKED | extra
APP_DIR = os.path.dirname(os.path.abspath(__file__))

ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]|\x1b\[\?25[hl]")
LINE_RE = re.compile(
    r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\.\d+\]\s+\[(\w+)\]\s+\[(\w+)\]\s+(.*)"
)
PLAYERS_RE = re.compile(r"Server updated: (\d+) players")
IP_RE = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")
STEAMID_RE = re.compile(r"\b7656\d{13}\b")


JOIN_NAME_RE = re.compile(
    r"connecting gamecar (\S+) \(([^|)]{2,48}?)\s*\|\s*(\d{17})\)")

JOIN_CAR_RE = re.compile(
    r"(\d{17}) connected \((?:true|false)\) on car ([a-z0-9_]+), with new carId (\S+)")

LEAVE_RE = re.compile(r"despawning (.{2,48}?) \(\d{17}\) on car")
DISCONNECT_RE = re.compile(r"Disconnected carId (\S+)")

PENALTY_RUNTIME_RE = re.compile(
    r"Penalty Type PenaltyType_(\w+) has no trans?formation")


NEW_LAP_RE = re.compile(r"New lap carId (\S+): (\d{1,2}):(\d{2})\.(\d{3})")


PIT_STATE_RE = re.compile(r"\[SERVER\]\[(\S+)\] Received pit_state:(.*)")
ON_TRACK_RE = re.compile(r"car on track but invalid pit id (\S+)")


SPLIT_RE = re.compile(r"On Split start \w+ end \w+ id (\d+) splittime (\d+)")


LAP_MS_PATTERNS = [
    re.compile(r'(?:best_?lap|lap_?time|laptime)(?:_ms)?["\':\s=]+(\d{4,7})\b', re.I),
]
LAP_STR_PATTERNS = [
    re.compile(r'(?:best ?lap|lap ?time|laptime)[:\s]+(\d{1,2}[:.]\d{2}[.:]\d{3})', re.I),
]

EVENT_MAP = [
    (re.compile(r"Listening to UDP", re.I), "Server started"),
    (re.compile(r"Restart Season", re.I), "New session started"),
]

SESSION_START_RE = re.compile(
    r"Listening to UDP|Restart Season|Remote .*created", re.I)


DUMP_NAME_RE = re.compile(r'"name":\s*"([^"]{2,40})"')
DUMP_FOLDER_RE = re.compile(r'"folder_path":\s*"content')
DUMP_EVENT_RE = re.compile(r'"event_name":\s*"(.+?)\s+(?:Time Attack|Race)"')

PENALTY_TEXT = {
    "Disqualification": "Disqualified",
    "Drive_Through": "Drive-through penalty",
    "Stop_And_Go": "Stop & go penalty",
    "Time_Penalty_Seconds": "Time penalty",
    "InvalidLap": "Lap invalidated",
    "InvalidNextLap": "Next lap invalidated",
    "Remove_Best_Laptime": "Best lap time removed",
    "Warning": "Warning",
    "Reprimand": "Reprimand",
    "Fine": "Fine",
    "Penalty_Laps": "Penalty laps",
    "Start_From_Pitlane": "Pit lane start",
    "Drop_Of_Grid_Position": "Grid drop",
    "Drop_Of_Place_In_Classification": "Classification drop",
    "MP_TeleportToPit": "Car returned to pits",
}
INVESTIGATION_TEXT = {
    "Collision": "Collision",
    "Racecar_Cut": "Track limits / cut",
    "Speeding": "Speeding",
    "Pit_Speeding": "Pit lane speeding",
    "Speeding_On_Start": "Speeding at the start",
    "Unsafe_Rejoin": "Unsafe rejoin",
    "Wrong_Way": "Driving the wrong way",
    "Illegal_Overtake": "Illegal overtake",
    "Damaged_Car": "Damaged car",
    "Ignored_Mandatory_Pit": "Mandatory pit stop ignored",
    "Lights_Off": "Lights off",
    "Pit_Entry": "Illegal pit entry",
    "Pit_Exit": "Illegal pit exit",
    "Reverse_In_Pitlane": "Reversing in the pit lane",
    "Wrong_Position_On_Start": "Wrong grid position at the start",
    "Race_Control": "Race control notice",
    "Exceeded_Driver_Stint_Limit": "Stint limit exceeded",
    "Ignored_Driver_Stint": "Stint rule ignored",
    "Driver_Ran_No_Stint": "Stint not completed",
    "StartFromPit": "Start from pits",
}
INVESTIGATION_RE = re.compile(r"InvestigationType_([A-Za-z_]+)")
FLAG_RES = [
    (re.compile(r"yellow[\s_]*flag", re.I), "Yellow flag", "flag-yellow"),
    (re.compile(r"green[\s_]*flag|EndGreenFlag", re.I),
     "Green flag — track clear", "flag-green"),
    (re.compile(r"blue[\s_]*flag", re.I), "Blue flag", "flag-blue"),
    (re.compile(r"red[\s_]*flag", re.I), "Red flag — session suspended",
     "flag-red"),
    (re.compile(r"safety[\s_]*car", re.I), "Safety car deployed", "flag-yellow"),
]

RC_NOISE_RE = re.compile(r'"type"\s*:')

_db_lock = threading.Lock()

LW = {"connected": False, "since": 0.0, "last_msg": 0.0}
LAP_INDEX = {}
CAR_INFO_FULL = {}
LIVE_CARS = {}
CONNECTED_CIDS = set()
CAR_DIAG = {}
DRIVER_STATUS = {}
SESSION_START = [None]
_pending_laps = deque()
_history = deque(maxlen=HISTORY_SIZE)
_history_ids = set()
_history_lock = threading.Lock()
_incidents = deque(maxlen=INCIDENTS_SIZE)


EMPTY_DB = {"version": 2, "tracks": {}}
EMPTY_TRACK = {"cars": {}, "record_history": [], "stats": {"laps_saved": 0}}


def sanitize(text):
    text = IP_RE.sub(HIDDEN_TEXT, text)
    text = STEAMID_RE.sub(HIDDEN_TEXT, text)
    return text.strip()


def clean_name(name):
    return sanitize(name)[:32]


def epoch_utc(ts_str):
    try:
        return calendar.timegm(time.strptime(ts_str, "%Y-%m-%d %H:%M:%S"))
    except Exception:
        return None


def read_json(path, default=None):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default if default is not None else {}


def _build_car_names():
    mapping = {}
    data = read_json(CARS_FILE)
    for c in data.get("cars", []):
        preset = c.get("name", "")
        display = c.get("display_name", "")
        m = re.match(r"preset_(.+?)_mech", preset)
        if m and display:
            mapping[m.group(1)] = display.split(" - ")[0]
    return mapping


_CAR_NAMES = _build_car_names()
_UPPER_TOKENS = {"gt", "gt2", "gt3", "gt4", "gtb", "gts", "rs", "r", "m",
                 "amg", "evo", "s", "csl", "lm", "mc", "jcw"}


def pretty_car(model):
    if not model:
        return None
    compact = model.replace("ks_", "").replace("_", "")
    for key, display in _CAR_NAMES.items():
        if key in compact:
            return display
    words = []
    for tok in model.replace("ks_", "").split("_"):
        words.append(tok.upper() if tok in _UPPER_TOKENS or
                     re.match(r"^[a-z]*\d+[a-z]*$", tok) and len(tok) <= 4
                     else tok.capitalize())
    return " ".join(words)


def current_track_key():
    season = read_json(SEASON_FILE)
    ev = season.get("event", {})
    track = ev.get("track", DEFAULT_TRACK)
    layout = ev.get("layout", "")
    return f"{track} {layout}".strip()


def load_db():
    db = read_json(DB_FILE)
    if db and db.get("version") == 2 and "tracks" in db:
        return db
    return json.loads(json.dumps(EMPTY_DB))


def track_data(db, track_key):
    return db["tracks"].setdefault(
        track_key, json.loads(json.dumps(EMPTY_TRACK)))


def _atomic_write(db):
    os.makedirs(os.path.dirname(DB_FILE), exist_ok=True)
    tmp = DB_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(db, f, indent=1)
    os.replace(tmp, DB_FILE)


def overall_best(tdata):
    best = None
    for car, data in tdata["cars"].items():
        for e in data["entries"]:
            if best is None or e["time_ms"] < best["time_ms"]:
                best = {**e, "car": car}
    return best


def save_lap(driver, car, time_ms, track_key, splits=None):
    driver = clean_name(driver)
    if driver.lower() in blocked_drivers():
        return False
    car = sanitize(car)[:40] if car else UNKNOWN_CAR
    tomb = removed_laps()
    if ((track_key, car, driver.lower(), time_ms) in tomb
            or ("*", car, driver.lower(), time_ms) in tomb):
        return False
    today = time.strftime("%Y-%m-%d")
    with _db_lock:
        db = load_db()
        tdata = track_data(db, track_key)
        prev_overall = overall_best(tdata)
        cat = tdata["cars"].setdefault(car, {"entries": []})
        entry = next((e for e in cat["entries"]
                      if e["driver"].lower() == driver.lower()), None)
        if entry:
            if time_ms >= entry["time_ms"]:
                return False
            entry["time_ms"] = time_ms
            entry["date"] = today
            if splits:
                entry["splits"] = splits
        else:
            new = {"driver": driver, "time_ms": time_ms, "date": today}
            if splits:
                new["splits"] = splits
            cat["entries"].append(new)
        cat["entries"].sort(key=lambda e: e["time_ms"])
        tdata["stats"]["laps_saved"] += 1
        if prev_overall is None or time_ms < prev_overall["time_ms"]:
            tdata["record_history"].append(
                {"driver": driver, "car": car, "time_ms": time_ms, "date": today})
            tdata["record_history"] = tdata["record_history"][-RECORD_HISTORY_KEEP:]
        _atomic_write(db)
        return True


def build_leaderboard(track_key=None):
    db = load_db()
    track_key = track_key or current_track_key()
    tdata = db["tracks"].get(track_key, EMPTY_TRACK)
    cars = []
    for car, data in sorted(tdata["cars"].items()):
        entries = data["entries"]
        if not entries:
            continue
        cars.append({"car": car, "record": entries[0],
                     "drivers": len(entries), "entries": entries})
    cars.sort(key=lambda c: c["record"]["time_ms"])
    top10 = sorted(
        ({**e, "car": c["car"]} for c in cars for e in c["entries"]),
        key=lambda e: e["time_ms"])[:10]
    return {
        "track": track_key,
        "current_track": current_track_key(),
        "tracks": sorted(t for t, d in db["tracks"].items() if d["cars"]),
        "overall": overall_best(tdata),
        "cars": cars,
        "top10": top10,
        "record_history": list(reversed(tdata["record_history"]))[:20],
        "sectors": max((len(e.get("splits") or []) for c in cars for e in c["entries"]), default=0),
        "stats": {
            "laps_saved": tdata["stats"]["laps_saved"],
            "cars_count": len(cars),
            "drivers_count": len({e["driver"].lower()
                                  for c in cars for e in c["entries"]}),
        },
    }


def tail_lines(path, max_bytes=LOG_TAIL_BYTES):
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            f.seek(max(0, size - max_bytes))
            raw = f.read().decode("utf-8", errors="replace")
    except Exception:
        return []
    text = ANSI_RE.sub("", raw)
    merged, current = [], ""
    for line in text.splitlines():
        if re.match(r"\[\d{4}-\d{2}-\d{2} ", line):
            if current:
                merged.append(current)
            current = line
        else:
            current += line
    if current:
        merged.append(current)
    return merged


def first_match(patterns, text):
    for p in patterns:
        m = p.search(text)
        if m:
            return m.group(1)
    return None


def parse_race_control(ts, msg):
    if RC_NOISE_RE.search(msg):
        return None
    m = PENALTY_RUNTIME_RE.search(msg)
    if m:
        return {"time": ts, "kind": "penalty",
                "msg": PENALTY_TEXT.get(m.group(1), "Penalty")}
    m = INVESTIGATION_RE.search(msg)
    if m:
        return {"time": ts, "kind": "investigation",
                "msg": INVESTIGATION_TEXT.get(m.group(1), "Under investigation")}
    for pattern, text, kind in FLAG_RES:
        if pattern.search(msg):
            return {"time": ts, "kind": kind, "msg": text}
    return None


def parse_log():
    lines = tail_lines(LOG_FILE)
    last_log_players = None
    events, race_control = [], []
    drivers = {}
    carid_info = {}
    carid_sid = {}


    last_sectors = [None, None, None]
    best_sectors = [None, None, None]
    last_lap = None
    session_start = None
    session_laps = {}
    last_dump_name, log_track_name, log_layout = None, None, None


    names = {}
    for line in lines:
        m = LINE_RE.match(line)
        if m:
            jm = JOIN_NAME_RE.search(m.group(4))
            if jm:
                names[jm.group(3)] = clean_name(jm.group(2))

    for line in lines:
        m = LINE_RE.match(line)
        if not m:
            continue
        ts, _ch, _lvl, msg = m.groups()

        pm = PLAYERS_RE.search(msg)
        if pm:
            last_log_players = int(pm.group(1))
            continue

        if SESSION_START_RE.search(msg):
            session_start = ts
            session_laps.clear()

        if '"' in msg:
            nm = DUMP_NAME_RE.search(msg)
            if nm:
                last_dump_name = nm.group(1)
            if DUMP_FOLDER_RE.search(msg) and last_dump_name:
                log_track_name = last_dump_name
            em = DUMP_EVENT_RE.search(msg)
            if em:
                log_layout = em.group(1)

        if JOIN_NAME_RE.search(msg):
            continue

        cm = JOIN_CAR_RE.search(msg)
        if cm:
            sid, model, carid = cm.groups()
            name = names.get(sid, UNKNOWN_DRIVER)
            car = pretty_car(model)
            is_rejoin = sid in drivers
            drivers[sid] = {"name": name, "car": car, "since": ts,
                            "status": STATUS_PIT, "cid": carid[:8]}
            carid_info[carid] = {"name": name, "car": car}
            carid_sid[carid] = sid
            if not is_rejoin:
                events.append({"time": ts, "kind": "join",
                               "msg": f"{name} joined", "extra": car})
            continue

        lm = LEAVE_RE.search(msg)
        if lm:
            name = clean_name(lm.group(1))
            gone = [sid for sid, d in drivers.items() if d["name"] == name]
            for sid in gone:
                drivers.pop(sid, None)
            events.append({"time": ts, "kind": "leave",
                           "msg": f"{name} left the server"})
            continue

        dm = DISCONNECT_RE.search(msg)
        if dm:
            sid = carid_sid.get(dm.group(1))
            gone = drivers.pop(sid, None) if sid else None
            if gone:
                events.append({"time": ts, "kind": "leave", "msg": f"{gone['name']} left the server"})
            continue

        pm2 = PIT_STATE_RE.search(msg)
        if pm2:
            sid = carid_sid.get(pm2.group(1))
            if sid in drivers:
                rest = pm2.group(2)
                if "Steady" in rest:
                    drivers[sid]["status"] = STATUS_PIT
                elif "OutOfTolerance" in rest:
                    drivers[sid]["status"] = STATUS_TRACK
            continue

        om = ON_TRACK_RE.search(msg)
        if om:
            sid = carid_sid.get(om.group(1))
            if sid in drivers:
                drivers[sid]["status"] = STATUS_TRACK
            continue

        sm = SPLIT_RE.search(msg)
        if sm:
            idx, sec_ms = int(sm.group(1)), int(sm.group(2))
            if 0 <= idx <= 2 and MIN_SECTOR_MS < sec_ms < MAX_SECTOR_MS:
                if best_sectors[idx] is None or sec_ms < best_sectors[idx]:
                    best_sectors[idx] = sec_ms
                last_sectors[idx] = {"ms": sec_ms, "ts": ts}
            continue


        nl = NEW_LAP_RE.search(msg)
        if nl:
            carid, mi, se, mms = nl.groups()
            lap_ms = (int(mi) * 60 + int(se)) * 1000 + int(mms)
            who = carid_info.get(carid)
            sid = carid_sid.get(carid)
            if sid in drivers:
                drivers[sid]["status"] = STATUS_TRACK
            if who and who["name"].lower() in blocked_drivers():
                continue
            lap_track = (f"{log_track_name} {log_layout}".strip()
                         if log_track_name and log_layout
                         else current_track_key())
            if who and MIN_LAP_MS < lap_ms < MAX_LAP_MS:
                lw_ev = LAP_INDEX.get((carid, lap_ms))
                lap_ok = True if lw_ev is None else bool(lw_ev["valid"])
                sl = session_laps.setdefault(
                    who["name"], {"driver": who["name"], "car": who["car"],
                                  "laps": 0, "last_ts": None, "best_ms": None})
                sl["laps"] += 1
                sl["last_ts"] = epoch_utc(ts)
                sl["car"] = who["car"]
                if lap_ok:
                    last_lap = {"ms": lap_ms, "ts": ts, "driver": who["name"]}
                    if sl["best_ms"] is None or lap_ms < sl["best_ms"]:
                        sl["best_ms"] = lap_ms
                    events.append(
                        {"time": ts, "kind": "lap",
                         "msg": f"{who['name']} — lap {int(mi)}:{se}.{mms}",
                         "extra": who["car"]})
                else:
                    events.append(
                        {"time": ts, "kind": "lap_invalid",
                         "msg": f"{who['name']} — lap {int(mi)}:{se}.{mms} "
                                f"invalidated",
                         "extra": who["car"]})
                if LOG_FALLBACK and not LW["connected"]:
                    save_lap(who["name"], who["car"], lap_ms, lap_track)
            continue

        rc = parse_race_control(ts, msg)
        if rc:

            if not (race_control and race_control[-1]["msg"] == rc["msg"]
                    and race_control[-1]["time"] == rc["time"]):
                race_control.append(rc)
            continue


        lap_ms = first_match(LAP_MS_PATTERNS, msg)
        lap_str = first_match(LAP_STR_PATTERNS, msg)
        if lap_ms or lap_str:
            ms = int(lap_ms) if lap_ms else None
            if ms is None:
                mm = re.match(r"(\d{1,2})[:.](\d{2})[.:](\d{3})", lap_str)
                if mm:
                    ms = (int(mm.group(1)) * 60 + int(mm.group(2))) * 1000 \
                        + int(mm.group(3))
            sid_m = STEAMID_RE.search(msg)
            who = names.get(sid_m.group(0)) if sid_m else None
            if ms and MIN_LAP_MS < ms < MAX_LAP_MS and who:
                car = drivers.get(sid_m.group(0), {}).get("car")
                if save_lap(who, car, ms):
                    events.append({"time": ts,
                                   "msg": f"Lap time recorded for {who}"})
            continue

        for pattern, public_text in EVENT_MAP:
            if pattern.search(msg):
                if "Listening" in pattern.pattern:
                    drivers.clear()
                events.append({"time": ts, "kind": "session",
                               "msg": public_text})
                break

    CAR_INFO_FULL.clear()
    CAR_INFO_FULL.update(carid_info)
    SESSION_START[0] = epoch_utc(session_start) if session_start else None
    live_out = None
    if any(last_sectors) or last_lap:
        live_out = {
            "sectors": [
                {"ms": s["ms"], "ts": epoch_utc(s["ts"])} if s else None
                for s in last_sectors],
            "best": best_sectors,
            "last_lap": ({"ms": last_lap["ms"], "ts": epoch_utc(last_lap["ts"]),
                          "driver": last_lap["driver"]} if last_lap else None),
        }
    session_out = {
        "id": epoch_utc(session_start) if session_start else None,
        "classification": sorted(
            session_laps.values(),
            key=lambda d: (-d["laps"], d["last_ts"] or 0)),
    }
    return (drivers, names, events, race_control, last_log_players,
            live_out, session_out)


def compute_status():
    clients, api_ok = None, False
    try:
        with urllib.request.urlopen(ACE_API, timeout=3) as r:
            clients = json.loads(r.read()).get("clients")
            api_ok = True
    except Exception:
        pass

    cfg = read_json(CONFIG_FILE)
    season = read_json(SEASON_FILE)
    (drivers, _names, events, race_control, last_log_players,
     live_lap, session) = parse_log()

    driver_list = list(drivers.values())
    tdata = load_db()["tracks"].get(current_track_key(), EMPTY_TRACK)
    for d in driver_list:
        pbs = [e["time_ms"] for c, data in tdata["cars"].items()
               for e in data["entries"]
               if e["driver"].lower() == d["name"].lower()
               and (d.get("car") is None or c == d["car"])]
        d["pb"] = min(pbs) if pbs else None


    for e in events:
        e["ts"] = epoch_utc(e["time"])
    for e in race_control:
        e["ts"] = epoch_utc(e["time"])
    for d in driver_list:
        d["since_ts"] = epoch_utc(d["since"])

    live_count = clients if clients is not None else last_log_players
    gone = {c["cid"] for c in (race_public() or {}).get("cars", []) if c.get("connected") is False}
    driver_list = [d for d in driver_list if d.get("cid") not in gone]
    if live_count == 0:
        driver_list = []
    DRIVER_STATUS.clear()
    DRIVER_STATUS.update({d["cid"]: d.get("status") for d in driver_list if d.get("cid")})
    CONNECTED_CIDS.clear()
    if live_count != 0:
        CONNECTED_CIDS.update(d["cid"] for d in driver_list if d.get("cid"))
    anonymous = max(0, (live_count or 0) - len(driver_list))

    lb = build_leaderboard()
    gc = season.get("game_config", {})
    duration_s = gc.get("practice_duration") or 0
    return {
        "online": api_ok,
        "players": live_count,
        "max_players": cfg.get("max_players"),
        "server_name": sanitize(str(cfg.get("server_name", DEFAULT_SERVER_NAME))),
        "track": season.get("event", {}).get("track"),
        "layout": season.get("event", {}).get("layout"),
        "track_length": season.get("event", {}).get("track_length"),
        "mode": season.get("game_type", "").replace("GameModeType_", ""),
        "session_duration_min": duration_s // 60 or None,
        "weather": season.get("weather_type", "").replace(
            "GameModeSelectionWeatherType_", ""),
        "open_access": not bool(cfg.get("driver_password")),
        "drivers": driver_list,
        "anonymous_drivers": anonymous,
        "overall": lb["overall"],
        "top10": lb["top10"],
        "cars_index": [{"car": c["car"], "record": c["record"],
                        "drivers": c["drivers"]} for c in lb["cars"]],
        "events": list(reversed(events[-30:])),
        "race_control": list(reversed(race_control[-25:])),
        "live_lap": live_lap,
        "session": session,
        "timing": build_timing(),
        "lapwatch": {"on": LW["connected"], "cars": len(LIVE_CARS)},
        "race": race_public(),
        "weekend": weekend_info(season),
        "updated": time.strftime("%H:%M:%S"),
        "updated_ts": time.time(),
    }


def _load_history():
    try:
        with open(HISTORY_FILE, encoding="utf-8") as f:
            for line in f.readlines()[-HISTORY_SIZE:]:
                try:
                    r = json.loads(line)
                    _history.append(r)
                    _history_ids.add(r["id"])
                except Exception:
                    pass
    except OSError:
        pass


def _append_history(rec):
    with _history_lock:
        _history.append(rec)
        _history_ids.add(rec["id"])
    try:
        os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
        with open(HISTORY_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, separators=(",", ":")) + "\n")
    except OSError as e:
        print(f"history write error: {e}", flush=True)


def process_lap(ev):
    info = CAR_INFO_FULL.get(ev["car"])
    if not info:
        return False
    with _history_lock:
        if ev["id"] in _history_ids:
            return True
    driver = clean_name(info["name"])
    rec = {"id": ev["id"], "ts": ev["ts"], "driver": driver,
           "car": info["car"] or UNKNOWN_CAR, "track": ev.get("track"),
           "ms": ev["ms"], "valid": bool(ev["valid"]), "flags": ev.get("flags"),
           "splits": ev.get("splits") or [], "cuts": ev.get("cuts", 0),
           "hits": ev.get("hits", 0), "lap": ev.get("lap"), "cid": ev["car"][:8]}
    _append_history(rec)
    saved = False
    if rec["valid"] and MIN_LAP_MS < rec["ms"] < MAX_LAP_MS and len(rec["splits"]) >= MIN_SPLITS_TO_SAVE:
        saved = save_lap(driver, rec["car"], rec["ms"], rec["track"], rec["splits"])
    rec["pb"] = saved
    WS.broadcast({"t": "lap", **rec})
    return True


def retry_pending():
    for _ in range(len(_pending_laps)):
        ev = _pending_laps.popleft()
        if time.time() - ev["ts"] > PENDING_LAP_TTL_S:
            continue
        if not process_lap(ev):
            _pending_laps.append(ev)


def build_timing():
    track = current_track_key()
    start = SESSION_START[0] or 0
    if RACE.get("session_start"):
        start = max(start, RACE["session_start"] - 5)
    with _history_lock:
        laps = [l for l in _history if l.get("track") == track]
    sec_best = [None, None, None]
    sec_best_by = [None, None, None]
    for l in laps:
        if not l["valid"]:
            continue
        for i, v in enumerate(l["splits"][:3]):
            if v and (sec_best[i] is None or v < sec_best[i]):
                sec_best[i], sec_best_by[i] = v, l["driver"]
    rows = {}
    for l in laps:
        if l["ts"] < start:
            continue
        r = rows.setdefault(l["driver"], {
            "name": l["driver"], "car": l["car"], "cid": l.get("cid"),
            "laps": 0, "valid": 0, "best_ms": None, "best_splits": None,
            "last_ms": None, "last_ok": None, "last_splits": None, "cuts": 0,
            "hits": 0, "last_ts": None})
        r["laps"] += 1
        r["cuts"] += l.get("cuts", 0)
        r["hits"] += l.get("hits", 0)
        r["car"], r["cid"] = l["car"], l.get("cid")
        r["last_ms"], r["last_ok"] = l["ms"], l["valid"]
        r["last_splits"], r["last_ts"] = l["splits"], l["ts"]
        if l["valid"]:
            r["valid"] += 1
            if r["best_ms"] is None or l["ms"] < r["best_ms"]:
                r["best_ms"], r["best_splits"] = l["ms"], l["splits"]
    out = sorted(rows.values(),
                 key=lambda r: (r["best_ms"] is None, r["best_ms"] or 0, -(r["last_ts"] or 0)))
    rp = race_public()
    if rp and rp["sort"] == "Race":
        pos = {c["cid"]: c for c in rp["cars"]}
        for c in rp["cars"]:
            if c["name"] and not any(r["cid"] == c["cid"] for r in out):
                out.append({"name": c["name"], "car": c["car"], "cid": c["cid"], "laps": 0, "valid": 0,
                            "best_ms": None, "best_splits": None, "last_ms": None, "last_ok": None,
                            "last_splits": None, "cuts": 0, "hits": 0, "last_ts": None})
        out.sort(key=lambda r: ((pos.get(r["cid"]) or {}).get("pos") or 999, r["best_ms"] or 1e12))
    sectors = max((len(l["splits"]) for l in laps), default=0) or track_sectors(track)
    lead = out[0]["best_ms"] if out and out[0]["best_ms"] else None
    for r in out:
        r["gap_ms"] = (r["best_ms"] - lead) if (lead and r["best_ms"]) else None
    return {"rows": out, "sector_best": sec_best, "sector_best_by": sec_best_by,
            "sectors": sectors}


def track_sectors(track_key):
    tdata = load_db()["tracks"].get(track_key) or {}
    return max((len(e.get("splits") or []) for c in tdata.get("cars", {}).values()
                for e in c["entries"]), default=0)


RACE = {}


def race_public():
    r = RACE
    if not r:
        return None
    started = SESSION_START[0]
    if started and (r.get("session_start") or 0) and r["session_start"] < started - 5:
        return None
    cars = []
    for c in r.get("cars", []):
        info = CAR_INFO_FULL.get(c["id"]) or {}
        cars.append({"cid": c["id"][:8], "name": info.get("name"), "car": info.get("car"),
                     "pos": c.get("pos"), "laps": c.get("laps_rt", c.get("laps")), "best_ms": c.get("best_ms"),
                     "last_ms": c.get("last_ms"), "ahead_ms": c.get("ahead_ms"), "npos": c.get("npos"),
                     "gap_ms": c.get("gap_ms"), "int_ms": c.get("int_ms"),
                     "loc": c.get("loc"), "flags": c.get("flags", 0) | c.get("lap_flags", 0),
                     "connected": c.get("connected"), "pen": c.get("pen", []), "inv": c.get("inv", []),
                     "pits": c.get("pits", 0), "mandatory": c.get("mandatory")})
    if r.get("sort") == "Race":
        cars.sort(key=lambda c: (c["pos"] is None, c["pos"] or 0))
    return {"mode": r.get("mode"), "session": r.get("session"), "phase": r.get("phase"),
            "phase_end": r.get("phase_end"), "session_start": r.get("session_start"), "sort": r.get("sort"),
            "pit_semaphore": r.get("pit_semaphore"), "cars": cars}


def weekend_info(season):
    gc = season.get("game_config", {})
    out = {"practice_min": (gc.get("practice_duration") or 0) // 60 or None,
           "qualify_min": (gc.get("qualify_duration") or 0) // 60 or None}
    if gc.get("race_duration"):
        laps = "LAPS" in str(gc.get("race_duration_type", ""))
        out["race_laps" if laps else "race_min"] = gc["race_duration"] if laps else gc["race_duration"] // 60
    return out


def compact_cars(frame):
    out = []
    for c in frame.get("cars", []):
        out.append({"i": c["id"][:8], "x": c["x"], "z": c["z"], "y": c.get("y"),
                    "pr": c.get("pr"), "el": c.get("el"), "dl": c.get("dl"), "rt": c.get("rt"),
                    "loc": c.get("loc"), "v": c["v"], "h": c["h"],
                    "ok": c["ok"], "w": c.get("w"), "l": c["lap"], "c": c["cuts"], "p": c.get("pit"),
                    "pl": c.get("pl"), "n": c.get("n"), "tl": c.get("tl"), "sl": c.get("sl", 0)})
    return out


def incident_msg(m):
    info = CAR_INFO_FULL.get(m["car"]) or {}
    return {"t": "inc", "k": m["t"], "ts": m["ts"], "name": info.get("name", UNKNOWN_DRIVER),
            "car": info.get("car"), "cid": m["car"][:8], "x": m.get("x"), "z": m.get("z"),
            "v": m.get("v"), "lap": m.get("lap"), "dmg": m.get("dmg"), "track": m.get("track"),
            "repair": m.get("repair"), "pen": m.get("pen"), "pen_ms": m.get("pen_ms"), "why": m.get("why"),
            "fuel": m.get("fuel"), "tyres": m.get("tyres"), "kind": m.get("kind"),
            "text": sanitize(m["text"]) if m.get("text") else None}


def lw_message(m):
    t = m.get("t")
    LW["last_msg"] = time.time()
    if t == "pos":
        cars = [c for c in compact_cars(m) if c["i"] in CONNECTED_CIDS]
        for c in cars:
            if c.get("sl") and DRIVER_STATUS.get(c["i"]) == STATUS_PIT:
                c["sl"] = 0
        LIVE_CARS.clear()
        LIVE_CARS.update({c["i"]: c for c in cars})
        LW["pos_ts"] = m["ts"]
        WS.broadcast({"t": "p", "ts": m["ts"], "c": cars})
    elif t == "lap":
        LAP_INDEX[(m["car"], m["ms"])] = m
        _pending_laps.append(m)
        retry_pending()
    elif t == "diag":
        cid = m["car"][:8]
        CAR_DIAG[cid] = m["d"]
        if cid in CONNECTED_CIDS:
            WS.broadcast({"t": "diag", "cid": cid, "d": m["d"]})
    elif t in ("cut", "hit", "reset"):
        msg = incident_msg(m)
        _incidents.append(msg)
        WS.broadcast(msg)
    elif t == "split":
        info = CAR_INFO_FULL.get(m["car"]) or {}
        WS.broadcast({"t": "split", "cid": m["car"][:8], "name": info.get("name"),
                      "id": m["id"], "ms": m["ms"], "ok": m["ok"], "lap": m["lap"],
                      "fin": m["fin"]})
    elif t == "race":
        RACE.clear()
        RACE.update(m)
        WS.broadcast({"t": "race", "r": race_public()})
    elif t in ("pit_in", "pit_out", "penalty", "rc"):
        msg = incident_msg(m)
        _incidents.append(msg)
        WS.broadcast(msg)
    elif t == "yellow":
        info = CAR_INFO_FULL.get(m["car"]) or {}
        WS.broadcast({"t": "yellow", "cid": m["car"][:8], "name": info.get("name", UNKNOWN_DRIVER), "on": m.get("on"),
                      "pr": m.get("pr"), "ts": m.get("ts")})
    elif t == "lapstart":
        WS.broadcast({"t": "lapstart", "cid": m["car"][:8], "lap": m["lap"]})
    elif t == "trace":
        WS.broadcast({"t": "trace", "track": m.get("track")})
    elif t == "hello":
        for ev in m.get("laps", []):
            LAP_INDEX[(ev["car"], ev["ms"])] = ev
            if ev["id"] not in _history_ids:
                _pending_laps.append(ev)
        for inc in m.get("incidents", []):
            _incidents.append(incident_msg(inc))
        for car_id, d in (m.get("diag") or {}).items():
            CAR_DIAG[car_id[:8]] = d
        if m.get("race"):
            RACE.clear()
            RACE.update(m["race"])
        retry_pending()


def lw_loop():
    while True:
        s = None
        try:
            if LW_SOCK.startswith("tcp://"):
                host, port = LW_SOCK[6:].rsplit(":", 1)
                s = socket.create_connection((host, int(port)), timeout=3)
                s.settimeout(None)
            else:
                s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                s.connect(LW_SOCK)
            LW["connected"], LW["since"] = True, time.time()
            WS.broadcast({"t": "lw", "on": True})
            buf = b""
            while True:
                chunk = s.recv(65536)
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    if line:
                        try:
                            lw_message(json.loads(line))
                        except Exception as e:
                            print(f"lapwatch msg error: {e}", flush=True)
        except (OSError, ValueError, AttributeError):
            pass
        finally:
            if s:
                try:
                    s.close()
                except OSError:
                    pass
            if LW["connected"]:
                LW["connected"] = False
                LIVE_CARS.clear()
                WS.broadcast({"t": "lw", "on": False})
        time.sleep(2)


WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def ws_frame(payload, opcode=0x1):
    n = len(payload)
    if n < 126:
        head = struct.pack("!BB", 0x80 | opcode, n)
    elif n < 65536:
        head = struct.pack("!BBH", 0x80 | opcode, 126, n)
    else:
        head = struct.pack("!BBQ", 0x80 | opcode, 127, n)
    return head + payload


class WSClient:
    __slots__ = ("sock", "q", "ev", "alive", "dropped")

    def __init__(self, sock):
        self.sock = sock
        self.q = deque(maxlen=WS_QUEUE)
        self.ev = threading.Event()
        self.alive = True
        self.dropped = 0


class WSHub:
    def __init__(self):
        self.clients = set()
        self.lock = threading.Lock()

    def add(self, c):
        with self.lock:
            if len(self.clients) >= MAX_WS_CLIENTS:
                return False
            self.clients.add(c)
            return True

    def remove(self, c):
        with self.lock:
            self.clients.discard(c)

    def count(self):
        return len(self.clients)

    def broadcast(self, obj):
        if not self.clients:
            return
        frame = ws_frame(json.dumps(obj, separators=(",", ":")).encode())
        with self.lock:
            for c in self.clients:
                if len(c.q) == c.q.maxlen:
                    c.dropped += 1
                c.q.append(frame)
                c.ev.set()


WS = WSHub()


def ws_read_frames(buf):
    ops = []
    while len(buf) >= 2:
        op = buf[0] & 0x0F
        ln = buf[1] & 0x7F
        masked = buf[1] & 0x80
        i = 2
        if ln == 126:
            if len(buf) < 4:
                break
            ln = struct.unpack("!H", buf[2:4])[0]
            i = 4
        elif ln == 127:
            if len(buf) < 10:
                break
            ln = struct.unpack("!Q", buf[2:10])[0]
            i = 10
        need = i + (4 if masked else 0) + ln
        if len(buf) < need:
            break
        ops.append(op)
        buf = buf[need:]
    return ops, buf


def updater_loop():
    while True:
        try:
            retry_pending()
            status = compute_status()
            body = json.dumps(status).encode()
            cmp = json.dumps({k: v for k, v in status.items()
                              if k not in ("updated", "updated_ts", "race")})
            changed = False
            with _state_lock:
                if cmp != _state.get("cmp"):
                    _state["seq"] += 1
                    _state["cmp"] = cmp
                    changed = True
                _state["json"] = body
                _state["obj"] = status
                _state["ts"] = time.time()
            if changed:
                WS.broadcast({"t": "status", "s": status})
                _state["hb"] = time.time()
            elif time.time() - _state.get("hb", 0) >= HEARTBEAT_S:
                WS.broadcast({"t": "hb", "ts": round(time.time(), 1)})
                _state["hb"] = time.time()
        except Exception as e:
            print(f"updater error: {e}", flush=True)
        time.sleep(REFRESH_S)


def get_state():
    with _state_lock:
        return _state["json"], _state["seq"]


def hello_frame():
    with _state_lock:
        status = _state.get("obj") or {}
    with _history_lock:
        laps = list(_history)[-HELLO_LAPS:]
    diag = {cid: d for cid, d in CAR_DIAG.items() if cid in CONNECTED_CIDS}
    return {"t": "hello", "s": status, "c": list(LIVE_CARS.values()), "dg": diag, "race": race_public(),
            "laps": laps, "inc": list(_incidents)[-40:], "lw": LW["connected"]}


def trace_for(track):
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", track or "").strip("_")
    if not safe:
        return None
    try:
        with open(os.path.join(LW_DIR, "traces", safe + ".json"), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def api_laps(qs):
    limit = max(1, min(500, int(qs.get("limit", ["60"])[0] or 60)))
    drv = (qs.get("driver", [""])[0] or "").lower()
    track = qs.get("track", [""])[0]
    only_valid = qs.get("valid", [""])[0] == "1"
    with _history_lock:
        rows = list(_history)
    out = [r for r in reversed(rows)
           if (not drv or r["driver"].lower() == drv)
           and (not track or r.get("track") == track)
           and (not only_valid or r["valid"])]
    return {"laps": out[:limit]}


def api_driver(name):
    name_l = name.lower()
    with _history_lock:
        mine = [r for r in _history if r["driver"].lower() == name_l]
    db = load_db()
    records = []
    for tk, tdata in db["tracks"].items():
        for car, data in tdata["cars"].items():
            ents = data["entries"]
            for pos, e in enumerate(ents, 1):
                if e["driver"].lower() == name_l:
                    records.append({"track": tk, "car": car, "time_ms": e["time_ms"],
                                    "date": e.get("date"), "pos": pos, "of": len(ents),
                                    "splits": e.get("splits")})
    if not mine and not records:
        return None
    valid = [r for r in mine if r["valid"]]
    best = min((r["ms"] for r in valid), default=None)
    clean = [r["ms"] for r in valid if best and r["ms"] <= best * CONSISTENCY_WINDOW]
    consistency = (round(statistics.pstdev(clean[-CONSISTENCY_LAPS:])) if len(clean) >= 3 else None)
    return {
        "name": name,
        "laps": len(mine), "valid": len(valid),
        "invalid": len(mine) - len(valid),
        "cuts": sum(r.get("cuts", 0) for r in mine),
        "cut_laps": sum(1 for r in mine if r.get("cuts")),
        "hits": sum(r.get("hits", 0) for r in mine),
        "valid_rate": round(100 * len(valid) / len(mine)) if mine else None,
        "consistency_ms": consistency,
        "records": sorted(records, key=lambda r: (r["track"], r["pos"], r["time_ms"])),
        "recent": list(reversed(mine))[:40],
        "cars": sorted({r["car"] for r in mine}),
    }


_state = {"json": b"{}", "obj": {}, "ts": 0.0, "seq": 0}
_state_lock = threading.Lock()

_sse_lock = threading.Lock()
_sse_count = [0]


STATIC_RE = re.compile(r"^/([a-z0-9_-]+\.(?:js|css))$")
STATIC_TYPES = {"js": "application/javascript; charset=utf-8", "css": "text/css; charset=utf-8"}
PAGES = [("/", "index.html"), ("/index.html", "index.html"), ("/records", "records.html"),
         ("/laps", "laps.html")]


def site_name():
    if SITE_NAME_FROM_SERVER:
        name = sanitize(str(read_json(CONFIG_FILE, {}).get("server_name") or "")).strip()
        if name:
            return name
    return SITE_NAME


def _site_config(name):
    cfg = {"name": name, "nameFromServer": SITE_NAME_FROM_SERVER, "locale": SITE_LOCALE,
           "speedUnit": "mph" if SPEED_UNIT == "mph" else "kmh"}
    if SITE_POWERED_BY and re.match(r"https?://", SITE_REPO_URL):
        cfg["poweredBy"] = {"url": SITE_REPO_URL, "label": SITE_REPO_LABEL}
    return json.dumps(cfg).replace("<", "\\u003c")


def _accent_style():
    if not SITE_ACCENT or not re.fullmatch(r"#[0-9A-Fa-f]{3,8}|[a-zA-Z]{3,20}", SITE_ACCENT):
        return ""
    return f"<style>:root{{--accent:{SITE_ACCENT}}}</style>"


_page_cache = {}


def render_page(template):
    path = os.path.join(APP_DIR, template)
    mtime = os.path.getmtime(path)
    name = site_name()
    hit = _page_cache.get(template)
    if hit and hit[0] == (mtime, name):
        return hit[1]
    with open(path, encoding="utf-8") as f:
        text = f.read()
    text = (text.replace("{{SITE_NAME}}", html.escape(name))
                .replace("{{SITE_DESCRIPTION}}", html.escape(SITE_DESCRIPTION))
                .replace("{{SITE_FOOTER}}", html.escape(SITE_FOOTER))
                .replace("{{SITE_CONFIG}}", _site_config(name))
                .replace("{{SITE_STYLE}}", _accent_style()))
    body = text.encode("utf-8")
    _page_cache[template] = ((mtime, name), body)
    return body


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _websocket(self):
        key = self.headers.get("Sec-WebSocket-Key")
        if (not key or "websocket" not in self.headers.get("Upgrade", "").lower()):
            self._send(b"Bad request", "text/plain", 400)
            return
        origin = self.headers.get("Origin")
        host = self.headers.get("Host", "")
        if CHECK_ORIGIN and origin and urllib.parse.urlparse(origin).netloc != host:
            self._send(b"Forbidden", "text/plain", 403)
            return
        accept = base64.b64encode(
            hashlib.sha1((key + WS_GUID).encode()).digest()).decode()
        self.wfile.write(
            ("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
             "Connection: Upgrade\r\nSec-WebSocket-Accept: " + accept +
             "\r\n\r\n").encode())
        self.wfile.flush()
        self.close_connection = True
        sock = self.connection
        sock.settimeout(8)
        try:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError:
            pass
        client = WSClient(sock)
        if not WS.add(client):
            sock.sendall(ws_frame(b"", 0x8))
            return
        try:
            client.q.append(ws_frame(json.dumps(hello_frame(),
                                                separators=(",", ":")).encode()))
            last_ping = time.time()
            rbuf = b""
            while client.alive:
                client.ev.wait(0.5)
                client.ev.clear()
                while client.q:
                    sock.sendall(client.q.popleft())
                r, _, _ = select.select([sock], [], [], 0)
                if r:
                    data = sock.recv(4096)
                    if not data:
                        break
                    rbuf += data
                    ops, rbuf = ws_read_frames(rbuf)
                    if 0x8 in ops:
                        break
                    if len(rbuf) > 65536:
                        break
                if time.time() - last_ping > WS_PING_S:
                    sock.sendall(ws_frame(b"", 0x9))
                    last_ping = time.time()
        except (OSError, ValueError):
            pass
        finally:
            client.alive = False
            WS.remove(client)

    def _stream(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        last_seq = -1
        try:
            while True:
                body, seq = get_state()
                if seq != last_seq:
                    self.wfile.write(b"data: " + body + b"\n\n")
                    self.wfile.flush()
                    last_seq = seq
                else:
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
                time.sleep(1.0)
        except (BrokenPipeError, ConnectionResetError, OSError):
            return

    def _send(self, body, ctype, code=200):
        host = self.headers.get("Host", "")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        ws_src = f"ws://{host} wss://{host}" if host else ""
        self.send_header(
            "Content-Security-Policy",
            "default-src 'none'; script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; "
            f"connect-src 'self' {ws_src}; "
            "img-src 'self' data:; base-uri 'none'; form-action 'none'; "
            "frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(json.dumps(obj).encode(), "application/json", code)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        qs = urllib.parse.parse_qs(parsed.query)
        if path == "/ws":
            return self._websocket()
        if path == "/api/status":
            body, _ = get_state()
            return self._send(body, "application/json")
        if path == "/api/leaderboard":
            track = qs.get("track", [None])[0]
            if track:
                track = sanitize(track)[:60]
            return self._json(build_leaderboard(track))
        if path == "/api/laps":
            try:
                return self._json(api_laps(qs))
            except ValueError:
                return self._json({"error": "invalid parameters"}, 400)
        if path == "/api/driver":
            name = clean_name(qs.get("name", [""])[0])
            d = api_driver(name) if name else None
            return self._json(d, 200) if d else self._json({"error": "driver not found"}, 404)
        if path == "/api/map":
            tk = sanitize(qs.get("track", [current_track_key()])[0])[:60]
            tr = trace_for(tk)
            return self._json(tr or {"track": tk, "pts": []})
        if path == "/api/race":
            return self._json(race_public() or {})
        if path == "/api/live":
            return self._json({"cars": list(LIVE_CARS.values()), "lw": LW["connected"]})
        if path == "/api/diag":
            cid = (qs.get("cid", [""])[0] or "")[:8]
            d = CAR_DIAG.get(cid) if cid in CONNECTED_CIDS else None
            return self._json({"cid": cid, "diag": d}, 200 if d else 404)
        if path == "/api/incidents":
            return self._json({"incidents": list(_incidents)[-100:]})
        if path == "/api/health":
            return self._json({"ok": True, "lapwatch": LW["connected"],
                               "ws_clients": WS.count(), "history": len(_history),
                               "live_cars": len(LIVE_CARS)})
        if path == "/api/stream":
            with _sse_lock:
                if _sse_count[0] >= MAX_SSE_CLIENTS:
                    return self._send(b"Too many streams", "text/plain", 429)
                _sse_count[0] += 1
            try:
                self._stream()
            finally:
                with _sse_lock:
                    _sse_count[0] -= 1
            return
        sm = STATIC_RE.match(path)
        if sm:
            fp = os.path.join(APP_DIR, sm.group(1))
            if os.path.isfile(fp):
                with open(fp, "rb") as f:
                    return self._send(f.read(), STATIC_TYPES[fp.rsplit(".", 1)[1]])
            return self._send(b"Not found", "text/plain", 404)
        template = dict(PAGES).get(path)
        if template is None and path.startswith("/car/"):
            template = "car.html"
        if template is None and path.startswith("/driver/"):
            template = "driver.html"
        if template:
            return self._send(render_page(template), "text/html; charset=utf-8")
        self._send(b"Not found", "text/plain", 404)

    def log_message(self, *args):
        pass


class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    request_queue_size = 64

    def handle_error(self, request, client_address):
        exc = sys.exc_info()[1]
        if isinstance(exc, OSError):
            return
        super().handle_error(request, client_address)


if __name__ == "__main__":
    _load_history()
    threading.Thread(target=updater_loop, daemon=True).start()
    threading.Thread(target=lw_loop, daemon=True).start()
    print(f"Dashboard listening on {BIND_HOST}:{PORT} (refresh {REFRESH_S}s)", flush=True)
    ThreadingHTTPServer((BIND_HOST, PORT), Handler).serve_forever()
