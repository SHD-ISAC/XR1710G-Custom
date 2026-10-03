# XR1710G integration status

This branch integrates official OpenWrt main into YYH's
`xr1710g-6.18-integration` device port.

- Device baseline: `c82129e7348fda30b9e2f90572e4f1b3c555c7f2`
- Official main: `0d212bc523580e3bd20d18d646987ca488f8d0ee`
- Kernel: Linux 6.18.54
- Target: `airoha/an7581`, `gemtek_xr1710g-ubi`
- Status: integration in progress; wireless and kernel patches are being rebased.
- Full firmware compilation and hardware tests have not passed for this commit.

The original XR1710G flash layout and bootloader compatibility are preserved.
Do not treat this development checkpoint as a tested firmware release.

The pinned feeds and device build seed are in `configs/`.
Upstream multi-target workflows only run in the official OpenWrt repository.
A dedicated XR1710G workflow will be added after patch preparation succeeds.
