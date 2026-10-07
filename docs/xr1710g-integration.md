# XR1710G integration and build verification

Official OpenWrt main is merged into YYH's `xr1710g-6.18-integration`
device port. The current firmware candidate was built from
`b03fae0c161829b54ea83cb173992d3c9fff205c`. Its full build, targeted regression
tests and actual image inspection passed. Physical-device validation is pending.

A second audit found that the preceding candidate's plain `dnsmasq` can fail
to start with retained DNSSEC settings from YYH's `dnsmasq-full`. The current
candidate restores the full variant and its YYH-equivalent feature set.
The actual ARM program extracted from the new image passes the configuration
regression tests under QEMU; no DNS/DHCP service was started by these tests.
See the [second image audit](xr1710g-network-regression.md#second-image-audit-retained-dnsdhcp-settings).

**The earlier hardware test failed:** after flashing the old build at
`f628bdc4dba371d9a0f00d3ba2ac392759e79d99`, the owner reported no Wi-Fi and
no usable Ethernet, including after a reset attempt, and has rolled back.
Do not use that old artifact as a known-good firmware.
The [code audit](xr1710g-network-regression.md) identifies a deterministic
MT7996 teardown deadlock introduced by duplicate backports. The corrected
driver is verified in the new images; the exact failing boot was not logged.

- Device baseline: `c82129e7348fda30b9e2f90572e4f1b3c555c7f2`
- Official main at the integration cutoff: `0d212bc523580e3bd20d18d646987ca488f8d0ee`
- Kernel: Linux 6.18.54
- Wireless: mac80211 backports 7.2; mt76 2026.09.01~be5ce791, package release 5
- Target: `airoha/an7581`, `gemtek_xr1710g-ubi`

## Current candidate and verified build

[GitHub Actions run 37524409837](https://github.com/SHD-ISAC/XR1710G-Custom/actions/runs/37524409837)
completed successfully on 2026-10-06 at 21:27 UTC (2026-10-07 05:27 China time).
It built the target Linux kernel, wireless drivers, selected packages and
complete firmware images from source. The mt76 archive hash check, whole-stack
patch application with `--fuzz=0`, all five regression cases, image metadata
checks, `sha256sum -c sha256sums` and the new ARM dnsmasq configuration tests
passed. [Build logs and configuration](https://github.com/SHD-ISAC/XR1710G-Custom/actions/runs/37524409837/artifacts/11445585633)
include both regression logs.

The downloaded artifact ZIP digest and all seven image-directory checksums
were verified independently. The kernel, DTB and rootfs FIT hashes also match.
The `mt7996e.ko` modules extracted from sysupgrade squashfs and recovery
initramfs are identical and no longer contain the consecutive same-mutex
locking sequence. The manifest lists 189 packages, `dnsmasq-full` 2.93-r3 and
MT7996 package release `r5`; the firmware revision is `r36905-b03fae0c16`.
The packaged DNSSEC trust anchors and the dnsmasq binary are identical in both
images. The sysupgrade binary passes basic DNS/DHCP and
DNSSEC/DHCPv6/nftset/conntrack configuration tests under QEMU. The checked core
programs and all their required libraries resolve to 33 files in the image.

[Download the current CI firmware artifact](https://github.com/SHD-ISAC/XR1710G-Custom/actions/runs/37524409837/artifacts/11445510943).
It contains:

- `openwrt-airoha-an7581-gemtek_xr1710g-ubi-squashfs-sysupgrade.itb`
- `openwrt-airoha-an7581-gemtek_xr1710g-ubi-initramfs-recovery.itb`
- `sha256sums`, image profiles, package manifest and build information

The sysupgrade image is 15,827,892 bytes (approximately 15.09 MiB); recovery is
13,762,560 bytes (13.125 MiB). The sysupgrade is 576 KiB larger than the preceding
14.53 MiB candidate because dnsmasq-full and its dependencies are restored.
Network services, MT7996/NPU firmware and startup links are present. The
embedded XR1710G DTB and all 11 regular hardware-firmware files match the actual
YYH August 31 release byte-for-byte.

| Image suffix | SHA256 |
| --- | --- |
| `squashfs-sysupgrade.itb` | `e6e4229591189a249ef170ac6cea2e63c9f36daf4f8978f5f3ae2c11c10a8e88` |
| `initramfs-recovery.itb` | `2889080c740d3e79cb5dd396ae07fb67cafd04601e442e023ae18b3c8fd96972` |

This artifact is retained until 2026-10-20 at 21:27 UTC. Check the source
commit when choosing an artifact. This is a candidate for physical validation,
not a hardware-verified release.

## Earlier failed hardware test

[Run 37156965190](https://github.com/SHD-ISAC/XR1710G-Custom/actions/runs/37156965190)
at `f628bdc4dba371d9a0f00d3ba2ac392759e79d99` compiled successfully on
2026-10-03, but the owner's subsequent hardware test failed as described above.
That artifact and the older local compilation establish only that the old
source compiled; they did not catch the runtime deadlock. Use the current
candidate link above when reviewing the correction.

## Flash compatibility: check before upgrading

The XR1710G DTS and flash layout from device baseline `c82129e` are preserved.
The actual YYH August 31 release has the same embedded DTB as this candidate.
This does **not** establish compatibility with an older installed firmware.
The image explicitly declares compatibility version **2.0**. The inherited
XR1710G device definition warns that the BMT/BBT boundary changed: migration
from the older layout requires an XR1710G chainloader/U-Boot matching the new
layout, followed by booting recovery/initramfs and recreating UBI.

Do not bypass an image compatibility rejection with `sysupgrade -F`.
Deselecting "keep settings" alone does not perform this layout migration.
Do not flash a W1700K bootloader or infer that this archive includes an XR1710G
chainloader; it contains the two firmware images listed above.

Read-only checks on the currently running router:

```sh
ubus call system board
uci -q get 'system.@system[0].compat_version'
cat /proc/mtd
```

An absent compatibility value is treated as 1.0 by OpenWrt's upgrade check.
The reported value alone is insufficient: confirm the actual flash layout
and installed bootloader before choosing an upgrade procedure.

## Build and maintain

The pinned feeds and device seed are in `configs/`. On a host with OpenWrt's
build dependencies installed:

```sh
cp configs/xr1710g-feeds.conf feeds.conf
./scripts/feeds update -a
./scripts/feeds install -a
cp configs/xr1710g.config .config
make defconfig
make download -j8
bash scripts/tests/check-xr1710g-mt76.sh
make -j$(nproc) V=s
python3 scripts/tests/xr1710g-dnsmasq-regression.py build_dir/target-*/root-airoha
```

Continue development on `xr1710g-custom`. The `XR1710G firmware` workflow uses
commit-pinned actions, builds this device on code pushes, checks image outputs,
and caches host tools and the source-built cross-toolchain for subsequent runs.
Documentation-only pushes do not rebuild firmware. Upstream multi-target
workflows only run in the official OpenWrt repository.

## Hardware validation

The corrected build and targeted regression tests do not establish that the
previous AP-mode IPv6/upload stall is fixed. Boot, Wi-Fi association/MLO,
Ethernet links, IPv4/IPv6 transfers in both
directions, AP/bridge behavior, and reboot recovery still need testing on an
actual XR1710G. The owner's first flash failed as described above. Hardware
results should record the exact firmware commit and network mode; source
regression tests and successful builds cannot establish hardware recovery.
