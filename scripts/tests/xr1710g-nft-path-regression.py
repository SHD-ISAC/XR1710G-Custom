#!/usr/bin/env python3
"""Exercise the prepared Netfilter bridge path and its failure cleanup."""
import argparse
import os
from pathlib import Path
import re
import subprocess
import tempfile


def function(source, name):
    match = re.search(r"(?m)^static int " + name + r"\(", source)
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
#include <errno.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
typedef uint8_t u8;
typedef uint16_t __u16, __be16;
#define ETH_ALEN 6
#define NF_FLOW_TABLE_ENCAP_MAX 2
#define BIT(n) (1U << (n))
#define CTINFO2DIR(info) ((info) & 1)
#define NFCT_INFOMASK 7
#define BROPT_VLAN_ENABLED 0
enum ip_conntrack_dir { ORIGINAL, REPLY };
enum flow_offload_xmit_type {
    FLOW_OFFLOAD_XMIT_NEIGH, FLOW_OFFLOAD_XMIT_DIRECT, FLOW_OFFLOAD_XMIT_XFRM,
};
enum {
    DEV_PATH_ETHERNET, DEV_PATH_IEEE80211, DEV_PATH_DSA, DEV_PATH_VLAN,
    DEV_PATH_LAG, DEV_PATH_PPPOE, DEV_PATH_BRIDGE, DEV_PATH_MTK_WDMA,
};
enum { DEV_PATH_BR_VLAN_KEEP, DEV_PATH_BR_VLAN_TAG, DEV_PATH_BR_VLAN_UNTAG,
       DEV_PATH_BR_VLAN_UNTAG_HW };
struct net_device { int ifindex; u8 dev_addr[ETH_ALEN]; };
struct dst_entry { const struct net_device *dev; int refs; };
struct nf_flow_route {
    struct {
        struct dst_entry *dst;
        enum flow_offload_xmit_type xmit_type;
        struct {
            int ifindex, hw_ifindex, bridge_path, bridge_vlan, port_vlans;
            u8 h_source[ETH_ALEN], h_dest[ETH_ALEN];
        } out;
        struct {
            int ifindex, num_encaps, ingress_vlans;
            struct { __u16 id; __be16 proto; } encap[NF_FLOW_TABLE_ENCAP_MAX];
        } in;
    } tuple[2];
};
struct flow_keys { int dir; };
struct nf_conn { int unused; };
struct nf_flowtable { bool hardware; };
struct nft_flowtable { struct nf_flowtable data; };
struct net_device_path_ctx {
    const struct net_device *dev;
    const struct flow_keys *flow;
    bool ieee80211;
};
struct net_device_path {
    const struct net_device *dev;
    int type;
    struct { __u16 id; __be16 proto; u8 h_dest[ETH_ALEN]; } encap;
    struct { int vlan_mode; __u16 vlan_id; __be16 vlan_proto; } bridge;
};
struct net_device_path_stack { int num_paths; struct net_device_path path[8]; };
struct ethhdr { u8 h_source[ETH_ALEN], h_dest[ETH_ALEN]; };
struct sk_buff {
    struct net_device *dev;
    struct ethhdr eth;
    bool bridging, tagged;
    __be16 vlan_proto;
};
struct nft_pktinfo { struct sk_buff *skb; struct net_device *in, *out; };
struct net_bridge_port { void *br; };
static struct net_bridge_port bridge_port;
static struct net_device ports[2] = {{10, {2, 0, 0, 0, 0, 10}},
                                     {11, {2, 0, 0, 0, 0, 11}}};
static struct dst_entry destinations[2] = {{&ports[0], 0}, {&ports[1], 0}};
static int attempts[2], rcu_depth;
static int missing_path = -1, unknown_path = -1, unregistered = -1;
static bool overflow, nested, missing_reply, xfrm_reply;
static struct net_device *nft_in(const struct nft_pktinfo *pkt) { return pkt->in; }
static struct net_device *nft_out(const struct nft_pktinfo *pkt) { return pkt->out; }
static int nft_flow_route_dir(const struct nft_pktinfo *pkt, const struct nf_conn *ct,
        struct nf_flow_route *route, enum ip_conntrack_dir dir, int ifindex) {
    assert(ifindex == ports[dir].ifindex);
    if (dir == REPLY && missing_reply)
        return -ENOENT;
    destinations[dir].refs++;
    route->tuple[dir].dst = &destinations[dir];
    route->tuple[dir].xmit_type = dir == REPLY && xfrm_reply ?
            FLOW_OFFLOAD_XMIT_XFRM : FLOW_OFFLOAD_XMIT_NEIGH;
    return 0;
}
static void dst_release(struct dst_entry *dst) { assert(dst->refs-- == 1); }
static void rcu_read_lock(void) { assert(!rcu_depth++); }
static void rcu_read_unlock(void) { assert(rcu_depth-- == 1); }
static struct net_bridge_port *br_port_get_rcu(struct net_device *dev) {
    assert(rcu_depth); return &bridge_port;
}
static bool br_opt_get(void *br, int option) { return false; }
static bool skb_vlan_tag_present(const struct sk_buff *skb) { return skb->tagged; }
static __u16 skb_vlan_tag_get_id(const struct sk_buff *skb) { return 37; }
static bool is_zero_ether_addr(const u8 *addr) {
    static const u8 zero[ETH_ALEN]; return !memcmp(addr, zero, ETH_ALEN);
}
static bool nft_is_valid_ether_device(const struct net_device *dev) { return !!dev; }
static bool nf_flowtable_hw_offload(const struct nf_flowtable *ft) { return ft->hardware; }
static bool nft_flow_offload_is_bridging(struct sk_buff *skb) { return skb->bridging; }
static struct ethhdr *eth_hdr(struct sk_buff *skb) { return &skb->eth; }
static int skb_get_nfct(const struct sk_buff *skb) { return ORIGINAL; }
static void nft_flow_keys_init(const struct nf_conn *ct, enum ip_conntrack_dir dir,
        struct flow_keys *flow) { flow->dir = dir; }
static void nft_br_vlan_dev_fill_forward_path(const struct nft_pktinfo *pkt,
        struct net_device_path_ctx *ctx) {}
static bool nft_flowtable_find_dev(const struct net_device *dev,
        struct nft_flowtable *ft) { return dev->ifindex != unregistered; }
static int nft_dev_fill_forward_path(struct net_device_path_ctx *ctx,
        const struct nf_flow_route *route, const struct dst_entry *dst,
        const struct nf_conn *ct, enum ip_conntrack_dir dir, u8 *ha,
        struct net_device_path_stack *stack) {
    const struct net_device *dev = dst->dev;
    const struct net_device_path vlan = {dev, DEV_PATH_VLAN, {37, 0x8100, {0}}};
    assert(ctx->dev == dev && ctx->ieee80211 && ctx->flow->dir == (int)dir);
    attempts[dir]++;
    if ((int)dir == missing_path)
        return -ENOENT;
    if (is_zero_ether_addr(ha))
        memcpy(ha, dev->dev_addr, ETH_ALEN);
    stack->num_paths = 0;
    stack->path[stack->num_paths++] = (struct net_device_path){dev, DEV_PATH_BRIDGE};
    if (overflow) {
        stack->path[stack->num_paths++] = vlan;
        stack->path[stack->num_paths++] = vlan;
    }
    if (nested) {
        stack->path[stack->num_paths++] = vlan;
        stack->path[stack->num_paths++] = (struct net_device_path){
            .dev = dev, .type = DEV_PATH_BRIDGE,
            .bridge = {DEV_PATH_BR_VLAN_KEEP, 37, 0x8100}
        };
    }
    stack->path[stack->num_paths++] = (struct net_device_path){
        dev, (int)dir == unknown_path ? -1 : DEV_PATH_IEEE80211
    };
    return 0;
}
'''

MAIN = r'''
int main(int argc, char **argv) {
    struct nf_flow_route route = {};
    struct sk_buff skb = {.dev = &ports[1], .bridging = true,
                          .tagged = true, .vlan_proto = 0x8100};
    struct nft_pktinfo pkt = {&skb, &ports[1], &ports[0]};
    struct nft_flowtable ft = {.data.hardware = true};
    struct nf_conn ct = {};
    assert(argc == 2);
    memcpy(skb.eth.h_dest, ports[0].dev_addr, ETH_ALEN);
    memcpy(skb.eth.h_source, ports[1].dev_addr, ETH_ALEN);
    if (!strcmp(argv[1], "missing-neighbour")) missing_path = ORIGINAL;
    if (!strcmp(argv[1], "unknown-reply-path")) unknown_path = REPLY;
    if (!strcmp(argv[1], "unregistered-reply-egress")) unregistered = ports[1].ifindex;
    if (!strcmp(argv[1], "too-many-vlans")) overflow = true;
    if (!strcmp(argv[1], "nested-bridge-vlans")) { nested = true; skb.tagged = false; }
    if (!strcmp(argv[1], "missing-reply-route")) missing_reply = true;
    if (!strcmp(argv[1], "mixed-xfrm-bridge")) xfrm_reply = true;
    if (!strcmp(argv[1], "preserve-routed-xfrm")) {
        skb.bridging = skb.tagged = false;
        route.tuple[ORIGINAL].dst = &destinations[ORIGINAL];
        route.tuple[ORIGINAL].xmit_type = FLOW_OFFLOAD_XMIT_XFRM;
        assert(!nft_dev_forward_path(&pkt, &route, &ct, ORIGINAL, &ft));
        assert(route.tuple[ORIGINAL].out.hw_ifindex == ports[ORIGINAL].ifindex);
        assert(route.tuple[ORIGINAL].xmit_type == FLOW_OFFLOAD_XMIT_XFRM);
        return 0;
    }
    int result = nft_flow_route_bridging(&pkt, &ct, &route, ORIGINAL, &ft);
    if (missing_path >= 0 || overflow || missing_reply || xfrm_reply ||
        unknown_path >= 0 || unregistered >= 0) {
        assert(result == -ENOENT && !destinations[0].refs && !destinations[1].refs);
        assert(attempts[0] == !(missing_reply || xfrm_reply));
        assert(attempts[1] == (unknown_path >= 0 || unregistered >= 0));
        assert(!route.tuple[1].out.ifindex);
    } else {
        assert(!result && attempts[0] == 1 && attempts[1] == 1);
        for (int i = 0; i < 2; i++) {
            assert(destinations[i].refs == 1);
            assert(route.tuple[i].out.hw_ifindex == ports[i].ifindex);
            assert(!memcmp(route.tuple[i].out.h_dest, ports[i].dev_addr, ETH_ALEN));
            assert(route.tuple[i].xmit_type == FLOW_OFFLOAD_XMIT_DIRECT);
            assert(route.tuple[!i].in.num_encaps == 1);
            assert(route.tuple[!i].in.encap[0].id == 37);
            assert(route.tuple[i].out.bridge_path);
            assert(route.tuple[i].out.bridge_vlan == nested);
            assert(!route.tuple[i].out.port_vlans);
        }
    }
    assert(!rcu_depth);
    return 0;
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kernel", type=Path, help="Prepared Linux source directory")
    args = parser.parse_args()
    source = (args.kernel / "net/netfilter/nf_flow_table_path.c").read_text()
    info = re.search(r"(?ms)^struct nft_forward_info \{.*?^\};", source)[0]
    names = ("nft_fill_vlan_passthrough_info", "nft_dev_path_info",
             "nft_dev_forward_path", "nft_flow_route_bridging")
    code = STUBS + info + "\n" + "".join(function(source, name) for name in names) + MAIN
    cases = ("tagged-bridge", "missing-neighbour", "unknown-reply-path",
             "unregistered-reply-egress", "too-many-vlans", "missing-reply-route",
             "mixed-xfrm-bridge", "preserve-routed-xfrm", "nested-bridge-vlans")
    with tempfile.TemporaryDirectory(prefix="xr1710g-nft-path-") as tmp:
        cfile, binary = Path(tmp) / "test.c", Path(tmp) / "test"
        cfile.write_text(code)
        subprocess.run([os.environ.get("HOSTCC", "cc"), "-std=gnu11", "-O0",
                        "-Wall", "-Werror", str(cfile), "-o", str(binary)], check=True)
        for case in cases:
            result = subprocess.run([str(binary), case], timeout=3, capture_output=True, text=True)
            print(f"{'PASS' if not result.returncode else 'FAIL'} {case}", flush=True)
            if result.returncode:
                raise RuntimeError(result.stderr.strip())


if __name__ == "__main__":
    main()
