#!/bin/sh
# Compile unmodified production functions with host hardware stand-ins.
set -eu
[ "$#" -eq 1 ] || { echo "Usage: sh build.sh /path/to/openwrt-pon-drivers" >&2; exit 1; }
R=$(cd "$1" && pwd)
H=$(cd "$(dirname "$0")" && pwd)
EN="$R/airoha-pon-frontends/src/airoha-en7572.c"
XP="$R/airoha-xpon/src/airoha-xpon-epon.c"
MAIN="$R/airoha-xpon/src/airoha-xpon-main.c"
T=$(mktemp -d "${TMPDIR:-/tmp}/phase1-p1.XXXXXX")
trap 'rm -rf "$T"' 0
trap 'exit 1' HUP INT TERM

extract() {
    awk -v sig="$2" '
        index($0, sig) == 1 { printing = 1; found = 1 }
        printing { print }
        printing && /^}/ { exit }
        END { if (!found) exit 1 }
    ' "$1" > "$T/$3" || {
        echo "Cannot extract $2 from $1" >&2
        exit 1
    }
}
definitions() {
    awk '/^#define / { copying = 1 }
         copying { print; copying = /\\$/ }' "$1" > "$T/$2"
}
definitions "$EN" en_defs.h
definitions "$XP" xp_defs.h
awk '/^struct en7572 \{/ { copying = 1; found = 1 }
     copying { print }
     copying && /^};/ { exit }
     END { if (!found) exit 1 }' "$EN" > "$T/en_struct.h"
extract "$EN" 'static u8 en7572_bob_u8(' en_bob8.c
extract "$EN" 'static u16 en7572_bob_u16(' en_bob16.c
extract "$EN" 'static int en7572_bob_base(' en_base.c
extract "$EN" 'static const char *en7572_mode_name(' en_mode.c
extract "$EN" 'static int en7572_prepare(' en_prepare.c
extract "$EN" 'static int en7572_set_tx_enable(' en_settx.c
extract "$XP" 'static int airoha_xpon_epon_arm_tx(' xp_armtx.c
extract "$XP" 'static int airoha_xpon_epon_start_mac(' xp_startmac.c
extract "$XP" 'int airoha_xpon_epon_recover_tx(' xp_recover.c
extract "$XP" 'int airoha_xpon_epon_advance(' xp_advance.c
extract "$MAIN" 'static void airoha_xpon_advance_rx_locked(' xp_advance_rx.c
extract "$MAIN" 'static void airoha_xpon_link_work(' xp_link_work.c
cp "$H/harness.c" "$H/stubs.h" "$T/"
"${CC:-cc}" -std=gnu11 -Wall -Wextra -Werror -Wno-unused-function -Wno-unused-variable \
    -o "$T/harness" "$T/harness.c"
"$T/harness"
