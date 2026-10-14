# Airoha PON optical frontends

| Provider | Devices | Calibration source |
| --- | --- | --- |
| `airoha-en7572` | EN7572 | 512-byte BOB NVMEM cell |
| `airoha-paged-bosa` | GN28L95, UX3363 | `APONCAL` NVMEM cell or board firmware |

## EN7572 calibration validation

Starting with frontend release r14, populated A0 and A2 BOB tables must have
IMOD, IAV, ERC DAC, TIA gain/bandwidth and PGA gain/capacitance codes that fit
their hardware fields. Out-of-range codes, including ASCII `0` bytes interpreted
as `0x3030`, fail probe with `-EINVAL` and identify the affected table in the
kernel log. The driver closes BEN before validation and does not upload rejected
calibration to MD32, truncate it into analog registers or report it as ready.
It does not silently substitute defaults or retry invalid populated tables.

Genuinely erased tables (all zero or all `0xff` in the calibration area) retain
the existing empty-table handling and missing-calibration status. Valid tables
retain the same analog settings. These range checks do not prove that a table
belongs to the device, detect every corruption or repair the underlying NVMEM
read path. A validation failure requires investigating the calibration source,
not bypassing the checks; this safeguard alone does not guarantee optical
synchronization or stable O5 registration.

## EN7572 restart handling (r15)

The first prepare reuses the fresh MD32 image loaded by probe. Each later
prepare reloads PM, DM and the same validated per-device BOB image, discarding
the previous session's converged APC/burst state. This follows the restart fix
in [yveming's branch](https://github.com/yveming/openwrt-pon-drivers/commit/4b2f9df548f8ec993cf6b6d338277eaecccf8c52),
but avoids a duplicate first load and covers empty-profile prepares too.
Both the board TX_DISABLE and internal BEN gate close before loading; a reload
error leaves the provider unprepared and propagates the error. TX enable checks
prepared state under the provider mutex. Reloading adds firmware-transfer time
to subsequent interface starts, not every OLT MAC reset or PMA retrain.

No BOB bytes are written to flash. The existing TX-DDMI word fallback remains;
the full A2 analog region is not automatically substituted for A0. Empty
profiles keep MD32-managed defaults, and out-of-range populated profiles still
fail validation before firmware startup. The original external restart report
concerns 10G-EPON; XG-PON/HWTC stability still needs device verification.