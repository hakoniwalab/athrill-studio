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
# SYS_STATUS: PX4 sets this health bit (not the present one) when arming would be accepted in the current mode
PREARM_CHECK = mavutil.mavlink.MAV_SYS_STATUS_PREARM_CHECK
EARTH_RADIUS = 6378137.0   # m, for the route's north/east metres to latitude/longitude near home


class Flight:
    def __init__(self, url: str, publish: Callable[[dict], None],
                 on_fault: Callable[[int], None] | None = None) -> None:
        self.url = url
        self.publish = publish
        self.on_fault = on_fault   # a planned fault: called with the motor (1-based) when its point is reached
        self.commands: queue.Queue[tuple[str, dict]] = queue.Queue()
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self.run, name="mavlink", daemon=True)
        self.state: dict = {"type": "flight", "connected": False, "armed": False}
        self.home_alt: float | None = None
        self.home_lat: float | None = None   # deg, the origin of the route's north/east metres
        self.home_lon: float | None = None
        self.prearm_ok: bool | None = None   # None: no SYS_STATUS yet
        # a route being flown: [[north, east], ...] m from home, the index of the point flown to, its altitude
        self.route: list[list[float]] = []
        self.route_index = 0
        self.route_alt = 2.5
        self.route_speed = 2.0
        self.route_fault: dict | None = None   # {"motor": n, "at": k}: stop motor n when point k (1-based) is reached
        self.route_sent = 0.0

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
            self.follow_route(now)
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
        elif kind == "SYS_STATUS":
            self.prearm_ok = bool(msg.onboard_control_sensors_health & PREARM_CHECK)
        elif kind == "HOME_POSITION":
            self.home_alt = msg.altitude / 1000.0
            self.home_lat = msg.latitude / 1e7
            self.home_lon = msg.longitude / 1e7
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
        # arm when PX4's pre-arm checks pass, rather than asking again and again before (each refusal is a
        # warning on PX4's console)
        if not self.prearm_ok:
            self.status("take-off: waiting for PX4's pre-arm checks")
            end = time.time() + 120
            while not self.prearm_ok and time.time() < end:
                msg = link.recv_match(blocking=True, timeout=1)
                if msg is not None:
                    self.handle(msg)
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

    # --- a route: go to each point in turn (MAV_CMD_DO_REPOSITION, as QGroundControl's "Go to location")
    def do_route(self, points: list, altitude: float = 2.5, speed: float = 2.0, fault: dict | None = None) -> None:
        if self.home_lat is None:
            self.status("route: no home position yet")
            return
        if not self.state.get("armed"):
            self.status("route: take off first")
            return
        self.route = [[float(n), float(e)] for n, e in points]
        self.route_index = 0
        self.route_alt = altitude
        self.route_speed = speed
        self.route_fault = fault if fault and 1 <= int(fault.get("at", 0)) <= len(self.route) else None
        self.route_sent = 0.0
        self.state["route"] = {"points": self.route, "index": 0, "fault": self.route_fault}
        plan = f"; motor {self.route_fault['motor']} stops at point {self.route_fault['at']}" if self.route_fault else ""
        self.status(f"route: {len(self.route)} points at {altitude} m, {speed} m/s{plan}")

    def do_route_clear(self) -> None:
        self.route = []
        self.state.pop("route", None)

    def follow_route(self, now: float) -> None:
        """Sends the current point, and the next one once the vehicle is within 0.8 m of it."""
        if not self.route or self.route_index >= len(self.route):
            return
        north, east = self.route[self.route_index]
        x, y = self.state.get("x"), self.state.get("y")
        if x is not None and math.hypot(north - x, east - y) < 0.8:
            self.route_index += 1
            self.state["route"] = {"points": self.route, "index": self.route_index, "fault": self.route_fault}
            if self.route_fault and self.route_index == int(self.route_fault["at"]) and self.on_fault:
                self.status(f"point {self.route_index} reached: stop motor {self.route_fault['motor']}")
                self.on_fault(int(self.route_fault["motor"]))
                self.route_fault = None
            if self.route_index >= len(self.route):
                self.status("route: done")
                return
            self.route_sent = 0.0
            north, east = self.route[self.route_index]
        if now - self.route_sent < 2.0:   # (re)send every 2 s until reached
            return
        lat = self.home_lat + math.degrees(north / EARTH_RADIUS)
        lon = self.home_lon + math.degrees(east / (EARTH_RADIUS * math.cos(math.radians(self.home_lat))))
        link = self.link
        link.mav.command_int_send(link.target_system, link.target_component, mavutil.mavlink.MAV_FRAME_GLOBAL,
                                  mavutil.mavlink.MAV_CMD_DO_REPOSITION, 0, 0,
                                  self.route_speed, mavutil.mavlink.MAV_DO_REPOSITION_FLAGS_CHANGE_MODE, 0, float("nan"),
                                  int(lat * 1e7), int(lon * 1e7), self.home_alt + self.route_alt)
        self.route_sent = now

