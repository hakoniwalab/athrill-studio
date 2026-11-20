"""Fly a route and stop a motor during it, through Studio's API, as the Flight tab does:

    python3 tests/route_fault_smoke.py [--real-time] [--stop-at 2] [--motor 3] [--manual]

Runs "PX4 v1.17.0 x500, fly a route and stop a motor from the browser" on the Pixhawk 4
(tools/fetch.sh and tools/setup-drone-motor.sh first, with an in-process sensor device that reads
HAKO_SENSOR_DEVICE_ROTOR_FAULT_FILE). Takes off to 2.5 m and flies a square of 6 m sides
(POST /api/flight/route) with a planned fault: Studio stops motor --motor when point --stop-at is reached.
With --manual the route has no plan, and the test stops the motor itself (POST /api/fault) when the
vehicle heads for that point, as the Stop buttons do. Requires the vehicle to move along the route (more than 4 m from home), PX4 to report
"Motor failure detected" after the stop, and the vehicle to come down below 0.35 m.
"""

from __future__ import annotations

import argparse
import asyncio
import math
import socket
import subprocess
import sys
import time
from pathlib import Path

import aiohttp

ROOT = Path(__file__).resolve().parent.parent
ROUTE = [[6.0, 0.0], [6.0, 6.0], [0.0, 6.0], [0.0, 0.0]]


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def fly(port: int, real_time: bool, stop_at: int, motor: int, manual: bool) -> list[str]:
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
            body = {"board": "pixhawk4", "firmware": "px4-x500-route", "real_time": real_time}
            async with http.post(f"{base}/api/run", json=body) as r:
                if r.status != 200:
                    return [f"run: HTTP {r.status} {await r.text()}"]
            phase, far, stopped_at, detected = "boot", 0.0, None, False
            deadline = time.time() + 600
            async for msg in ws:
                if time.time() > deadline:
                    failures.append(f"timed out in phase {phase}")
                    break
                m = msg.json()
                if m["type"] == "flight_status":
                    print("  ", m["text"])
                    if "Motor failure detected" in m["text"] and stopped_at is not None:
                        detected = True
                if m["type"] == "state" and m["state"] == "exited":
                    failures.append(f"athrill3 exited in phase {phase}: {m}")
                    break
                if m["type"] != "flight":
                    continue
                if "x" in m:
                    far = max(far, math.hypot(m["x"], m["y"]))
                if phase == "boot" and m.get("ready"):
                    phase = "takeoff"
                    await http.post(f"{base}/api/flight/takeoff", json={"altitude": 2.5})
                elif phase == "takeoff" and m.get("armed") and m.get("alt", 0) > 2.2:
                    phase = "route"
                    body = {"points": ROUTE, "altitude": 2.5}
                    if not manual:
                        body["fault"] = {"motor": motor, "at": stop_at}
                    await http.post(f"{base}/api/flight/route", json=body)
                elif phase == "route" and m.get("route", {}).get("index", 0) >= stop_at:
                    phase = "fault"
                    stopped_at = (round(m["x"], 2), round(m["y"], 2), round(m.get("alt", 0), 2))
                    print(f"point {stop_at} reached at north {stopped_at[0]} m, east {stopped_at[1]} m, altitude {stopped_at[2]} m")
                    if manual:
                        async with http.post(f"{base}/api/fault", json={"motor": motor, "stop": True}) as r:
                            print("fault:", await r.json())
                elif phase == "fault" and detected and m.get("alt", 9) < 0.35:
                    print(f"on the ground (altitude {m['alt']:.2f} m), farthest {far:.1f} m from home")
                    phase = "done"
                    break
            await http.post(f"{base}/api/stop")
    if far <= 4.0:
        failures.append(f"did not fly the route (farthest {far:.1f} m)")
    if not detected:
        failures.append("PX4 did not report Motor failure detected after the stop")
    if phase != "done":
        failures.append(f"ended in phase {phase}")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--real-time", action="store_true")
    parser.add_argument("--stop-at", type=int, default=2, help="stop the motor when heading for this route point (0-based)")
    parser.add_argument("--motor", type=int, default=3, help="the motor to stop (1-based, PX4's order)")
    parser.add_argument("--manual", action="store_true", help="stop the motor through POST /api/fault, not a planned fault")
    args = parser.parse_args()
    port = free_port()
    server = subprocess.Popen([sys.executable, "-m", "studio.server", "--port", str(port)], cwd=ROOT)
    try:
        failures = asyncio.run(fly(port, args.real_time, args.stop_at, args.motor, args.manual))
    finally:
        server.terminate()
        server.wait(15)
    for f in failures:
        print(f"FAIL: {f}")
    print("PASS" if not failures else "SOME CHECKS FAILED")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
