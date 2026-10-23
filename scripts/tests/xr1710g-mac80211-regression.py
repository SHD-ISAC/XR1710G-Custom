#!/usr/bin/env python3
"""Exercise prepared mac80211 management-frame link selection with host stubs.

Compile the real channel-selection block from ieee80211_mgmt_tx(). This
checks link/channel decisions, not radio transmission or physical hardware.
"""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile


STUBS = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
#define BIT(n) (1UL << (n))
#define ARRAY_SIZE(a) (sizeof(a) / sizeof((a)[0]))
#define rcu_dereference(p) (p)
enum { NL80211_IFTYPE_AP, NL80211_IFTYPE_STATION,
       NL80211_IFTYPE_NAN, NL80211_IFTYPE_NAN_DATA };
struct channel { int number; };
struct ieee80211_chanctx_conf { struct { struct channel *chan; } def; };
struct ieee80211_bss_conf {
    unsigned char addr[6];
    struct ieee80211_chanctx_conf *chanctx_conf;
};
struct ieee80211_vif {
    unsigned char addr[6];
    unsigned long active_links, valid_links;
    int type;
    struct ieee80211_bss_conf *link_conf[16];
};
struct ieee80211_sub_if_data { struct ieee80211_vif vif; };
struct ieee80211_mgmt { unsigned char sa[6]; };
struct params { struct channel *chan; int link_id; };
struct result { int link_id; bool need_offchan; };
static int rcu_depth;
static void rcu_read_lock(void) { assert(!rcu_depth); rcu_depth++; }
static void rcu_read_unlock(void) { assert(rcu_depth == 1); rcu_depth--; }
static bool ether_addr_equal(const unsigned char *a, const unsigned char *b) {
    return !memcmp(a, b, 6);
}
static struct result select_link(struct ieee80211_sub_if_data *sdata,
                                 struct ieee80211_mgmt *mgmt,
                                 struct params *params, bool mlo_sta,
                                 bool need_offchan) {
    int link_id = -1;
'''

MAIN = r'''
    assert(!rcu_depth);
    return (struct result){link_id, need_offchan};
}
int main(int argc, char **argv) {
    const unsigned char mld[6] = {2, 0, 0, 0, 0, 1};
    const unsigned char link[6] = {2, 0, 0, 0, 0, 2};
    struct channel channels[3] = {{6}, {36}, {149}};
    struct ieee80211_chanctx_conf ctx[2] = {{{&channels[0]}}, {{&channels[1]}}};
    struct ieee80211_bss_conf conf[2] = {0};
    struct ieee80211_sub_if_data sdata = {0};
    struct ieee80211_mgmt mgmt;
    struct params p = {&channels[1], -1};
    int expected_link = 1;
    bool expected_offchan = false, known = true, offchan = false;
    assert(argc == 2);
    memcpy(sdata.vif.addr, mld, 6);
    memcpy(conf[0].addr, mld, 6); /* Lower link shares the MLD address. */
    memcpy(conf[1].addr, link, 6);
    memcpy(mgmt.sa, mld, 6);
    for (int i = 0; i < 2; i++) {
        conf[i].chanctx_conf = &ctx[i]; sdata.vif.link_conf[i] = &conf[i];
    }
    sdata.vif.type = NL80211_IFTYPE_AP;
    sdata.vif.active_links = sdata.vif.valid_links = BIT(0) | BIT(1);
    if (!strcmp(argv[1], "mld-unknown-peer")) known = false;
    if (!strcmp(argv[1], "station-mld-unknown-peer")) {
        sdata.vif.type = NL80211_IFTYPE_STATION; known = false;
    }
    if (!strcmp(argv[1], "link-source-address")) {
        memcpy(mgmt.sa, link, 6); p.link_id = 1;
    }
    if (!strcmp(argv[1], "single-link")) {
        sdata.vif.active_links = sdata.vif.valid_links = 0;
        sdata.vif.link_conf[1] = NULL; p.chan = &channels[0];
        expected_link = -1; known = false;
    }
    if (!strcmp(argv[1], "missing-channel")) {
        p.chan = &channels[2]; expected_link = -1; expected_offchan = true;
    }
    if (!strcmp(argv[1], "no-channel")) { p.chan = NULL; expected_link = -1; }
    if (!strcmp(argv[1], "forced-offchannel")) {
        offchan = expected_offchan = true; expected_link = -1;
    }
    if (!strcmp(argv[1], "nan-schedule") || !strcmp(argv[1], "nan-data-schedule")) {
        sdata.vif.type = !strcmp(argv[1], "nan-schedule") ?
                         NL80211_IFTYPE_NAN : NL80211_IFTYPE_NAN_DATA;
        expected_link = -1;
    }
    struct result result = select_link(&sdata, &mgmt, &p, known, offchan);
    if (result.link_id != expected_link || result.need_offchan != expected_offchan) {
        fprintf(stderr, "link=%d offchannel=%d; expected link=%d offchannel=%d\n",
                result.link_id, result.need_offchan, expected_link, expected_offchan);
        return 1;
    }
    return 0;
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Prepared mac80211 source directory")
    args = parser.parse_args()
    source = (args.source / "net/mac80211/offchannel.c").read_text()
    start = source.index("\t/* Check if the operating channel is the requested channel */")
    end = source.index("\n\tif (need_offchan && !params->offchan)", start)
    block = source[start:end]
    cases = ["mld-known-peer", "mld-unknown-peer", "station-mld-unknown-peer",
             "link-source-address", "single-link", "missing-channel", "no-channel",
             "forced-offchannel", "nan-schedule", "nan-data-schedule"]
    with tempfile.TemporaryDirectory(prefix="xr1710g-mac80211-regression-") as tmp:
        cfile, binary = Path(tmp) / "test.c", Path(tmp) / "test"
        cfile.write_text(STUBS + block + MAIN)
        subprocess.run([os.environ.get("HOSTCC", "cc"), "-std=gnu11", "-O0",
                        "-Wall", "-Werror", str(cfile), "-o", str(binary)], check=True)
        for case in cases:
            result = subprocess.run([str(binary), case], capture_output=True,
                                    text=True, timeout=3)
            print(f"{'PASS' if result.returncode == 0 else 'FAIL'} {case}", flush=True)
            if result.returncode:
                raise RuntimeError(result.stderr.strip())


if __name__ == "__main__":
    main()
