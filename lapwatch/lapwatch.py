#!/usr/bin/env python3
import argparse
import json
import math
import os
import re
import select
import socket
import struct
import sys
import threading
import time
from collections import deque
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _env(name, default, cast=str):
    v = os.environ.get(name)
    return default if v is None or v == "" else cast(v)


GAME_PORT = _env("LW_PORT", 9600, int)
OUT_DIR = Path(_env("LW_OUT", "/dash-data/lapwatch"))
SEASON_FILE = _env("LW_SEASON", "/srv-config/season_def.json")
SCHEMA_FILE = _env("LW_SCHEMA", str(HERE / "schema.json"))
SOCKET_PATH = _env("LW_SOCKET", "")
POS_HZ = _env("LW_POS_HZ", 10.0, float)
HITS_ENABLED = _env("LW_HITS", "0") == "1"
TRACE_STEP_S = _env("LW_TRACE_STEP_S", 0.2, float)
TRACE_MAX_POINTS = _env("LW_TRACE_MAX_POINTS", 6000, int)
TRACE_MIN_POINTS = _env("LW_TRACE_MIN_POINTS", 50, int)
TRACE_MIN_LAP_MS = _env("LW_TRACE_MIN_LAP_MS", 20000, int)
REF_MATCH_M = _env("LW_REF_MATCH_M", 35.0, float)
REF_LOST_M = _env("LW_REF_LOST_M", 150.0, float)
REF_SEARCH_WINDOW = _env("LW_REF_SEARCH_WINDOW", 90, int)
DELTA_MIN_MS = _env("LW_DELTA_MIN_MS", 3000, int)
CAR_STALE_S = _env("LW_CAR_STALE_S", 15.0, float)
PIT_REQUEST_WINDOW_S = _env("LW_PIT_REQUEST_WINDOW_S", 15.0, float)
RESET_DEDUP_S = _env("LW_RESET_DEDUP_S", 3.0, float)
MIN_IMPACT_MS = _env("LW_MIN_IMPACT_MS", 2.0, float)
FLOOR_NORMAL_Y = _env("LW_FLOOR_NORMAL_Y", 0.6, float)
PIT_START_GAP_M = _env("LW_PIT_START_GAP_M", 60.0, float)
DIAG_INTERVAL_S = _env("LW_DIAG_INTERVAL_S", 1.0, float)
RECENT_LAPS = _env("LW_RECENT_LAPS", 300, int)
RECENT_INCIDENTS = _env("LW_RECENT_INCIDENTS", 200, int)
DEFAULT_TRACK = _env("LW_DEFAULT_TRACK", "Track")
SLOW_RATIO = _env("LW_SLOW_RATIO", 0.4, float)
SLOW_MIN_REF_KMH = _env("LW_SLOW_MIN_REF_KMH", 80.0, float)
SLOW_ABS_KMH = _env("LW_SLOW_ABS_KMH", 30.0, float)
SLOW_CONFIRM_S = _env("LW_SLOW_CONFIRM_S", 1.5, float)
SLOW_CLEAR_S = _env("LW_SLOW_CLEAR_S", 3.0, float)
UDP_TELEMETRY_SIZE = 63
STREAM_GAP_S = _env("LW_STREAM_GAP_S", 2.0, float)
STREAM_NEW_CONN_BYTES = 1 << 20
HEAL_INTERVAL_S = _env("LW_HEAL_INTERVAL_S", 2.0, float)
UNBOUND_RECENT_S = _env("LW_UNBOUND_RECENT_S", 3.0, float)
TCP_SYN, TCP_FIN, TCP_RST = 0x02, 0x01, 0x04
NULL_ID = "0000000000000000-0000000000000000"
NO_YELLOW_PHASES = ("Start_", "RollingStart", "Waiting_For_Players")

T_DOUBLE, T_FLOAT, T_INT64, T_UINT64, T_INT32, T_FIXED64, T_FIXED32, T_BOOL, T_STRING, \
    T_GROUP, T_MESSAGE, T_BYTES, T_UINT32, T_ENUM, T_SFIXED32, T_SFIXED64, T_SINT32, \
    T_SINT64 = range(1, 19)
_SCALAR_FIXED = {T_DOUBLE: ("<d", 8), T_FIXED64: ("<Q", 8), T_SFIXED64: ("<q", 8),
                 T_FLOAT: ("<f", 4), T_FIXED32: ("<I", 4), T_SFIXED32: ("<i", 4)}


class Truncated(Exception):
    pass


def _varint(b, i):
    r = s = 0
    while True:
        if i >= len(b):
            raise Truncated
        c = b[i]
        i += 1
        r |= (c & 0x7F) << s
        if not c & 0x80:
            return r, i
        s += 7
        if s > 70:
            raise Truncated


def _signed(v, bits):
    v &= (1 << bits) - 1
    return v - (1 << bits) if v >> (bits - 1) else v


class Schema:
    def __init__(self, path):
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        self.msgs = {k: {int(n): f for n, f in v["f"].items()}
                     for k, v in data["messages"].items()}
        self.by_short = {}
        for full in self.msgs:
            self.by_short.setdefault(full.split(".")[-1], full)
            self.by_short[full] = full

    def lookup(self, name):
        return self.by_short.get(name)

    def decode(self, buf, mname, depth=0):
        if mname.endswith("PGUID"):
            a = b_ = 0
            i = 0
            try:
                while i < len(buf):
                    tag, i = _varint(buf, i)
                    num, wt = tag >> 3, tag & 7
                    if wt == 0:
                        v, i = _varint(buf, i)
                        if num == 1:
                            a = v
                        elif num == 2:
                            b_ = v
                    elif wt == 1:
                        v = struct.unpack("<Q", buf[i:i + 8])[0]
                        i += 8
                        if num == 1:
                            a = v
                        elif num == 2:
                            b_ = v
                    elif wt == 2:
                        ln, i = _varint(buf, i)
                        i += ln
                    elif wt == 5:
                        i += 4
                    else:
                        break
            except (Truncated, struct.error):
                pass
            return f"{a:016x}-{b_:016x}"
        fields = self.msgs.get(mname, {})
        out = {}
        i, n = 0, len(buf)
        while i < n:
            try:
                tag, i = _varint(buf, i)
                num, wt = tag >> 3, tag & 7
                f = fields.get(num)
                if wt == 0:
                    v, i = _varint(buf, i)
                    raw = v
                elif wt == 1:
                    raw = buf[i:i + 8]
                    if len(raw) < 8:
                        break
                    i += 8
                elif wt == 5:
                    raw = buf[i:i + 4]
                    if len(raw) < 4:
                        break
                    i += 4
                elif wt == 2:
                    ln, i = _varint(buf, i)
                    raw = buf[i:i + ln]
                    if len(raw) < ln:
                        break
                    i += ln
                else:
                    break
            except Truncated:
                break
            if f is None:
                continue
            t, name = f["t"], f["n"]
            if wt == 2 and f["r"] and t not in (T_STRING, T_BYTES, T_MESSAGE, T_GROUP):
                vals = self._packed(raw, t)
                out.setdefault(name, []).extend(vals)
                continue
            val = self._value(raw, wt, t, f, depth)
            if f["r"]:
                out.setdefault(name, []).append(val)
            else:
                out[name] = val
        return out

    def _packed(self, raw, t):
        vals, i = [], 0
        try:
            if t in _SCALAR_FIXED:
                fmt, sz = _SCALAR_FIXED[t]
                while i + sz <= len(raw):
                    vals.append(struct.unpack(fmt, raw[i:i + sz])[0])
                    i += sz
            else:
                while i < len(raw):
                    v, i = _varint(raw, i)
                    vals.append(self._int(v, t))
        except Truncated:
            pass
        return vals

    @staticmethod
    def _int(v, t):
        if t == T_INT32:
            return _signed(v, 32)
        if t == T_INT64:
            return _signed(v, 64)
        if t == T_BOOL:
            return bool(v)
        if t == T_SINT32:
            return (v >> 1) ^ -(v & 1)
        if t == T_SINT64:
            return (v >> 1) ^ -(v & 1)
        return v

    def _value(self, raw, wt, t, f, depth):
        if wt == 0:
            v = self._int(raw, t)
            if t == T_ENUM and "e" in f:
                return f["e"].get(str(v), f["e"].get(v, v))
            return v
        if wt in (1, 5):
            fmt, sz = _SCALAR_FIXED.get(t, ("<Q" if wt == 1 else "<I", 8 if wt == 1 else 4))
            return struct.unpack(fmt, raw)[0]
        if t == T_STRING:
            return raw.decode("utf-8", "replace")
        if t == T_BYTES:
            return raw.hex()
        if t in (T_MESSAGE, T_GROUP) and depth < 8:
            m = f.get("m")
            if m is None:
                return None
            d = self.decode(raw, m, depth + 1)
            if m.endswith("google.protobuf.Any") or m == "Any":
                url = d.get("type_url", "")
                sub = self.lookup(url.rsplit("/", 1)[-1])
                if sub and "value" in d:
                    try:
                        d["value"] = self.decode(bytes.fromhex(d["value"]), sub, depth + 1)
                    except Exception:
                        pass
            return d
        return None


def _before(a, b):
    return ((a - b) & 0xFFFFFFFF) > 0x7FFFFFFF


class Stream:

    def __init__(self):
        self.next = None
        self.buf = bytearray()
        self.ooo = {}
        self.gap_since = None

    def feed(self, seq, data, now=None):
        if not data:
            return
        if self.next is not None:
            ahead = (seq - self.next) & 0xFFFFFFFF
            behind = (self.next - seq) & 0xFFFFFFFF
            if min(ahead, behind) > STREAM_NEW_CONN_BYTES:
                self.next = None
                self.buf.clear()
                self.ooo.clear()
                self.gap_since = None
        if self.next is None:
            self.next = seq
        if seq == self.next:
            self.buf += data
            self.next = (self.next + len(data)) & 0xFFFFFFFF
        elif _before(seq, self.next):
            skip = (self.next - seq) & 0xFFFFFFFF
            if skip < len(data):
                self.buf += data[skip:]
                self.next = (self.next + len(data) - skip) & 0xFFFFFFFF
        else:
            if len(self.ooo) > 64:
                self.ooo.clear()
                self.next = seq
                self.buf.clear()
                self.buf += data
                self.next = (seq + len(data)) & 0xFFFFFFFF
                return
            self.ooo[seq] = data
        while self.next in self.ooo:
            d = self.ooo.pop(self.next)
            self.buf += d
            self.next = (self.next + len(d)) & 0xFFFFFFFF
        if not self.ooo:
            self.gap_since = None
        elif now is not None:
            self.gap_since = self.gap_since or now
            if now - self.gap_since > STREAM_GAP_S:
                self.next = min(self.ooo, key=lambda k: (k - self.next) & 0xFFFFFFFF)
                self.buf.clear()
                self.gap_since = None
                while self.next in self.ooo:
                    d = self.ooo.pop(self.next)
                    self.buf += d
                    self.next = (self.next + len(d)) & 0xFFFFFFFF

    def frames(self):
        buf = self.buf
        while True:
            if len(buf) < 2:
                return
            ln = buf[0] | (buf[1] << 8)
            if ln == 0:
                del buf[:2]
                continue
            if ln > 60000:
                del buf[:1]
                continue
            if len(buf) < 2 + ln:
                return
            body = bytes(buf[2:2 + ln])
            if len(body) >= 3:
                typ = body[0] | (body[1] << 8)
                nl = body[2]
                nm = body[3:3 + nl]
                if typ == 2 and nl >= 3 and len(nm) == nl and all(32 <= c < 127 for c in nm):
                    del buf[:2 + ln]
                    yield nm.decode("ascii"), body[3 + nl:]
                    continue
            del buf[:1]


class RefLap:

    def __init__(self, doc):
        self.pts = [p for p in doc.get("pts", []) if len(p) >= 2]
        self.ms = doc.get("ms")
        self.has_t = bool(self.pts) and all(len(p) >= 4 and p[3] is not None for p in self.pts)
        self.cum = [0.0]
        for a, b in zip(self.pts, self.pts[1:]):
            self.cum.append(self.cum[-1] + math.hypot(b[0] - a[0], b[1] - a[1]))
        self.total = self.cum[-1] or 1.0
        self.vref = []
        if self.has_t:
            n, k = len(self.pts), 3
            for i in range(n):
                a, b = max(0, i - k), min(n - 1, i + k)
                dt = (self.pts[b][3] - self.pts[a][3]) / 1000.0
                self.vref.append((self.cum[b] - self.cum[a]) / dt * 3.6 if dt > 0 else None)

    def locate(self, x, z, hint=None, window=REF_SEARCH_WINDOW):
        n = len(self.pts)
        if n == 0:
            return None, 1e9
        idx = range(n) if hint is None else (
            (hint + k) % n for k in range(-window // 3, window))
        best, bd = None, 1e18
        for i in idx:
            p = self.pts[i]
            d = (p[0] - x) ** 2 + (p[1] - z) ** 2
            if d < bd:
                best, bd = i, d
        return best, math.sqrt(bd)


def _bytes8(v):
    return list(int(v or 0).to_bytes(8, "little"))


def car_label(cid):
    return cid


class Hub:
    def __init__(self, schema, out_dir, live_server=None, season_file=SEASON_FILE):
        self.schema = schema
        self.out = Path(out_dir)
        self.out.mkdir(parents=True, exist_ok=True)
        (self.out / "traces").mkdir(exist_ok=True)
        self.live = live_server
        self.season_file = season_file
        self.now = time.time()
        self.replay = False
        self.cars = {}
        self.ip_car = {}
        self.streams = {}
        self.seen_laps = set()
        self._seen_splits = set()
        self.recent_laps = deque(maxlen=RECENT_LAPS)
        self.recent_incidents = deque(maxlen=RECENT_INCIDENTS)
        self.stats = {"pkts": 0, "tcp_msgs": 0, "udp_pos": 0, "laps": 0, "start": time.time()}
        self.msg_counts = {}
        self._laps_f = open(self.out / "laps.jsonl", "a", encoding="utf-8")
        self._inc_f = open(self.out / "incidents.jsonl", "a", encoding="utf-8")
        self._load_history()
        self.lock = threading.RLock()
        self._ref = None
        self._ref_check = 0.0
        self._resets_seen = {}
        self._race_events_seen = set()
        self._passings = {}
        self._unbound = {}
        self.connected = {}
        self._last_heal = 0.0
        self.stats.update({"udp_unbound": 0, "healed": 0, "rebinds": 0, "conn_closed": 0})
        self._rc_seen = {}
        self._last_pass = {}
        self.race = None
        self._race_reset()
        self._race_load()

    def _load_history(self):
        p = self.out / "laps.jsonl"
        try:
            with open(p, encoding="utf-8") as f:
                for line in f.readlines()[-RECENT_LAPS:]:
                    try:
                        e = json.loads(line)
                        self.seen_laps.add(e["id"])
                        self.recent_laps.append(e)
                    except Exception:
                        pass
        except OSError:
            pass

    def track_key(self):
        try:
            ev = json.loads(Path(self.season_file).read_text()).get("event", {})
            return f"{ev.get('track', DEFAULT_TRACK)} {ev.get('layout', '')}".strip()
        except Exception:
            return DEFAULT_TRACK

    def trace_path(self, track):
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", track).strip("_") or "track"
        return self.out / "traces" / f"{safe}.json"

    def ref(self):
        if self.now - self._ref_check < 5 and self._ref is not None:
            return self._ref[2]
        self._ref_check = self.now
        track = self.track_key()
        p = self.trace_path(track)
        try:
            mt = p.stat().st_mtime
        except OSError:
            self._ref = (track, 0, None)
            return None
        if self._ref is None or self._ref[0] != track or self._ref[1] != mt:
            try:
                self._ref = (track, mt, RefLap(json.loads(p.read_text())))
            except Exception:
                self._ref = (track, mt, None)
            for c in self.cars.values():
                c["ref_i"] = None
        return self._ref[2]

    def car(self, cid):
        c = self.cars.get(cid)
        if c is None:
            c = {"id": cid, "ip": None, "x": None, "y": None, "z": None, "v": 0.0,
                 "h": 0.0, "pos_t": 0.0, "lap": 0, "cuts": 0, "hits": 0, "ok": True,
                 "splits": [], "pit": None, "pitlane": False, "elec": None,
                 "n_pos": None, "trace": [], "last_trace_t": 0.0, "marks": {},
                 "finished": None, "seen": self.now, "number": None, "dirty": True,
                 "why": None, "start": None, "start_pending": False,
                 "lap_t0": None, "ref_i": None, "prog": None, "rt": None,
                 "diag": {"elec": None, "assists": None, "instr": None, "loc": None,
                          "pit": None, "plan": None, "bop": None,
                          "tyres": None, "body_dirt": None, "damage": None,
                          "contacts": {"lap": 0, "total": 0, "last_kmh": None, "last_ts": None,
                                       "last_with": None},
                          "resets": 0, "last_reset": None},
                 "diag_dirty": True, "diag_sent": 0.0}
            self.cars[cid] = c
        c["seen"] = self.now
        return c

    def packet(self, ts, ip_src, sport, ip_dst, dport, proto, tcp_seq, payload, flags=0):
        self.now = ts
        self.stats["pkts"] += 1
        c2s = dport == GAME_PORT
        client = ip_src if c2s else ip_dst
        cport = sport if c2s else dport
        if proto == 6:
            key = (client, cport, c2s)
            if flags & TCP_SYN:
                self.streams.pop(key, None)
            if flags & (TCP_FIN | TCP_RST):
                self._connection_closed(client, cport)
            if not payload:
                return
            st = self.streams.get(key)
            if st is None:
                st = self.streams[key] = Stream()
            st.feed(tcp_seq, payload, self.now)
            for name, body in st.frames():
                self.message(name, body, c2s, client)
        elif proto == 17 and c2s and len(payload) == UDP_TELEMETRY_SIZE and payload[0] == 1:
            self.udp_position(client, payload)

    def _connection_closed(self, client, cport):
        for k in [k for k in self.streams if k[0] == client and k[1] == cport]:
            del self.streams[k]
        if not any(k[0] == client for k in self.streams) and client in self.ip_car:
            del self.ip_car[client]
            self.stats["conn_closed"] += 1

    def heal(self):
        now = self.now
        for ip, cid in list(self.ip_car.items()):
            if self.connected.get(cid) is False:
                del self.ip_car[ip]
        self._unbound = {ip: t for ip, t in self._unbound.items() if now - t < UNBOUND_RECENT_S * 10}
        unbound = [ip for ip, t in self._unbound.items() if now - t < UNBOUND_RECENT_S and ip not in self.ip_car]
        if len(unbound) != 1:
            return
        bound = set(self.ip_car.values())
        with_pos = {c["id"] for c in self.cars.values() if now - c["pos_t"] < UNBOUND_RECENT_S}
        cands = [cid for cid, on in self.connected.items() if on and cid not in bound and cid not in with_pos]
        if len(cands) == 1:
            self._bind(unbound[0], cands[0])
            self.stats["healed"] += 1
            print(f"lapwatch: client re-bound to car {cands[0][:8]} by elimination", flush=True)

    def udp_position(self, ip, p):
        cid = self.ip_car.get(ip)
        if cid is None:
            self._unbound[ip] = self.now
            self.stats["udp_unbound"] += 1
            return
        try:
            x, y, z = struct.unpack_from("<fff", p, 9)
            vx, vy, vz = struct.unpack_from("<fff", p, 33)
        except struct.error:
            return
        if not (abs(x) < 1e5 and abs(z) < 1e5):
            return
        self.stats["udp_pos"] += 1
        c = self.car(cid)
        c["x"], c["y"], c["z"] = x, y, z
        sp = math.hypot(vx, vz)
        c["v"] = sp * 3.6
        if sp > 1.0:
            c["h"] = math.degrees(math.atan2(vx, vz)) % 360
        c["pos_t"] = self.now
        c["tel"] = (p[53], p[51] | p[52] << 8, p[54], p[55], p[50] - 128)
        c["dirty"] = True
        if c.get("start_pending"):
            c["start"], c["start_pending"] = (round(x, 1), round(z, 1)), False
        ref = self.ref()
        if ref is not None:
            i, d = ref.locate(x, z, c["ref_i"])
            if i is not None and d < REF_MATCH_M:
                c["ref_i"] = i
                c["prog"] = ref.cum[i] / ref.total
                c["rt"] = ref.pts[i][3] if ref.has_t else None
                c["ref_v"] = ref.vref[i] if ref.vref else None
                c["last_prog"] = c["prog"]
            else:
                c["ref_i"] = None if d > REF_LOST_M else c["ref_i"]
                c["prog"], c["rt"], c["ref_v"] = None, None, None
        self._slow_update(c)
        if self.now - c["last_trace_t"] >= TRACE_STEP_S:
            c["last_trace_t"] = self.now
            t = round((self.now - c["lap_t0"]) * 1000) if c["lap_t0"] else None
            c["trace"].append((round(x, 1), round(z, 1), round(y, 1), t))
            if len(c["trace"]) > TRACE_MAX_POINTS:
                del c["trace"][:TRACE_MAX_POINTS // 6]

    def message(self, name, body, c2s, client):
        self.stats["tcp_msgs"] += 1
        self.msg_counts[name] = self.msg_counts.get(name, 0) + 1
        if name == "ServerWorldTime":
            return
        full = self.schema.lookup(name)
        if full is None or full not in self.schema.msgs:
            return
        try:
            m = self.schema.decode(body, full)
        except Exception:
            return
        with self.lock:
            if c2s and isinstance(m, dict):
                for k in ("car_id", "my_car_pguid"):
                    v = m.get(k)
                    if isinstance(v, str) and v != NULL_ID:
                        self._bind(client, v)
                        break
            fn = getattr(self, "on_" + re.sub(r"\W", "_", name), None)
            if fn:
                fn(m, c2s, client)

    def _bind(self, client, cid):
        if cid and client:
            if self.ip_car.get(client) not in (None, cid):
                self.stats["rebinds"] += 1
            self.ip_car[client] = cid
            self._unbound.pop(client, None)
            c = self.car(cid)
            c["ip"] = client
            return c
        return self.car(cid) if cid else None

    def on_SplitFromRemoteMessage(self, m, c2s, client):
        if not m.get("car_id"):
            return
        sid = m.get("split_id", 0)
        ms = m.get("split_time", 0)
        lapno = m.get("laps_count", 0)
        key = (m["car_id"], lapno, sid, ms, bool(m.get("is_finish_line")))
        if key in self._seen_splits:
            return
        self._seen_splits.add(key)
        if len(self._seen_splits) > 5000:
            self._seen_splits.clear()
        c = self.car(m["car_id"])
        valid = bool(m.get("is_valid"))
        c["n_pos"] = m.get("n_pos")
        c["lap"] = lapno
        pos = (c["x"], c["z"]) if c["x"] is not None else None
        if m.get("is_finish_line"):
            c["finished"] = {"trace": c["trace"], "marks": dict(c["marks"]),
                             "start": c.get("start"), "finish": pos, "valid": valid,
                             "laptime": m.get("laptime"), "cuts": c["cuts"], "hits": c["hits"]}
            c["trace"], c["marks"] = [], {}
            c["splits"] = []
            c["cuts"] = c["hits"] = 0
            c["ok"] = True
            c["why"] = None
            c["start"], c["start_pending"] = None, True
            c["lap_t0"] = self.now
            c["diag"]["contacts"]["lap"] = 0
            c["diag_dirty"] = True
            self.emit({"t": "lapstart", "car": c["id"], "lap": lapno})
        elif m.get("is_start_line") and sid == 0 and ms == 0:
            c["splits"], c["marks"], c["trace"] = [], {}, []
            c["cuts"] = c["hits"] = 0
            c["ok"], c["why"] = True, None
            c["start"], c["start_pending"] = None, True
            c["lap_t0"] = self.now
            c["diag"]["contacts"]["lap"] = 0
            c["diag_dirty"] = True
        else:
            c["splits"].append({"id": sid, "ms": ms, "ok": valid})
            c["ok"] = valid and c["cuts"] == 0
            if not valid and c["why"] is None:
                c["why"] = "cut" if c["cuts"] else "inv"
            if pos:
                c["marks"][sid] = pos
        c["dirty"] = True
        self.emit({"t": "split", "car": c["id"], "id": sid, "ms": ms, "ok": valid,
                   "lap": lapno, "fin": bool(m.get("is_finish_line"))})
        self._race_passing(c["id"], lapno, sid, bool(m.get("is_finish_line")))

    def on_UpdateDirtStatus(self, m, c2s, client):
        if not c2s:
            return
        c = self._bind(client, m.get("car_id"))
        if c is None:
            return
        c["diag"]["body_dirt"] = _bytes8(m.get("dirt_values"))
        c["diag_dirty"] = True

    def on_UpdateTyreStatus(self, m, c2s, client):
        if not c2s:
            return
        c = self._bind(client, m.get("car_id"))
        if c is None:
            return
        dw = _bytes8(m.get("tyre_dmg_and_wear"))
        dd = _bytes8(m.get("tyre_dirt_and_wetness"))
        c["diag"]["tyres"] = {"wear": dw[0:4], "damage": dw[4:8], "dirt": dd[0:4], "wet": dd[4:8]}
        c["diag_dirty"] = True

    def on_UpdateVisualDamages(self, m, c2s, client):
        if not m.get("car_id"):
            return
        c = self._bind(client, m["car_id"]) if c2s else self.car(m["car_id"])
        v = list(m.get("visual_damages") or [])
        zones = ("front", "rear", "left", "right", "center")
        c["diag"]["damage"] = {z: round(v[i], 3) if i < len(v) else 0.0 for i, z in enumerate(zones)}
        c["diag_dirty"] = True

    def on_CommandFromUI_TeleportToPit(self, m, c2s, client):
        cid = self.ip_car.get(client) if c2s else None
        if cid:
            self.car(cid)["want_pit"] = self.now

    def on_TeleportCarCommand(self, m, c2s, client):
        cid = m.get("car_id")
        if not cid:
            return
        c = self.car(cid)
        if self.now - c.get("want_pit", 0) > PIT_REQUEST_WINDOW_S:
            return
        last = self._resets_seen.get(cid, 0)
        if self.now - last < RESET_DEDUP_S:
            return
        self._resets_seen[cid] = self.now
        d = c["diag"]
        d["resets"] += 1
        d["last_reset"] = round(self.now, 1)
        c["diag_dirty"] = True
        self.incident({"t": "reset", "ts": round(self.now, 3), "car": cid, "lap": c["lap"],
                       "repair": bool(m.get("repair_car")), "x": c["x"], "z": c["z"],
                       "track": self.track_key()})

    def on_RaceTimingCut(self, m, c2s, client):
        if not c2s:
            return
        c = self._bind(client, m.get("car_id"))
        if c is None:
            return
        if not m.get("remove_current_lap") or c["lap"] < 1 or c["pitlane"]:
            return
        c["cuts"] += 1
        c["ok"] = False
        c["why"] = "cut"
        c["dirty"] = True
        if c["cuts"] == 1:
            inc = {"t": "cut", "ts": round(self.now, 3), "car": c["id"], "lap": c["lap"],
                   "x": c["x"], "z": c["z"], "track": self.track_key()}
            self.incident(inc)

    def on_CarCollisionEventData(self, m, c2s, client):
        if not c2s:
            return
        c = self._bind(client, m.get("my_car_pguid"))
        if c is None:
            return
        v = m.get("relative_impact_velocity", 0.0)
        n = m.get("normal") or {}
        if v < MIN_IMPACT_MS or abs(n.get("y", 0.0)) > FLOOR_NORMAL_Y:
            return
        ct = c["diag"]["contacts"]
        ct["lap"] += 1
        ct["total"] += 1
        ct["last_kmh"] = round(v * 3.6)
        ct["last_ts"] = round(self.now, 1)
        ct["last_with"] = "car" if m.get("optional_other_car_pguid") else "barrier"
        c["diag_dirty"] = True
        if not HITS_ENABLED:
            return
        c["hits"] += 1
        wp = m.get("worldPos") or {}
        inc = {"t": "hit", "ts": round(self.now, 3), "car": c["id"], "lap": c["lap"],
               "v": round(v * 3.6, 1), "x": wp.get("x"), "z": wp.get("z"),
               "other": m.get("optional_other_car_pguid"),
               "dmg": bool(m.get("damages")), "track": self.track_key()}
        self.incident(inc)

    def on_PlatformRaceGameCarTimelineMessage(self, m, c2s, client):
        if c2s:
            c = self._bind(client, m.get("car_id"))
        else:
            c = self.car(m["car_id"]) if m.get("car_id") else None
        if c is None:
            return
        c["pitlane"] = bool(m.get("on_pitlane"))
        c["dirty"] = True

    def on_UpdateGameCarState(self, m, c2s, client):
        if not c2s:
            return
        c = self._bind(client, m.get("car_id"))
        if c is None:
            return
        d = c["diag"]
        if "pit_state" in m:
            ps = m["pit_state"]
            c["pit"] = ps.get("pit_step")
            d["pit"] = {"step": ps.get("pit_step"), "slot": ps.get("pit_slot"),
                        "enabled": bool(ps.get("is_enabled")),
                        "time_ms": ps.get("total_pit_time_ms")}
        if "electronics_values" in m:
            e = dict(m["electronics_values"])
            if "brake_bias" in e:
                e["brake_bias"] = round(e["brake_bias"], 4)
            c["elec"] = d["elec"] = e
        if "assists_values" in m:
            d["assists"] = dict(m["assists_values"])
        if "instrumentation_values" in m:
            iv = m["instrumentation_values"]
            d["instr"] = {k: iv.get(k) for k in ("main_light_stage", "wiper_level", "rain_lights",
                                                 "warning_lights", "flashing_lights") if k in iv}
        if "car_location" in m:
            d["loc"] = (m["car_location"] or {}).get("type", "Unassigned")
        if "pit_stop_values" in m:
            d["plan"] = dict(m["pit_stop_values"])
        if "bop_data" in m:
            d["bop"] = dict(m["bop_data"])
        c["dirty"] = True
        c["diag_dirty"] = True

    def on_PlatformRaceLeaderboard_LineUpdateEvent(self, m, c2s, client):
        if c2s:
            return
        line = m.get("updated_line") or {}
        cid = line.get("car_id")
        state = line.get("car_state") or {}
        last = state.get("last_lap") or {}
        if not cid:
            return
        c = self.car(cid)
        c["number"] = line.get("car_number")
        rc = self._race_car(cid)
        if "is_connected" in line:
            self.connected[cid] = bool(line["is_connected"])
        rc["laps"] = line.get("laps", rc.get("laps", 0))
        rc["flags"] = state.get("current_flags", rc.get("flags", 0))
        if (state.get("best_personal_lap") or {}).get("laptime_ms"):
            rc["best_ms"] = state["best_personal_lap"]["laptime_ms"]
        if last.get("laptime_ms"):
            rc["last_ms"] = last["laptime_ms"]
        if m.get("position") and self.race.get("sort") == "Race":
            rc["pos_lb"] = m["position"]
            order = [k for k in self.race["order"] if k != cid]
            order.insert(min(len(order), m["position"] - 1), cid)
            self.race["order"] = order
        self._race_dirty = True
        if not m.get("was_finish_line") or not last.get("laptime_ms"):
            return
        lid = last.get("lap_snowflake_id")
        if lid in self.seen_laps:
            return
        self.seen_laps.add(lid)
        flags = last.get("flags", 0)
        fin = c.get("finished") or {}
        valid = bool(flags & 2) and not (flags & 1)
        ev = {"t": "lap", "id": lid, "ts": round(self.now, 3), "car": cid,
              "lap": line.get("laps"), "ms": last["laptime_ms"],
              "splits": last.get("splits", []), "flags": flags, "valid": valid,
              "pos": m.get("position"), "n": line.get("car_number"),
              "cuts": fin.get("cuts", 0), "hits": fin.get("hits", 0),
              "track": self.track_key(), "session_ts": last.get("session_timestamp")}
        self.stats["laps"] += 1
        self.recent_laps.append(ev)
        self._laps_f.write(json.dumps(ev, separators=(",", ":")) + "\n")
        self._laps_f.flush()
        if valid and len(ev["splits"]) >= 1 and fin.get("trace"):
            self.save_trace(ev, fin)
        self.emit(ev)

    def _race_reset(self):
        self.race = {"mode": None, "session": None, "phase": None, "phase_end": None, "session_start": None,
                     "sort": None, "order": [], "cars": {}, "penalties": {}, "investigations": {},
                     "pit_semaphore": None, "mandatory": {}, "pits": {}, "name": None,
                     "session_index": self.race.get("session_index", -1) if getattr(self, "race", None) else -1}
        self._race_start_gm = None
        self._race_dirty = True

    def _race_load(self):
        try:
            doc = json.loads((self.out / "race.json").read_text())
        except (OSError, ValueError):
            return
        if time.time() - doc.get("saved", 0) > 4 * 3600:
            return
        for k in ("mode", "session", "phase", "phase_end", "session_start", "sort", "session_index", "pit_semaphore"):
            self.race[k] = doc.get(k, self.race.get(k))
        self._race_start_gm = doc.get("start_gm")

    def race_save(self):
        doc = {k: self.race.get(k) for k in ("mode", "session", "phase", "phase_end", "session_start", "sort",
                                             "session_index", "pit_semaphore")}
        doc.update({"start_gm": self._race_start_gm, "saved": time.time()})
        try:
            tmp = self.out / "race.tmp"
            tmp.write_text(json.dumps(doc))
            os.replace(tmp, self.out / "race.json")
        except OSError:
            pass

    def _race_car(self, cid):
        return self.race["cars"].setdefault(cid, {})

    def _session_label(self, mode, length_s):
        try:
            season = json.loads(Path(self.season_file).read_text())
        except Exception:
            season = {}
        gt = season.get("game_type", "")
        if mode == "InstantRace":
            return "Race"
        if gt.endswith("HOTLAP"):
            return "Hotlap"
        if not gt.endswith("RACE_WEEKEND"):
            return "Practice"
        gc = season.get("game_config", {})
        cands = [(n, gc.get(k) or 0) for n, k in (("Practice", "practice_duration"), ("Qualifying", "qualify_duration"),
                                                   ("Warm-up", "warmup_duration")) if gc.get(k)]
        if length_s:
            close = [n for n, d in cands if abs(d - length_s) <= 5]
            if len(close) == 1:
                return close[0]
        idx = self.race["session_index"]
        return cands[idx][0] if 0 <= idx < len(cands) else (cands[0][0] if cands else "Practice")

    def _race_phase(self, mode, data):
        cur = data.get("current_gamemode_time") or 0.0
        first = (data.get("session_phase_pairs") or [{}])[0]
        start = data.get("start_gamemode_time")
        if start is None:
            start = (first.get("end_timestamp") or {}).get("timestamp")
        if start is not None:
            start = (mode, round(start, 1))
        if start is not None and start != (tuple(self._race_start_gm) if isinstance(self._race_start_gm, list) else self._race_start_gm):
            idx, prev = self.race["session_index"], self.race.get("mode")
            self._race_reset()
            self.race["session_index"] = idx + 1 if (prev == mode == "TimeAttack" and idx >= 0) else 0
            self._race_start_gm = start
        pairs = data.get("session_phase_pairs") or []
        enum0 = "Waiting_For_Players" if mode == "InstantRace" else "Waiting_For_Start"
        phase = data.get("current_phase", enum0)
        self.race["mode"] = mode
        self.race["phase"] = phase
        end = None
        names = [p.get("phase", enum0) for p in pairs]
        for p in pairs:
            if p.get("phase", enum0) == phase and p.get("is_set"):
                ts = (p.get("end_timestamp") or {}).get("timestamp")
                if ts is not None:
                    end = self.now + (ts - cur) / 1000.0
        self.race["phase_end"] = round(end, 1) if end else None
        first_end = None
        sess_end = None
        for p, n in zip(pairs, names):
            ts = (p.get("end_timestamp") or {}).get("timestamp")
            if ts is None or not p.get("is_set"):
                continue
            if n == enum0:
                first_end = ts
            if n == "Session":
                sess_end = ts
        if first_end is not None and self.race["session_start"] is None and phase != enum0:
            self.race["session_start"] = round(self.now - (cur - first_end) / 1000.0, 1)
        length = (sess_end - first_end) / 1000.0 if sess_end and first_end is not None else None
        self.race["session"] = self.race.get("name") or self._session_label(mode, length)
        self._race_dirty = True

    def _race_leaderboard(self, lb):
        self.race["sort"] = lb.get("type", "PlatformRaceLeaderboardSortType_Qualy").rsplit("_", 1)[-1]
        order = []
        for line in lb.get("lines") or []:
            cid = line.get("car_id")
            if not cid:
                continue
            order.append(cid)
            self.connected[cid] = bool(line.get("is_connected"))
            st = line.get("car_state") or {}
            c = self._race_car(cid)
            c.update({"laps": line.get("laps", 0), "connected": bool(line.get("is_connected")),
                      "number": line.get("car_number"), "flags": st.get("current_flags", 0),
                      "best_ms": (st.get("best_personal_lap") or {}).get("laptime_ms"),
                      "last_ms": (st.get("last_lap") or {}).get("laptime_ms")})
        if order:
            self.race["order"] = order
            if self.race["sort"] == "Race":
                for i, cid in enumerate(order):
                    self._race_car(cid)["pos_lb"] = i + 1
        if lb.get("penalties"):
            self._race_penalties(lb["penalties"])

    def _race_penalties(self, pc):
        out = {}
        for item in pc.get("session_penalties") or []:
            cid = item.get("car_id")
            if not cid:
                continue
            def conv(p):
                pd = p.get("penalty_data") or {}
                return {"type": str(pd.get("type", "PenaltyType_Warning")).replace("PenaltyType_", ""),
                        "time_ms": pd.get("penalty_time_ms"),
                        "why": str(p.get("investigation", "")).replace("InvestigationType_", "") or None,
                        "lap": p.get("given_lap_count")}
            out[cid] = {"pending": [conv(p) for p in item.get("pending_penalties") or []],
                        "cleared": len(item.get("cleared_penalties") or [])}
        self.race["penalties"] = out

    def _race_positions(self, rp):
        gaps = {f.get("car_id"): f.get("time_ahead_current") for f in rp.get("filtered_time") or [] if f.get("car_id")}
        for car in rp.get("cars") or []:
            cid = car.get("car_id")
            if not cid:
                continue
            c = self._race_car(cid)
            c.update({"pos": car.get("position"), "laps_rt": car.get("lap_count"),
                      "npos": round(car.get("n_pos", 0.0), 4), "ahead_ms": gaps.get(cid, car.get("time_ahead")),
                      "loc": ((car.get("carLocation") or {}).get("type") or "Unassigned").replace("Type_", "")})

    def _race_realtime(self, rl):
        for car in rl.get("cars") or []:
            cid = car.get("car_id")
            if cid:
                c = self._race_car(cid)
                c.update({"pos": car.get("position", c.get("pos")), "laps_rt": car.get("lap_count", c.get("laps_rt")),
                          "lap_flags": car.get("lap_flags", 0)})

    def on_BroadcastStateMessage(self, m, c2s, client):
        if c2s:
            return
        desc = m.get("descriptor_name") or ""
        mode = desc.split(".", 1)[0]
        if mode not in ("TimeAttack", "InstantRace", "HotStint"):
            return
        any_ = m.get("message") or {}
        url = any_.get("type_url", "").rsplit("/", 1)[-1]
        val = any_.get("value")
        if not isinstance(val, dict):
            if isinstance(val, str) and m.get("field_number") == 1000:
                self.race["name"] = val
            return
        if url.endswith("SessionPhaseData"):
            self._race_phase(mode, val)
        elif url == "PlatformRaceLeaderboard":
            self._race_leaderboard(val)
        elif url == "PlatformRacePenaltyCollection":
            self._race_penalties(val)
        elif url == "RealtimePositions":
            self._race_positions(val)
        elif url == "RealtimeLeaderboard":
            self._race_realtime(val)
        elif url.endswith("TrackStatus"):
            self.race["pit_semaphore"] = val.get("pitexit_semaphore", "Off")
        elif url.endswith("MandatoryPistops"):
            self.race["mandatory"] = {i["car_id"]: i.get("done") or [] for i in val.get("items") or [] if i.get("car_id")}
        elif url == "StringValue" and isinstance(val.get("value"), str):
            self.race["name"] = val["value"]
        else:
            return
        self.race["mode"] = mode
        self._race_dirty = True

    def on_BroadcastCarStateMessage(self, m, c2s, client):
        if c2s or not m.get("car_id"):
            return
        val = (m.get("message") or {}).get("value")
        if isinstance(val, dict) and "types" in val:
            types = [str(t).replace("InvestigationType_", "") for t in val.get("types") or []]
            self.race["investigations"][m["car_id"]] = types
            self._race_dirty = True

    def _race_event(self, kind, cid, extra):
        key = (kind, cid, round(self.now))
        if key in self._race_events_seen:
            return
        self._race_events_seen.add(key)
        if len(self._race_events_seen) > 2000:
            self._race_events_seen.clear()
        c = self.cars.get(cid) or {}
        self.incident({"t": kind, "ts": round(self.now, 3), "car": cid, "lap": c.get("lap"),
                       "x": c.get("x"), "z": c.get("z"), "track": self.track_key(), **extra})

    def on_PlatformPitstopStart(self, m, c2s, client):
        cid = m.get("car_id")
        if cid:
            self._race_event("pit_in", cid, {})

    def on_PlatformPitstopEnd(self, m, c2s, client):
        cid = m.get("car_id")
        if not cid:
            return
        key = ("pit_out", cid, round(self.now))
        if key not in self._race_events_seen:
            p = self.race["pits"]
            p[cid] = p.get(cid, 0) + 1
            self._race_dirty = True
        self._race_event("pit_out", cid, {"fuel": bool(m.get("has_refuelled")),
                                          "tyres": m.get("changed_tyres_count", 0) if m.get("has_changed_tyres") else 0,
                                          "pit_ms": m.get("session_time_pitlane_crossed_ms")})

    def on_PlatformPenaltyScoredMessage(self, m, c2s, client):
        cid = m.get("car_id")
        if not cid:
            return
        p = m.get("penalty") or {}
        pd = p.get("penalty_data") or {}
        self._race_event("penalty", cid, {"pen": str(pd.get("type", "PenaltyType_Warning")).replace("PenaltyType_", ""),
                                          "pen_ms": pd.get("penalty_time_ms"),
                                          "why": str(p.get("investigation", "")).replace("InvestigationType_", "")})

    def _race_passing(self, cid, lapno, sid, fin):
        if self.race.get("mode") != "InstantRace":
            return
        key = (lapno, sid, fin)
        self._passings.setdefault(key, {})[cid] = self.now
        self._last_pass[cid] = key
        if len(self._passings) > 400:
            for k in sorted(self._passings)[:100]:
                del self._passings[k]

    def _race_gaps(self, order):
        out = {}
        for i, cid in enumerate(order):
            k = self._last_pass.get(cid)
            pts = self._passings.get(k) if k else None
            if not pts or cid not in pts:
                continue
            t = pts[cid]
            lead = pts.get(order[0]) if order else None
            ahead = pts.get(order[i - 1]) if i > 0 else None
            out[cid] = {"gap_ms": round((t - lead) * 1000) if lead is not None and i > 0 else (0 if i == 0 else None),
                        "int_ms": round((t - ahead) * 1000) if ahead is not None else None}
        return out

    NOTIFY_KINDS = {"UINotificationType_SessionPenalty": "penalty", "UINotificationType_RaceControl": "race_control",
                    "UINotificationType_Session": "session", "UINotificationType_Weather": "weather"}
    NOTIFY_KEYS = {"PENALTY_ADDED_KEY": "Penalty", "PENALTY_CLEARED_KEY": "Penalty served",
                   "PENALTY_REMOVED_KEY": "Penalty removed"}

    def on_UINotification(self, m, c2s, client):
        if c2s:
            return
        kind = self.NOTIFY_KINDS.get(m.get("type"))
        if not kind:
            return
        words = []
        for t in m.get("tuples") or []:
            for v in t.get("values") or []:
                v = str(v)
                mm = re.match(r"\{([A-Z_]+)\}", v)
                if mm:
                    words.append(self.NOTIFY_KEYS.get(mm.group(1), mm.group(1).replace("_KEY", "").replace("_", " ").title()))
                    continue
                v = re.sub(r"^(PenaltyType|InvestigationType|UINotification\w*?)_", "", v).replace("_", " ")
                if v:
                    words.append(v)
        text = " · ".join(w for w in words if w)[:160]
        if not text:
            return
        cid = m.get("car_pguid") or ""
        key = ("rc", cid, text)
        if self.now - self._rc_seen.get(key, 0) < 10:
            return
        self._rc_seen[key] = self.now
        c = self.cars.get(cid) or {}
        self.incident({"t": "rc", "ts": round(self.now, 3), "car": cid, "lap": c.get("lap"), "kind": kind,
                       "text": text, "track": self.track_key()})

    def race_frame(self):
        with self.lock:
            r = self.race
            cars = []
            gaps = self._race_gaps(r["order"]) if r.get("sort") == "Race" else {}
            for cid in list(r["order"]) + [k for k in r["cars"] if k not in r["order"]]:
                c = dict(r["cars"].get(cid) or {})
                c["id"] = cid
                if c.get("pos") is None and c.get("pos_lb") is not None:
                    c["pos"] = c["pos_lb"]
                c.update(gaps.get(cid, {}))
                c["pen"] = (r["penalties"].get(cid) or {}).get("pending", [])
                c["inv"] = r["investigations"].get(cid, [])
                c["pits"] = r["pits"].get(cid, 0)
                if cid in r["mandatory"]:
                    c["mandatory"] = r["mandatory"][cid]
                cars.append(c)
            return {"t": "race", "ts": round(self.now, 3), "mode": r["mode"], "session": r["session"],
                    "phase": r["phase"], "phase_end": r["phase_end"], "session_start": r["session_start"],
                    "sort": r["sort"], "pit_semaphore": r["pit_semaphore"], "cars": cars}

    def save_trace(self, ev, fin):
        pts = fin["trace"]
        if len(pts) < TRACE_MIN_POINTS or ev["ms"] < TRACE_MIN_LAP_MS:
            return
        track = ev["track"]
        path = self.trace_path(track)
        try:
            cur = json.loads(path.read_text())
            if cur.get("v", 1) >= 2 and cur.get("ms", 1e12) <= ev["ms"]:
                return
        except Exception:
            pass
        if not all(len(p) >= 4 and p[3] is not None for p in pts):
            return
        marks = [{"k": f"s{k + 1}", "x": v[0], "z": v[1]}
                 for k, v in sorted(fin["marks"].items()) if v]
        if fin.get("finish"):
            marks.append({"k": "fin", "x": fin["finish"][0], "z": fin["finish"][1]})
        st = fin.get("start")
        if st and fin.get("finish") and math.hypot(st[0] - fin["finish"][0], st[1] - fin["finish"][1]) > PIT_START_GAP_M:
            marks.append({"k": "start", "x": st[0], "z": st[1]})
        doc = {"v": 2, "track": track, "ms": ev["ms"], "saved": int(self.now),
               "pts": [list(p) for p in pts], "marks": marks}
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(doc, separators=(",", ":")))
        os.replace(tmp, path)
        self.emit({"t": "trace", "track": track})

    def incident(self, inc):
        self.recent_incidents.append(inc)
        self._inc_f.write(json.dumps(inc, separators=(",", ":")) + "\n")
        self._inc_f.flush()
        self.emit(inc)

    def emit(self, obj):
        if self.live:
            self.live.broadcast(obj)

    def _slow_update(self, c):
        phase = self.race.get("phase") or ""
        on_track = (not c["pitlane"] and c["diag"]["loc"] not in ("Pitlane", "Pitentry", "Pitexit")
                    and c.get("last_prog") is not None and not phase.startswith(NO_YELLOW_PHASES))
        ref_v = c.get("ref_v")
        if ref_v and ref_v >= SLOW_MIN_REF_KMH:
            slow_now = c["v"] < ref_v * SLOW_RATIO
        else:
            slow_now = c["v"] < SLOW_ABS_KMH
        slow_now = bool(on_track and slow_now)
        if slow_now:
            c["slow_since"] = c.get("slow_since") or self.now
            c["fast_since"] = None
            if not c.get("slow") and self.now - c["slow_since"] >= SLOW_CONFIRM_S:
                c["slow"] = True
                c["dirty"] = True
                self.emit({"t": "yellow", "car": c["id"], "on": True, "pr": c.get("last_prog"), "ts": round(self.now, 3)})
        else:
            c["slow_since"] = None
            c["fast_since"] = c.get("fast_since") or self.now
            if c.get("slow") and (self.now - c["fast_since"] >= SLOW_CLEAR_S or not on_track):
                c["slow"] = False
                c["dirty"] = True
                self.emit({"t": "yellow", "car": c["id"], "on": False, "ts": round(self.now, 3)})

    def positions_frame(self):
        with self.lock:
            cars = []
            for c in self.cars.values():
                if c["x"] is None or self.now - c["pos_t"] > CAR_STALE_S:
                    continue
                cars.append({"id": c["id"], "x": round(c["x"], 1), "z": round(c["z"], 1),
                             "y": round(c["y"], 1), "v": round(c["v"]), "h": round(c["h"]),
                             "lap": c["lap"], "ok": c["ok"], "cuts": c["cuts"],
                             "pit": c["pit"], "pl": c["pitlane"], "n": c["number"], "w": c["why"],
                             "np": c["n_pos"], "sp": len(c["splits"]),
                             "pr": round(c["prog"], 4) if c["prog"] is not None else None,
                             "el": round((self.now - c["lap_t0"]) * 1000) if c["lap_t0"] else None,
                             "rt": c["rt"], "loc": c["diag"]["loc"], "tl": c.get("tel"),
                             "sl": 1 if c.get("slow") else 0})
                if cars[-1]["el"] is not None and cars[-1]["el"] < 0:
                    cars[-1]["el"] = None
                if cars[-1]["el"] is not None and cars[-1]["rt"] is not None and cars[-1]["el"] > DELTA_MIN_MS:
                    cars[-1]["dl"] = cars[-1]["el"] - cars[-1]["rt"]
                c["dirty"] = False
            return {"t": "pos", "ts": round(self.now, 3), "cars": cars}

    def diag_frames(self, min_interval=DIAG_INTERVAL_S):
        out = []
        with self.lock:
            for c in self.cars.values():
                if c["diag_dirty"] and self.now - c["diag_sent"] >= min_interval:
                    c["diag_dirty"] = False
                    c["diag_sent"] = self.now
                    out.append({"t": "diag", "car": c["id"], "d": c["diag"]})
        return out

    def snapshot(self):
        with self.lock:
            cars = []
            for c in self.cars.values():
                cars.append({k: c[k] for k in ("id", "lap", "ok", "cuts", "hits", "pit",
                                               "pitlane", "elec", "number", "splits")})
            return {"t": "hello", "ts": round(self.now, 3), "track": self.track_key(),
                    "laps": list(self.recent_laps), "incidents": list(self.recent_incidents),
                    "cars": cars, "diag": {c["id"]: c["diag"] for c in self.cars.values()},
                    "race": self.race_frame()}

    def health(self):
        unbound = [ip for ip, t in self._unbound.items() if self.now - t < UNBOUND_RECENT_S]
        return {"ts": time.time(), "alive": True, "uptime": round(time.time() - self.stats["start"]),
                **{k: self.stats[k] for k in ("pkts", "tcp_msgs", "udp_pos", "laps", "healed", "rebinds", "conn_closed")},
                "cars": len(self.cars), "bound_clients": len(self.ip_car), "unbound_clients": len(unbound),
                "track": self.track_key()}


class LiveServer:
    def __init__(self, path):
        self.path = path
        self.clients = []
        self.lock = threading.Lock()
        self.hub = None
        if path.startswith("tcp://"):
            host, port = path[6:].rsplit(":", 1)
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.sock.bind((host, int(port)))
        else:
            try:
                os.unlink(path)
            except OSError:
                pass
            self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.sock.bind(path)
            os.chmod(path, 0o666)
        self.sock.listen(8)

    def serve(self):
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            conn.settimeout(2.0)
            try:
                conn.sendall((json.dumps(self.hub.snapshot()) + "\n").encode())
            except OSError:
                conn.close()
                continue
            with self.lock:
                self.clients.append(conn)

    def broadcast(self, obj):
        data = (json.dumps(obj, separators=(",", ":")) + "\n").encode()
        with self.lock:
            alive = []
            for c in self.clients:
                try:
                    c.sendall(data)
                    alive.append(c)
                except OSError:
                    try:
                        c.close()
                    except OSError:
                        pass
            self.clients = alive


def parse_ip(ip):
    r = parse_ip_flags(ip)
    return r[:7] if r else None


def parse_ip_flags(ip):
    if len(ip) < 20 or ip[0] >> 4 != 4:
        return None
    ihl = (ip[0] & 15) * 4
    frag = struct.unpack(">H", ip[6:8])[0]
    if frag & 0x3FFF:
        return None
    proto = ip[9]
    tlen = struct.unpack(">H", ip[2:4])[0]
    t = ip[ihl:tlen] if tlen else ip[ihl:]
    src = socket.inet_ntoa(ip[12:16])
    dst = socket.inet_ntoa(ip[16:20])
    if proto == 6 and len(t) >= 20:
        sp, dp, seq = struct.unpack(">HHI", t[:8])
        off = (t[12] >> 4) * 4
        return src, sp, dst, dp, 6, seq, t[off:], t[13]
    if proto == 17 and len(t) >= 8:
        sp, dp = struct.unpack(">HH", t[:4])
        return src, sp, dst, dp, 17, 0, t[8:], 0
    return None


def frame_to_ip(link, data):
    if link == 1:
        if len(data) < 14:
            return None
        et = struct.unpack(">H", data[12:14])[0]
        off = 14
        if et == 0x8100 and len(data) >= 18:
            et = struct.unpack(">H", data[16:18])[0]
            off = 18
        return data[off:] if et == 0x0800 else None
    if link == 113:
        return data[16:] if len(data) > 16 and struct.unpack(">H", data[14:16])[0] == 0x0800 else None
    if link == 276:
        return data[20:] if len(data) > 20 and struct.unpack(">H", data[0:2])[0] == 0x0800 else None
    return None


def handle_frame(hub, ts, link, data):
    ip = frame_to_ip(link, data)
    if ip is None:
        return
    r = parse_ip_flags(ip)
    if r is None:
        return
    src, sp, dst, dp, proto, seq, payload, flags = r
    if sp != GAME_PORT and dp != GAME_PORT:
        return
    hub.packet(ts, src, sp, dst, dp, proto, seq, payload, flags)
    if hub.now - hub._last_heal >= HEAL_INTERVAL_S:
        hub._last_heal = hub.now
        with hub.lock:
            hub.heal()


def read_pcap(path):
    d = Path(path).read_bytes()
    end = "<" if d[:4] == b"\xd4\xc3\xb2\xa1" else ">"
    link = struct.unpack(end + "HHiIII", d[4:24])[5]
    i = 24
    while i + 16 <= len(d):
        s, us, incl, _ = struct.unpack(end + "IIII", d[i:i + 16])
        i += 16
        yield s + us / 1e6, link, d[i:i + incl]
        i += incl


def run_replay(hub, pcap):
    for ts, link, data in read_pcap(pcap):
        hub.now = ts
        handle_frame(hub, ts, link, data)


def run_replay_live(hub, live, pcap, speed, loop):
    hub.replay = True
    threading.Thread(target=live.serve, daemon=True).start()
    start_ticker(hub, live)
    while True:
        first = last = None
        shift = time.time()
        for ts, link, data in read_pcap(pcap):
            if first is None:
                first = ts
                shift = time.time() - ts
            if last is not None:
                dt = (ts - last) / speed
                if 0 < dt < 5:
                    time.sleep(dt)
            last = ts
            hub.now = ts + shift
            handle_frame(hub, hub.now, link, data)
        hub.seen_laps.clear()
        hub._seen_splits.clear()
        if not loop:
            break
        time.sleep(3)


def start_ticker(hub, live):
    def ticker():
        period = 1.0 / POS_HZ
        last_h = 0
        while True:
            time.sleep(period)
            if not hub.replay:
                hub.now = time.time()
            frame = hub.positions_frame()
            if frame["cars"]:
                live.broadcast(frame)
            for df in hub.diag_frames():
                live.broadcast(df)
            if hub._race_dirty and time.time() - ticker.race_t >= 1.0:
                ticker.race_t = time.time()
                hub._race_dirty = False
                live.broadcast(hub.race_frame())
                hub.race_save()
            if time.time() - last_h >= 1.0:
                last_h = time.time()
                try:
                    tmp = hub.out / "live.tmp"
                    tmp.write_text(json.dumps({"health": hub.health(), "pos": frame}))
                    os.replace(tmp, hub.out / "live.json")
                except OSError:
                    pass

    ticker.race_t = 0.0
    threading.Thread(target=ticker, daemon=True).start()


def attach_bpf(sock, port):
    import ctypes

    class Insn(ctypes.Structure):
        _fields_ = [("code", ctypes.c_ushort), ("jt", ctypes.c_ubyte),
                    ("jf", ctypes.c_ubyte), ("k", ctypes.c_uint)]

    class Prog(ctypes.Structure):
        _fields_ = [("len", ctypes.c_ushort), ("filter", ctypes.POINTER(Insn))]

    code = [
        (0x28, 0, 0, 12),
        (0x15, 0, 10, 0x0800),
        (0x30, 0, 0, 23),
        (0x15, 1, 0, 6),
        (0x15, 0, 7, 17),
        (0x28, 0, 0, 20),
        (0x45, 5, 0, 0x1FFF),
        (0xB1, 0, 0, 14),
        (0x48, 0, 0, 14),
        (0x15, 3, 0, port),
        (0x48, 0, 0, 16),
        (0x15, 1, 0, port),
        (0x06, 0, 0, 0),
        (0x06, 0, 0, 0xFFFF),
    ]
    arr = (Insn * len(code))(*[Insn(*c) for c in code])
    prog = Prog(len(code), arr)
    sock.setsockopt(socket.SOL_SOCKET, 26, bytes(prog))
    return arr


def run_live(hub, live, args):
    threading.Thread(target=live.serve, daemon=True).start()

    start_ticker(hub, live)
    s = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.ntohs(3))
    try:
        _keep = attach_bpf(s, GAME_PORT)
        print("lapwatch: kernel BPF filter active", flush=True)
    except Exception as e:
        print(f"lapwatch: BPF unavailable ({e}), filtering in userspace", flush=True)
    if args.iface:
        s.bind((args.iface, 0))
    s.settimeout(1.0)
    print(f"lapwatch: listening (game port {GAME_PORT}), output {hub.out}", flush=True)
    while True:
        try:
            data = s.recv(65535)
        except socket.timeout:
            continue
        hub.now = time.time()
        handle_frame(hub, hub.now, 1, data)


def main():
    ap = argparse.ArgumentParser(description="Passive observer of the Assetto Corsa EVO server protocol")
    ap.add_argument("--pcap", help="replay a pcap file instead of capturing live traffic")
    ap.add_argument("--out", default=str(OUT_DIR), help="output directory")
    ap.add_argument("--iface", default=os.environ.get("LW_IFACE"), help="network interface to capture on")
    ap.add_argument("--season", default=SEASON_FILE, help="season_def.json of the game server")
    ap.add_argument("--dump", action="store_true", help="with --pcap: print a JSON summary")
    ap.add_argument("--serve", action="store_true", help="with --pcap: replay in real time on the live socket")
    ap.add_argument("--speed", type=float, default=1.0, help="with --serve: replay speed factor")
    ap.add_argument("--sock", default=SOCKET_PATH or None, help="live socket path, or tcp://HOST:PORT")
    ap.add_argument("--loop", action="store_true", help="with --serve: replay forever")
    args = ap.parse_args()
    schema = Schema(SCHEMA_FILE)
    if args.pcap and args.serve:
        Path(args.out).mkdir(parents=True, exist_ok=True)
        live = LiveServer(args.sock or os.path.join(args.out, "live.sock"))
        hub = Hub(schema, args.out, live, args.season)
        live.hub = hub
        run_replay_live(hub, live, args.pcap, args.speed, args.loop)
        return
    if args.pcap:
        hub = Hub(schema, args.out, None, args.season)
        run_replay(hub, args.pcap)
        if args.dump:
            print(json.dumps({"stats": hub.stats, "msgs": hub.msg_counts,
                              "laps": list(hub.recent_laps),
                              "incidents": list(hub.recent_incidents)}, indent=1))
        return
    Path(args.out).mkdir(parents=True, exist_ok=True)
    live = LiveServer(args.sock or os.path.join(args.out, "live.sock"))
    hub = Hub(schema, args.out, live, args.season)
    live.hub = hub
    run_live(hub, live, args)


if __name__ == "__main__":
    main()
