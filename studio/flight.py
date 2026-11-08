"""The ground-station side of a flying firmware: MAVLink to PX4, as QGroundControl does.

A thread talks MAVLink (pymavlink is blocking) and hands telemetry to the
asyncio side with a callback. Commands (take off, land) run in the same thread,
in order. Nothing here changes the firmware or Athrill: MAVLink is the
firmware's own telemetry link (TELEM1 on TCP).
"""

from __future__ import annotations

import math
import queue
import threading
import time
from typing import Callable

from pymavlink import mavutil

TELEMETRY_HZ = 10


class Flight:
    def __init__(self, url: str, publish: Callable[[dict], None]) -> None:
        self.url = url
        self.publish = publish
        self.commands: queue.Queue[tuple[str, dict]] = queue.Queue()
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self.run, name="mavlink", daemon=True)
        self.state: dict = {"type": "flight", "connected": False, "armed": False}
        self.home_alt: float | None = None

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()

    def command(self, name: str, **args) -> None:
        self.commands.put((name, args))

    # --- the MAVLink thread
    def run(self) -> None:
        link = None
        while not self.stop_event.is_set() and link is None:
            try:
                link = mavutil.mavlink_connection(self.url, source_system=255, autoreconnect=False)
                if link.wait_heartbeat(timeout=2) is None:
                    link.close()
                    link = None
            except OSError:
                link = None
                time.sleep(1)
        if link is None:
            return
        self.link = link
        self.status("connected to PX4 over MAVLink")
        self.state["connected"] = True
        link.mav.request_data_stream_send(link.target_system, link.target_component,
                                          mavutil.mavlink.MAV_DATA_STREAM_ALL, 10, 1)
        last_heartbeat = last_publish = 0.0
        while not self.stop_event.is_set():
            now = time.time()
            if now - last_heartbeat > 1:
                link.mav.heartbeat_send(mavutil.mavlink.MAV_TYPE_GCS, mavutil.mavlink.MAV_AUTOPILOT_INVALID, 0, 0, 0)
                if self.home_alt is None:
                    link.mav.command_long_send(link.target_system, link.target_component,
                                               mavutil.mavlink.MAV_CMD_REQUEST_MESSAGE, 0, 242, 0, 0, 0, 0, 0, 0)
                last_heartbeat = now
            try:
                name, args = self.commands.get_nowait()
                getattr(self, f"do_{name}")(**args)
            except queue.Empty:
                pass
            msg = link.recv_match(blocking=True, timeout=0.05)
            if msg is not None:
                self.handle(msg)
            if now - last_publish > 1 / TELEMETRY_HZ:
                self.publish(dict(self.state))
                last_publish = now
        link.close()

    def handle(self, msg) -> None:
        kind = msg.get_type()
        if kind == "HEARTBEAT" and msg.get_srcComponent() == 1:
            self.state["armed"] = bool(msg.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED)
            self.state["mode"] = mavutil.mode_string_v10(msg)
        elif kind == "GLOBAL_POSITION_INT":
            self.state["alt"] = msg.relative_alt / 1000.0
            self.state["time_boot_ms"] = msg.time_boot_ms
        elif kind == "LOCAL_POSITION_NED":
            self.state.update(x=msg.x, y=msg.y, z=msg.z)
        elif kind == "ATTITUDE":
            self.state.update(roll=math.degrees(msg.roll), pitch=math.degrees(msg.pitch),
                              yaw=math.degrees(msg.yaw))
        elif kind == "HOME_POSITION":
            self.home_alt = msg.altitude / 1000.0
            self.state["ready"] = True
        elif kind == "STATUSTEXT":
            self.status("PX4: " + msg.text)

    def status(self, text: str) -> None:
        self.publish({"type": "flight_status", "text": text})

    def wait_ack(self, command: int, timeout: float) -> int | None:
        end = time.time() + timeout
        while time.time() < end:
            msg = self.link.recv_match(blocking=True, timeout=0.2)
            if msg is None:
                continue
            if msg.get_type() == "COMMAND_ACK" and msg.command == command:
                return msg.result
            self.handle(msg)
        return None

    def do_takeoff(self, altitude: float = 2.5) -> None:
        link = self.link
        if self.home_alt is None:
            self.status("take-off: waiting for PX4's home position (EKF not ready yet)")
            end = time.time() + 120
            while self.home_alt is None and time.time() < end:
                link.mav.command_long_send(link.target_system, link.target_component,
                                           mavutil.mavlink.MAV_CMD_REQUEST_MESSAGE, 0, 242, 0, 0, 0, 0, 0, 0)
                msg = link.recv_match(blocking=True, timeout=1)
                if msg is not None:
                    self.handle(msg)
            if self.home_alt is None:
                self.status("take-off: no home position")
                return
        for _ in range(20):
            link.mav.command_long_send(link.target_system, link.target_component,
                                       mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM, 0, 1, 0, 0, 0, 0, 0, 0)
            if self.wait_ack(mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM, 5) == 0:
                break
            time.sleep(1)
        else:
            self.status("take-off: arming denied")
            return
        self.status("armed")
        # MAV_CMD_NAV_TAKEOFF takes the altitude above mean sea level: home plus the climb
        link.mav.command_long_send(link.target_system, link.target_component, mavutil.mavlink.MAV_CMD_NAV_TAKEOFF,
                                   0, 0, 0, 0, float("nan"), float("nan"), float("nan"), self.home_alt + altitude)
        result = self.wait_ack(mavutil.mavlink.MAV_CMD_NAV_TAKEOFF, 5)
        self.status(f"take-off to {altitude} m: {'accepted' if result == 0 else f'result {result}'}")

    def do_land(self) -> None:
        link = self.link
        link.mav.command_long_send(link.target_system, link.target_component, mavutil.mavlink.MAV_CMD_NAV_LAND,
                                   0, 0, 0, 0, float("nan"), float("nan"), float("nan"), 0)
        result = self.wait_ack(mavutil.mavlink.MAV_CMD_NAV_LAND, 5)
        self.status(f"land: {'accepted' if result == 0 else f'result {result}'}")
