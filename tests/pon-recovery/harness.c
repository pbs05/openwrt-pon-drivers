/* Host fault injection. Worker and MAC control flow comes from production C.
 * MMIO, I2C, optical input, PCS RX, firmware reload, and scheduling are stubs.
 * Registration/data-path side effects and XG-PON paths are outside this check.
 * This does not validate kernel concurrency, firmware execution, or hardware.
 */
#include "stubs.h"
#include "en_defs.h"
#include "xp_defs.h"
#include "en_struct.h"

#define CHECK(condition) do { \
    if (!(condition)) { \
        fprintf(stderr, "%s:%d: FAIL: %s\n", __FILE__, __LINE__, #condition); \
        return 1; \
    } \
} while (0)

static int i2c_writes, i2c_fail_from = -1, i2c_fail_count;
static int prepare_calls, reset_calls, rx_starts;
static int en7572_write(struct i2c_client *client, u16 reg, const void *data, size_t len)
{
    (void)client; (void)reg; (void)data; (void)len;
    ++i2c_writes;
    if (i2c_writes >= i2c_fail_from && i2c_fail_from >= 0 && i2c_fail_count > 0) {
        --i2c_fail_count;
        return -EIO;
    }
    return 0;
}
static int en7572_update_bits(struct en7572 *en, u16 reg, u32 mask, u32 value)
{
    (void)mask; (void)value;
    return en7572_write(en->runtime, reg, NULL, 4);
}
static void en7572_log_state(struct en7572 *en, const char *tag) { (void)en; (void)tag; }
static const unsigned int en7572_sample_ms[] = {2000, 2000, 4000};
static struct en7572 EN;
static u8 BOB[512];
static struct i2c_client RT, PG;
static struct gpio_desc TXDIS;
static void *airoha_pon_frontend_priv(struct airoha_pon_frontend *frontend)
{
    (void)frontend;
    return &EN;
}
#include "en_bob8.c"
#include "en_bob16.c"
#include "en_base.c"
#include "en_mode.c"
#include "en_prepare.c"
#include "en_settx.c"

static int airoha_pon_frontend_prepare(struct airoha_pon_frontend *frontend,
                                     enum airoha_pon_frontend_mode mode)
{
    ++prepare_calls;
    return en7572_prepare(frontend, mode);
}
static int airoha_pon_frontend_set_tx_enable(struct airoha_pon_frontend *frontend, bool on)
{
    return en7572_set_tx_enable(frontend, on);
}
static int airoha_pon_frontend_reset(struct airoha_pon_frontend *frontend)
{
    (void)frontend;
    ++reset_calls;
    EN.prepared = false;
    EN.tx_gate_enabled = false;
    return 0;
}
static int airoha_pon_frontend_get_signal_status(struct airoha_pon_frontend *frontend,
                                struct airoha_pon_frontend_signal_status *status)
{
    (void)frontend;
    status->signal_valid = true;
    status->signal_present = true;
    return 0;
}
static void airoha_pon_frontend_get_diagnostics(struct airoha_pon_frontend *frontend,
                                struct airoha_pon_frontend_diagnostics *diagnostics)
{
    (void)frontend; (void)diagnostics;
}

/* Only fields consumed by the extracted EPON/worker functions are needed. */
enum airoha_xpon_mode { AIROHA_XPON_MODE_EPON_10G_1G, AIROHA_XPON_MODE_EPON_10G_10G };
struct airoha_xpon_mode_info { enum airoha_pon_frontend_mode frontend_mode; };
static const struct airoha_xpon_mode_info MODE = {AIROHA_PON_FRONTEND_MODE_EPON_10G_1G};
static const struct airoha_xpon_mode_info *airoha_xpon_mode_info(enum airoha_xpon_mode mode)
{
    (void)mode;
    return &MODE;
}
static bool airoha_xpon_mode_is_epon(enum airoha_xpon_mode mode) { (void)mode; return true; }
static const char *airoha_xpon_mode_name(enum airoha_xpon_mode mode) { (void)mode; return "EPON"; }
struct airoha_xpon {
    struct device *dev;
    struct airoha_pon_frontend *frontend;
    struct delayed_work link_work;
    struct mutex state_lock;
    enum airoha_xpon_mode active_mode;
    bool tx_armed, rx_active, pcs_profile_valid, mac_initialized, stopping, optical_signal;
    int lifecycle, last_start_error, phy_events, mac_restart_pending;
    int data_path_retry_pending, sn_exchange_pending, emergency_stop_pending, serial_enable_pending;
    struct {
        bool frontend_reset_pending, frontend_reset_forced, frontend_reload_forced;
        bool pcs_synced, discovery_seen;
        unsigned int tx_rearm_count, frontend_reset_count, registered_timeout_streak;
        unsigned int requests_since_message, sync_time, channel, recovery_count, full_reinit_count;
        unsigned int sync_loss_count;
        int mpcp_state, pending_events, pending_error_events;
        u16 llid;
        unsigned long frontend_reset_after, denied_until, sync_loss_since;
    } epon;
};
static u32 airoha_epon_read(struct airoha_xpon *xpon, u32 reg) { (void)xpon; (void)reg; return 0; }
static void airoha_epon_write(struct airoha_xpon *xpon, u32 reg, u32 value)
{
    (void)xpon; (void)reg; (void)value;
}
/* PCS/MMIO are stubs; preserve RX/TX state transitions used by the worker. */
static void airoha_xpon_epon_stop_rx(struct airoha_xpon *xpon)
{
    airoha_pon_frontend_set_tx_enable(xpon->frontend, false);
    xpon->tx_armed = false;
    xpon->rx_active = false;
    xpon->epon.pcs_synced = false;
    xpon->mac_initialized = false;
}
static int airoha_xpon_epon_start_rx(struct airoha_xpon *xpon)
{
    ++rx_starts;
    xpon->rx_active = true;
    xpon->epon.pcs_synced = false;
    return 0;
}
#include "xp_armtx.c"
#include "xp_startmac.c"
#include "xp_recover.c"
#include "xp_advance.c"
#include "xp_advance_rx.c"
#include "xp_link_work.c"

static struct airoha_xpon X;
static struct airoha_pon_frontend FE;
static struct device DEV;
static int initial_prepare_writes;
static int reset_world(void)
{
    memset(&X, 0, sizeof(X));
    memset(&EN, 0, sizeof(EN));
    EN.runtime = &RT; EN.program = &PG; EN.tx_disable = &TXDIS; EN.bob = BOB;
    EN.bob_a0_valid = EN.bob_a2_valid = true;
    X.dev = &DEV; X.frontend = &FE;
    i2c_writes = prepare_calls = reset_calls = rx_starts = i2c_fail_count = 0;
    i2c_fail_from = -1;
    jiffies = 1000;
    CHECK(airoha_pon_frontend_prepare(&FE, MODE.frontend_mode) == 0);
    initial_prepare_writes = i2c_writes;
    CHECK(airoha_xpon_epon_start_mac(&X) == 0);
    CHECK(X.tx_armed && EN.tx_gate_enabled);
    X.rx_active = true;
    X.epon.pcs_synced = true;
    prepare_calls = 0;
    return 0;
}
static int poll_once(void)
{
    X.link_work.queued = 0;
    airoha_xpon_link_work(&X.link_work.work);
    CHECK(X.state_lock.held == 0 && EN.lock.held == 0);
    CHECK(X.link_work.queued);
    jiffies += X.link_work.delay;
    return 0;
}
static int recovery_case(int stage, int fail_offset, int fail_count)
{
    CHECK(reset_world() == 0);
    if (stage == 2)
        X.epon.tx_rearm_count = AIROHA_EPON_TX_REARM_ATTEMPTS;
    X.epon.frontend_reset_pending = true;
    /* stop_rx writes BEN once; the next operation starts prepare(). */
    i2c_fail_from = i2c_writes + 1 + fail_offset;
    i2c_fail_count = fail_count;
    CHECK(poll_once() == 0);
    CHECK(!EN.prepared && !X.tx_armed && !X.rx_active);
    CHECK(prepare_calls == 1 && rx_starts == 0);
    CHECK(reset_calls == (stage == 2 ? 1 : 0));
    int recovered_at = 0;
    for (int poll = 2; poll <= 20; ++poll) {
        CHECK(poll_once() == 0);
        if (X.tx_armed) { recovered_at = poll; break; }
    }
    CHECK(recovered_at > 0);
    CHECK(i2c_fail_count == 0 && EN.prepared && EN.tx_gate_enabled);
    CHECK(X.rx_active && X.mac_initialized && X.epon.pcs_synced);
    CHECK(rx_starts == 1 && prepare_calls == fail_count + 1);
    printf("PASS stage=%d I2C_offset=%d failures=%d: TX armed at worker pass %d\n",
           stage, fail_offset, fail_count, recovered_at);
    return 0;
}
static int healthy_case(void)
{
    CHECK(reset_world() == 0);
    X.tx_armed = false;
    CHECK(airoha_xpon_epon_start_mac(&X) == 0);
    CHECK(X.tx_armed && EN.tx_gate_enabled && prepare_calls == 0);
    CHECK(poll_once() == 0);
    CHECK(prepare_calls == 0);
    puts("PASS prepared frontend: no redundant prepare");
    return 0;
}
int main(void)
{
    CHECK(reset_world() == 0);
    int writes = initial_prepare_writes;
    for (int stage = 1; stage <= 2; ++stage) {
        for (int offset = 1; offset <= writes; ++offset)
            CHECK(recovery_case(stage, offset, 1) == 0);
        CHECK(recovery_case(stage, 1, 5) == 0);
    }
    CHECK(healthy_case() == 0);
    puts("All production-worker recovery assertions passed");
    return 0;
}
