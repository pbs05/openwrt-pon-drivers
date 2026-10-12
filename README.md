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
settings. The load-time module parameter `xgpon_stock_bwmap=1` explicitly
opts in to writing the stock AN7583 `0x00820000` baseline before publishing
burst profiles on each MAC initialization. MAC reset does not clear inherited
optional BWmap filters. This setting is not selected automatically by OLT vendor.

In an AN7583/HWTC test, replacing the inherited `0x00821f1f` setting with the
stock baseline enabled ACK transmission, LOID acceptance and service provisioning;
restoring the inherited setting reproduced early activation failure. Subsequent
OLT deactivation still occurred with the stock baseline. Individual filter tests
did not isolate the responsible bit, and ZTEG interoperability has not been
verified. The opt-in is a diagnostic compatibility setting, not a complete
registration fix. The `mac` snapshot exposes `bwmap_check_control` and
`bwmap_check_status`.

For an unloaded module, enable it with
`modprobe airoha-xpon xgpon_stock_bwmap=1`. For persistent OpenWrt configuration,
append `xgpon_stock_bwmap=1` to the existing `airoha-xpon` entry in
`/etc/modules.d/`, then reboot. Do not add a second module entry or unload the
driver on a live PON connection. The parameter is read-only after loading;
inspect `/sys/module/airoha_xpon/parameters/xgpon_stock_bwmap` to check the
selected setting. Omitting the parameter preserves the pre-r72 behavior of
not writing this register; it does not restore a register changed earlier.

默认情况下，XG-PON MAC 激活保留现有 `DBG_BWM_CHK_CTRL` 设置。只有在模块
加载时指定 `xgpon_stock_bwmap=1`，才会在每次 MAC 初始化、发布 burst profile
之前写入 AN7583 原厂基准值 `0x00820000`。MAC 复位不会清除继承的可选 BWmap
过滤设置，也不会根据 OLT 厂商自动启用此选项。

在 AN7583/HWTC 的一次测试中，将继承值 `0x00821f1f` 改为原厂基准值后，
ACK 发送、LOID 接受和业务下发成功；恢复继承值则早期激活故障复现。但使用
原厂基准值后仍发生后续 OLT 撤销，逐位测试也未确定具体原因，ZTEG 兼容性
尚未验证。因此该选项是诊断兼容设置，不是完整注册修复。
`mac` 快照显示 `bwmap_check_control` 和 `bwmap_check_status`。

模块尚未加载时可使用 `modprobe airoha-xpon xgpon_stock_bwmap=1`。
在 OpenWrt 上持久启用时，将 `xgpon_stock_bwmap=1` 追加到 `/etc/modules.d/`
中已有的 `airoha-xpon` 条目后重启，不要新增重复条目，也不要在活动 PON
连接上卸载驱动。参数加载后只读，可检查
`/sys/module/airoha_xpon/parameters/xgpon_stock_bwmap`。
不指定参数时保留 r72 之前不写此寄存器的行为，但不会还原此前已被修改的值。

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
