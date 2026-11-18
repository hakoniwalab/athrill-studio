"""Renders a recorded Studio flight to an mp4, picture by picture.

    python3 tools/render-video.py <script.json> <out.mp4> [--studio http://127.0.0.1:8765] [--chrome <path>]

Studio (python3 -m studio.server) must be running and have recorded a flight on the script's board (a run of a
firmware with flight_trace). Headless Chrome opens web/replay.html, loads GET /api/record/<board>, and for each
frame draws the virtual time the script maps it to; the pictures go to ffmpeg. The result does not depend on the
speed of the machine or of the run: every frame is the recorded flight at its exact virtual time.

The script (JSON):
  {"board": "pixhawk4", "fps": 30,
   "segments": [{"from": 33.0, "to": 39.9, "speed": 1.0}, ...],     virtual seconds, played at speed
   "captions": [{"from": 33.0, "to": 39.9, "text": "..."}, ...],      on virtual time
   "camera": {"azimuth": 0.6, "elevation": 0.16, "distance": 3.0, "orbit": 0.02},   orbit: rad per virtual s
   "card": {"seconds": 3.0, "fade": 0.6, "title": "...", "lines": ["...", "..."]}}
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import aiohttp

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PORT = 9333
WIDTH, HEIGHT = 1920, 1080
WARMUP = 2.0          # virtual s drawn before the first frame, to settle the camera


class Cdp:
    """A minimal Chrome DevTools Protocol client over one page's WebSocket."""

    def __init__(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        self.ws = ws
        self.next_id = 0

    async def call(self, method: str, **params) -> dict:
        self.next_id += 1
        my_id = self.next_id
        await self.ws.send_json({"id": my_id, "method": method, "params": params})
        while True:
            msg = await self.ws.receive_json()
            if msg.get("id") == my_id:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})

    async def eval(self, expression: str):
        result = await self.call("Runtime.evaluate", expression=expression, awaitPromise=True, returnByValue=True)
        if "exceptionDetails" in result:
            raise RuntimeError(f"{expression[:80]}: {result['exceptionDetails']}")
        return result.get("result", {}).get("value")


def frame_times(script: dict) -> list[tuple[float, float]]:
    """(virtual time, virtual dt) of every frame of the segments."""
    fps = script.get("fps", 30)
    frames = []
    for seg in script["segments"]:
        step = seg.get("speed", 1.0) / fps
        t = seg["from"]
        while t < seg["to"] - 1e-9:
            frames.append((t, step))
            t += step
    return frames


def caption_at(script: dict, t: float) -> str:
    for c in script.get("captions", []):
        if c["from"] <= t < c["to"]:
            return c["text"]
    return ""


async def render(script: dict, out: Path, studio: str, chrome: str) -> None:
    profile = tempfile.mkdtemp(prefix="studio-render-")
    browser = subprocess.Popen(
        [chrome, "--headless=new", f"--remote-debugging-port={PORT}", f"--user-data-dir={profile}",
         f"--window-size={WIDTH},{HEIGHT}", "--hide-scrollbars", "--force-device-scale-factor=1",
         "--enable-unsafe-swiftshader", "--no-first-run", "--no-default-browser-check", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    fps = script.get("fps", 30)
    encoder = None
    try:
        async with aiohttp.ClientSession() as http:
            for _ in range(100):
                try:
                    async with http.get(f"http://127.0.0.1:{PORT}/json/list") as r:
                        pages = [p for p in await r.json() if p.get("type") == "page"]
                        if pages:
                            break
                except aiohttp.ClientError:
                    pass
                await asyncio.sleep(0.1)
            else:
                raise RuntimeError("headless Chrome did not start")
            async with http.ws_connect(pages[0]["webSocketDebuggerUrl"], max_msg_size=0) as ws:
                cdp = Cdp(ws)
                await cdp.call("Emulation.setDeviceMetricsOverride", width=WIDTH, height=HEIGHT,
                               deviceScaleFactor=1, mobile=False)
                await cdp.call("Page.enable")
                await cdp.call("Page.navigate", url=f"{studio}/web/replay.html")
                for _ in range(300):
                    if await cdp.eval("Boolean(window.replay && window.studioModelsLoaded)"):
                        break
                    await asyncio.sleep(0.1)
                else:
                    raise RuntimeError("replay page not ready (models not loaded?)")
                models = await cdp.eval("window.studioModelsLoaded")
                info = await cdp.eval(
                    f"fetch('/api/record/{script['board']}').then(r => r.json()).then(rec => replay.load(rec))")
                print(f"record: {info}, models: {models}", file=sys.stderr)
                cam = script.get("camera", {})
                base_az = cam.get("azimuth", 0.6)
                await cdp.eval(f"Object.assign(replay.view, {json.dumps({k: cam[k] for k in ('azimuth', 'elevation', 'distance') if k in cam})})")
                frames = frame_times(script)
                t0 = frames[0][0]
                # settle the chase camera on the vehicle before the first frame
                t = t0 - WARMUP
                while t < t0:
                    await cdp.eval(f"replay.renderAt({t}, {1 / fps})")
                    t += 1 / fps
                encoder = subprocess.Popen(
                    ["ffmpeg", "-v", "error", "-y", "-f", "image2pipe", "-framerate", str(fps), "-i", "-",
                     "-c:v", "libx264", "-preset", "slow", "-crf", str(script.get("crf", 20)), "-pix_fmt", "yuv420p",
                     "-movflags", "+faststart", str(out)], stdin=subprocess.PIPE)

                async def shoot() -> None:
                    shot = await cdp.call("Page.captureScreenshot", format="jpeg", quality=92)
                    encoder.stdin.write(base64.b64decode(shot["data"]))

                last_caption = None
                for i, (t, dt) in enumerate(frames):
                    if "orbit" in cam:
                        await cdp.eval(f"replay.view.azimuth = {base_az + cam['orbit'] * (t - t0)}")
                    caption = caption_at(script, t)
                    if caption != last_caption:
                        await cdp.eval(f"overlay.caption({json.dumps(caption)})")
                        last_caption = caption
                    await cdp.eval(f"replay.renderAt({t}, {dt})")
                    await shoot()
                    if i % fps == 0:
                        print(f"frame {i}/{len(frames)} virtual {t:.2f} s", file=sys.stderr)
                card = script.get("card")
                if card:
                    await cdp.eval("overlay.caption('')")
                    n = int(card.get("seconds", 3.0) * fps)
                    fade = max(1, int(card.get("fade", 0.6) * fps))
                    lines = card.get("lines", []) + ["", ""]
                    for i in range(n):
                        opacity = min(1.0, (i + 1) / fade)
                        await cdp.eval(f"overlay.card({opacity}, {json.dumps(card.get('title', ''))}, "
                                       f"{json.dumps(lines[0])}, {json.dumps(lines[1])})")
                        await shoot()
    finally:
        if encoder is not None:
            encoder.stdin.close()
            encoder.wait()
        browser.terminate()
        browser.wait()
        shutil.rmtree(profile, ignore_errors=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Render a recorded Studio flight to an mp4")
    parser.add_argument("script")
    parser.add_argument("out")
    parser.add_argument("--studio", default="http://127.0.0.1:8765")
    parser.add_argument("--chrome", default=CHROME)
    args = parser.parse_args()
    script = json.loads(Path(args.script).read_text(encoding="utf-8"))
    asyncio.run(render(script, Path(args.out), args.studio, args.chrome))
    print(f"wrote {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
