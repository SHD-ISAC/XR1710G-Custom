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

The `mt7996e.ko` module extracted from the old CI recovery image confirms that
the faulty code was shipped. Its `mt7996_remove_interface` symbol starts at
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

The earlier firmware archive also contains the required Ethernet/Wi-Fi
packages, DHCP/DNS and LuCI. Its sysupgrade FIT is 15,238,068 bytes
(approximately 14.53 MiB), with a kernel, XR1710G DTB and squashfs rootfs.
The small compressed size alone does not indicate an incomplete firmware.
The XR1710G DTS and port definitions are unchanged from the YYH baseline.

The patched Airoha Ethernet/NPU, PCIe and pinctrl source was reconstructed
against Linux 6.18.44 (YYH baseline) and 6.18.54 (integration). That comparison
did not reveal a lost XR1710G board adaptation. It does not exclude additional
runtime issues. Ethernet links, DHCP, Wi-Fi, resets and AP-mode IPv6 still need
physical-device verification after the corrected build succeeds.
