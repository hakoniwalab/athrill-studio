"""End-to-end flight through Studio, as the Flight tab does it:

    python3 tests/flight_smoke.py

Starts the server, runs PX4 with the in-process x500 on the Pixhawk 4
(tools/fetch.sh and tools/setup-drone.sh first), waits until PX4 reports its
home position over MAVLink, takes off to 2.5 m with POST /api/flight/takeoff,
and requires the altitude to stay within 2.5 +- 0.3 m for 10 s of PX4's time
after 20 s; then lands and requires the altitude below 0.3 m and the vehicle
disarmed. Prints the RTF from Athrill's progress report when the athrill3 has it.
"""

from __future__ import annotations

import asyncio
import socket
import subprocess
import sys
import time
from pathlib import Path

import aiohttp

ROOT = Path(__file__).resolve().parent.parent
TARGET, BAND = 2.5, 0.3


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def fly(port: int) -> list[str]:
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
            async with http.post(f"{base}/api/run", json={"board": "pixhawk4", "firmware": "px4-x500"}) as r:
                if r.status != 200:
                    return [f"run: HTTP {r.status} {await r.text()}"]
            phase, t_takeoff, hold, rtf = "boot", None, [], None
            deadline = time.time() + 600
            async for msg in ws:
                if time.time() > deadline:
                    failures.append(f"timed out in phase {phase}")
                    break
                m = msg.json()
                if m["type"] == "progress" and m["wall_usec"] > 0:
                    rtf = m["virtual_usec"] / m["wall_usec"]
                if m["type"] == "flight_status":
                    print("  ", m["text"])
                if m["type"] == "state" and m["state"] == "exited":
                    failures.append(f"athrill3 exited in phase {phase}: {m}")
                    break
                if m["type"] != "flight":
                    continue
                if phase == "boot" and m.get("ready"):
                    phase = "takeoff"
                    await http.post(f"{base}/api/flight/takeoff", json={"altitude": TARGET})
                elif phase == "takeoff" and m.get("armed") and "alt" in m:
                    t = m["time_boot_ms"] / 1000
                    t_takeoff = t_takeoff or t
                    if t - t_takeoff >= 20:
                        hold.append(m["alt"])
                    if t - t_takeoff >= 30:
                        lo, hi = min(hold), max(hold)
                        print(f"hold: {lo:.2f} to {hi:.2f} m over 10 s of PX4 time")
                        if abs(lo - TARGET) > BAND or abs(hi - TARGET) > BAND:
                            failures.append(f"not holding {TARGET} m: {lo:.2f} to {hi:.2f}")
                        phase = "land"
                        await http.post(f"{base}/api/flight/land")
                elif phase == "land" and not m.get("armed") and m.get("alt", 9) < 0.3:
                    print(f"landed and disarmed (altitude {m['alt']:.2f} m)")
                    phase = "done"
                    break
            await http.post(f"{base}/api/stop")
    if rtf is not None:
        print(f"RTF over the run {rtf:.2f}")
    return failures


def main() -> int:
    port = free_port()
    server = subprocess.Popen([sys.executable, "-m", "studio.server", "--port", str(port)], cwd=ROOT)
    try:
        failures = asyncio.run(fly(port))
    finally:
        server.terminate()
        server.wait(15)
    for f in failures:
        print(f"FAIL: {f}")
    print("PASS" if not failures else "SOME CHECKS FAILED")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
