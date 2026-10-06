#!/usr/bin/env python3
"""Check the built ARM dnsmasq without starting a DNS/DHCP service.

Run with qemu-aarch64 and the built or extracted XR1710G root filesystem.
This checks userspace configuration compatibility, not packet delivery or
physical-device boot. --test only parses configuration and exits.
"""
import argparse
from pathlib import Path
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rootfs", type=Path)
    parser.add_argument("--qemu", default="qemu-aarch64")
    args = parser.parse_args()
    root = args.rootfs.resolve()
    binary = root / "usr/sbin/dnsmasq"
    command = [args.qemu, "-L", str(root), str(binary)]

    def run(*options):
        result = subprocess.run(command + list(options), capture_output=True,
                                text=True, timeout=20)
        if result.returncode:
            raise RuntimeError(f"dnsmasq exited {result.returncode}: "
                               f"{result.stdout}{result.stderr}")
        return result.stdout + result.stderr

    version = run("--version")
    options = next(line.partition(":")[2].split() for line in version.splitlines()
                   if line.startswith("Compile time options:"))
    print("Built dnsmasq features:", " ".join(options), flush=True)

    with tempfile.TemporaryDirectory(prefix="xr1710g-dnsmasq-") as tmp:
        config = Path(tmp) / "dnsmasq.conf"
        basic = "domain-needed\nbogus-priv\ndhcp-range=192.0.2.100,192.0.2.150,255.255.255.0,12h\n"
        config.write_text(basic)
        run("--test", f"--conf-file={config}")
        print("PASS: basic DNS/DHCP configuration", flush=True)

        # Use the trust anchors actually installed by dnsmasq-full. A plain
        # dnsmasq image lacks this file as well as the DNSSEC feature.
        anchors = root / "usr/share/dnsmasq/trust-anchors.conf"
        if not anchors.is_file():
            raise RuntimeError("missing packaged DNSSEC trust anchors")
        config.write_text(basic + anchors.read_text() + "\n"
                          "dnssec\n"
                          "dhcp-range=fd00::100,fd00::150,64,12h\n"
                          "nftset=/example.invalid/4#inet#fw4#xr1710g_test\n"
                          "conntrack\n")
        run("--test", f"--conf-file={config}")
        print("PASS: DNSSEC/DHCPv6/nftset/conntrack configuration", flush=True)

    required = {"IPv6", "DHCP", "DHCPv6", "DNSSEC", "nftset", "conntrack", "auth", "TFTP"}
    missing = required - set(options)
    if missing:
        raise RuntimeError("missing YYH-compatible features: " + ", ".join(sorted(missing)))
    print("PASS: required YYH DNS/DHCP capabilities retained", flush=True)


if __name__ == "__main__":
    main()
