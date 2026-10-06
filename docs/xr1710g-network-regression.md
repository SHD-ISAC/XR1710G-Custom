# XR1710G network failure audit

The owner flashed the firmware built at `f628bdc4dba371d9a0f00d3ba2ac392759e79d99`
and reported a steady green LED, no Wi-Fi, no Ethernet DHCP and no accessible
management service. A reset attempt did not help. The owner has rolled back.
No serial log or kernel backtrace from the failing boot is available.

## Confirmed integration defects

The merge updated mt76 from `59676919ea408b0b13a9d23f2e2e1a1ab407fba1`
to `be5ce7910521492d4a2e4ce7ee3843680a46c047`, but retained several backports
already present in the newer source. GNU patch accepted them, sometimes by
discarding context with fuzz. Compilation did not detect the resulting bugs.

1. **Teardown deadlock (patch 0129).** The final `mt7996_remove_interface()`
   calls `mutex_lock(&dev->mt76.mutex)` twice consecutively. Linux mutexes
   are not recursive; interface removal blocks on the second call. The
   upstream fix is already in [50480826f5a9](https://github.com/openwrt/mt76/commit/50480826f5a9d2c615296bb12493ffee8c6b1281).
   This is a concrete explanation for stuck Wi-Fi teardown/reconfiguration.
   Network operations can also stall if the caller holds shared networking
   locks. Without a failing-device trace, this remains a strong candidate
   rather than proof of every symptom observed during this boot.
2. **Wrong MLD error path (patch 0117).** Its hunk was applied to failure of
   `get_own_mld_idx()`, not failure of `get_free_idx()` as intended. It clears
   a group bit before this interface has acquired a group, potentially
   releasing another interface's allocation. The correct remap-failure
   cleanup already exists upstream in [d67367ec3260](https://github.com/openwrt/mt76/commit/d67367ec326036675749b49fcc5f532acfd8b357).
3. **Double STBC conversion (patch 0140).** Both RX rate decoders halve the
   spatial-stream count twice. For example, NSTS 4 becomes NSS 1 rather than
   NSS 2. The conversion is already in [10a1541fb264](https://github.com/openwrt/mt76/commit/10a1541fb264831d717125ef32b16901f0fe0cec).
   This affects rate reporting and is not an explanation for missing Ethernet.

Eight redundant patches are removed. Their upstream implementations remain:

| Local patch | Upstream mt76 commit |
| --- | --- |
| 0101 EEPROM length check | `3eb3ab6b43f2e8108cdb0bea7891c900aabc5eed` |
| 0117 MLD group error cleanup | `d67367ec326036675749b49fcc5f532acfd8b357` |
| 0119 background radar index | `1ece37f8a93a3c2a02914e106b692f5393d59f3e` |
| 0124 queues after recovery | `130273a947ce7636ac1533e89b624061f8944fd1` |
| 0129 interface teardown lock | `50480826f5a9d2c615296bb12493ffee8c6b1281` |
| 0131 link index bounds | `8a03e88fc036bcbc83dce647dd322c0c5f40143b` |
| 0140 STBC RX NSS | `10a1541fb264831d717125ef32b16901f0fe0cec` |
| 0144 MLD individual TWT | `074472e615e94db31e23d0fef4a9ca9b085f5ce1` |

Four retained patches (0001, 0080, 0130, 9990) are refreshed against the
current source without changing their applied code. In particular, 0130
is not present upstream and remains necessary. NPU lifetime/recovery patches,
power controls and other board customizations remain in the stack.

## Validation

The `mt7996e.ko` modules extracted from the old CI sysupgrade squashfs and
recovery initramfs are byte-for-byte identical (SHA256
`b0d31a132c40f607fd51138fdc4f7c2ccd41973ff1c53d0c131ff63ee9dcd879`).
They confirm that the faulty code was shipped in the normal upgrade image,
not just a source reconstruction. Its `mt7996_remove_interface` symbol starts at
`.text+0x950c`; `readelf -rW` shows consecutive `mutex_lock` call relocations
at `.text+0x953c` and `.text+0x9544`, followed by the duplicated unlock calls.

`scripts/tests/check-xr1710g-mt76.sh` verifies the downloaded source archive's
configured SHA256, applies the entire mt76 patch stack with `--fuzz=0`, then
runs `xr1710g-mt76-regression.py`. CI runs this before building firmware and
uploads `mt76-patch-check.log`. Plain line offsets remain acceptable; ignoring
unmatched context does not.

The regression program extracts the actual prepared C bodies of
`mt7996_remove_interface()` and `mt7996_change_vif_links()`, compiles them with
host-side hardware stubs, and executes them with an error-checking POSIX mutex.
It tests empty and active interface teardown, full group allocation, full
remap allocation, and successful allocation/release.

Against the old prepared source, both teardown cases report recursive locking
and the full-group case corrupts the existing allocation bitmap. The remap
failure and successful allocation cases pass. Against the corrected source,
all five cases pass, and all remaining patches apply without fuzz. These tests
cover the identified control-flow errors, not kernel scheduling or hardware.

### Corrected build and image inspection

[Run 37267098667](https://github.com/SHD-ISAC/XR1710G-Custom/actions/runs/37267098667)
at `6485d6a8edf9076ff7de65330682d19ec12f40e5` completed successfully on
2026-10-05 at 06:00 UTC. Its `mt76-patch-check.log` records the matching source
archive SHA256, complete patch application without fuzz, and five passing
regression cases. The full target build and image output checks also passed.
The first attempted CI run stopped before compilation because the new helper
used hyphens instead of dots in the source archive date; commit `6485d6a8ed`
corrected that filename without bypassing the check.

The [new firmware artifact](https://github.com/SHD-ISAC/XR1710G-Custom/actions/runs/37267098667/artifacts/11328112301)
and [build logs](https://github.com/SHD-ISAC/XR1710G-Custom/actions/runs/37267098667/artifacts/11327982857)
were downloaded and their artifact digests verified. All seven checksums in
the image directory and every image payload's FIT CRC32/SHA1 passed.
The image manifest has 184 packages and `kmod-mt7996e` release `r5`.

Both new images contain the same corrected `mt7996e.ko`, SHA256
`e0d7a8339b1462a78703ae4d451e871d11381e328715ddab107a87f2c95fd13b`.
In `mt7996_remove_interface`, the first lock at `.text+0x953c` is followed by
the corresponding unlock at `.text+0x95bc`; the old second consecutive lock
is absent. Later locking at `.text+0x96a4` belongs to the inlined PHY-stop path,
not another consecutive acquisition of the already-held mutex. The function
size falls from 540 to 524 bytes. This confirms the fix reached both the
normal sysupgrade squashfs and the recovery initramfs.

The new sysupgrade SHA256 is
`dd0682294ff9969511342e0892b20e896e6db605cd235800a6ef74506716badc`.
The embedded DTB matches the earlier build byte-for-byte; network binaries,
startup links and device firmware are present in the sysupgrade filesystem.

### Second image audit: retained DNS/DHCP settings

The actual YYH release asset from
[`xr1710g_260831`](https://github.com/YYH2913/openwrt/releases/tag/xr1710g_260831)
was downloaded and checked against its published SHA256
`32499de4f30d1de6e72bb9f1c7310361e80dc1b60f3aaf4220032f178568eccd`.
Its embedded XR1710G DTB and every regular file under `/lib/firmware/` are
byte-for-byte identical to the candidate built at `6485d6a8ed`. The XR1710G
LAN/WAN definitions, network init script, default DHCP/firewall configuration
and preinit scripts also have identical contents. No physical-network driver
is missing from the candidate. Core network executables have their required
shared libraries. This does not establish successful driver initialization.

The package comparison exposed another real compatibility defect: YYH ships
`dnsmasq-full`, while the minimal device seed selected plain `dnsmasq`.
The actual init script exits before starting dnsmasq if retained UCI settings
request `dnssec=1` and the binary lacks DNSSEC. Such a configuration can lose
both DNS and DHCP. The owner's DNSSEC setting is unknown, and the factory
default does not enable DNSSEC, so this is not proof of the reset-boot failure.

Both actual AArch64 binaries were run with QEMU user-mode emulation, using
`--version` and `--test` only (no network service was started). Both report
version 2.93. The same DNSSEC configuration passes with YYH's binary and exits
1 with the candidate's binary because the option is unsupported. YYH also
has DHCPv6, nftset, conntrack and authoritative-DNS capabilities omitted from
the plain variant.

The build seed now explicitly selects `dnsmasq-full` and its YYH-equivalent
features, leaving ipset disabled as in that release. CI rejects the plain
variant and runs `xr1710g-dnsmasq-regression.py` against the built ARM binary
and its libraries. It checks a basic configuration and one containing DNSSEC,
DHCPv6, nftset and conntrack, and verifies the packaged trust anchors and
feature flags. This userspace test cannot validate hardware or live DHCP.

### Remaining hardware verification

The earlier firmware archive also contains the required Ethernet/Wi-Fi
packages, DHCP/DNS and LuCI. Its sysupgrade FIT is 15,238,068 bytes
(approximately 14.53 MiB), with a kernel, XR1710G DTB and squashfs rootfs.
The extracted squashfs includes `netifd`, `dnsmasq`, `uhttpd`, the MT7996/NPU
firmware, and enabled network, DHCP, Wi-Fi and web-service startup links.
The small compressed size alone does not indicate an incomplete firmware.
The XR1710G DTS and port definitions are unchanged from the YYH baseline.

The patched Airoha Ethernet/NPU, PCIe and pinctrl source was reconstructed
against Linux 6.18.44 (YYH baseline) and 6.18.54 (integration). That comparison
did not reveal a lost XR1710G board adaptation. It does not exclude additional
runtime issues. Ethernet links, DHCP, Wi-Fi, resets and AP-mode IPv6 still need
physical-device verification with the corrected candidate. No successful
hardware test of this candidate is claimed.
