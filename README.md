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

With debugfs mounted, inspect
`/sys/kernel/debug/airoha-xpon-<interface>/registration` and `mac` after a
ranging attempt. The registration snapshot records the latest initial
Ranging-Time flags, EqD, TX synchronization state before and after the EqD
write, the bounded TX-ready wait result, PLOAMu FIFO state around the Ranging
ACK, and the ACK submission result. The driver waits up to 3000 us for TX
synchronization before entering O5 and submitting the initial Ranging ACK. If
the wait expires, it leaves the ONU in O4, does not submit the ACK, and records
the timeout. The snapshot also exposes TX-late and resynchronization counters.

挂载 debugfs 后，可在一次测距尝试后检查对应接口目录下的 `registration`
和 `mac`。诊断快照记录最近一次初始 Ranging-Time 的 flags、EqD、EqD 写入前后
的 TX 同步状态、有界等待结果、Ranging ACK 前后的 PLOAMu FIFO 状态及 ACK
提交结果，并显示 TX late 与重新同步计数。驱动在进入 O5 和提交首次 Ranging
ACK 前最多等待 TX 同步 3000 微秒；超时则保持 O4、不提交 ACK，并记录超时。
