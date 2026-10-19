import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lapwatch"))
import lapwatch as L

FIXTURE = Path(os.environ.get("FIXTURE", ROOT / "tests" / "fixtures" / "session.pcap"))
SCHEMA = ROOT / "lapwatch" / "schema.json"
OUT_LAP_MS = 1121787
CLEAN_LAP_MS = 116202
CUT_LAP_MS = 102240
fails = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""))
    if not cond:
        fails.append(name)


def main():
    tmp = Path(tempfile.mkdtemp())
    season = tmp / "season.json"
    season.write_text(json.dumps({"event": {"track": "Monza", "layout": "GP"}}))
    hub = L.Hub(L.Schema(SCHEMA), tmp / "out", None, str(season))
    L.run_replay(hub, FIXTURE)

    laps = list(hub.recent_laps)
    check("3 laps detected", len(laps) == 3, len(laps))
    by_ms = {l["ms"]: l for l in laps}
    check("lap out of the pits is NOT valid (flags 1)",
          by_ms.get(OUT_LAP_MS, {}).get("valid") is False and by_ms[OUT_LAP_MS]["flags"] == 1)
    check("clean lap 1:56.202 is VALID (flags 2)",
          by_ms.get(CLEAN_LAP_MS, {}).get("valid") is True and by_ms[CLEAN_LAP_MS]["flags"] == 2)
    check("lap with a cut 1:42.240 is NOT valid", by_ms.get(CUT_LAP_MS, {}).get("valid") is False)
    check("cuts counted on the dirty lap", by_ms.get(CUT_LAP_MS, {}).get("cuts", 0) >= 1,
          by_ms.get(CUT_LAP_MS, {}).get("cuts"))
    check("impacts NOT recorded by default", all(l["hits"] == 0 for l in laps))
    check("sector sum = lap time (clean lap)", sum(by_ms[CLEAN_LAP_MS]["splits"]) == CLEAN_LAP_MS,
          by_ms[CLEAN_LAP_MS]["splits"])
    check("3 sectors per lap", all(len(l["splits"]) == 3 for l in laps))
    check("car identified", all(len(l["car"]) == 33 for l in laps))
    check("UDP positions decoded", hub.stats["udp_pos"] > 1000, hub.stats["udp_pos"])
    kinds = {i["t"] for i in hub.recent_incidents}
    check("incidents: cuts and resets, no impacts", "cut" in kinds and "hit" not in kinds
          and kinds <= {"cut", "reset"}, kinds)

    tr = list((tmp / "out" / "traces").glob("*.json"))
    check("map trace saved", len(tr) == 1, tr)
    doc = {}
    if tr:
        doc = json.loads(tr[0].read_text())
        check("trace from the fastest valid lap", doc["ms"] == CLEAN_LAP_MS, doc["ms"])
        check("trace with >= 300 points", len(doc["pts"]) >= 300, len(doc["pts"]))
        check("finish and sector markers", {m["k"] for m in doc["marks"]} >= {"fin", "s1", "s2"})

    car = next(iter(hub.cars.values()))
    d = car["diag"]
    check("electronics decoded (TC/ABS/brake bias)",
          (d["elec"] or {}).get("tc_level") == 5 and d["elec"].get("abs_level") == 4
          and abs(d["elec"].get("brake_bias", 0) - 0.6) < 1e-6, d["elec"])
    check("tyre wear per wheel (4 values)",
          d["tyres"] and len(d["tyres"]["wear"]) == 4 and min(d["tyres"]["wear"]) >= 5, d["tyres"])
    check("bodywork damage in 5 zones",
          d["damage"] and set(d["damage"]) == {"front", "rear", "left", "right", "center"}, d["damage"])
    check("floor scrapes ignored", d["contacts"]["total"] == 0, d["contacts"])
    check("return to pits detected", d["resets"] >= 1, d["resets"])
    check("car location known", d["loc"] == "Track", d["loc"])
    check("telemetry decoded (gear, rpm, pedals)", car.get("tel") is not None and len(car["tel"]) == 5, car.get("tel"))
    if tr:
        check("v2 trace with altitude and time",
              doc.get("v") == 2 and len(doc["pts"][0]) == 4 and doc["pts"][-1][3] > 100000, doc["pts"][-1])

    out2 = tmp / "out2"
    (out2 / "traces").mkdir(parents=True)
    if tr:
        (out2 / "traces" / tr[0].name).write_bytes(tr[0].read_bytes())
    hub3 = L.Hub(L.Schema(SCHEMA), out2, None, str(season))
    deltas, last = {}, 0
    for ts, link, data in L.read_pcap(FIXTURE):
        hub3.now = ts
        L.handle_frame(hub3, ts, link, data)
        if ts - last > 5:
            last = ts
            for c in hub3.positions_frame()["cars"]:
                if c.get("dl") is not None:
                    deltas.setdefault(c["lap"], []).append(c["dl"])
    ref_lap = [abs(x) for x in deltas.get(3, [])]
    cut_lap = deltas.get(4, [])
    check("delta ~0 on the reference lap itself", ref_lap and max(ref_lap) < 500, ref_lap[:5])
    check("strongly negative delta on the cut lap", cut_lap and min(cut_lap) < -8000, cut_lap[:5])

    hub2 = L.Hub(L.Schema(SCHEMA), tmp / "out", None, str(season))
    L.run_replay(hub2, FIXTURE)
    check("no duplicates after a restart (laps.jsonl reloaded)", len(hub2.recent_laps) == 3, len(hub2.recent_laps))

    robustness(tmp, season)

    print("\n%s" % ("ALL PASSED" if not fails else f"FAILED: {fails}"))
    return 1 if fails else 0


def robustness(tmp, season):
    st = L.Stream()
    st.feed(1000, b"aaaa", 0.0)
    st.feed(1000 + 50_000_000, b"bbbb", 0.1)
    check("stream: a new connection on the same port restarts the stream", bytes(st.buf) == b"bbbb", bytes(st.buf))

    st = L.Stream()
    st.feed(1000, b"aaaa", 0.0)
    st.feed(1008, b"cccc", 0.5)
    st.feed(1012, b"dddd", 0.5 + L.STREAM_GAP_S + 0.1)
    check("stream: a lost segment is skipped after the gap timeout", bytes(st.buf) == b"cccc" + b"dddd", bytes(st.buf))

    hub = L.Hub(L.Schema(SCHEMA), tmp / "rob", None, str(season))
    a, b = "A" * 16 + "-" + "1" * 16, "B" * 16 + "-" + "2" * 16
    hub.now = 10.0
    hub._bind("10.0.0.1", a)
    hub.streams[("10.0.0.1", 5000, True)] = L.Stream()
    hub.packet(10.0, "10.0.0.1", 5000, "10.0.0.9", L.GAME_PORT, 6, 0, b"", L.TCP_FIN)
    check("closing the TCP connection unbinds the client", "10.0.0.1" not in hub.ip_car, hub.ip_car)

    hub.streams[("10.0.0.2", 6000, True)] = L.Stream()
    hub.packet(11.0, "10.0.0.2", 6000, "10.0.0.9", L.GAME_PORT, 6, 0, b"", L.TCP_SYN)
    check("a SYN drops the old stream state", ("10.0.0.2", 6000, True) not in hub.streams)

    hub.connected = {a: True, b: True}
    hub._bind("10.0.0.3", a)
    pkt = bytearray(L.UDP_TELEMETRY_SIZE)
    pkt[0] = 1
    hub.now = 12.0
    hub.udp_position("10.0.0.4", bytes(pkt))
    hub.heal()
    check("an unknown client is re-bound to the only connected car without positions",
          hub.ip_car.get("10.0.0.4") == b and hub.stats["healed"] == 1, hub.ip_car)

    hub.connected[a] = False
    hub.heal()
    check("clients of disconnected cars are unbound", "10.0.0.3" not in hub.ip_car, hub.ip_car)

    c = hub.car(a)
    c.update({"pitlane": False, "v": 0.0, "last_prog": 0.74, "ref_v": None, "lap_t0": None})
    c["diag"]["loc"] = "Track"
    hub.race["phase"] = "Session"
    for t in (20.0, 21.0, 22.0):
        hub.now = t
        hub._slow_update(c)
    check("yellow: a car stopped on track is flagged without a lap start", c.get("slow") is True)

    c2 = hub.car(b)
    c2.update({"pitlane": True, "v": 0.0, "last_prog": 0.1, "ref_v": None})
    for t in (20.0, 21.0, 22.0):
        hub.now = t
        hub._slow_update(c2)
    check("yellow: a car in the pit lane is not flagged", not c2.get("slow"))

    c2.update({"pitlane": False, "slow": False, "slow_since": None})
    c2["diag"]["loc"] = "Track"
    hub.race["phase"] = "Start_Countdown_Lights_On"
    for t in (30.0, 31.0, 32.0):
        hub.now = t
        hub._slow_update(c2)
    check("yellow: cars on the grid are not flagged", not c2.get("slow"))

    c.update({"v": 250.0, "ref_v": 260.0})
    hub.race["phase"] = "Session"
    for t in (40.0, 42.0, 44.0):
        hub.now = t
        hub._slow_update(c)
    check("yellow clears when the car is back up to speed", c.get("slow") is False)


if __name__ == "__main__":
    sys.exit(main())
