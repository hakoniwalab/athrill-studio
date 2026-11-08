"""End-to-end check of Studio, as a browser uses it:

    python3 tests/smoke.py [board] [firmware] [expected console text]

Starts the server on a free port, reads the board's Devicetree over REST,
starts the firmware with POST /api/run and listens on /ws. Passes when the
console stream contains the expected text, Athrill reported at least one model
of the board's Devicetree, and the run exited. Needs tools/fetch.sh first.
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


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def check(port: int, board: str, firmware: str, expected: str) -> list[str]:
    base = f"http://127.0.0.1:{port}"
    failures: list[str] = []
    async with aiohttp.ClientSession() as http:
        for _ in range(100):
            try:
                async with http.get(f"{base}/api/boards") as r:
                    if r.status == 200:
                        break
            except aiohttp.ClientConnectionError:
                await asyncio.sleep(0.1)
        async with http.get(f"{base}/api/boards/{board}/devicetree") as r:
            dt = await r.json()
        nodes = {n["path"] for n in dt["nodes"]}
        print(f"devicetree: {dt['model']}: {len(dt['nodes'])} nodes, {len(dt['edges'])} references")
        if len(dt["nodes"]) < 10:
            failures.append("devicetree: fewer than 10 nodes")
        console = ""
        modelled: set[str] = set()
        exited = None
        async with http.ws_connect(f"{base}/ws") as ws:
            async with http.post(f"{base}/api/run", json={"board": board, "firmware": firmware}) as r:
                if r.status != 200:
                    failures.append(f"run: HTTP {r.status} {await r.text()}")
                    return failures
            deadline = time.time() + 300
            async for msg in ws:
                m = msg.json()
                if m["type"] == "console":
                    console += m["data"]
                elif m["type"] == "model":
                    modelled.add(m["path"])
                elif m["type"] == "state" and m["state"] == "exited":
                    exited = m
                    break
                if time.time() > deadline:
                    failures.append("no exit within 300 s")
                    break
        print(f"console: {len(console)} characters; models: {len(modelled)}; exit: {exited}")
        if expected not in console:
            failures.append(f"console: no {expected!r}")
        if not modelled:
            failures.append("no model reported")
        if not modelled <= nodes:
            failures.append(f"models outside the shown Devicetree: {sorted(modelled - nodes)[:3]}")
        if exited is None:
            failures.append("the run did not report its exit")
    return failures


def main() -> int:
    board = sys.argv[1] if len(sys.argv) > 1 else "nucleo-f767zi"
    firmware = sys.argv[2] if len(sys.argv) > 2 else "zephyr-hello-world"
    expected = sys.argv[3] if len(sys.argv) > 3 else "Hello World! nucleo_f767zi/stm32f767xx"
    port = free_port()
    server = subprocess.Popen([sys.executable, "-m", "studio.server", "--port", str(port)], cwd=ROOT)
    try:
        failures = asyncio.run(check(port, board, firmware, expected))
    finally:
        server.terminate()
        server.wait(10)
    for f in failures:
        print(f"FAIL: {f}")
    print("PASS" if not failures else "SOME CHECKS FAILED")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
