#!/usr/bin/env python3
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

BASE = Path(os.environ.get("ACE_DIR", Path(__file__).resolve().parent.parent))
CONTAINER = os.environ.get("ACE_CONTAINER", "acevo-server")
SITE = os.environ.get("SITE_URL", "http://127.0.0.1:8090").rstrip("/")
SEASON = BASE / "server-data" / "server" / "season_def.json"
LOG = BASE / "server-data" / "logs" / "server.log"
EVENTS = BASE / "server-data" / "server" / "events_practice.json"
RESULTS = BASE / "tools" / "track_boot_results.json"
BOOT_TIMEOUT_S = int(os.environ.get("BOOT_TIMEOUT_S", "180"))
ANSI = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]")
TS_RE = re.compile(r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")


def set_event(e, original):
    s = json.loads(json.dumps(original))
    s["game_type"] = "GameModeType_PRACTICE"
    s["event"] = {k: e[k] for k in ("track", "layout", "event_name", "track_length", "max_pit_slot")}
    SEASON.write_text(json.dumps(s, indent=2))


def restart():
    subprocess.run(["docker", "restart", "-t", "20", CONTAINER], capture_output=True, timeout=120)


def wait_boot(restart_epoch):
    t0 = time.time()
    while time.time() - t0 < BOOT_TIMEOUT_S:
        try:
            raw = ANSI.sub("", LOG.read_text(errors="replace"))
            m = TS_RE.search(raw)
            if m:
                first = time.mktime(time.strptime(m.group(1), "%Y-%m-%d %H:%M:%S"))
                if first >= restart_epoch - 5 and "Listening to UDP" in raw:
                    return raw
        except OSError:
            pass
        time.sleep(4)
    return None


def dashboard_sees(e):
    for _ in range(8):
        try:
            with urllib.request.urlopen(SITE + "/api/status", timeout=5) as r:
                st = json.loads(r.read())
            if st.get("track") == e["track"] and st.get("layout") == e["layout"] and st.get("online"):
                return True
        except Exception:
            pass
        time.sleep(3)
    return False


def main():
    if "--yes" not in sys.argv:
        sys.exit("This restarts the game server once per track and disconnects every driver. Re-run with --yes.")
    events = json.loads(EVENTS.read_text())["events"]
    original = json.loads(SEASON.read_text())
    results = []
    try:
        for i, e in enumerate(events):
            key = f"{e['track']} {e['layout']}"
            set_event(e, original)
            t_restart = time.time()
            restart()
            raw = wait_boot(t_restart)
            res = {"track": key, "boot": raw is not None,
                   "log_track": bool(raw) and f'"name": "{e["track"]}"' in raw,
                   "log_event": bool(raw) and e["event_name"] in raw}
            res["dashboard"] = res["boot"] and dashboard_sees(e)
            res["verdict"] = "OK" if all(res[k] for k in ("boot", "log_track", "log_event", "dashboard")) else "FAIL"
            results.append(res)
            print(f"[{i + 1}/{len(events)}] {res['verdict']} {key}", flush=True)
            RESULTS.write_text(json.dumps({"results": results}, indent=1))
    finally:
        SEASON.write_text(json.dumps(original, indent=2))
        t_restart = time.time()
        restart()
        print("Original configuration restored:", "OK" if wait_boot(t_restart) else "CHECK MANUALLY", flush=True)
    fails = [r for r in results if r["verdict"] == "FAIL"]
    print(f"RESULT: {len(results) - len(fails)}/{len(results)} tracks OK", flush=True)
    for f in fails:
        print("  FAIL:", f, flush=True)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
