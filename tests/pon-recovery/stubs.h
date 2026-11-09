/* Minimal kernel stand-ins for a host build of the real functions. */
#include <stdio.h>
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include <errno.h>
#include <stddef.h>
typedef uint8_t u8; typedef uint16_t u16; typedef uint32_t u32; typedef int16_t s16;
#define BIT(n) (1UL << (n))
#define GENMASK(h, l) (((~0UL) << (l)) & (~0UL >> (sizeof(long) * 8 - 1 - (h))))
#define FIELD_PREP(m, v) (((unsigned long)(v) << __builtin_ctzl(m)) & (m))
#define READ_ONCE(x) (x)
#define WRITE_ONCE(x, v) ((x) = (v))
#define U32_MAX 0xffffffffU
struct mutex { int held; };
static inline void mutex_lock(struct mutex *m) { m->held++; }
static inline void mutex_unlock(struct mutex *m) { m->held--; }
struct work_struct { int unused; };
struct delayed_work { struct work_struct work; int queued; unsigned long delay; };
#define container_of(p, t, member) ((t *)((char *)(p) - offsetof(t, member)))
#define to_delayed_work(p) container_of(p, struct delayed_work, work)
struct i2c_client { int dev; };
struct gpio_desc { int value; };
struct device { int x; };
static unsigned long jiffies = 1000;
static inline unsigned long msecs_to_jiffies(unsigned int ms) { return ms; }
#define time_before(a, b) ((long)((a) - (b)) < 0)
static inline void cancel_delayed_work(struct delayed_work *w) { w->queued = 0; }
static inline void mod_delayed_work(void *wq, struct delayed_work *w, unsigned long d) { (void)wq; (void)d; w->queued = 1; }
static inline void schedule_delayed_work(struct delayed_work *w, unsigned long d) { w->queued = 1; w->delay = d; }
static void *system_wq;
static inline void gpiod_set_value_cansleep(struct gpio_desc *g, int v) { g->value = v; }
static int verbose = 0;
#define dev_warn(d, ...) do { (void)(d); if (verbose) { printf("    [warn] "); printf(__VA_ARGS__); } } while (0)
#define dev_err(d, ...)  do { (void)(d); if (verbose) { printf("    [err ] "); printf(__VA_ARGS__); } } while (0)
#define dev_info(d, ...) do { (void)(d); if (verbose) { printf("    [info] "); printf(__VA_ARGS__); } } while (0)
#define dev_warn_ratelimited dev_warn
static inline void atomic_set(int *p, int value) { *p = value; }
static inline int atomic_xchg(int *p, int value) { int old = *p; *p = value; return old; }
#define regmap_set_bits(...) ((void)0)
#define regmap_clear_bits(...) ((void)0)
#define udelay(...) ((void)0)
#define airoha_epon_update_bits(...) ((void)0)
#define airoha_pon_phy_update_bits(...) ((void)0)
#define airoha_xpon_epon_program_mac(...) (0)
#define airoha_xpon_epon_reset_registration(...) ((void)0)
#define airoha_xpon_epon_pcs_synced(...) (true)
#define airoha_xpon_epon_is_1g(...) (false)
#define airoha_xpon_epon_los(...) (false)
#define airoha_xpon_xgpon_los(...) (false)
#define airoha_xpon_leds_update(...) ((void)0)
#define airoha_xpon_handle_optical_loss_locked(...) (false)
#define airoha_xpon_xgpon_advance(...) ((void)0)
#define airoha_xpon_xgpon_drain_ploamd_locked(...) ((void)0)
#define airoha_xpon_xgpon_restart_mac(...) ((void)0)
#define airoha_xpon_retry_data_paths(...) ((void)0)
#define airoha_xpon_xgpon_note_serial_number(...) ((void)0)
#define airoha_xpon_xgpon_emergency_stop(...) ((void)0)
#define airoha_xpon_xgpon_enable_serial_number(...) ((void)0)
#define airoha_xpon_popup_timeout(...) ((void)0)
#define airoha_xpon_xgpon_counters_update(...) ((void)0)
static inline u16 get_unaligned_le16(const u8 *p) { return p[0] | (p[1] << 8); }
enum airoha_pon_frontend_mode {
	AIROHA_PON_FRONTEND_MODE_GPON, AIROHA_PON_FRONTEND_MODE_XGPON,
	AIROHA_PON_FRONTEND_MODE_XGSPON, AIROHA_PON_FRONTEND_MODE_EPON_1G,
	AIROHA_PON_FRONTEND_MODE_EPON_10G_1G, AIROHA_PON_FRONTEND_MODE_EPON_10G_10G,
};
struct airoha_pon_frontend { int unused; };
struct airoha_pon_frontend_diagnostics { u32 valid; s16 temperature; u16 voltage, tx_bias, tx_power, rx_power; int calibration; bool tx_gate_enabled; };
struct airoha_pon_frontend_signal_status { bool signal_present, signal_valid; };
#define AIROHA_XPON_LINK_POLL_MS 1000
#define AIROHA_XPON_RETRAIN_RETRY_MS 1000
#define AIROHA_XPON_NO_SYNC_RECOVERY_MS 1000
enum { AIROHA_XPON_ERROR, AIROHA_XPON_PROTOCOL_ACTIVATING, AIROHA_XPON_WAIT_LINE_SYNC };
enum { AIROHA_EPON_MPCP_REGISTERING, AIROHA_EPON_MPCP_DENIED };
