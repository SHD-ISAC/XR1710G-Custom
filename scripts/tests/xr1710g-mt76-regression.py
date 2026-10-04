#!/usr/bin/env python3
"""Exercise real patched mt7996 functions with host-side hardware stubs.

This checks teardown locking and MLD allocation failure handling, not device
boot or radio operation. The C function bodies come from the prepared source.
"""
import argparse
import os
from pathlib import Path
import re
import subprocess
import tempfile


def function(source, name):
    match = re.search(r"(?:static\s+)?(?:void|int)\s+" + name + r"\s*\(", source)
    if not match:
        raise RuntimeError(f"Cannot find {name}; review the updated driver")
    start = source.index("{", match.end())
    depth = 0
    for pos in range(start, len(source)):
        depth += (source[pos] == "{") - (source[pos] == "}")
        if not depth:
            return source[match.start():pos + 1]
    raise RuntimeError(f"Unterminated function: {name}")


STUBS = r'''
#include <assert.h>
#include <errno.h>
#include <pthread.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef uint16_t u16;
typedef uint32_t u32;
#define IEEE80211_MLD_MAX_NUM_LINKS 16
#define MT7996_MAX_RADIOS 3
#define BIT(n) (1UL << (n))
#define BIT_ULL(n) (1ULL << (n))
#define for_each_set_bit(i, mask, count) \
    for ((i) = 0; (i) < (count); (i)++) if (*(mask) & BIT(i))
struct mt7996_phy { int unused; };
struct mt76_dev { pthread_mutex_t mutex; };
struct mt7996_dev {
    struct mt76_dev mt76;
    struct mt7996_phy *radio_phy[MT7996_MAX_RADIOS];
    uint64_t mld_idx_mask, mld_remap_idx_mask;
};
struct mt7996_vif {
    struct { unsigned long valid_links; } mt76;
    int mld_group_idx, mld_remap_idx;
};
struct mt7996_vif_link { struct { struct { int phy_idx; } wcid; } msta_link; };
struct ieee80211_hw { struct mt7996_dev *dev; };
struct ieee80211_vif { void *drv_priv; };
struct ieee80211_bss_conf { int unused; };
struct mt7996_radio_data { u32 active_mask, monitor_mask; };
static int locks, unlocks, cleanup_calls, destroyed;
static bool held, own_full, remap_full;
static struct mt7996_vif_link test_link;
static void mutex_lock(pthread_mutex_t *m) {
    int err = pthread_mutex_lock(m);
    if (err) {
        fprintf(stderr, "mutex_lock failed: %s\n", strerror(err));
        exit(70);
    }
    assert(!held);
    held = true;
    locks++;
}
static void mutex_unlock(pthread_mutex_t *m) {
    assert(held);
    held = false;
    unlocks++;
    assert(!pthread_mutex_unlock(m));
}
static struct mt7996_dev *mt7996_hw_dev(struct ieee80211_hw *hw) { return hw->dev; }
static struct mt7996_vif_link *mt7996_vif_link(struct mt7996_dev *d,
        struct ieee80211_vif *v, unsigned int id) { return &test_link; }
static struct mt7996_phy *__mt7996_phy(struct mt7996_dev *d, int id) {
    return d->radio_phy[id];
}
static void mt7996_vif_link_destroy(struct mt7996_phy *p,
        struct mt7996_vif_link *l, struct ieee80211_vif *v, void *sta) {
    assert(held);
    destroyed++;
}
static void mt7996_remove_iter(void) {}
static void ieee80211_iterate_active_interfaces_mtx(struct ieee80211_hw *h,
        int flags, void (*iter)(void), void *data) {}
static void mt76_vif_cleanup(struct mt76_dev *d, struct ieee80211_vif *v) {
    /* The real helper takes this mutex itself. */
    assert(!held);
    assert(!pthread_mutex_trylock(&d->mutex));
    assert(!pthread_mutex_unlock(&d->mutex));
    cleanup_calls++;
}
static void mt7996_set_monitor(struct mt7996_phy *p, bool enabled) {}
static void mt7996_stop_phy(struct mt7996_phy *p) {}
static int get_own_mld_idx(uint64_t mask, bool mld) { return own_full ? -1 : 3; }
static int get_free_idx(uint64_t mask, int min, int max) { return remap_full ? 0 : 4; }
'''

MAIN = r'''
int main(int argc, char **argv) {
    struct mt7996_dev dev = {0};
    struct mt7996_phy phy = {0};
    struct mt7996_vif mvif = { .mld_group_idx = 5 };
    struct ieee80211_vif vif = { .drv_priv = &mvif };
    struct ieee80211_hw hw = { .dev = &dev };
    pthread_mutexattr_t attr;
    assert(argc == 2);
    assert(!pthread_mutexattr_init(&attr));
    assert(!pthread_mutexattr_settype(&attr, PTHREAD_MUTEX_ERRORCHECK));
    assert(!pthread_mutex_init(&dev.mt76.mutex, &attr));
    if (!strncmp(argv[1], "teardown-", 9)) {
        bool active = !strcmp(argv[1], "teardown-active");
        dev.radio_phy[0] = &phy;
        mvif.mt76.valid_links = active ? 1 : 0;
        mt7996_remove_interface(&hw, &vif);
        assert(cleanup_calls == 1);
        assert(destroyed == (int)active);
        assert(locks == 1 && unlocks == 1 && !held);
    } else {
        dev.mld_idx_mask = BIT_ULL(5); /* Owned by another interface. */
        own_full = !strcmp(argv[1], "mld-full");
        remap_full = !strcmp(argv[1], "mld-remap-full");
        int ret = mt7996_change_vif_links(&hw, &vif, 0, 1, NULL);
        if (own_full || remap_full) {
            assert(ret == -ENOSPC);
            assert(dev.mld_idx_mask == BIT_ULL(5));
            assert(dev.mld_remap_idx_mask == 0);
        } else {
            assert(ret == 0);
            assert(dev.mld_idx_mask == (BIT_ULL(5) | BIT_ULL(3)));
            assert(dev.mld_remap_idx_mask == BIT_ULL(3));
            assert(!mt7996_change_vif_links(&hw, &vif, 1, 0, NULL));
            assert(dev.mld_idx_mask == BIT_ULL(5));
            assert(dev.mld_remap_idx_mask == 0);
        }
        assert(!held && locks == unlocks);
    }
    assert(!pthread_mutex_destroy(&dev.mt76.mutex));
    assert(!pthread_mutexattr_destroy(&attr));
    return 0;
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Prepared mt76 source directory")
    args = parser.parse_args()
    source = (args.source / "mt7996/main.c").read_text()
    bodies = "\n".join(function(source, name) for name in (
        "mt7996_remove_interface", "mt7996_change_vif_links"))
    failed = False
    with tempfile.TemporaryDirectory(prefix="xr1710g-mt76-test-") as tmp:
        cfile, binary = Path(tmp) / "regression.c", Path(tmp) / "regression"
        cfile.write_text(STUBS + bodies + MAIN)
        subprocess.run([os.environ.get("HOSTCC", "cc"), "-std=gnu11", "-O0",
                        "-Wall", "-Werror", "-pthread", str(cfile), "-o", str(binary)],
                       check=True)
        for case in ("teardown-empty", "teardown-active", "mld-full",
                     "mld-remap-full", "mld-success"):
            try:
                result = subprocess.run([str(binary), case], timeout=3,
                                        capture_output=True, text=True)
                ok = result.returncode == 0
                detail = result.stderr.strip()
            except subprocess.TimeoutExpired:
                ok, detail = False, "timed out (possible deadlock)"
            print(f"{'PASS' if ok else 'FAIL'} {case}" + (f": {detail}" if detail else ""))
            failed |= not ok
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
