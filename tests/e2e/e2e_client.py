import base64
import json
import os
import re
import socket
import struct
import sys
import time
import urllib.parse
import urllib.request

HOST, PORT = "127.0.0.1", int(os.environ.get("E2E_PORT", "8099"))
DURATION = float(os.environ.get("E2E_SECONDS", "75"))
fails = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""), flush=True)
    if not cond:
        fails.append(name)


def http(path, raw=False):
    with urllib.request.urlopen(f"http://{HOST}:{PORT}{path}", timeout=10) as r:
        body = r.read()
        return (r, body) if raw else json.loads(body)


class WS:
    def __init__(self):
        self.s = socket.create_connection((HOST, PORT), timeout=5)
        key = base64.b64encode(os.urandom(16)).decode()
        self.s.sendall((f"GET /ws HTTP/1.1\r\nHost: {HOST}:{PORT}\r\nUpgrade: websocket\r\n"
                        f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
                        f"Sec-WebSocket-Version: 13\r\n\r\n").encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            buf += self.s.recv(4096)
        head, self.buf = buf.split(b"\r\n\r\n", 1)
        self.head = head.decode()
        self.s.settimeout(1.0)

    def frames(self):
        try:
            d = self.s.recv(65536)
            if not d:
                return None
            self.buf += d
        except socket.timeout:
            pass
        out = []
        while len(self.buf) >= 2:
            op, ln = self.buf[0] & 15, self.buf[1] & 127
            i = 2
            if ln == 126:
                if len(self.buf) < 4: break
                ln, i = struct.unpack("!H", self.buf[2:4])[0], 4
            elif ln == 127:
                if len(self.buf) < 10: break
                ln, i = struct.unpack("!Q", self.buf[2:10])[0], 10
            if len(self.buf) < i + ln:
                break
            payload = self.buf[i:i + ln]
            self.buf = self.buf[i + ln:]
            if op == 1:
                out.append(json.loads(payload))
        return out


def main():
    ws = WS()
    check("WebSocket handshake 101", ws.head.startswith("HTTP/1.1 101"), ws.head[:40])
    msgs, t0, first_p, lat = [], time.time(), None, []
    mid = None
    while time.time() - t0 < DURATION:
        if mid is None and time.time() - t0 > 20:
            mid = http("/api/health")
        fr = ws.frames()
        if fr is None:
            break
        for m in fr:
            msgs.append((time.time() - t0, m))
    kinds = {}
    for _, m in msgs:
        kinds[m["t"]] = kinds.get(m["t"], 0) + 1
    print("messages received:", kinds, flush=True)
    check("initial hello", kinds.get("hello") == 1)
    check("live positions (>= 100 frames)", kinds.get("p", 0) >= 100, kinds.get("p"))
    cars = [c for _, m in msgs if m["t"] == "p" for c in m["c"]]
    check("frames carry coordinates", all("x" in c and "z" in c for c in cars[:50]))
    check("plausible speeds (0-400 km/h)", all(0 <= c["v"] < 400 for c in cars))
    laps = {m["ms"]: m for _, m in msgs if m["t"] == "lap"}
    check("3 lap events over WebSocket", len(laps) == 3, sorted(laps))
    check("clean lap valid and PB", laps.get(116202, {}).get("valid") is True and laps[116202].get("pb") is True)
    check("cut lap invalidated", laps.get(102240, {}).get("valid") is False)
    check("out lap invalidated", laps.get(1121787, {}).get("valid") is False)
    check("driver name resolved from the log", all(l.get("driver") == "Test Driver" for l in laps.values()))
    check("live incident events", kinds.get("inc", 0) >= 1, kinds.get("inc"))
    check("live split events", kinds.get("split", 0) >= 3, kinds.get("split"))
    check("status pushed", kinds.get("status", 0) >= 1)
    check("car diagnostics over WebSocket", kinds.get("diag", 0) >= 1, kinds.get("diag"))
    dg = [m["d"] for _, m in msgs if m["t"] == "diag"]
    check("diagnostics: electronics and tyres", any((d.get("elec") or {}).get("tc_level") == 5 for d in dg)
          and any(d.get("tyres") for d in dg))
    check("lap progress (after the first trace)", any(c.get("pr") is not None for c in cars))
    check("running lap time", any(c.get("el") is not None and c["el"] >= 0 for c in cars))
    check("no negative lap time", all(c.get("el") is None or c["el"] >= 0 for c in cars))
    check("live delta computed", any(c.get("dl") is not None for c in cars))
    cid = next((c["i"] for c in cars), None)
    if cid:
        dj = http("/api/diag?cid=" + cid)
        check("api/diag for the connected car", dj.get("diag") and "tyres" in dj["diag"])
    check("map trace event", kinds.get("trace", 0) >= 1, kinds.get("trace"))

    st = [m["s"] for _, m in msgs if m["t"] == "status"][-1]
    rows = (st.get("timing") or {}).get("rows") or []
    check("timing: 1 driver", len(rows) == 1, rows)
    if rows:
        r = rows[0]
        check("best = valid lap", r["best_ms"] == 116202, r["best_ms"])
        check("last lap invalid", r["last_ok"] is False and r["last_ms"] == 102240)
        check("1 valid lap out of 3", (r["valid"], r["laps"]) == (1, 3), (r["valid"], r["laps"]))
        check("cuts counted", r["cuts"] >= 1, r["cuts"])
    check("best sectors", (st["timing"]["sector_best"] or [None])[0] == 36828, st["timing"]["sector_best"])
    check("lapwatch on during the session", any(m["s"]["lapwatch"]["on"] for _, m in msgs if m["t"] == "status"))

    lb = http("/api/leaderboard")
    check("leaderboard: valid lap only", lb["overall"] and lb["overall"]["time_ms"] == 116202, lb["overall"])
    check("leaderboard: sectors saved", lb["overall"] and len(lb["overall"].get("splits", [])) == 3)
    check("leaderboard: cut lap excluded", all(e["time_ms"] != 102240 for c in lb["cars"] for e in c["entries"]))
    api = http("/api/laps?limit=10")
    check("api/laps: 3 laps", len(api["laps"]) == 3)
    check("api/laps valid=1", len(http("/api/laps?valid=1")["laps"]) == 1)
    drv = http("/api/driver?name=" + urllib.parse.quote("Test Driver"))
    check("api/driver statistics", (drv["laps"], drv["valid"], drv["invalid"]) == (3, 1, 2), drv["laps"])
    check("api/driver records", drv["records"] and drv["records"][0]["pos"] == 1)
    try:
        http("/api/driver?name=Nobody")
        check("unknown driver -> 404", False)
    except urllib.error.HTTPError as e:
        check("unknown driver -> 404", e.code == 404)
    mp = http("/api/map?track=" + urllib.parse.quote("Monza GP"))
    check("api/map trace", len(mp.get("pts", [])) >= 300, len(mp.get("pts", [])))
    check("api/health (mid-session)", mid and mid["lapwatch"] is True and mid["ws_clients"] >= 1, mid)

    for path in ("/", "/records", "/laps", "/driver/Test%20Driver", "/car/Porsche%20992", "/style.css",
                 "/app.js", "/map.js", "/live.js", "/records.js", "/driver.js", "/laps.js", "/car.js"):
        r, body = http(path, raw=True)
        check(f"GET {path} 200", r.status == 200 and len(body) > 100)
    r, _ = http("/", raw=True)
    csp = r.headers.get("Content-Security-Policy", "")
    check("CSP: scripts from 'self' only, ws allowed", "script-src 'self'" in csp and f"ws://{HOST}:{PORT}" in csp, csp)
    try:
        http("/../etc/passwd", raw=True)
        check("path traversal blocked", False)
    except urllib.error.HTTPError as e:
        check("path traversal blocked", e.code == 404)
    s = socket.create_connection((HOST, PORT), timeout=5)
    s.sendall((f"GET /ws HTTP/1.1\r\nHost: {HOST}:{PORT}\r\nOrigin: http://evil.example\r\nUpgrade: websocket\r\n"
               f"Connection: Upgrade\r\nSec-WebSocket-Key: x3JJHMbDL1EzLkh9GBhXDw==\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
    check("WS: foreign origin rejected (403)", b" 403 " in s.recv(200))
    blob = json.dumps([st, lb, api, drv])
    check("no SteamID/IP in public output", not re.search(r"7656\d{13}|\b\d{1,3}(?:\.\d{1,3}){3}\b", blob))

    print("\n" + ("ALL PASSED" if not fails else f"FAILED ({len(fails)}): {fails}"))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
