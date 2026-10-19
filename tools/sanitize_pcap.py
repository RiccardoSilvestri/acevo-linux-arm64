#!/usr/bin/env python3
import argparse
import hashlib
import re
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lapwatch"))
import lapwatch as L

STEAMID_RE = re.compile(rb"7656\d{13}")
EPOCH = 1767225600


def checksum(data):
    if len(data) % 2:
        data += b"\0"
    s = sum(struct.unpack(f"!{len(data) // 2}H", data))
    s = (s >> 16) + (s & 0xFFFF)
    s += s >> 16
    return ~s & 0xFFFF


def ip_header(src, dst, proto, payload_len, ident):
    h = struct.pack("!BBHHHBBH4s4s", 0x45, 0, 20 + payload_len, ident & 0xFFFF, 0, 64, proto, 0, src, dst)
    return h[:10] + struct.pack("!H", checksum(h)) + h[12:]


def main():
    ap = argparse.ArgumentParser(description="Build an anonymised replay fixture from a live capture")
    ap.add_argument("src", help="input pcap (tcpdump -w)")
    ap.add_argument("dst", help="output pcap")
    ap.add_argument("--port", type=int, default=9600, help="game port")
    ap.add_argument("--steamid", default="76561198000000001", help="replacement SteamID (17 digits)")
    ap.add_argument("--replace", action="append", default=[],
                    help="extra OLD=NEW byte replacement inside payloads (same length)")
    ap.add_argument("--epoch", type=int, default=EPOCH, help="timestamp of the first packet in the output")
    args = ap.parse_args()
    assert len(args.steamid) == 17 and args.steamid.isdigit()
    extra = []
    for r in args.replace:
        old, new = r.split("=", 1)
        assert len(old) == len(new), f"replacement must keep the length: {r}"
        extra.append((old.encode(), new.encode()))

    packets = []
    server = None
    tcp_clients = set()
    for ts, link, data in L.read_pcap(args.src):
        ip = L.frame_to_ip(link, data)
        if ip is None:
            continue
        r = L.parse_ip(ip)
        if r is None:
            continue
        src, sp, dst, dp, proto, seq, payload = r
        if sp != args.port and dp != args.port:
            continue
        if proto == 6:
            if not payload:
                continue
            if sp == args.port:
                server = server or src
                tcp_clients.add(dst)
            else:
                server = server or dst
                tcp_clients.add(src)
        elif not (proto == 17 and dp == args.port and len(payload) == L.UDP_TELEMETRY_SIZE and payload[0] == 1):
            continue
        packets.append((ts, src, sp, dst, dp, proto, seq, payload))
    if server is None:
        sys.exit("no TCP game traffic found")

    addr = {server: bytes([10, 0, 0, 1])}
    for c in sorted(tcp_clients, key=lambda x: hashlib.sha256(x.encode()).hexdigest()):
        addr[c] = bytes([10, 0, 1, len(addr)])
    fake_id = args.steamid.encode()
    t0 = packets[0][0]
    out = bytearray(struct.pack("<IHHiIII", 0xa1b2c3d4, 2, 4, 0, 0, 65535, 1))
    kept = 0
    for n, (ts, src, sp, dst, dp, proto, seq, payload) in enumerate(packets):
        if src not in addr or dst not in addr:
            continue
        payload = STEAMID_RE.sub(fake_id, payload)
        for old, new in extra:
            payload = payload.replace(old, new)
        if proto == 6:
            seg = struct.pack("!HHIIBBHHH", sp, dp, seq, 0, 0x50, 0x18, 65535, 0, 0) + payload
        else:
            seg = struct.pack("!HHHH", sp, dp, 8 + len(payload), 0) + payload
        frame = (b"\x02\x00\x00\x00\x00\x02" + b"\x02\x00\x00\x00\x00\x01" + b"\x08\x00"
                 + ip_header(addr[src], addr[dst], proto, len(seg), n) + seg)
        t = args.epoch + (ts - t0)
        sec = int(t)
        usec = int(round((t - sec) * 1e6))
        if usec >= 1000000:
            sec, usec = sec + 1, usec - 1000000
        out += struct.pack("<IIII", sec, usec, len(frame), len(frame)) + frame
        kept += 1
    Path(args.dst).write_bytes(bytes(out))
    print(f"{kept} packets written to {args.dst} ({len(tcp_clients)} client(s), "
          f"{len(out) // 1024} KiB)")


if __name__ == "__main__":
    main()
