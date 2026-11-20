# Athrill Studio

**See your firmware run.**

Athrill Studio is a browser-based development and visualization environment for the [Athrill](https://github.com/toppers/athrill) microcontroller emulator.

Select a virtual board, run real firmware, and explore what is happening inside the emulated hardware — all from your browser.

The goal is simple:

**Make embedded systems development more accessible, observable, and fun.**

## What is Athrill Studio?

Embedded development often requires hardware boards, serial consoles, debuggers, and specialized tools.

Athrill Studio brings these elements together in one interactive workspace.

The vision includes:

- **Virtual Board Explorer** — Visualize CPUs, peripherals, and device connections directly from Devicetree (DTB).
- **Firmware Launcher** — Select and launch supported PX4, ArduPilot, or Zephyr firmware.
- **Live Device Monitor** — Observe UART, SPI, I2C, DMA, GPIO, and interrupt activity.
- **Interactive Console** — Access firmware consoles such as NuttX NSH from the browser.
- **Execution Monitor** — Monitor instruction counts, virtual time, and real-time factor (RTF).
- **Hakoniwa Integration** — Connect virtual hardware to Hakoniwa simulations, including drone physics and actuator outputs.

## Try the PX4 motor-failure demo on your PC

The official PX4 firmware runs on an emulated Pixhawk 4 and flies the Hakoniwa Drone x500. Then an emulated ESC
stops one motor, and PX4 notices it through its own DShot driver and the ESC telemetry. You watch it in the browser.

### What you can do

- Run the **official, unmodified PX4 v1.17.0** firmware (`px4_fmu-v5_default`) on an emulated Pixhawk 4. Its own
  drivers read the emulated IMU, barometer, magnetometer and GPS chips, and it drives the motors over **DShot600**.
- **Fly** the free edition of [Hakoniwa Drone](https://github.com/toppers/hakoniwa-drone-core)'s x500 (MuJoCo
  physics, in the Athrill process): take off, hold 2.5 m, land.
- **Stop a motor** inside the emulated ESC (motor 3 at 40 s of virtual time). The ESC keeps answering with zero
  current and zero rpm, PX4 reports `Motor failure detected` from that telemetry, and the x500 comes down.
- **Watch** it in the browser: the x500 in 3D, PX4's console, the altitude and each rotor's speed.
- **Repeat** it as often as you like under the same conditions, with no hardware at risk.
- **Check** it without the browser: one command runs both flights and prints `PASS` or `FAIL`.

### What it does not do (yet)

- **No proof of hardware behaviour.** The chips are functional models with an exact virtual clock (one instruction
  is one clock), not cycle- or electrically accurate copies of the silicon.
- **One board and one firmware.** It is verified with the Pixhawk 4 and PX4 v1.17.0 only. The Pixhawk 6C and
  ArduPilot have DShot examples in [athrill-target-stm32](https://github.com/hakoniwalab/athrill-target-stm32), but
  not in this demo.
- **The fault is set at start.** Motor 3 stops at a fixed virtual time. You cannot inject a fault from the browser
  during a flight yet.
- **PX4 detects; it does not compensate.** This is stock PX4 behaviour. It reports the failure but does not switch
  to flying on the remaining motors, so the x500 falls.
- **Flights are not bit-identical.** With Real time on, MAVLink commands arrive at wall-clock times, so two flights
  differ slightly (PX4 reported the failure between 40.10 and 40.16 s of virtual time in our runs). Runs without
  outside input, such as PX4's bench and SIH checks in athrill-target-stm32, are bit-identical.
- **One vehicle, the provided firmware.** Several vehicles, or firmware you built yourself, are not supported yet.

### Can I run it on my PC?

| | Supported | Not yet |
| --- | --- | --- |
| Computer | Apple silicon Mac (macOS 14 or later); Windows 11 with WSL2 (Ubuntu 24.04, x86_64) | Intel Mac, Windows without WSL2, Linux on Arm |
| Tools | Python 3.12, CMake, a C/C++ compiler, git, curl, unzip, Ruby, a browser | |
| Disk and network | About 2 GB (about 1 GB of it is the emulated SD card of each run); network for the first setup | |

**Not needed:** a flight controller or drone, a GPU, administrator rights (`sudo`), or any account or licence. Every
part is public and free.

It runs through a [Hakoniwa Business Pack](https://github.com/hakoniwalab/hakoniwa-business-pack) Recipe. The Recipe
fetches and builds everything inside the Business Pack workspace, at pinned releases and commits, and installs
nothing outside it. In an empty directory:

```bash
git clone https://github.com/hakoniwalab/hakoniwa-business-pack.git
cd hakoniwa-business-pack
python3.12 tools/recipe/athrill_studio_px4.py configure
python3.12 tools/recipe/athrill_studio_px4.py fetch
python3.12 tools/recipe/athrill_studio_px4.py build
python3.12 tools/recipe/athrill_studio_px4.py prepare
python3.12 tools/recipe/athrill_studio_px4.py scenario
```

- `configure` builds the Business Pack Foundation (the Hakoniwa core) and clones the parts next to
  `hakoniwa-business-pack`.
- `fetch` downloads the release files and checks their SHA-256.
- `build` builds the in-process sensor device.
- `prepare` runs PX4's first boot.
- `scenario` runs both flights and prints `PASS` for each.

From an empty directory this took about 6.5 minutes on an Apple M2 Pro and about 10 minutes on WSL2, most of it the
first Foundation build. To watch the flights:

```bash
python3.12 tools/recipe/athrill_studio_px4.py start
```

Open `http://localhost:8765/` (on WSL2, in the Windows browser). Choose **Holybro Pixhawk 4**, turn **Real time** on
and open the **Flight** tab:
- "PX4 v1.17.0 flying the x500 (in process, DShot ESCs)": **Run**, then **Take off 2.5 m** and **Land**.
- "PX4 v1.17.0 x500, motor 3 stops at 40 s": **Run**. Studio takes off by itself, and motor 3 stops at 40 s.

On WSL2, Studio listens on every interface so that the Windows browser can reach it, so other machines on your
network can reach it too. Stop it with:

```bash
python3.12 tools/recipe/athrill_studio_px4.py stop
```

## Architecture

Athrill Studio does not replace the Athrill emulator.

Instead, it adds a browser-based interface to its existing execution and device-model infrastructure.

```text
           Athrill Studio
             (Browser)
                 |
            WebSocket
                 |
           Studio Backend
                 |
        +--------+--------+
        |                 |
     Athrill        Devicetree
   CPU Emulator     Device Models
        |                 |
        +--------+--------+
                 |
           Firmware ELF
                 |
        PX4 / ArduPilot / Zephyr
                 |
          Hakoniwa Simulation
              (optional)
```

The architecture separates firmware execution, hardware emulation, and visualization.

Athrill remains usable independently of Studio.

## Target Platforms

The initial development targets include:

| Virtual board | Architecture |
|---|---|
| Pixhawk 4 | STM32F765 / Arm Cortex-M7 |
| Pixhawk 6C | STM32H743 / Arm Cortex-M7 |
| STM32 Nucleo | STM32F7 / STM32H7 |
| Erbium | RISC-V |

Availability depends on the corresponding Athrill target, device models, and firmware configuration.

## Design Principles

1. **Devicetree-driven** — Board topology comes from the virtual board configuration, not hard-coded UI definitions.
2. **Non-intrusive observation** — Visualization should not change firmware behavior or virtual-time execution.
3. **Reproducibility** — Preserve deterministic execution and make traces useful for verification and debugging.
4. **Modularity** — Keep the emulator, device models, browser backend, and frontend independently maintainable.
5. **Extensibility** — Support additional boards and peripherals without redesigning the UI.

## Try it (first milestone)

Today Studio starts Zephyr's samples on the emulated **NUCLEO-F767ZI** and **NUCLEO-H743ZI**, shows their console in
the browser, and draws each board's Devicetree as a graph.

```sh
tools/fetch.sh                 # the athrill-target-stm32 release of versions.txt and athrill-device's board DTBs, into work/
python3 -m pip install aiohttp pyyaml
python3 -m studio.server       # then open http://127.0.0.1:8765/
```

- **Console**: pick a board and a firmware (Zephyr `hello_world`, `synchronization`, `philosophers`) and press
  Run. The firmware's console is a terminal (xterm.js), so `philosophers` redraws its table in place. Athrill's own
  lines are under "Athrill log".
- **Real time and RTF**: the "Real time" switch keeps virtual time from running ahead of the wall clock
  (`DEBUG_FUNC_REAL_TIME 1`), so `synchronization` greets every 0.5 s of your time. Without it Athrill runs as fast as
  it can. The meter shows the virtual time and the real-time factor from Athrill's progress report
  (`DEBUG_FUNC_PROGRESS_MSEC`, toppers/athrill#90); the athrill3 release of versions.txt has it.
- **Flight**: on the Pixhawk 4, "PX4 v1.17.0 flying the Hakoniwa Drone x500 (in process)" runs PX4 with its own
  drivers on the emulated chips, whose samples come from the Hakoniwa Drone x500 physics and sensor models running
  inside Athrill (no Hakoniwa runtime, no second process). Studio talks MAVLink to PX4 (TCP 5760): "Take off 2.5 m"
  and "Land", the x500 in 3D, its altitude and attitude. One-time setup, with the in-process sensor device built from
  athrill-device (`board/common`, `HAKO_SENSOR_DEVICE_BUILD_INPROC=ON`), a Hakoniwa Drone release, the x500 airframe
  and PX4's first-boot images (athrill-target-stm32 `examples/px4-hakoniwa`):
  `tools/setup-drone.sh <inproc library dir> <hakoniwa-drone-core> <airframe dir> <seed dir>`.
  `python3 tests/flight_smoke.py` takes off, holds 2.5 m and lands through the API (`--firmware px4-x500-dshot`
  for the same flight on the DShot ESCs of the next item).
- **Flight with rotor status, and the motor-failure demo**: with the sensor device's motor-status build
  (athrill-device `HAKO_SENSOR_DEVICE_BUILD_INPROC_MOTOR=ON`), "PX4 ... x500 (in process, DShot ESCs)" flies the x500
  on DShot600 ESCs, and "PX4 ... x500, motor 3 stops at 40 s" takes off by itself and stops motor 3 in its emulated
  ESC: PX4 reports "Motor failure detected" from the ESC telemetry and the x500 comes down. The Flight tab draws the
  x500 of hakoniwa-threejs-drone from the device's flight trace (the aircraft's truth about every 10 ms of virtual
  time), interpolated, beside PX4's console. One-time setup:
  `tools/setup-drone-motor.sh <athrill3> <athrill-device> <inproc build dir> <drone-core> <DShot seed dir>`.
  `python3 tests/motor_stop_smoke.py` runs the motor-failure demo through the API and requires the climb, PX4's
  report and the descent (`--real-time` as with the switch).
- **Fly a route and stop a motor from the browser**: "PX4 v1.17.0 x500, fly a route and stop a motor from the
  browser" uses the same setup with the sensor device as the ESC's fault model (`pixhawk4-hakoniwa-dshot-asset.dtb`,
  and an in-process sensor device with `HAKO_SENSOR_DEVICE_ROTOR_FAULT_FILE`, athrill-device after its rotor-fault
  file). After **Take off 2.5 m**, click the map (north up, 1 m grid, home in the middle) to set the route's
  points, optionally plan a fault ("stop motor 3 at point 2"), and press **Fly route**: Studio sends PX4 each point
  in turn over MAVLink (`MAV_CMD_DO_REPOSITION`, 2 m/s), the path shows on the ground, and the planned motor stops
  when its point is reached. The **Stop 1-4** buttons stop a motor at any moment, **Restore all** brings them back.
  Studio writes the rotor scales to `work/run/<board>/rotor-fault.txt`, which the sensor device reads every 20 ms
  of virtual time; PX4 detects the stop from the ESC telemetry. `python3 tests/route_fault_smoke.py` flies a 6 m
  square with the fault planned at point 2 (`--manual` stops it through the API instead) and requires the route,
  PX4's report and the descent.
- **Video of a recorded flight**: a run with the flight trace leaves `work/run/<board>/flight.txt` and
  `timeline.jsonl` (the console and PX4's status texts on virtual time). `python3 tools/render-video.py
  tools/videos/motor-stop.json out.mp4` draws it frame by frame in headless Chrome (`web/replay.html`, 1920x1080) with
  the script's segments (slow motion), captions and closing card, and encodes it with ffmpeg. Every frame is the
  recorded flight at its exact virtual time, whatever the speed of the machine.
- **Devicetree**: the board's DTB as a graph. Nodes are the enabled nodes with a `compatible`. The grey lines are the
  bus tree, and the dashed ones are references: interrupt, DMA, clock, reset, GPIO, pin control. Blue nodes are the ones
  Athrill built a model for in the last run. Click a node for its compatible, registers, model and references.
- `python3 tests/smoke.py` checks the path end to end. It starts the server, reads the Devicetree, runs
  `hello_world` through the API and requires the greeting and the models over the WebSocket.

The backend (`studio/server.py`) runs Athrill unchanged and only reads what it prints. Boards are listed in
`boards.yaml`. The DTB is read by `studio/dtb.py` (no dependency). The browser gets JSON over REST and a WebSocket
for now; a binary transport (Hakoniwa PDU) can replace the stream for high-rate device data.

## Project Status

**Early development — work in progress.** The first milestone above runs; the rest of this README is the direction.

This README describes the intended direction of Athrill Studio. The listed features are not all guaranteed to be available yet.

The first milestone focuses on a single virtual board, its Devicetree topology, firmware execution, and interactive console. Device activity visualization and Hakoniwa integration will be expanded incrementally.

Installation instructions and runnable examples will be added as the implementation becomes publicly available.

## Related Projects

- [Athrill](https://github.com/toppers/athrill) — Microcontroller emulator
- [athrill-device](https://github.com/hakoniwalab/athrill-device) — Devicetree-driven virtual device framework
- [athrill-target-stm32](https://github.com/hakoniwalab/athrill-target-stm32) — STM32 / Pixhawk emulation
- [athrill-target-riscv](https://github.com/hakoniwalab/athrill-target-riscv) — RISC-V emulation
- [Hakoniwa Urban Mobility](https://github.com/hakoniwalab/hakoniwa-urban-mobility) — Browser-driven simulation environment

## License

See [LICENSE](LICENSE).

---

**Athrill Studio — Make the invisible hardware visible.**

*Time begins to move.*
