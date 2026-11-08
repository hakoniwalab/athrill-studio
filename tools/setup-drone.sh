#!/bin/sh
# Prepares the drone of Studio in work/drone/: PX4 on the emulated Pixhawk 4
# flying the Hakoniwa Drone x500, with the aircraft inside Athrill (the
# in-process sensor device: no Hakoniwa runtime, no second process).
#   tools/setup-drone.sh <inproc library dir> <hakoniwa-drone-core dir> <airframe dir> <seed dir>
# <inproc library dir>   libhako_sensor_device_inproc.dylib (athrill-device board/common,
#                        HAKO_SENSOR_DEVICE_BUILD_INPROC=ON, 32-bit) and the libraries beside it
# <hakoniwa-drone-core>  the Hakoniwa Drone release root (its MuJoCo models are relative to it)
# <airframe dir>         the x500 airframe (drone_config_0.json)
# <seed dir>             fram.bin and sd.img after PX4's first boot with the x500 parameters
#                        (athrill-target-stm32 examples/px4-hakoniwa makes them)
# The PX4 ELF comes from the athrill-target-stm32 release (tools/fetch.sh).
set -eu
[ $# -eq 4 ] || { sed -n 2,13p "$0" >&2; exit 2; }
HERE=$(cd "$(dirname "$0")/.." && pwd)
D=$HERE/work/drone
abs() { (cd "$1" && pwd); }
mkdir -p "$D"
for name in lib drone-core airframe seed; do rm -f "$D/$name"; done
ln -s "$(abs "$1")" "$D/lib"
ln -s "$(abs "$2")" "$D/drone-core"
ln -s "$(abs "$3")" "$D/airframe"
ln -s "$(abs "$4")" "$D/seed"
for need in lib/libhako_sensor_device_inproc.dylib airframe/drone_config_0.json seed/fram.bin seed/sd.img; do
	[ -e "$D/$need" ] || { echo "missing $D/$need" >&2; exit 1; }
done
echo "drone ready in $D"
