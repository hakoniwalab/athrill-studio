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
tools/fetch.sh                 # the athrill-target-stm32 v0.3.0 release and athrill-device's board DTBs, into work/
python3 -m pip install aiohttp pyyaml
python3 -m studio.server       # then open http://127.0.0.1:8765/
```

- **Console**: pick a board and a firmware (Zephyr `hello_world`, `synchronization`, `philosophers`) and press
  Run. The firmware's console is a terminal (xterm.js), so `philosophers` redraws its table in place. Athrill's own
  lines are under "Athrill log".
- **Real time and RTF**: the "Real time" switch keeps virtual time from running ahead of the wall clock
  (`DEBUG_FUNC_REAL_TIME 1`), so `synchronization` greets every 0.5 s of your time. Without it Athrill runs as fast as
  it can. The meter shows the virtual time and the real-time factor from Athrill's progress report
  (`DEBUG_FUNC_PROGRESS_MSEC`, toppers/athrill#90). Until a release of athrill3 has it, set `STUDIO_ATHRILL3` to a
  locally built `athrill3`; the release's `athrill3` runs too, without the meter.
- **Flight**: on the Pixhawk 4, "PX4 v1.17.0 flying the Hakoniwa Drone x500 (in process)" runs PX4 with its own
  drivers on the emulated chips, whose samples come from the Hakoniwa Drone x500 physics and sensor models running
  inside Athrill (no Hakoniwa runtime, no second process). Studio talks MAVLink to PX4 (TCP 5760): "Take off 2.5 m"
  and "Land", the x500 in 3D, its altitude and attitude. One-time setup, with the in-process sensor device built from
  athrill-device (`board/common`, `HAKO_SENSOR_DEVICE_BUILD_INPROC=ON`), a Hakoniwa Drone release, the x500 airframe
  and PX4's first-boot images (athrill-target-stm32 `examples/px4-hakoniwa`):
  `tools/setup-drone.sh <inproc library dir> <hakoniwa-drone-core> <airframe dir> <seed dir>`.
  `python3 tests/flight_smoke.py` takes off, holds 2.5 m and lands through the API.
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
