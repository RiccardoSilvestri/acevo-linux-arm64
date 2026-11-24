"""Departed drivers must not linger: log following and connection closing."""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "dashboard"))
sys.path.insert(0, str(ROOT / "lapwatch"))
import app as D
import lapwatch as L

fails = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""))
    if not cond:
        fails.append(name)


def rec(msg, channel="server", second=1):
    return f"[2026-01-01 00:00:{second:02d}.000] [{channel}] [info] {msg}\r\r\n".encode()


def log_tail(tmp):
    log = tmp / "server.log"
    ping = rec("Received Ping from 10.0.0.1 [50000]", "network")
    probe = (rec("New connection received 480") + rec("Alive connections: 1")
             + rec("connection closed 7 due to not established conn") + rec("Server Late, dt 0.51", "network"))
    log.write_bytes(rec("Restart Season") + (ping + probe) * 8000 + rec("Server updated: 0 players"))
    check("log bigger than the tail budget", log.stat().st_size > D.LOG_TAIL_BYTES)

    got = D.tail_lines(str(log))
    check("session marker survives a flood of pings", any("Restart Season" in l for l in got), len(got))
    check("only meaningful records are kept", len(got) == 2, got[:5])

    with open(log, "ab") as f:
        f.write(ping + rec("Disconnected carId abc", "gameplay")[:30])
    check("unfinished line is not parsed yet", not any("Disconn" in l for l in D.tail_lines(str(log))))
    with open(log, "ab") as f:
        f.write(rec("Disconnected carId abc", "gameplay")[30:])
    got = D.tail_lines(str(log))
    check("line completed on a later read", got[-1].endswith("Disconnected carId abc"), got[-1])
    check("nothing is read twice", sum("Restart Season" in l for l in got) == 1)

    with open(log, "ab") as f:
        f.write(rec('connecting gamecar x (Received Ping from | 76561198000000001)'))
    check("a driver name cannot hide a line",
          "connecting gamecar" in D.tail_lines(str(log))[-1])

    os.replace(log, tmp / "server.log.old")
    log.write_bytes(rec("Listening to UDP port 9600"))
    got = D.tail_lines(str(log))
    check("rotated log starts afresh", len(got) == 1 and "Listening" in got[0], got)

    big = tmp / "budget.log"
    big.write_bytes(b"".join(rec(f"line {i}") for i in range(500)))
    tail = D.LogTail(str(big), 2000)
    got = tail.read()
    check("size budget keeps the newest records",
          got[-1].endswith("line 499") and sum(map(len, got)) < 2100, len(got))


def departures(tmp):
    season = tmp / "season.json"
    season.write_text(json.dumps({"event": {"track": "Monza", "layout": "GP"}}))
    hub = L.Hub(L.Schema(ROOT / "lapwatch" / "schema.json"), tmp / "out", None, str(season))
    for ip, cid in (("10.0.0.1", "a" * 33), ("10.0.0.2", "b" * 33)):
        hub._bind(ip, cid)
        hub.connected[cid] = True
        hub._race_car(cid)["connected"] = True
    hub._race_dirty = False
    hub.packet(1.0, "10.0.0.1", 50000, "10.9.9.9", L.GAME_PORT, 6, 1, b"", L.TCP_FIN)
    state = {c["id"]: c["connected"] for c in hub.race_frame()["cars"]}
    check("closed connection marks that car as gone", state["a" * 33] is False and hub.connected["a" * 33] is False)
    check("other drivers stay connected", state["b" * 33] is True)
    check("the change is published", hub._race_dirty)


def main():
    tmp = Path(tempfile.mkdtemp())
    log_tail(tmp)
    departures(tmp)
    print(f"{len(fails)} failed")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
