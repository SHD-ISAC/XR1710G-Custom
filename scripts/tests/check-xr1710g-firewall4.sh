#!/usr/bin/env bash
# Check the package patch stack against firewall4's pinned source.
set -euo pipefail
repo_root=$(cd "$(dirname "$0")/../.." && pwd)
package="$repo_root/package/network/config/firewall4"
source_date=$(sed -n 's/^PKG_SOURCE_DATE:=//p' "$package/Makefile")
source_commit=$(sed -n 's/^PKG_SOURCE_VERSION:=//p' "$package/Makefile")
source_hash=$(sed -n 's/^PKG_MIRROR_HASH:=//p' "$package/Makefile")
source_name="firewall4-${source_date//-/.}~${source_commit:0:8}"
archive="${1:-$repo_root/dl/$source_name.tar.zst}"

check_tmp=$(mktemp -d -t xr1710g-firewall4.XXXXXXXX)
trap 'rm -rf "$check_tmp"' EXIT
printf '%s  %s\n' "$source_hash" "$archive" | sha256sum --check
tar --zstd -xf "$archive" -C "$check_tmp"
PATCH='patch --fuzz=0' "$repo_root/scripts/patch-kernel.sh" \
    "$check_tmp/$source_name" "$package/patches"
