#!/usr/bin/env bash
# Validate the complete patch stack against the pinned, downloaded mt76 source.
set -euo pipefail
repo_root=$(cd "$(dirname "$0")/../.." && pwd)
check_tmp=$(mktemp -d -t xr1710g-mt76.XXXXXXXX)
trap 'rm -rf "$check_tmp"' EXIT
cd "$repo_root"
if [ "$#" -eq 1 ]; then
    # Optional pristine source tree for local review; never modify it in place.
    cp -a "$1" "$check_tmp/source"
else
    source_date=$(sed -n 's/^PKG_SOURCE_DATE:=//p' package/kernel/mt76/Makefile)
    source_commit=$(sed -n 's/^PKG_SOURCE_VERSION:=//p' package/kernel/mt76/Makefile)
    source_name="mt76-${source_date}~${source_commit:0:8}"
    source_hash=$(sed -n 's/^PKG_MIRROR_HASH:=//p' package/kernel/mt76/Makefile)
    archive="$repo_root/dl/$source_name.tar.zst"
    printf '%s  %s\n' "$source_hash" "$archive" | sha256sum --check
    tar --zstd -xf "$archive" -C "$check_tmp"
    mv "$check_tmp/$source_name" "$check_tmp/source"
fi
PATCH='patch --fuzz=0' ./scripts/patch-kernel.sh \
    "$check_tmp/source" "$repo_root/package/kernel/mt76/patches"
python3 scripts/tests/xr1710g-mt76-regression.py "$check_tmp/source"
