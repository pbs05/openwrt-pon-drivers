#!/usr/bin/env python3
"""Execute the real SPI transaction helpers against fault-injected MMIO.

Run with python3 tests/test_spi_restore.py (requires a native C compiler).
This checks controller state preservation, not electrical SPI timing.
"""

import os
from pathlib import Path
import re
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "src/fmcs_spi.c").read_text()
HEADER = (ROOT / "src/fmcs.h").read_text()


def function(name):
    start = re.search(r"static (?:int|void) " + name + r"\(", SOURCE).start()
    opening = SOURCE.index("{", start)
    depth = 1
    end = opening + 1
    while depth:
        depth += (SOURCE[end] == "{") - (SOURCE[end] == "}")
        end += 1
    return SOURCE[start:end]


fixture = r"""
#include <assert.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef uint32_t u32;
typedef uint8_t u8;
struct fmcs_priv { void *spi_base; void *spi_ctrl; int fpga_status; };
static unsigned int spi_dummy = 1;
static unsigned int spi_rx_skip = 1;
#define READ_ONCE(x) (x)
#define atomic_read(x) (*(x))
static int prepare_error, op_error, tx_error, rx_error, op_count;
static u32 readl(void *p) { return *(u32 *)p; }
static void writel(u32 v, void *p) { *(u32 *)p = v; }
#define readl_poll_timeout(p, v, condition, delay, timeout) \
    ((v) = readl(p), prepare_error ? -ETIMEDOUT : ((condition) ? 0 : -ETIMEDOUT))
static int an7581_spi_op_write(struct fmcs_priv *p, u32 cmd, u32 len)
{
    (void)len;
    ++op_count;
    assert(readl(p->spi_base + REG_SPI_CS_SEL) == 1);
    assert(readl(p->spi_base + REG_SPI_NFI2SPI_EN) == 0);
    assert(readl(p->spi_base + REG_SPI_CTRL_MANUAL_EN) == 1);
    assert(readl(p->spi_base + REG_SPI_CTRL_DUMMY) == spi_dummy);
    return op_error == (int)cmd + 1 ? -ETIMEDOUT : 0;
}
static int an7581_spi_write_bytes(struct fmcs_priv *p, const u8 *b, u32 len)
{ (void)p; (void)b; (void)len; return tx_error ? -EIO : 0; }
static int an7581_spi_read_bytes(struct fmcs_priv *p, u8 *b, u32 len)
{
    (void)p;
    /* Leading zero bit, then 0xA55AC301; final payload LSB is in byte five. */
    const u8 wire[] = {0x52, 0xad, 0x61, 0x80, 0x80};
    assert(len == sizeof(wire));
    memcpy(b, wire, len);
    return rx_error ? -EIO : 0;
}
"""

checks = r"""
int main(void)
{
    u32 mmio[0x140 / 4], saved[0x140 / 4];
    struct fmcs_priv p = { mmio, (void *)1, FMCS_FPGA_STATUS_READY };
    u8 tx[9] = {0}, rx[4];
    /* Preserve both the manual and DMA states used by NAND. */
    for (int mode = 0; mode < 2; ++mode) {
        for (int read = 0; read < 2; ++read) {
            for (int fault = 0; fault < 6; ++fault) {
                memset(mmio, 0, sizeof(mmio));
                mmio[REG_SPI_INT_CLEAR / 4] = 1;
                mmio[REG_SPI_MANUAL_OP_CTRL / 4] = mode ? 0 : 9;
                mmio[REG_SPI_CTRL_MANUAL_EN / 4] = mode ? 0 : 1;
                mmio[REG_SPI_NFI2SPI_EN / 4] = mode;
                mmio[REG_SPI_CTRL_DUMMY / 4] = 0;
                memcpy(saved, mmio, sizeof(mmio));
                prepare_error = fault == 1;
                op_error = fault == 2 ? SPI_OP_ASSERT_CS + 1 :
                           fault == 5 ? SPI_OP_DEASSERT_CS + 1 : 0;
                tx_error = fault == 3;
                rx_error = fault == 4;
                op_count = 0;
                int ret = read ? fmcs_raw_spi_read_locked(&p, tx, 1, rx, 4) :
                                 fmcs_raw_spi_write_locked(&p, tx, 9);
                assert(!memcmp(mmio, saved, sizeof(mmio)));
                assert((ret != 0) == (fault != 0 && (read || fault != 4)));
                assert(op_count == (fault == 1 ? 0 : 2));
                if (read && !ret) {
                    const u8 expected[] = {0xa5, 0x5a, 0xc3, 0x01};
                    assert(!memcmp(rx, expected, sizeof(expected)));
                }
            }
        }
    }
    prepare_error = op_error = tx_error = rx_error = 0;
    p.fpga_status = FMCS_FPGA_STATUS_PROGRAMMING;
    op_count = 0;
    assert(fmcs_raw_spi_write_locked(&p, tx, 9) == -EBUSY);
    assert(fmcs_raw_spi_read_locked(&p, tx, 1, rx, 4) == -EBUSY);
    assert(op_count == 0);
    assert(!memcmp(mmio, saved, sizeof(mmio)));
    puts("PASS: 24 success/fault transactions restore NAND state; programming blocks SPI");
    return 0;
}
"""

defines = "\n".join(re.findall(r"^#define (?:REG_SPI_|SPI_OP_).*$", HEADER, re.M))
status = HEADER[HEADER.index("enum fmcs_fpga_status {"):HEADER.index("};", HEADER.index("enum fmcs_fpga_status {")) + 2]
state = SOURCE[SOURCE.index("struct fmcs_spi_state {"):SOURCE.index("};", SOURCE.index("struct fmcs_spi_state {")) + 2]
helpers = "\n".join(function(name) for name in (
    "fmcs_spi_restore", "fmcs_spi_prepare",
    "fmcs_raw_spi_write_locked", "fmcs_raw_spi_read_locked",
))
with tempfile.TemporaryDirectory() as tmp:
    path = Path(tmp)
    (path / "test.c").write_text(defines + "\n" + status + "\n" + fixture + state + helpers + checks)
    subprocess.run([os.environ.get("CC", "cc"), "-std=gnu11", "-Wall", "-Wextra", "-Werror",
                    str(path / "test.c"), "-o", str(path / "test")], check=True)
    subprocess.run([str(path / "test")], check=True)
