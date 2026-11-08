#!/bin/sh
# Fetches what Athrill Studio runs into work/, at the versions of versions.txt:
#   tools/fetch.sh
# - the athrill3 release of athrill-target-stm32 for this host, with bindings/
# - the Zephyr sample ELFs of the same release
# - athrill-device at the pinned commit (the board Devicetrees)
# Downloads are checked against the release's SHA256SUMS. Needs curl, git, tar.
set -eu
HERE=$(cd "$(dirname "$0")/.." && pwd)
WORK=$HERE/work
v() { awk -v k="$1" '$1 == k { print $2 }' "$HERE/versions.txt"; }
STM32=$(v athrill-target-stm32)
DEVICE=$(v athrill-device)
case "$(uname -s)-$(uname -m)" in
Darwin-arm64) HOST=macos-arm64 ;;
Linux-x86_64) HOST=linux-x86_64 ;;
*) echo "no athrill3 release for $(uname -s) $(uname -m)" >&2; exit 1 ;;
esac
mkdir -p "$WORK/download"
cd "$WORK/download"
URL=https://github.com/hakoniwalab/athrill-target-stm32/releases/download/$STM32
get() { [ -s "$1" ] || curl -fsSLO --retry 5 --retry-all-errors "$URL/$1"; }
get SHA256SUMS
get "athrill3-$STM32-$HOST.tar.gz"
get "zephyr-samples-$STM32.tar.gz"
if command -v sha256sum > /dev/null; then SUM="sha256sum -c"; else SUM="shasum -a 256 -c"; fi
grep -E " (athrill3-$STM32-$HOST|zephyr-samples-$STM32)\.tar\.gz\$" SHA256SUMS > SHA256SUMS.used
$SUM SHA256SUMS.used
tar xzf "athrill3-$STM32-$HOST.tar.gz" -C "$WORK"
tar xzf "zephyr-samples-$STM32.tar.gz" -C "$WORK"
rm -f "$WORK/athrill3-stm32"
ln -s "athrill3-$STM32-$HOST" "$WORK/athrill3-stm32"
rm -f "$WORK/zephyr-stm32"
ln -s "zephyr-samples-$STM32" "$WORK/zephyr-stm32"
if [ "$(git -C "$WORK/athrill-device" rev-parse HEAD 2>/dev/null || true)" != "$DEVICE" ]; then
	rm -rf "$WORK/athrill-device"
	git init -q "$WORK/athrill-device"
	git -C "$WORK/athrill-device" fetch -q --depth 1 https://github.com/hakoniwalab/athrill-device.git "$DEVICE"
	git -C "$WORK/athrill-device" checkout -q FETCH_HEAD
fi
echo "ready: $WORK/athrill3-stm32/athrill3, $WORK/zephyr-stm32, athrill-device $DEVICE"
