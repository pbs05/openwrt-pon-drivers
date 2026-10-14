# WIP Airoha PON kernel drivers

PON MAC and optical frontend drivers for Airoha AN7581/AN7583.

Airoha AN7581/AN7583 的 PON MAC 与光前端驱动。

Work in progress. APIs may change substantially.

开发中，API 可能发生大幅变更。

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
