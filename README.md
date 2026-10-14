# WIP Airoha PON kernel drivers

PON MAC and optical frontend drivers for Airoha AN7581/AN7583.

Airoha AN7581/AN7583 的 PON MAC 与光前端驱动。

Work in progress. APIs may change substantially.

开发中，API 可能发生大幅变更。

**快速入口：[BWmap 兼容模式的启用、验证与关闭](#bwmap-usage)**。
该选项**默认关闭**，升级驱动并不会自动启用。

<a id="bwmap-usage"></a>

## XG-PON BWmap 兼容模式：使用方法

适用于已安装本分支 **xPON r74 或更新版本**的 XG-PON 线路；当前版本为 r75。
AN7583/HWTC 上实测原厂过滤值 `0x00820000` 可让 ACK、LOID 认证和业务下发继续，
但后续仍可能收到 OLT Deactivate，**不是保证注册成功的开关，也不是 AES 超时修复**。
不根据 OLT 厂商自动启用，不影响 EPON；其他硬件/OLT 的效果需单独验证。

### 1. 按使用的界面选择启用方式

| 用户态界面 | 持久启用方式 |
| --- | --- |
| `luci-app-pon`，配套 `airoha-ponctl` 0.2.0-r2 / LuCI 0.1.0-r4 或更新版本 | **PON → 配置 → PON 线路 → XG-PON BWmap 兼容模式 → 原厂过滤设置（HWTC 兼容）**，保存并应用，再重启 PON 线路。 |
| 自定义 [`luci-app-onu`（`dev` 分支）](https://github.com/rayniel/OpenWrt_ONU_CONFIG/tree/dev) | 当前没有 BWmap 开关，后端也未读取 `pon.<线路>.xgpon_stock_bwmap`；请用下面的驱动模块参数方式，不要只写 UCI。 |

**自定义 ONU / 没有对应界面时：**

先找到已有的模块加载条目：

```sh
grep -n 'airoha[-_]xpon' /etc/modules.d/*
```

编辑匹配文件中**已有的** `airoha-xpon` 条目，保留其他参数，添加或修改
`xgpon_stock_bwmap=1`。例如 `/etc/modules.d/airoha-xpon` 中的该行：

```text
airoha-xpon xgpon_stock_bwmap=1
```

不要新增第二条模块加载记录，也不要在活动 PON 连接上卸载驱动。
**模块参数需要重启设备才会重新加载**，仅在 ONU 页重启线路不足以加载修改后的模块参数。
重启会中断网络，请自行选择维护时间。

如果只想临时测试，可在驱动已加载时执行
`echo 1 > /sys/class/net/pon0/xpon/xgpon_stock_bwmap`，
再使用 **ONU → 诊断 → 重启 PON 线路**。这不是持久配置，驱动重载或设备重启后会丢失。
接口不是 `pon0` 时替换为实际名称；每线路显式配置的 `0` / `1` 优先于模块默认值。

### 2. 确认已作用到硬件

重新启动并完成下行同步、MAC 初始化后，检查：

```sh
cat /sys/class/net/pon0/xpon/xgpon_stock_bwmap
grep 'bwmap_check_control:' /sys/kernel/debug/airoha-xpon-pon0/mac
```

若 debugfs 尚未挂载，先执行 `mount -t debugfs debugfs /sys/kernel/debug`。
第二条输出应为 **`bwmap_check_control: 0x00820000`**。第一条只表示暂存策略：
`default` 表示跟随模块参数，因此模块参数启用时显示 `default` 也正常。
仅看到 UCI 值为 `1`、模块参数为 `Y` 或界面显示 O5，都不能替代硬件读回验证。

### 3. 关闭 / 回退

通过 `luci-app-pon` 启用的，选择关闭或将对应 UCI 选项设为 `0`，再重启线路。
通过模块参数持久启用的，将原条目改为 `xgpon_stock_bwmap=0` 并重启设备；
同时确认没有每线路显式 `1` 覆盖。临时测试可写
`echo 0 > /sys/class/net/pon0/xpon/xgpon_stock_bwmap` 后重启线路。
`default` 是跟随模块默认值，**不等于强制关闭**。
关闭只会恢复本次驱动加载期间启用前保存的过滤值，不能撤销上一次启动或加载驱动前的寄存器改动。

## Optical frontends / 光前端

| Device / 器件 | Driver / 驱动 |
| --- | --- |
| EN7572 | `airoha-en7572` |
| GN28L95 | `airoha-paged-bosa` |
| UX3363 | `airoha-paged-bosa` |

## Protocols / 协议

| Mode / 模式 | Status / 状态 |
| --- | --- |
| GPON | ❌ |
| XG-PON | ✅️ |
| XGS-PON | ❓ |
| EPON 1G/1G | ❌ |
| 10G-EPON 10G/1G | ✅️ |
| 10G-EPON 10G/10G | ❓ |

- ✅ tested / 已测试
- ❓ untested / 未测试
- ❌ not yet implemented due to the lack of compatible devices / 我没有找到兼容设备，暂未实现

## XG-PON ranging diagnostics / XG-PON 测距诊断

### Improvements informed by other drivers (xPON r75 / frontend r15)

External fixes are compared and adapted, not merged as whole driver trees:

| Source | Integration |
| --- | --- |
| [gbosek `a65fa75`](https://github.com/gbosek/openwrt-pon-drivers/commit/a65fa752647028fcea8395315d54d5e8c031f78e) | Its r70 restores the original r68 AES/IRQ behavior, already present here. |
| [lunatickochiya `e369dd6`](https://github.com/lunatickochiya/openwrt-pon-drivers/commit/e369dd6335a3ae2d8b3fc49bb433abc7379f7464) | Keep AES switch completion advisory; add a rate-limited warning and `key_switch_timeouts` in the `crypto` snapshot rather than silently ignoring it or aborting Key Confirm. |
| [liuyuf78fk `3e581b6`](https://github.com/liuyuf78fk/openwrt-pon-drivers/commit/3e581b6ca6b9b5223e0739d6bf53053a5a489ea9) | Try `state_lock` in the threaded IRQ and defer FIFO draining to `link_work` on contention, preserving `state_lock -> ploam_lock` without blocking an IRQ that recovery synchronizes. Do not import its fatal advisory AES timeout. |
| [naoki66 `e19bde0`](https://github.com/naoki66/openwrt-pon-drivers/commit/e19bde08ac3f3218a783f22165d9a5ded06046d2) | Do not import the proposed seven-state model or its fatal AES timeout. No state-machine replacement is part of this release. |
| [yveming `4b2f9df`](https://github.com/yveming/openwrt-pon-drivers/commit/4b2f9df548f8ec993cf6b6d338277eaecccf8c52) | Reload EN7572 MD32 on subsequent interface starts, including empty-table profiles; reuse probe's fresh image on the first prepare. |
| [qianxuu `5257f0c`](https://github.com/qianxuu/openwrt-pon-drivers/commit/5257f0c247f863d202eac1fc7f206f85e23aed67) | Empty-table MD32 defaults were already integrated; preserve r14's calibration validation. |
| [yveming `176afc7`](https://github.com/yveming/openwrt-pon-drivers/commit/176afc7379ee2a6f6ffcbe03dd9988326d6c64fb) | Do not copy the complete A2 analog calibration into A0 automatically; retain per-profile data and the existing empty-profile defaults. |

The external state-machine patch is not a drop-in XG-PON correction:
G.987.3 (01/2014), clauses 11.3.3.5 and 12.2, retain combined `O2_3`;
Disable_Serial_Number option `0x0f` disables all ONUs, not enables them.
Its O6 handling would also discard the O5 epoch before the recommended 100 ms
TO2 expires. These changes do not establish the cause of the observed OLT
Deactivate. Proper O6/O7 support, including emergency-stop persistence, remains
separate work; this release preserves the existing activation/recovery behavior.

AES advisory timeout compatibility does not prove that the hardware switched
keys. The warning and per-epoch counter expose this uncertainty; no keys or
credentials are logged. Existing ranging ACK, BWmap and invalid-BOB safeguards
remain in place. Unsupported GPON MAC support is not enabled by importing a
different fork's experimental mode/PHY changes.

参考外部分支完善当前驱动，而非整包合并：保留 AES 超时不阻断 Confirm 的行为，但增加告警和计数；
统一 PLOAM 锁顺序并在 IRQ 锁竞争时延后处理；线路再次启动时重新加载 MD32，
失败明确报错且保持 TX 关闭。本次不替换状态机，不照搬 O2/O3 拆分或错误的 DisableSN 解释；
不自动跨模式复制整块模拟校准，不启用未经验证的 GPON 实验路径。
这些是源码整合，尚不代表已在 AN7583/HWTC 上验证稳定 O5。

Source-level regressions require Python 3 and the pure-Python `pycparser`
package. Run `python3 -m unittest discover -s tests -v`; they do not build the
driver or replace kernel type checking and on-device validation.

By default, XG-PON MAC activation preserves the existing `DBG_BWM_CHK_CTRL`
settings. Enabling stock BWmap compatibility writes the stock AN7583
`0x00820000` baseline before publishing burst profiles on each MAC initialization.
MAC reset does not clear inherited optional BWmap filters. The setting is
opt-in, not selected automatically by OLT vendor, and has no effect on EPON.

In an AN7583/HWTC test, replacing the inherited `0x00821f1f` setting with the
stock baseline enabled ACK transmission, LOID acceptance and service provisioning;
restoring the inherited setting reproduced early activation failure. Subsequent
OLT deactivation still occurred with the stock baseline. Individual filter tests
did not isolate the responsible bit. The user reports successful registration
on a ZTEG OLT with r68, but stock-filter interoperability there has not been
verified. The opt-in is a compatibility setting, not a complete
registration fix. The `mac` snapshot exposes `bwmap_check_control` and
`bwmap_check_status`.

Starting with r74, `/sys/class/net/pon0/xpon/xgpon_stock_bwmap` stages a per-line
policy: `default` follows the load-time module parameter, `1` enables stock
filters, and `0` preserves inherited filters. Writes do not change the live MAC;
the policy takes effect on its next initialization (including an OLT-triggered
MAC restart). For deterministic application, restart the PON line after saving.
If this driver enabled stock filters earlier, disabling restores the value
saved immediately before enabling, on the next MAC initialization. This saved
value is held only for the current driver load; it cannot undo register changes
made before probe or recover a previous boot's value.

With `airoha-ponctl` 0.2.0-r2 and `luci-app-pon` 0.1.0-r4 from
[the userspace compatibility branch](https://github.com/rayniel/openwrt-pon-userspace/tree/rayniel/hwtc-pm-compatibility),
select **PON → Configuration → PON line → XG-PON BWmap compatibility →
Stock filters (HWTC compatibility)**, save and apply, then restart the PON line
or reboot. The equivalent persistent UCI setting is:

```sh
uci set pon.line0.xgpon_stock_bwmap='1'
uci commit pon
/etc/init.d/pon reload
# Reboot, or use LuCI's PON diagnostics "Restart PON line".
```

Replace `line0` and `pon0` if your configured section/device names differ.
Setting the UCI option to `0` explicitly disables the override; `default`
returns to the module policy. The sysfs value reports the staged policy, not
hardware readback. Check `bwmap_check_control` in the `mac` snapshot to verify
`0x00820000` after activation.

The older load-time interface remains available:
`modprobe airoha-xpon xgpon_stock_bwmap=1` for an unloaded module, or append
that parameter to the existing `airoha-xpon` entry in `/etc/modules.d/` and
reboot. Do not add a duplicate entry or unload the driver on a live PON
connection. `/sys/module/airoha_xpon/parameters/xgpon_stock_bwmap` is read-only
and reports only this default, not a per-line override.

默认仍保留继承的过滤设置，不根据 OLT 厂商自动开启。原厂值 `0x00820000`
已在 AN7583/HWTC 的单变量测试中使 ACK、LOID 认证和业务下发得以继续，但
后续 OLT 撤销仍需结合 userspace PM 修复验证，不能保证最终注册成功。用户
已确认 r68 可在 ZTEG OLT 注册；该场景不默认启用原厂过滤设置。本选项不影响 EPON。

r74 新增每线路 sysfs 选项，配合上述 userspace 版本，可在 LuCI 的
**PON → 配置 → PON 线路 → XG-PON BWmap 兼容模式**中选择
**原厂过滤设置（HWTC 兼容）**。保存并应用后，在 PON 诊断页重启线路，
或重启设备。也可使用上述 UCI 命令持久开启，设为 `0` 关闭，设为 `default`
跟随模块加载参数。若本次驱动加载期间开启过，关闭后会在下次 MAC 初始化
恢复开启前保存的值；不能恢复驱动加载之前或上一次启动留下的修改。

sysfs 写入只暂存策略，不在活动连接上直接改变寄存器；下次 MAC 初始化
（包括 OLT 触发的 MAC 重启）生效。读取该属性只能确认暂存策略，应通过
`mac` 快照中的 `bwmap_check_control` 确认硬件值。原 r73 的模块加载参数仍可
使用，但无需再手工修改 `/etc/modules.d/` 即可通过 UCI/LuCI 控制。

With debugfs mounted, inspect
`/sys/kernel/debug/airoha-xpon-<interface>/registration` and `mac` after a
ranging attempt. The registration snapshot records the latest initial
Ranging-Time flags, EqD, TX synchronization state before and after the EqD
write, the bounded TX-ready wait result, PLOAMu FIFO state around the Ranging
ACK, and the ACK submission result. The driver waits up to 3000 us for TX
synchronization before entering O5 and submitting the initial Ranging ACK. If
the wait expires, it leaves the ONU in O4, does not submit the ACK, and records
the timeout. ACKs select the current PLOAM integrity-key group, and directed
Profile and Ranging-Time messages in O5 are acknowledged, including retries.
ACK submission failures are reported instead of being counted as accepted
messages. The snapshot also exposes TX-late and resynchronization counters,
hardware Registration send events, the key index sampled before the initial
ACK, and the hardware ACK counter before submission and at a subsequent O5
Deactivate. `ranging_deactivated` indicates whether the latter sample is valid.
A successful FIFO submission does not prove transmission or OLT acceptance;
even an increased hardware ACK counter does not prove OLT acceptance.

The same snapshot records each accepted O5 Request Registration without
exposing the ONU serial number, Registration-ID, or keys. It includes the
request sequence, raw current hardware key index, unchanged PLOAM control key
index, submission result, FIFO state, PLOAMu TX counter, Registration-sent
interrupt count, and the interval and counter values at a subsequent
Deactivate. If both send counters advance, investigation should focus on the
hardware-generated Registration MIC/key selection and message contents. If
neither advances after a successful FIFO submission, investigate the HWTC
BWmap/grant path instead.

Issue [pbs05/openwrt-pon-drivers#3](https://github.com/pbs05/openwrt-pon-drivers/issues/3)
documents an Airoha vendor path that polls `AIROHA_XGPON_TX_SYNC_READY` for up
to 3000 us before a Ranging ACK. This branch already implements that bounded
wait. XGS-PON-specific `RSP_TIME=0x1543` and `EqD << 2` behavior from that
report is not applied to this 2.5G-upstream XG-PON path.

挂载 debugfs 后，可在一次测距尝试后检查对应接口目录下的 `registration`
和 `mac`。诊断快照记录最近一次初始 Ranging-Time 的 flags、EqD、EqD 写入前后
的 TX 同步状态、有界等待结果、Ranging ACK 前后的 PLOAMu FIFO 状态及 ACK
提交结果，并显示 TX late 与重新同步计数。驱动在进入 O5 和提交首次 Ranging
ACK 前最多等待 TX 同步 3000 微秒；超时则保持 O4、不提交 ACK，并记录超时。
ACK 使用当前 PLOAM 完整性密钥组；O5 中收到单播 Profile 或 Ranging-Time
（包括重发）也会回 ACK。ACK 提交失败会记录错误，不再计入成功处理消息。
快照还显示硬件 Registration 发送事件计数、首次 ACK 前的密钥索引，以及
ACK 提交前和随后 O5 收到 Deactivate 时的硬件 ACK 计数；
`ranging_deactivated` 标明后一采样是否有效。FIFO 提交成功不等于报文已发送
或被 OLT 接受，硬件 ACK 计数增加也不能证明 OLT 已接受。

同一快照还记录 O5 Request Registration 的 seq、当前硬件 key index、
未修改的 PLOAM control key index、提交返回值、FIFO、PLOAMu TX、
Registration-sent 中断，以及随后 Deactivate 的间隔和计数。两个发送计数均增长
时，重点检查硬件生成的 Registration MIC、PIK 选择和消息内容；FIFO 提交成功但
两个计数均不增长时，优先检查 HWTC BWmap/grant 路径。诊断不输出 SN、
Registration-ID、LOID 或密钥。
