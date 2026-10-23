#!/usr/bin/env python3
"""Apply mac80211's complete Build/Patch sequence to its verified archive.

Use the firmware build's patch order with stricter zero-fuzz matching.
This catches preparation conflicts, including patches for unselected drivers;
the firmware workflow separately compiles the selected target modules.
"""
import argparse
import hashlib
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile


def main():
    repo = Path(__file__).resolve().parents[2]
    package = repo / "package/kernel/mac80211"
    makefile = (package / "Makefile").read_text()

    def value(name):
        return re.search(r"^" + name + r":=(\S+)$", makefile, re.M)[1]

    name = "backports-" + value("PKG_SOURCE_VERSION")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", nargs="?", type=Path,
                        default=repo / "dl" / (name + ".tar.zst"))
    args = parser.parse_args()
    archive = args.archive.resolve()
    with archive.open("rb") as stream:
        actual_hash = hashlib.file_digest(stream, "sha256").hexdigest()
    if actual_hash != value("PKG_HASH"):
        raise RuntimeError("mac80211 source archive hash mismatch")
    print("PASS: pinned mac80211 archive SHA256", flush=True)

    block = makefile.split("define Build/Patch\n", 1)[1].split("\nendef", 1)[0]
    folders = re.findall(
        r"\$\(call PatchDir,\$\(PKG_BUILD_DIR\),\$\(PATCH_DIR\)/([a-z0-9]+),\1/\)",
        block)
    if (folders[:2] != ["build", "subsys"] or
            len(folders) != block.count("$(call PatchDir,")):
        raise RuntimeError("Review the changed mac80211 Build/Patch sequence")

    count = 0
    with tempfile.TemporaryDirectory(prefix="xr1710g-mac80211-") as tmp:
        subprocess.run(["tar", "--zstd", "-xf", str(archive), "-C", tmp], check=True)
        source = Path(tmp) / name
        for folder in folders:
            patches = package / "patches" / folder
            count += len(list(patches.glob("*.patch")))
            subprocess.run(["sh", str(repo / "scripts/patch-kernel.sh"),
                            str(source), str(patches)], cwd=repo,
                           env={**os.environ, "LC_ALL": "C", "PATCH": "patch --fuzz=0"},
                           check=True)
        print(f"PASS: complete mac80211 patch stack ({count} patches, "
              f"{len(folders)} directories)", flush=True)
        subprocess.run([sys.executable,
                        str(repo / "scripts/tests/xr1710g-mac80211-regression.py"),
                        str(source)], check=True)


if __name__ == "__main__":
    main()
