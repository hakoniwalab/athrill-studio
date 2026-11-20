#!/bin/sh
# Prepares work/drone-motor/: PX4 on the emulated Pixhawk 4 flying the Hakoniwa
# Drone x500 in process, with the sensor device's motor-status build. That build
# reports each rotor's speed and writes the flight trace (the aircraft's truth
# pose, rotor speeds and duty), which the Flight tab draws.
#   tools/setup-drone-motor.sh <athrill3> <athrill-device> <inproc build dir> <drone-core> <seed dshot>
# <athrill3>          an athrill3 built from athrill-target-stm32 main (JIT, DShot ESCs)
# <athrill-device>    the athrill-device checkout of that build (its boards/ DTBs)
# <inproc build dir>  libhako_sensor_device_inproc_motor.dylib (.so on Linux) with the flight trace
#                     (athrill-device board/common, HAKO_SENSOR_DEVICE_BUILD_INPROC_MOTOR=ON)
#                     and the libraries beside it
# <drone-core>        the Hakoniwa Drone build with rotor status (its MuJoCo models and
#                     config/drone/x500-athrill-px4 are relative to it)
# <seed dshot>        fram.bin and sd.img after PX4's first boot with the x500 and DShot
#                     parameters (athrill-target-stm32 examples/px4-hakoniwa-dshot, ATHRILL_PREPARE_ONLY=1)
set -eu
[ $# -eq 5 ] || { sed -n 2,15p "$0" >&2; exit 2; }
HERE=$(cd "$(dirname "$0")/.." && pwd)
D=$HERE/work/drone-motor
abs() { (cd "$(dirname "$1")" && echo "$(pwd)/$(basename "$1")"); }
mkdir -p "$D"
for name in athrill3 athrill-device lib plugin drone-core seed-pwm seed-dshot; do rm -f "$D/$name"; done
ln -s "$(abs "$1")" "$D/athrill3"
ln -s "$(abs "$2")" "$D/athrill-device"
ln -s "$(abs "$3")" "$D/lib"
ln -s "$(abs "$4")" "$D/drone-core"
ln -s "$(abs "$5")" "$D/seed-dshot"
# the sensor device for this host: .dylib on macOS, .so on Linux
case "$(uname -s)" in Darwin) EXT=dylib ;; *) EXT=so ;; esac
ln -s "lib/libhako_sensor_device_inproc_motor.$EXT" "$D/plugin"
for need in athrill3 plugin \
	athrill-device/boards/pixhawk4/pixhawk4-hakoniwa-dshot.dtb \
	drone-core/config/drone/x500-athrill-px4/drone_config_0.json \
	seed-dshot/fram.bin seed-dshot/sd.img; do
	[ -e "$D/$need" ] || { echo "missing $D/$need" >&2; exit 1; }
done
echo "drone (motor status) ready in $D"
