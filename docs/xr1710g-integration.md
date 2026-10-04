# XR1710G integration and build verification

Official OpenWrt main is merged into YYH's `xr1710g-6.18-integration`
device port. The previously compiled firmware source is commit
`f628bdc4dba371d9a0f00d3ba2ac392759e79d99`.

**Hardware test failed:** the owner reported no Wi-Fi and no usable Ethernet
network after flashing this artifact, including after a reset attempt, and
has rolled back. Do not use the old artifact as a known-good firmware.
The [code audit](xr1710g-network-regression.md) identifies a deterministic
MT7996 teardown deadlock introduced by duplicate backports. The fix requires
a new build and hardware validation; the exact failing boot was not logged.

- Device baseline: `c82129e7348fda30b9e2f90572e4f1b3c555c7f2`
- Official main at the integration cutoff: `0d212bc523580e3bd20d18d646987ca488f8d0ee`
- Kernel: Linux 6.18.54
- Wireless: mac80211 backports 7.2; mt76 2026.09.01~be5ce791
- Target: `airoha/an7581`, `gemtek_xr1710g-ubi`

## Verified build

[GitHub Actions run 37156965190](https://github.com/SHD-ISAC/XR1710G-Custom/actions/runs/37156965190)
completed successfully on 2026-10-03 at 23:07 UTC (2026-10-04 at 07:07 China time).
The compiler toolchain, Linux kernel, wireless drivers, selected packages and
complete firmware images were built from source. Image metadata checks and
`sha256sum -c sha256sums` passed. Logs, configuration and firmware were uploaded.

A separate local build using OpenWrt's checksum-verified GCC 14.4.0 musl
cross-toolchain also passed, including mac80211, MT7996, both firmware images,
image checksums and inspection of FIT/sysupgrade metadata.

[Download the CI firmware artifact](https://github.com/SHD-ISAC/XR1710G-Custom/actions/runs/37156965190/artifacts/11287730934).
It contains:

- `openwrt-airoha-an7581-gemtek_xr1710g-ubi-squashfs-sysupgrade.itb`
- `openwrt-airoha-an7581-gemtek_xr1710g-ubi-initramfs-recovery.itb`
- `sha256sums`, image profiles, package manifest and build information

This artifact is retained until 2026-10-17. Check the run's commit before
choosing an artifact. This link is retained for diagnosis of the failed build,
not as an upgrade recommendation.

## Flash compatibility: check before upgrading

The XR1710G DTS and flash layout from device baseline `c82129e` are preserved.
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
make -j$(nproc) V=s
```

Continue development on `xr1710g-custom`. The `XR1710G firmware` workflow uses
commit-pinned actions, builds this device on code pushes, checks image outputs,
and caches host tools and the source-built cross-toolchain for subsequent runs.
Documentation-only pushes do not rebuild firmware. Upstream multi-target
workflows only run in the official OpenWrt repository.

## Hardware validation

Compilation does not establish that the previous AP-mode IPv6/upload stall is
fixed. Boot, Wi-Fi association/MLO, Ethernet links, IPv4/IPv6 transfers in both
directions, AP/bridge behavior, and reboot recovery still need testing on an
actual XR1710G. The owner's first flash failed as described above. Hardware
results should record the exact firmware commit and network mode; source
regression tests and successful builds cannot establish hardware recovery.
