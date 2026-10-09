#!/usr/bin/env python3
"""Run the real collector/FIFO helpers with fault-injected SPI/user copies.

Requires a native C compiler. Kernel scheduling/electrical timing is checked
separately on the device; this checks ownership, bounded draining and loss
accounting, including queue wraparound and a failed user copy.
"""
import os
from pathlib import Path
import re
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
source = (root / "src/fmcs_main.c").read_text()
header = (root / "src/fmcs.h").read_text()


def function(name):
    start = re.search(r"static (?:int|void|unsigned int) " + name + r"\(", source).start()
    opening = source.index("{", start)
    depth, end = 1, opening + 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end]


fixture = r"""
#include <assert.h>
#include <errno.h>
#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
typedef uint32_t u32;
typedef uint64_t u64;
#define __user
#define atomic_read(p) (*(p))
struct fmcs_ploam_msg { unsigned char data[16]; u32 len; };
struct fmcs_priv {
    int ploam_rx_lock, fpga_status;
    struct fmcs_ploam_msg ploam_rx_queue[FMCS_PLOAM_RX_DEPTH];
    u32 ploam_rx_head, ploam_rx_count;
    u64 rx_received, rx_enqueued, rx_dequeued, rx_dropped, rx_flushed;
    u64 rx_empty, rx_errors, rx_copy_faults, rx_budget_hits, rx_irqs;
    u32 rx_last_events;
};
static int copy_fault, spi_fault, frames, reads, deliveries;
static u32 events;
static void mutex_lock(int *p) { assert(!*p); *p = 1; }
static void mutex_unlock(int *p) { assert(*p); *p = 0; }
static int copy_to_user(void *dest, const void *src, size_t len) {
    if (copy_fault) return 1;
    memcpy(dest, src, len); return 0;
}
static int fmcs_spi_read_fpga_reg(struct fmcs_priv *p, u32 addr, u32 *v) {
    assert(p->ploam_rx_lock && addr == 0xb0);
    *v = events; return spi_fault;
}
static int fmcs_spi_recv_ploam(struct fmcs_priv *p, unsigned char *data, size_t *len) {
    assert(p->ploam_rx_lock); reads++;
    if (spi_fault) return spi_fault;
    if (frames) { data[0] = frames--; data[1] = 1; *len = 13; }
    else *len = 0;
    return 0;
}
static void fmcs_rx_ploam_frame(struct fmcs_priv *p, const unsigned char *d, size_t len) {
    assert(p->ploam_rx_lock && d[1] == 1 && len == 13); deliveries++;
}
"""
checks = r"""
static void accounting(struct fmcs_priv *p) {
    assert(p->rx_received == p->rx_enqueued + p->rx_dropped);
    assert(p->rx_enqueued == p->rx_dequeued + p->rx_flushed + p->ploam_rx_count);
    assert(p->ploam_rx_count <= FMCS_PLOAM_RX_DEPTH);
}
int main(void) {
    struct fmcs_priv p = { .fpga_status = 2 };
    struct fmcs_ploam_msg msg = { .len = 13 }, out;
    for (u32 i = 0; i < 4096; i++) {
        memcpy(msg.data, &i, sizeof(i));
        fmcs_ploam_enqueue_locked(&p, &msg);
        assert(!fmcs_ploam_dequeue(&p, &out));
        assert(out.len == 13 && !memcmp(out.data, &i, sizeof(i)));
        accounting(&p);
    }
    for (u32 i = 0; i <= FMCS_PLOAM_RX_DEPTH; i++) {
        memcpy(msg.data, &i, sizeof(i)); fmcs_ploam_enqueue_locked(&p, &msg);
    }
    assert(p.rx_dropped == 1);
    copy_fault = 1;
    assert(fmcs_ploam_dequeue(&p, &out) == -EFAULT);
    assert(p.ploam_rx_count == FMCS_PLOAM_RX_DEPTH && p.rx_copy_faults == 1);
    copy_fault = 0;
    for (u32 i = 0; i < FMCS_PLOAM_RX_DEPTH; i++) {
        assert(!fmcs_ploam_dequeue(&p, &out));
        assert(!memcmp(out.data, &i, sizeof(i)));
    }
    memset(&out, 0xff, sizeof(out));
    assert(!fmcs_ploam_dequeue(&p, &out));
    assert(!out.len && !out.data[0] && !out.data[15]);
    assert(reads == 0); /* ioctl never reads hardware */
    frames = FMCS_PLOAM_RX_BUDGET + 1;
    assert(fmcs_ploam_collect(&p, false) == FMCS_PLOAM_RX_BUDGET);
    assert(reads == FMCS_PLOAM_RX_BUDGET && frames == 1 && p.rx_budget_hits == 1);
    assert(fmcs_ploam_collect(&p, false) == 1 && !frames);
    assert(deliveries == FMCS_PLOAM_RX_BUDGET + 1);
    spi_fault = -EIO;
    assert(!fmcs_ploam_collect(&p, false) && p.rx_errors == 1);
    spi_fault = 0;
    events = 0;
    int saved = reads;
    assert(!fmcs_ploam_collect(&p, true) && reads == saved);
    events = 1; frames = 1;
    assert(fmcs_ploam_collect(&p, true) == 1 && p.rx_last_events == 1);
    p.fpga_status = 1;
    saved = reads;
    assert(!fmcs_ploam_collect(&p, false) && reads == saved);
    fmcs_ploam_flush_locked(&p);
    assert(!p.ploam_rx_count);
    accounting(&p);
    puts("PASS: FIFO ordering/wraparound/overflow, copy-fault retention, bounded collector, reset and SPI errors");
    return 0;
}
"""
defines = "\n".join(re.findall(r"^#define FMCS_PLOAM_RX_.*$", header, re.M))
helpers = "\n".join(function(n) for n in (
    "fmcs_ploam_flush_locked", "fmcs_ploam_enqueue_locked",
    "fmcs_ploam_dequeue", "fmcs_ploam_collect",
))
# Keep the enum used by the actual collector rather than shadowing its values.
status = header[header.index("enum fmcs_fpga_status {"):header.index("};", header.index("enum fmcs_fpga_status {")) + 2]
with tempfile.TemporaryDirectory() as tmp:
    path = Path(tmp)
    (path / "test.c").write_text(defines + "\n" + status + fixture + helpers + checks)
    subprocess.run([os.environ.get("CC", "cc"), "-std=gnu11", "-Wall", "-Wextra", "-Werror",
                    str(path / "test.c"), "-o", str(path / "test")], check=True)
    subprocess.run([str(path / "test")], check=True)
