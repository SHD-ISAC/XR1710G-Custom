#!/usr/bin/env python3
"""Run the actual upgrade script against fake NAND/UBI and FIT helpers."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


MOCKS = r'''
board_name() { printf '%s' "$BOARD"; }
nand_find_ubi() { [ "$1" = ubi ] && [ "$NO_UBI" = 0 ] && echo ubi51; }
nand_find_volume() {
	[ "$1" = ubi51 ] && [ "$2" = factory ] && [ -e "$WORK/factory" ] && echo ubi51_0
}
find_mtd_index() { [ "$1" = vendor ] && echo 51; }
fit_check_image() { echo "check:$1"; return 7; }
fit_do_upgrade() { echo "fit:$1"; }
nand_do_upgrade() { echo "nand:$1"; }
v() { :; }
cat() {
	if [ "$1" = /sys/class/mtd/mtd51/erasesize ]; then echo 131072
	else command cat "$@"; fi
}
dd() {
	local i args=("$@")
	for i in "${!args[@]}"; do
		[ "${args[i]}" != if=/dev/mtd51 ] || args[i]="if=$WORK/vendor"
	done
	command dd "${args[@]}"
}
hexdump() {
	local offset=0 length format file bytes
	while [ "$#" -gt 1 ]; do
		case "$1" in
		-v) shift ;;
		-s) offset="$2"; shift 2 ;;
		-n) length="$2"; shift 2 ;;
		-e) format="$2"; shift 2 ;;
		*) return 4 ;;
		esac
	done
	file="$1"
	[ "$file" != /dev/mtd51 ] || file="$WORK/vendor"
	[ "$file" != /dev/ubi51_0 ] || file="$WORK/factory"
	bytes="$(od -An -v -j "$offset" -N "$length" -tx1 "$file" 2>/dev/null)" || return 1
	set -- $bytes
	if [ "$length" = 6 ]; then
		[ "$#" = 6 ] && printf '%s:%s:%s:%s:%s:%s' "$@"
	else
		printf '%s' "$@"
	fi
}
ubimkvol() {
	[ "$*" = '/dev/ubi51 -N factory -t static -s 65536' ] || return 5
	echo create
	: > "$WORK/factory"
}
ubiupdatevol() {
	[ "$1" = /dev/ubi51_0 ] || return 6
	echo update
	[ "$WRITE_FAIL" = 0 ] && cp "$2" "$WORK/factory"
}
source "$PLATFORM"
"$ENTRY" test.itb
'''


def main():
    platform = (Path(__file__).resolve().parents[2] /
                "target/linux/airoha/an7581/base-files/lib/upgrade/platform.sh")
    wlan = b"\x90\x79" + b"\xa5" * (0x1E00 - 2)
    wan, lan = bytes.fromhex("021122334455"), bytes.fromhex("021122334466")
    expected = bytearray(0x10000)
    expected[:len(wlan)] = wlan
    expected[0x5000:0x5006], expected[0x6000:0x6006] = wan, lan
    expected[0x7000:0x7001] = b"3"
    expected[0x8000:0x800B] = b"XR1710GTEST"
    cases = (
        ("preserve-valid", 0, "fit:test.itb"),
        ("rebuild-missing", 0, "create\nupdate\nfit:test.itb"),
        ("rebuild-empty", 0, "update\nfit:test.itb"),
        ("short-dsd", 1, ""),
        ("short-eeprom", 1, ""),
        ("wrong-serial", 1, ""),
        ("multicast-mac", 1, ""),
        ("no-ubi", 1, ""),
        ("write-failed", 1, "create\nupdate"),
        ("fit-check-failure", 7, "check:test.itb"),
        ("w1700k-fit-dispatch", 0, "fit:test.itb"),
    )
    with tempfile.TemporaryDirectory(prefix="xr1710g-upgrade-") as tmp:
        root = Path(tmp)
        for name, code, stdout in cases:
            work = root / name
            work.mkdir()
            vendor, factory = work / "vendor", work / "factory"
            dsd = (f"wan_mac={wan.hex(':')}\nlan_mac={lan.hex(':')}\n"
                   "fan_id=3\nserial_number=XR1710GTEST\n").encode()
            if name == "wrong-serial":
                dsd = dsd.replace(b"XR1710G", b"W1700K_")
            if name == "multicast-mac":
                dsd = dsd.replace(b"02:11", b"03:11", 1)
            with vendor.open("wb") as f:
                f.seek(0x400000)
                f.write(dsd)
                if name != "short-dsd":
                    f.seek(0x405000)
                    f.write(wlan if name != "short-eeprom" else wlan[:512])
            if name == "preserve-valid":
                factory.write_bytes(expected)
            if name == "rebuild-empty":
                factory.touch()
            entry = "platform_check_image" if name == "fit-check-failure" else "platform_do_upgrade"
            board = "gemtek,w1700k-ubi" if name == "w1700k-fit-dispatch" else "gemtek,xr1710g-ubi"
            result = subprocess.run(
                [shutil.which("bash"), "-c", MOCKS], capture_output=True, text=True,
                env={**os.environ, "WORK": str(work), "PLATFORM": str(platform),
                     "ENTRY": entry, "BOARD": board, "NO_UBI": str(int(name == "no-ubi")),
                     "WRITE_FAIL": str(int(name == "write-failed"))}, timeout=5)
            assert (result.returncode, result.stdout.strip()) == (code, stdout), (
                name, result.returncode, result.stdout, result.stderr)
            if name in ("preserve-valid", "rebuild-missing", "rebuild-empty"):
                assert factory.read_bytes() == expected, name
            elif name == "write-failed":
                assert not factory.stat().st_size, name
            else:
                assert not factory.exists(), name
            print(f"PASS {name}", flush=True)


if __name__ == "__main__":
    main()
