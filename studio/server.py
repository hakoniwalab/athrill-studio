"""Athrill Studio backend: boards, their Devicetree, and a firmware run.

    python3 -m studio.server [--port 8765]

REST
  GET  /api/boards                      the boards of boards.yaml
  GET  /api/boards/{id}/devicetree      nodes and references of the board's DTB
  POST /api/run   {"board", "firmware", "real_time"}  start the firmware on athrill3 (one run at a time);
                  real_time keeps virtual time from running ahead of the wall clock
  POST /api/stop                        stop the run
WebSocket /ws, JSON messages:
  {"type": "console", "data": "..."}    the firmware's console output, as written
  {"type": "athrill", "line": "..."}    Athrill's own lines (start-up, end state)
  {"type": "model", "path", "compatible", "model"}  a model Athrill built from the DTB
  {"type": "progress", "clock", "virtual_usec", "wall_usec"}  Athrill's virtual time, every 200 ms of it
  {"type": "state", "state": "running" | "exited", ...}

Athrill is run unchanged; Studio only reads what it prints. The stream goes
through one place, Hub.publish(), so a binary transport (Hakoniwa PDU) can
replace the JSON one later without touching the run.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import time
from pathlib import Path

import yaml
from aiohttp import WSMsgType, web

from . import dtb

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"

# Lines Athrill prints itself (start-up, models, end state); the rest is the console.
ATHRILL_LINE = re.compile(
    r"^(DEVICE_|TARGET_TICK |INFO: |core id num=|address bus:|ROM :|RAM :|DEV :|ELF |Elf loading|"
    r"Not found: |DEBUG_FUNC_|EXIT for |SAMPLES |FINAL |ERROR|WARNING|search_region|mpu_)"
)
DEVICE_MODEL = re.compile(r"^DEVICE_MODEL path=(\S+) compatible=(\S+) provider=(\S+) model=(\S+)")
PROGRESS = re.compile(r"^PROGRESS clock=(\d+) virtual_usec=(\d+) wall_usec=(\d+)")
PROGRESS_MSEC = 200   # how often Athrill reports its virtual time (DEBUG_FUNC_PROGRESS_MSEC)
FLUSH_SECONDS = 0.05


def athrill_path(board: dict) -> str:
    """The board's athrill3, or STUDIO_ATHRILL3 for every board (a local build)."""
    return os.environ.get("STUDIO_ATHRILL3") or str(ROOT / board["athrill"])


def load_boards() -> list[dict]:
    with open(ROOT / "boards.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)["boards"]


class Hub:
    """The browsers connected to /ws."""

    def __init__(self) -> None:
        self.sockets: set[web.WebSocketResponse] = set()

    async def publish(self, message: dict) -> None:
        text = json.dumps(message)
        for ws in list(self.sockets):
            try:
                await ws.send_str(text)
            except ConnectionError:
                self.sockets.discard(ws)


class Run:
    """One athrill3 process and the reading of its output."""

    def __init__(self, hub: Hub) -> None:
        self.hub = hub
        self.process: asyncio.subprocess.Process | None = None
        self.tasks: list[asyncio.Task] = []
        self.info: dict = {"state": "idle"}
        self.models: dict[str, dict] = {}   # the models of the last run, for browsers that join later

    async def start(self, board: dict, firmware: dict, real_time: bool = False) -> None:
        await self.stop()
        self.models = {}
        work = ROOT / "work" / "run" / board["id"]
        work.mkdir(parents=True, exist_ok=True)
        (work / "memory.txt").write_text("\n".join(board["memory"]) + "\n")
        # The progress report needs an athrill3 with DEBUG_FUNC_PROGRESS_MSEC
        # (toppers/athrill#90); an older one ignores the key, and Studio then
        # shows the wall time only.
        config = [f"DEVICE_CPU_FREQ {board['cpu_mhz']}", *board["device_config"],
                  f"DEVICE_CONFIG_DEVICE_TREE {ROOT / board['devicetree']}",
                  f"DEBUG_FUNC_PROGRESS_MSEC {PROGRESS_MSEC}"]
        if real_time:
            config.append("DEBUG_FUNC_REAL_TIME 1")
        (work / "device_config.txt").write_text("\n".join(config) + "\n")
        clocks = board["cpu_mhz"] * 1_000_000 * int(firmware.get("seconds", 10))
        command = [athrill_path(board), "-c1", "-m", "memory.txt", "-d", "device_config.txt",
                   "-t", str(clocks), str(ROOT / firmware["elf"])]
        env = dict(os.environ)
        self.process = await asyncio.create_subprocess_exec(
            *command, cwd=work, env=env,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        self.info = {"state": "running", "board": board["id"], "firmware": firmware["id"],
                     "virtual_seconds": firmware.get("seconds"), "real_time": real_time,
                     "started": time.time()}
        await self.hub.publish({"type": "state", **self.info})
        self.tasks = [asyncio.create_task(self.read_stdout()),
                      asyncio.create_task(self.read_stderr()),
                      asyncio.create_task(self.wait())]

    async def stop(self) -> None:
        if self.process is not None and self.process.returncode is None:
            self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), 5)
            except asyncio.TimeoutError:
                self.process.kill()
        for task in self.tasks:
            if task is not asyncio.current_task():
                await asyncio.gather(task, return_exceptions=True)
        self.tasks = []

    async def model(self, m: re.Match) -> None:
        message = {"type": "model", "board": self.info.get("board"), "path": m.group(1),
                   "compatible": m.group(2), "provider": m.group(3), "model": m.group(4)}
        self.models[m.group(1)] = message
        await self.hub.publish(message)

    async def line(self, text: str) -> None:
        """One complete stdout line: Athrill's own, or the console's."""
        stripped = text.rstrip("\r\n")
        if ATHRILL_LINE.match(stripped):
            m = DEVICE_MODEL.match(stripped)
            if m:
                await self.model(m)
            else:
                await self.hub.publish({"type": "athrill", "line": stripped})
        else:
            await self.hub.publish({"type": "console", "data": text})

    async def read_stdout(self) -> None:
        """Lines go one by one; a partial line (a prompt, an escape sequence)
        goes to the console when nothing more arrives for FLUSH_SECONDS."""
        assert self.process and self.process.stdout
        buffer = ""
        while True:
            try:
                chunk = await asyncio.wait_for(self.process.stdout.read(4096), FLUSH_SECONDS)
            except asyncio.TimeoutError:
                if buffer:
                    await self.hub.publish({"type": "console", "data": buffer})
                    buffer = ""
                continue
            if not chunk:
                break
            buffer += chunk.decode("utf-8", "replace")
            while "\n" in buffer:
                head, buffer = buffer.split("\n", 1)
                await self.line(head + "\n")
        if buffer:
            await self.line(buffer)

    async def read_stderr(self) -> None:
        assert self.process and self.process.stderr
        async for raw in self.process.stderr:
            line = raw.decode("utf-8", "replace").rstrip()
            m = DEVICE_MODEL.match(line)
            p = PROGRESS.match(line)
            if m:
                await self.model(m)
            elif p:
                virtual_usec, wall_usec = int(p.group(2)), int(p.group(3))
                await self.hub.publish({"type": "progress", "clock": int(p.group(1)),
                                        "virtual_usec": virtual_usec, "wall_usec": wall_usec})
            else:
                await self.hub.publish({"type": "athrill", "line": line})

    async def wait(self) -> None:
        assert self.process
        code = await self.process.wait()
        await asyncio.sleep(FLUSH_SECONDS * 2)
        self.info = {**self.info, "state": "exited", "exit_code": code,
                     "wall_seconds": round(time.time() - self.info["started"], 2)}
        await self.hub.publish({"type": "state", **self.info})


def make_app() -> web.Application:
    app = web.Application()
    hub = Hub()
    run = Run(hub)
    boards = {b["id"]: b for b in load_boards()}

    async def index(_request: web.Request) -> web.FileResponse:
        return web.FileResponse(WEB / "index.html")

    async def list_boards(_request: web.Request) -> web.Response:
        return web.json_response([
            {"id": b["id"], "title": b["title"], "soc": b.get("soc", ""),
             "firmware": [{"id": f["id"], "title": f["title"], "seconds": f.get("seconds")}
                          for f in b.get("firmware", [])],
             "devicetree": b["devicetree"]}
            for b in boards.values()])

    async def devicetree(request: web.Request) -> web.Response:
        board = boards.get(request.match_info["id"])
        if board is None:
            raise web.HTTPNotFound(text="no such board")
        path = ROOT / board["devicetree"]
        if not path.exists():
            raise web.HTTPNotFound(text=f"{board['devicetree']} not found: run tools/fetch.sh")
        return web.json_response(dtb.describe(path.read_bytes()))

    async def start(request: web.Request) -> web.Response:
        body = await request.json()
        board = boards.get(body.get("board"))
        if board is None:
            raise web.HTTPBadRequest(text="no such board")
        firmware = next((f for f in board.get("firmware", []) if f["id"] == body.get("firmware")), None)
        if firmware is None:
            raise web.HTTPBadRequest(text="no such firmware on this board")
        for need in (athrill_path(board), firmware["elf"], board["devicetree"]):
            if not (ROOT / need).exists():
                raise web.HTTPBadRequest(text=f"{need} not found: run tools/fetch.sh")
        await run.start(board, firmware, bool(body.get("real_time")))
        return web.json_response(run.info)

    async def stop(_request: web.Request) -> web.Response:
        await run.stop()
        return web.json_response(run.info)

    async def status(_request: web.Request) -> web.Response:
        return web.json_response(run.info)

    async def websocket(request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=20)
        await ws.prepare(request)
        hub.sockets.add(ws)
        await ws.send_str(json.dumps({"type": "state", **run.info}))
        for message in run.models.values():
            await ws.send_str(json.dumps(message))
        async for msg in ws:
            if msg.type == WSMsgType.ERROR:
                break
        hub.sockets.discard(ws)
        return ws

    async def on_shutdown(_app: web.Application) -> None:
        await run.stop()
        for ws in list(hub.sockets):
            await ws.close()

    app.router.add_get("/", index)
    app.router.add_static("/web/", WEB)
    app.router.add_get("/api/boards", list_boards)
    app.router.add_get("/api/boards/{id}/devicetree", devicetree)
    app.router.add_post("/api/run", start)
    app.router.add_post("/api/stop", stop)
    app.router.add_get("/api/status", status)
    app.router.add_get("/ws", websocket)
    app.on_shutdown.append(on_shutdown)
    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Athrill Studio backend")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    print(f"Athrill Studio on http://{args.host}:{args.port}/")
    web.run_app(make_app(), host=args.host, port=args.port, print=None)


if __name__ == "__main__":
    main()
