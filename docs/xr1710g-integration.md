# XR1710G integration status

This branch integrates official OpenWrt main into YYH's
`xr1710g-6.18-integration` device port.

- Device baseline: `c82129e7348fda30b9e2f90572e4f1b3c555c7f2`
- Official main: `0d212bc523580e3bd20d18d646987ca488f8d0ee`
- Kernel: Linux 6.18.54
- Target: `airoha/an7581`, `gemtek_xr1710g-ubi`
- Status: kernel (644 patches), mac80211 and mt76 patch preparation passed.
  Full firmware compilation is in progress.
- Full firmware compilation and hardware tests have not passed for this commit.

The original XR1710G flash layout and bootloader compatibility are preserved.
Do not treat this development checkpoint as a tested firmware release.

The pinned feeds and device build seed are in `configs/`.
Upstream multi-target workflows only run in the official OpenWrt repository.
The `XR1710G firmware` workflow builds the complete image from source, checks
image metadata and checksums, and keeps logs and firmware as Actions artifacts.
It uses commit-pinned actions and runs on pushes to `xr1710g-custom`.

## Local build

```sh
cp configs/xr1710g-feeds.conf feeds.conf
./scripts/feeds update -a
./scripts/feeds install -a
cp configs/xr1710g.config .config
make defconfig
make download -j8
make -j$(nproc) V=s
```

## Hardware validation still required

Boot, Wi-Fi association/MLO, Ethernet links, reboot recovery, and IPv4/IPv6
throughput have not been tested on a physical XR1710G. In particular, the
previous AP-mode IPv6/upload stall must be retested; compilation cannot
establish that it is fixed.
