#!/usr/bin/env python3
"""Compile prepared forward-path functions with controlled host-side devices.

Check the context API and separation between a stable Wi-Fi bridge egress
and the driver-specific WDMA lookup. These tests do not transmit packets.
"""
import argparse
import os
from pathlib import Path
import re
import subprocess
import tempfile


def function(source, name):
    match = re.search(r"(?m)^(?:static )?(?:int|bool)\s*\n?" + name + r"\(", source)
    if not match:
        raise RuntimeError(f"Cannot find prepared function {name}")
    start = source.index("{", match.end())
    depth = 1
    end = start + 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[match.start():end] + "\n"


STUBS = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
typedef unsigned char u8;
#define ETH_ALEN 6
#define NET_DEVICE_PATH_STACK_MAX 8
#define WARN_ON_ONCE(x) (x)
enum { DEV_PATH_ETHERNET, DEV_PATH_BRIDGE, DEV_PATH_IEEE80211, DEV_PATH_MTK_WDMA };
struct flow_keys { unsigned int sentinel; };
struct net_device;
struct net_device_path_ctx {
    const struct net_device *dev;
    const struct flow_keys *flow;
    u8 daddr[ETH_ALEN];
    bool ieee80211;
};
struct net_device_path {
    int type;
    const struct net_device *dev;
    struct { int wdma_idx, bss, wcid; } mtk_wdma;
};
struct net_device_path_stack { int num_paths; struct net_device_path path[8]; };
struct net_device_ops {
    int (*ndo_fill_forward_path)(struct net_device_path_ctx *, struct net_device_path *);
};
struct net_device { const struct net_device_ops *netdev_ops; int refs; };
struct airoha_ppe { int unused; };
struct airoha_foe_entry { int unused; };
struct airoha_flow_data { struct { u8 h_dest[6], h_source[6]; } eth; };
struct airoha_wdma_info { int idx, bss, wcid; };
struct ethhdr { u8 h_dest[6], h_source[6]; };
struct sk_buff { struct net_device *dev; struct ethhdr eth; };
static struct net_device bridge, ingress, wifi, wired;
static struct net_device *selected;
static bool master_present = true, path_error;
static int rcu_depth, driver_calls, prepare_calls;
static const u8 destination[6] = {2, 0, 0, 0, 0, 1};
static const u8 origin[6] = {2, 0, 0, 0, 0, 2};
static void ether_addr_copy(u8 *to, const u8 *from) { memcpy(to, from, 6); }
static bool is_valid_ether_addr(const u8 *a) {
    static const u8 zero[6]; return !(a[0] & 1) && memcmp(a, zero, 6);
}
static void rcu_read_lock(void) { assert(!rcu_depth); rcu_depth++; }
static void rcu_read_unlock(void) { assert(rcu_depth == 1); rcu_depth--; }
static void dev_hold(struct net_device *dev) { dev->refs++; }
static void dev_put(struct net_device *dev) { assert(dev->refs > 0); dev->refs--; }
static struct ethhdr *eth_hdr(struct sk_buff *skb) { return &skb->eth; }
static struct net_device *airoha_ppe_foe_get_bridge_master(struct net_device *dev) {
    assert(dev == &ingress);
    if (!master_present) return NULL;
    dev_hold(&bridge); return &bridge;
}
static bool airoha_ppe_foe_prepare_bridge_subflow_dev(struct airoha_ppe *ppe,
        struct net_device *dev, struct airoha_flow_data *data,
        struct airoha_foe_entry *hwe) {
    assert(!rcu_depth && dev == selected && dev != &ingress);
    assert(dev->refs == 1 && bridge.refs == 0);
    assert(!memcmp(data->eth.h_dest, destination, 6));
    assert(!memcmp(data->eth.h_source, origin, 6));
    prepare_calls++; return true;
}
static struct net_device_path *dev_fwd_path(struct net_device_path_stack *stack) {
    int k = stack->num_paths++;
    return k < NET_DEVICE_PATH_STACK_MAX ? &stack->path[k] : NULL;
}
'''

DEVICE_STUBS = r'''
    /* Driver-specific discovery is permitted only for the hardware lookup. */
    driver_calls++;
    path->type = DEV_PATH_MTK_WDMA; path->dev = ctx->dev;
    path->mtk_wdma.wdma_idx = 1; path->mtk_wdma.bss = 3; path->mtk_wdma.wcid = 42;
    ctx->dev = NULL;
    return 0;
}
static int bridge_path(struct net_device_path_ctx *ctx, struct net_device_path *path) {
    assert(rcu_depth == 1 && ctx->dev == &bridge);
    assert(!memcmp(ctx->daddr, destination, 6));
    if (path_error) return -ENOENT;
    path->type = DEV_PATH_BRIDGE; path->dev = ctx->dev;
    ctx->dev = selected; return 0;
}
static const struct net_device_ops bridge_ops = {bridge_path};
static const struct net_device_ops wifi_ops = {wifi_path};
static const struct net_device_ops wired_ops = {0};
'''

MAIN = r'''
int main(int argc, char **argv) {
    struct airoha_ppe ppe = {};
    struct airoha_foe_entry hwe = {};
    struct airoha_wdma_info wdma = {};
    struct sk_buff skb = {.dev = &ingress};
    assert(argc == 2);
    bridge.netdev_ops = &bridge_ops; wifi.netdev_ops = &wifi_ops;
    wired.netdev_ops = &wired_ops; selected = &wifi;
    memcpy(skb.eth.h_dest, destination, 6); memcpy(skb.eth.h_source, origin, 6);
    bool expected = true;
    if (!strcmp(argv[1], "bridge-wired")) selected = &wired;
    if (!strcmp(argv[1], "missing-master")) { master_present = false; expected = false; }
    if (!strcmp(argv[1], "path-error")) { path_error = true; expected = false; }
    if (!strcmp(argv[1], "invalid-address")) { skb.eth.h_dest[0] = 1; expected = false; }
    if (!strcmp(argv[1], "hardware-wdma")) {
        assert(!airoha_ppe_get_wdma_info(&wifi, destination, &wdma));
        assert(wdma.idx == 1 && wdma.bss == 3 && wdma.wcid == 42);
        assert(driver_calls == 1 && !prepare_calls);
    } else if (!strcmp(argv[1], "hardware-not-wifi")) {
        assert(airoha_ppe_get_wdma_info(&wired, destination, &wdma) == -EINVAL);
        assert(!driver_calls && !prepare_calls);
    } else {
        assert(airoha_ppe_foe_prepare_bridge_subflow(&ppe, &skb, &hwe) == expected);
        assert(prepare_calls == expected && !driver_calls);
    }
    assert(!rcu_depth && !bridge.refs && !wifi.refs && !wired.refs);
    return 0;
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kernel", type=Path, help="Prepared Linux source directory")
    args = parser.parse_args()
    core = (args.kernel / "net/core/dev.c").read_text()
    ppe = (args.kernel / "drivers/net/ethernet/airoha/airoha_ppe.c").read_text()
    iface = (args.kernel / "net/mac80211/iface.c").read_text()
    wifi = function(iface, "ieee80211_netdev_fill_forward_path")
    # Compile the real upstream early-return branch, before driver-specific lookup.
    branch = wifi[wifi.index("\tif (ctx->ieee80211)"):wifi.index("\n\tsdata =")]
    code = (STUBS + function(core, "dev_fill_forward_path") +
            "static int wifi_path(struct net_device_path_ctx *ctx, "
            "struct net_device_path *path) {\n" + branch + DEVICE_STUBS +
            function(ppe, "airoha_ppe_get_wdma_info") +
            function(ppe, "airoha_ppe_foe_prepare_bridge_subflow") + MAIN)
    cases = ["bridge-wifi", "bridge-wired", "missing-master", "path-error",
             "invalid-address", "hardware-wdma", "hardware-not-wifi"]
    with tempfile.TemporaryDirectory(prefix="xr1710g-forward-path-") as tmp:
        source, binary = Path(tmp) / "test.c", Path(tmp) / "test"
        source.write_text(code)
        subprocess.run([os.environ.get("HOSTCC", "cc"), "-std=gnu11", "-O0",
                        "-Wall", "-Werror", str(source), "-o", str(binary)], check=True)
        for case in cases:
            result = subprocess.run([str(binary), case], capture_output=True,
                                    text=True, timeout=3)
            print(f"{'PASS' if not result.returncode else 'FAIL'} {case}", flush=True)
            if result.returncode:
                raise RuntimeError(result.stderr.strip())


if __name__ == "__main__":
    main()
