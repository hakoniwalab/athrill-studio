"""The motor-failure demo through Studio, as the Flight tab shows it:

    python3 tests/motor_stop_smoke.py [--real-time]

Starts the server and runs "PX4 v1.17.0 x500, motor 3 stops at 40 s" on the
Pixhawk 4 (tools/fetch.sh and tools/setup-drone-motor.sh first). Studio takes
off by itself; the emulated ESC stops motor 3 at 40 s of virtual time. Requires
the x500 to climb above 2 m, PX4 to report "Motor failure detected", and the
x500 to come down below 0.35 m after that, all from what Studio streams. Then
reads the recorded flight trace (GET /api/record/pixhawk4) and prints when
motor 3 stopped, when PX4 reported it and when the x500 reached the ground.
"""

from __future__ import annotations

import argparse
import asyncio
import socket
import subprocess
import sys
import time
from pathlib import Path

import aiohttp

ROOT = Path(__file__).resolve().parent.parent
STOP_SECONDS = 40.0


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def fly(port: int, real_time: bool) -> list[str]:
    base = f"http://127.0.0.1:{port}"
    failures: list[str] = []
    async with aiohttp.ClientSession() as http:
        for _ in range(100):
            try:
                async with http.get(f"{base}/api/boards"):
                    break
            except aiohttp.ClientConnectionError:
                await asyncio.sleep(0.1)
        async with http.ws_connect(f"{base}/ws") as ws:
            body = {"board": "pixhawk4", "firmware": "px4-x500-motor-stop", "real_time": real_time}
            async with http.post(f"{base}/api/run", json=body) as r:
                if r.status != 200:
                    return [f"run: HTTP {r.status} {await r.text()}"]
            max_alt, detected, landed = 0.0, False, False
            deadline = time.time() + 600
            async for msg in ws:
                if time.time() > deadline:
                    failures.append("timed out")
                    break
                m = msg.json()
                if m["type"] == "flight_status":
                    print("  ", m["text"])
                    if "Motor failure detected" in m["text"]:
                        detected = True
                if m["type"] == "state" and m["state"] == "exited":
                    failures.append(f"athrill3 exited: {m}")
                    break
                if m["type"] == "flight" and "alt" in m:
                    max_alt = max(max_alt, m["alt"])
                    if detected and max_alt > 2.0 and m["alt"] < 0.35:
                        print(f"on the ground (altitude {m['alt']:.2f} m)")
                        landed = True
                        break
            await http.post(f"{base}/api/stop")
            if max_alt <= 2.0:
                failures.append(f"did not climb above 2 m (max {max_alt:.2f} m)")
            if not detected:
                failures.append("PX4 did not report Motor failure detected")
            if not landed:
                failures.append("the x500 did not come down")
            async with http.get(f"{base}/api/record/pixhawk4") as r:
                if r.status == 200:
                    report(await r.json())
    return failures


def report(record: dict) -> None:
    """When motor 3 stopped, PX4 reported it, and the x500 reached the ground, in virtual seconds."""
    # each sample: [t_usec, x, y, z, roll, pitch, yaw, rpm[], duty[]]
    trace = record.get("trace", [])
    stop = next((s[0] / 1e6 for s in trace if s[0] / 1e6 >= STOP_SECONDS - 0.1 and len(s[7]) > 2 and s[7][2] < 100), None)
    ground = next((s[0] / 1e6 for s in trace if s[0] / 1e6 > STOP_SECONDS and s[3] < 0.35), None)
    reported = next((e["t"] for e in record.get("timeline", []) if "Motor failure detected" in (e.get("text") or e.get("data") or "")), None)
    print(f"virtual time: motor 3 stopped {stop}, PX4 reported {reported}, on the ground {ground}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--real-time", action="store_true", help="keep virtual time to the wall clock, as the Flight tab's switch")
    args = parser.parse_args()
    port = free_port()
    server = subprocess.Popen([sys.executable, "-m", "studio.server", "--port", str(port)], cwd=ROOT)
    try:
        failures = asyncio.run(fly(port, args.real_time))
    finally:
        server.terminate()
        server.wait(15)
    for f in failures:
        print(f"FAIL: {f}")
    print("PASS" if not failures else "SOME CHECKS FAILED")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
