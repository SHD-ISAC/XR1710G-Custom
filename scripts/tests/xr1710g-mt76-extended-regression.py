#!/usr/bin/env python3
"""Exercise prepared driver teardown and event-validation control flow.

Real C function bodies (or their validation prefixes) are compiled with
host-side stubs. This is not kernel, DMA, IRQ or physical-device testing.
"""
import argparse
import importlib.util
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location(
    "mt76_regression", Path(__file__).with_name("xr1710g-mt76-regression.py"))
legacy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(legacy)

NAPI_STUBS = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define ARRAY_SIZE(a) ((int)(sizeof(a) / sizeof((a)[0])))
#define BIT(n) (1UL << (n))
static bool test_bit(int n, unsigned long *v) { return !!(*v & BIT(n)); }
static inline bool test_and_set_bit(int n, unsigned long *v) {
    bool prev = test_bit(n, v); *v |= BIT(n); return prev;
}
static void set_bit(int n, unsigned long *v) { *v |= BIT(n); }
static void clear_bit(int n, unsigned long *v) { *v &= ~BIT(n); }
enum mt76_rxq_id { TEST_RX0 = 0 };
struct napi_struct { void *dev; bool enabled; int disable_count; };
struct page_pool { int qid; };
struct mt76_queue { int ndesc; struct page_pool *page_pool; };
struct mt76_phy { struct mt76_queue *q_tx[1]; };
struct mt76_dev {
    struct napi_struct napi[3], tx_napi;
    unsigned long napi_registered, napi_teardown_disabled;
    struct mt76_queue q_rx[3], *q_mcu[1];
    struct mt76_phy *phys[1];
    struct { int wed, wed_hif2; } mmio;
    void *dev, *napi_dev, *tx_napi_dev;
    int tx_worker, irq_tasklet;
};
struct mt7996_dev {
    struct mt76_dev mt76;
    int dump_work, reset_work, rc_work, phy;
    struct { int work; } wed_rro;
};
static struct mt76_dev *active;
static bool unregistered, stopped;
static void napi_disable(struct napi_struct *n) {
    if (!n->dev || !n->enabled) {
        fprintf(stderr, "duplicate or invalid napi_disable\n"); exit(70);
    }
    n->enabled = false; n->disable_count++;
}
static void napi_enable(struct napi_struct *n) { assert(!n->enabled); n->enabled = true; }
static void netif_napi_del(struct napi_struct *n) {
    assert(n->dev && !n->enabled); n->dev = NULL;
}
static void netif_napi_add(void *d, struct napi_struct *n,
                         int (*poll)(struct napi_struct *, int)) {
    assert(!n->dev); n->dev = (void *)1;
}
static void mt76_dma_rx_fill_buf(struct mt76_dev *d, struct mt76_queue *q, bool b) {}
static void mt76_worker_disable(int *w) {}
static void mt76_dma_tx_cleanup(struct mt76_dev *d, struct mt76_queue *q, bool b) {}
static void mt76_dma_rx_cleanup(struct mt76_dev *d, struct mt76_queue *q) {
    int id = q - d->q_rx; assert(!d->napi[id].enabled);
}
static void page_pool_destroy(struct page_pool *p) {
    assert(active->napi[p->qid].dev && !active->napi[p->qid].enabled);
}
static bool mtk_wed_device_active(int *w) { return false; }
static void mtk_wed_device_detach(int *w) {}
static void mt76_free_pending_txwi(struct mt76_dev *d) {}
static void mt76_free_pending_rxwi(struct mt76_dev *d) {}
static void free_netdev(void *d) {}
static void cancel_work_sync(int *w) {}
static int mt7996_npu_hw_stop_teardown(struct mt7996_dev *d) {
    assert(!unregistered); stopped = true; return 0;
}
#define dev_warn(...) ((void)0)
static int *mt7996_phy3(struct mt7996_dev *d) { return NULL; }
static int *mt7996_phy2(struct mt7996_dev *d) { return NULL; }
static void mt7996_unregister_phy(int *p) {}
static void mt7996_unregister_thermal(int *p) {}
static void mt7996_coredump_unregister(struct mt7996_dev *d) {}
static void mt76_unregister_device(struct mt76_dev *d) {
    assert(stopped); unregistered = true;
}
static void mt76_npu_rx_queues_deinit(struct mt76_dev *d) {
    if (!test_bit(2, &d->napi_registered)) return;
    napi_disable(&d->napi[2]);
    page_pool_destroy(d->q_rx[2].page_pool); d->q_rx[2].page_pool = NULL;
    netif_napi_del(&d->napi[2]); clear_bit(2, &d->napi_registered);
}
static void mt7996_wed_rro_free(struct mt7996_dev *d) {}
static void mt7996_mcu_exit(struct mt7996_dev *d) {
    for (int i = 0; i < ARRAY_SIZE(d->mt76.napi); i++)
        assert(!d->mt76.napi[i].enabled);
}
static void mt7996_tx_token_put(struct mt7996_dev *d) {}
static void mt76_dma_cleanup(struct mt76_dev *d);
static void mt7996_dma_cleanup(struct mt7996_dev *d) { mt76_dma_cleanup(&d->mt76); }
static bool mt7996_has_hwrro(struct mt7996_dev *d) { return false; }
static void mt7996_rro_msdu_page_map_free(struct mt7996_dev *d) {}
static void tasklet_disable(int *t) {}
static void mt76_free_device(struct mt76_dev *d) {
    assert(!d->napi_registered);
    for (int i = 0; i < ARRAY_SIZE(d->napi); i++) {
        assert(!d->napi[i].dev && !d->q_rx[i].page_pool);
    }
}
'''

NAPI_MAIN = r'''
int main(int argc, char **argv) {
    struct mt7996_dev d = {0};
    struct page_pool pools[3] = {{0}, {1}, {2}};
    assert(argc == 2); active = &d.mt76;
    active->tx_napi.dev = (void *)1; active->tx_napi.enabled = true;
    bool empty = !strcmp(argv[1], "napi-empty");
    bool direct = !strcmp(argv[1], "napi-direct");
    bool npu = !strcmp(argv[1], "napi-with-npu");
    bool reregister = !strcmp(argv[1], "napi-reregister");
    if (!empty) {
        active->q_rx[0].ndesc = 1; active->q_rx[0].page_pool = &pools[0];
        if (reregister) {
            active->napi_teardown_disabled = BIT(0);
            mt76_dma_rx_queue_init(active, TEST_RX0, NULL);
            assert(!test_bit(0, &active->napi_teardown_disabled));
        } else {
            active->napi[0].dev = (void *)1; active->napi[0].enabled = true;
            active->napi_registered = BIT(0);
        }
    }
    if (npu) {
        active->q_rx[2].ndesc = 1; active->q_rx[2].page_pool = &pools[2];
        active->napi[2].dev = (void *)1; active->napi[2].enabled = true;
        set_bit(2, &active->napi_registered);
    }
    if (direct || reregister) mt76_dma_cleanup(active);
    else mt7996_unregister_device(&d);
    mt76_free_device(active);
    assert(active->napi[0].disable_count == !empty);
    assert(active->napi[2].disable_count == npu);
    assert(active->tx_napi.disable_count == 1);
    assert(!active->napi_teardown_disabled);
    return 0;
}
'''

EVENT_STUBS = r'''
#include <assert.h>
#include <stdbool.h>
#include <errno.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
typedef uint8_t u8;
typedef uint16_t u16;
typedef uint32_t u32;
typedef uint16_t __le16;
typedef uint32_t __le32;
#define IEEE80211_NUM_ACS 4
#define __packed __attribute__((packed))
#define DECLARE_FLEX_ARRAY(type, name) struct { struct {} empty_ ## name; type name[]; }
#define le16_to_cpu(v) (v)
enum { UNI_ALL_STA_TXRX_RATE, UNI_ALL_STA_TXRX_ADM_STAT, UNI_ALL_STA_TXRX_MSDU_COUNT,
       UNI_ALL_STA_TXRX_AIR_TIME };
struct mt7996_dev { int unused; };
struct mt7996_mcu_rxd { u8 data[36]; };
struct sk_buff { unsigned char *data; size_t len; };
static int delivered = -1, freed;
static void *skb_pull(struct sk_buff *s, size_t len) {
    if (s->len < len) return NULL;
    s->data += len; s->len -= len; return s->data;
}
static void dev_kfree_skb(struct sk_buff *s) { freed++; }
'''

EVENT_MAIN = r'''
int main(int argc, char **argv) {
    unsigned char data[1024] = {0};
    struct mt7996_dev dev = {0};
    struct mt7996_mcu_all_sta_info_event *e =
        (void *)(data + sizeof(struct mt7996_mcu_rxd));
    struct sk_buff skb = {data, sizeof(struct mt7996_mcu_rxd) + sizeof(*e) +
                               2 * sizeof(e->airtime[0])};
    assert(argc == 2);
    if (!strncmp(argv[1], "per-", 4)) {
        skb.len = sizeof(struct mt7996_mcu_per_sta_info_event);
        bool short_reply = !strcmp(argv[1], "per-short");
        if (short_reply) skb.len--;
        assert(check_per_header(&skb) == (short_reply ? -EINVAL : 0));
        assert(freed == short_reply); return 0;
    }
    e->tag = UNI_ALL_STA_TXRX_AIR_TIME; e->sta_num = 2;
    int expected = 2;
    if (!strcmp(argv[1], "event-rxd-short")) { skb.len = 1; expected = -1; }
    if (!strcmp(argv[1], "event-header-short")) {
        skb.len = sizeof(struct mt7996_mcu_rxd) + sizeof(*e) - 1; expected = -1;
    }
    if (!strcmp(argv[1], "event-count-overflow")) { e->sta_num = 65535; expected = 2; }
    if (!strcmp(argv[1], "event-unknown-tag")) { e->tag = 65535; expected = -1; }
    mt7996_mcu_rx_all_sta_info_event(&dev, &skb);
    assert(delivered == expected); return 0;
}
'''


def declaration(source, name):
    start = source.index("struct " + name + " {")
    pos = source.index("{", start)
    depth = 0
    for end in range(pos, len(source)):
        depth += (source[end] == "{") - (source[end] == "}")
        if not depth:
            return source[start:source.index(";", end) + 1]
    raise RuntimeError("Missing declaration: " + name)


def run_suite(code, cases):
    with tempfile.TemporaryDirectory(prefix="xr1710g-mt76-extended-") as tmp:
        cfile, program = Path(tmp) / "test.c", Path(tmp) / "test"
        cfile.write_text(code)
        subprocess.run([os.environ.get("HOSTCC", "cc"), "-std=gnu11", "-O0",
                        "-Wall", "-Werror", str(cfile), "-o", str(program)], check=True)
        for case in cases:
            result = subprocess.run([str(program), case], timeout=3, capture_output=True, text=True)
            print(f"{'PASS' if result.returncode == 0 else 'FAIL'} {case}")
            if result.returncode:
                raise RuntimeError(case + ": " + result.stderr)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    root = parser.parse_args().source
    dma = (root / "dma.c").read_text()
    init = (root / "mt7996/init.c").read_text()
    functions = "\n".join([legacy.function(dma, "mt76_dma_rx_queue_init"),
                            legacy.function(dma, "mt76_dma_cleanup"),
                            legacy.function(init, "mt7996_unregister_device")])
    run_suite(NAPI_STUBS + functions + NAPI_MAIN,
              ["napi-normal", "napi-with-npu", "napi-empty", "napi-direct", "napi-reregister"])

    mcu = (root / "mt7996/mcu.c").read_text()
    header = (root / "mt7996/mcu.h").read_text()
    declarations = "\n".join(declaration(header, name) for name in
                              ["all_sta_trx_rate", "mt7996_mcu_all_sta_info_event",
                               "mt7996_mcu_per_sta_info_event"])
    event = legacy.function(mcu, "mt7996_mcu_rx_all_sta_info_event")
    loop = re.search(r"\n\s*for \(i = 0; i < sta_num; i\+\+\)", event)
    if not loop:
        raise RuntimeError("Review changed station-event validation")
    prefix = event[:loop.start()] + "\n(void)i; delivered = sta_num;\n}\n"
    per = legacy.function(mcu, "mt7996_mcu_get_per_sta_info")
    guard = re.search(r"if \(skb->len < sizeof\(\*res\)\) \{[^}]+\}", per)
    if not guard or guard.start() > per.index("resp_sta_num ="):
        raise RuntimeError("Local reply header must be checked before sta_num")
    per_check = "int check_per_header(struct sk_buff *skb) {\n" + \
                "struct mt7996_mcu_per_sta_info_event *res;\n" + guard[0] + "\nreturn 0;\n}\n"
    run_suite(EVENT_STUBS + declarations + prefix + per_check + EVENT_MAIN,
              ["event-valid", "event-rxd-short", "event-header-short", "event-count-overflow",
               "event-unknown-tag", "per-short", "per-valid"])


if __name__ == "__main__":
    main()
