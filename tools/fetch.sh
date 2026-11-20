#!/bin/sh
# Fetches what Athrill Studio runs into work/, at the versions of versions.txt:
#   tools/fetch.sh
# - the athrill3 release of athrill-target-stm32 for this host, with bindings/
# - the PX4 ELF (px4_fmu-v5_default) of the same release, and the Zephyr sample ELFs of their release
# - athrill-device at the pinned commit (the board Devicetrees)
# Downloads are checked against the release's SHA256SUMS. Needs curl, git, tar.
set -eu
HERE=$(cd "$(dirname "$0")/.." && pwd)
WORK=$HERE/work
v() { awk -v k="$1" '$1 == k { print $2 }' "$HERE/versions.txt"; }
STM32=$(v athrill-target-stm32)
ZEPHYR=$(v zephyr-samples)
DEVICE=$(v athrill-device)
case "$(uname -s)-$(uname -m)" in
Darwin-arm64) HOST=macos-arm64 ;;
Linux-x86_64) HOST=linux-x86_64 ;;
*) echo "no athrill3 release for $(uname -s) $(uname -m)" >&2; exit 1 ;;
esac
mkdir -p "$WORK/download"
cd "$WORK/download"
RELEASES=https://github.com/hakoniwalab/athrill-target-stm32/releases/download
# get <release> <file> [<local name>]
get() { [ -s "${3:-$2}" ] || curl -fsSL --retry 5 --retry-all-errors -o "${3:-$2}" "$RELEASES/$1/$2"; }
get "$STM32" SHA256SUMS
get "$STM32" "athrill3-$STM32-$HOST.tar.gz"
get "$STM32" px4_fmu-v5_default.elf
get "$ZEPHYR" SHA256SUMS SHA256SUMS.zephyr
get "$ZEPHYR" "zephyr-samples-$ZEPHYR.tar.gz"
if command -v sha256sum > /dev/null; then SUM="sha256sum -c"; else SUM="shasum -a 256 -c"; fi
grep -E " (athrill3-$STM32-$HOST\.tar\.gz|px4_fmu-v5_default\.elf)\$" SHA256SUMS > SHA256SUMS.used
grep -E " zephyr-samples-$ZEPHYR\.tar\.gz\$" SHA256SUMS.zephyr >> SHA256SUMS.used
$SUM SHA256SUMS.used
tar xzf "athrill3-$STM32-$HOST.tar.gz" -C "$WORK"
tar xzf "zephyr-samples-$ZEPHYR.tar.gz" -C "$WORK"
rm -f "$WORK/athrill3-stm32"
ln -s "athrill3-$STM32-$HOST" "$WORK/athrill3-stm32"
rm -f "$WORK/zephyr-stm32"
ln -s "zephyr-samples-$ZEPHYR" "$WORK/zephyr-stm32"
if [ "$(git -C "$WORK/athrill-device" rev-parse HEAD 2>/dev/null || true)" != "$DEVICE" ]; then
	rm -rf "$WORK/athrill-device"
	git init -q "$WORK/athrill-device"
	git -C "$WORK/athrill-device" fetch -q --depth 1 https://github.com/hakoniwalab/athrill-device.git "$DEVICE"
	git -C "$WORK/athrill-device" checkout -q FETCH_HEAD
fi
echo "ready: $WORK/athrill3-stm32/athrill3, $WORK/zephyr-stm32, athrill-device $DEVICE"
