# Nokia XG-040G-MF / AN7583 XG-PON 故障报告

## 说明

本文整理自此前已经完成的设备 SSH、`ponctl`、日志采样、原光猫参数
对照和驱动源码分析，不代表当前时刻重新登录设备得到的实时状态。

为避免泄露敏感信息，本文不记录设备登录凭据、完整序列号、LOID、
Registration-ID 内容或密钥。

## 设备与环境

| 项目 | 已知信息 |
| --- | --- |
| 设备 | Nokia XG-040G-MF |
| SoC/PON MAC | Airoha AN7583 |
| 系统 | PonWrt snapshot |
| 内核 | `6.18.52`，当前采样 revision `r41558-a57faf93c6` |
| PON 制式 | XG-PON，2.5G 上行 |
| OLT 厂商判断 | Burst Profile 的 PON Tag 解码为 `HWTC PON`，可高置信判断为华为系统，但无法确定具体 OLT 型号或板卡 |
| 当前驱动上游 | `pbs05/openwrt-pon-drivers`，WIP，包 release 68 |

## 故障完整清单

| # | 故障或现象 | 已取得证据 | 当前判断 | 状态 |
| --- | --- | --- | --- | --- |
| 1 | XG-PON 激活循环，无法稳定上线 | 稳定重复 `O2_3 → O4 → O5 → Deactivate → O2_3`；最新固件至少一次在 O5 收到三次 `Assign Alloc-ID 0x0a` 后被撤销 | 当前最高可信故障点是默认 Alloc-ID ACK 缺失 | 已修复源码，等待设备验证 |
| 2 | OMCI 完全未建立 | OMCI 收发计数持续为 0，密钥交换也未开始 | 不是 OMCI 配置协商失败，而是 OLT 在 OMCI 之前已撤销 ONU | 已确认是主故障的结果，不是首要根因 |
| 3 | OLT 下发流程在 O5 中终止 | 历史周期曾进入 Request Registration；最新周期中 HWTC 三次重发 `Assign Alloc-ID 0x0a` 后 Deactivate | 若该 Alloc-ID 等于 ONU-ID，旧驱动直接拒绝且不发 ACK；vendor 会用 shadow T-CONT 0 并 ACK OK | 已按 vendor 行为修复 |
| 4 | 首次 Ranging ACK 可能早于 TX 时序同步完成 | 上机诊断显示 EqD 写前、写后和 ACK 阶段 `TX_SYNC_READY=1`，ACK 返回 0 | 本机样本不支持 ACK 等待假设；Issue #3 的 vendor 等待仍是有效外部证据，但不是当前首要方向 | 已基本排除 |
| 5 | Ranging ACK 返回值原先被忽略 | `airoha_xpon_send_ack()` 返回值未被记录；TX gate 关闭、FIFO overrun、空间不足均不可观察 | 即使 ACK 没有成功提交，旧日志也可能表现为已经进入 O5 | 已在本地诊断补丁中修复不可观察问题，不改变协议行为 |
| 6 | PLOAMu FIFO 可能堵塞或空间不足 | 上机诊断显示 FIFO 无 overrun、可用空间充足，Ranging ACK 提交成功 | 首次测距 ACK 没有卡在 FIFO；Registration 仍需独立采集提交和发送计数 | 测距路径已排除，已增加 Registration FIFO 快照 |
| 7 | 可能出现 TX late，现有 resync 太晚 | 上机诊断显示 `tx_late=0`、`tx_resync=0`、`blocked=0` | 当前样本不支持首个 burst TX late | 已基本排除 |
| 8 | 曾观察到 `tx_error=0x4` | 旧采样中 MAC 留有 `tx_error=0x4`，定义指向上行 Burst Profile 无效 | 可能是实际异常，也可能是 Deactivate/清表留下的瞬态状态，不能单独定根因 | 保留为关联证据，不建议据此直接改寄存器 |
| 9 | 硬件自动回复与软件 ACK 是否重复，曾存在疑点 | 驱动存在 O2/O4 硬件回复机制，同时软件路径提交 Ranging ACK；每轮 O2 可见 3 个 SN 响应，O4 后可见 1 个上行 PLOAM | 尚无证据证明重复 ACK，需要诊断 FIFO/计数明确实际提交和发送情况 | 未证实，不应先修改自动回复行为 |
| 10 | 身份/认证配置曾不一致，但已基本排除 | PonWrt 已恢复并锁存与成功中兴 ONU 相同的 LOID 和 Registration-ID；另一台 ZNHG603 使用不同 SN 也可凭 LOID 注册 | OLT 不像是按单一 SN 白名单绑定；SN 不是当前首要方向 | 基本排除，仍需保证每轮 active identity 未丢失 |
| 11 | OMCC 兼容值无效 | `OMCC=0x86` 已生效，OMCI 仍为 0，激活循环不变；此前也使用过其他值 | OLT 在 OMCC/OMCI 真正参与之前已经撤销 | 已排除为当前根因 |
| 12 | 光功率偏弱 | 冷启动恢复后接收功率约 `-25.2` 至 `-25.38 dBm` | 较弱，但设备仍能保持 XGTC 同步、接收 Profile、分配 ONU-ID 并完成测距，不足以解释固定的测距后 Deactivate | 风险项，不是当前首要根因 |
| 13 | 热重启后 BOSA/前端初始化异常 | 一次异常重启后遥测变为约 `99.29°C / 4.45V / -40 dBm`，XGTC 长期 hunt；冷断电后恢复正常遥测和原有激活循环 | 独立于主故障，属于热重启后前端未正确复位或初始化 | 冷断电可恢复，应单独跟踪 |
| 14 | 直接访问活动 MAC MMIO 存在异常重启风险 | 排查期间设备 uptime 异常归零，随后停止裸寄存器访问 | 无法严格证明读取动作就是重启根因，但活动 MAC 上使用 `devmem` 风险不可接受 | 已停止；后续只使用驱动 debugfs、`ponctl` 和日志 |
| 15 | `RSP_TIME`/EqD 无运行时安全调节入口 | 当前 XG-PON 驱动使用 `RSP_TIME=0x551`，约对应 2.5G 上行 35 µs；没有 UCI/`ponctl` 开关 | 不应直接用 `devmem` 修改；Issue #3 的 XGS `0x1543` 和 `EqD << 2` 不适用于本机 XG-PON | 保持原值，诊断轮不做行为改变 |
| 16 | Registration 专项诊断尚未在目标内核运行 | 当前工作区仍无匹配 OpenWrt SDK、kernel build tree 或工具链；设备现有固件已包含较完整的测距诊断，但不含本次新增的 Registration 快照 | 不能在本机安全产出与 `6.18.52` 匹配的 `.ko`，也不能提供未经验证的二进制 | 需要在匹配的 PonWrt 构建环境编译 |
| 17 | 成功 ONU 基准已经建立 | 中兴 ZXHN F7015TV3 重启后稳定 O5/Registered，`LoidState=1`，OMCI、PLOAM 和业务 GEM 均正常；使用与 PonWrt 相同的 LOID/Registration-ID、不同 SN | 光路、OLT 端口及凭据组合可用，故障集中在 PonWrt/AN7583 Registration 实现 | 已确认 |
| 18 | Registration PLOAM 的 MIC/密钥或格式可能异常 | 中兴成功路径会对方向字节和 40 字节 Registration 内容生成 activation PLOAM MIC 后再发送；AN7583 使用 44 字节硬件控制/FIFO 格式，由 MAC 生成 MIC | 密钥寄存器顺序已与 vendor setter/getter 对照一致；仅在默认 Alloc-ID ACK 修复后仍失败时继续追查 | 次级假设 |

## 已排除或基本排除的项目

- 不同 SN 的中兴和 ZNHG603 均可使用该线路凭据注册，未发现单一 SN
  白名单证据。
- 已测试原机真实 Registration-ID，现象不变。
- 已测试 Registration-ID 留空，现象不变。
- 原机 GPON/PON password 为空。
- `OMCC=0x86` 已测试，OMCI 仍为 0，现象不变。
- 冷断电后光模块恢复正常，但原有激活循环仍存在。
- 上行光路并非完全不可用：设备可以发出 SN 响应和 O4 上行 PLOAM。
- 问题发生在 OMCI 和业务 GEM 建立之前。

## 当前最高可信根因

最新周期暴露了一个可直接证明的 vendor 行为差异：

1. 首次 Ranging ACK 已在 O5 后、`TX_SYNC_READY=1` 时成功入 FIFO，随后
   `TX_PLOAMU_CNT` 和 `TX_ACK_PLOAMU_CNT` 均增长，不能再判断为完全未发送。
2. HWTC 随后至少一次连续三次下发 `Assign Alloc-ID 0x0a`，但没有继续建立
   OMCI，最终 Deactivate。
3. 驱动自身已注明 T-CONT 0 shadow ONU-ID，却在
   `airoha_xpon_accept_alloc_id()` 中把 `alloc_id == onu_id` 当作 `-EINVAL`
   直接返回，因此不会发送任何 ACK。
4. Airoha vendor `ploam_recv_assign_alloc_id()` 对相同情况不创建新 T-CONT，
   但仍发送 `XGPON_PLOAM_ACK_OK`。
5. 这能完整解释严格的 HWTC 重发三次后撤销，而较宽容或流程不同的 ZTEG
   可以注册。r76 已按 vendor 行为修复：默认 Alloc-ID 使用 shadow T-CONT 0
   并 ACK OK；其他 Alloc-ID 路径不变。

该判断仍需设备实测确认 `0x0a` 同时是当轮 ONU-ID，并确认修复后 OLT 不再
重复该消息而继续 Request Registration/OMCI。若仍失败，再回到 Registration
MIC/PIK 和消息内容排查。

Issue #3 所引用的 Airoha vendor 路径为：

```text
收到 Ranging-Time
→ 写入 EqD
→ gponDevGetTxSyncRdy
→ 最长等待 TX_SYNC_READY 3000 µs
→ 发送 Ranging ACK
```

该证据解释了为何最初优先检查测距时序；本机诊断现已显示 ready、ACK、
FIFO 和 TX late 均正常，因此本轮不引入这项等待。

## 不应直接应用的外部方案

- ODI Issue #29 和 PR #33 针对 RTL9602C/GPON，不能直接应用于
  AN7583/XG-PON。
- XGS-PON 的 `RSP_TIME=0x1543` 和 `EqD << 2` 属于 10G 上行时基，
  不能用于当前 XG-PON 2.5G 上行。
- 不应通过 `devmem` 修改活动 MAC 的 EqD、RSP_TIME 或 resync 寄存器。
- 不应安装其他内核版本编译的通用 `.ko`。

## 已完成的审阅分支诊断补丁

本地工作分支：

```text
rayniel-an7583-ranging-diagnostics
```

审阅分支：

<https://github.com/rayniel/openwrt-pon-drivers/tree/rayniel/an7583-xgpon-diagnostics>

当前状态：

- 诊断改动提交并推送到上述审阅分支。
- r76 默认 Alloc-ID ACK 修复已在本地完成，等待验证和推送。
- 未创建 Pull Request。
- 没有生成未经验证的 `.ko`。

改动文件：

- `airoha-xpon/src/airoha-xpon-ploam.c`
- `airoha-xpon/src/airoha-xpon-private.h`
- `airoha-xpon/src/airoha-xpon-diagnostics.c`
- `README.md`

新增诊断：

- 首次接受的 O4 Ranging-Time raw flags。
- 解析后的 `absolute` 和 `positive`。
- 首次 EqD。
- 写 EqD 前后的 `TX_SYNC_READY`。
- Ranging ACK 的真实返回值。
- ACK 提交使用的 PLOAMu FIFO 状态。
- ACK 提交后的 PLOAMu FIFO 状态。
- ACK 提交前后及 Deactivate 时的总 PLOAMu TX 和 ACK TX 计数。
- O2/O4 回复控制值。
- ACK 前及 Deactivate 时的上行 Burst Profile valid 位图。
- ACK 前后及 Deactivate 时的 BWmap 检查和 TX error 状态。
- FIFO raw、valid、overrun 和 available words。
- TX late、resync、resync failure 和 PLOAMu blocked 当前计数。
- 上述计数在最近一次首次测距事件中的快照。
- Request Registration 的 seq 和当前硬件 key index。
- Registration 提交返回值及 FIFO 前后状态。
- Registration 提交前后 PLOAMu TX 计数。
- Request 时和 Deactivate 时的 Registration-sent IRQ 计数。
- Request 到随后 Deactivate 的毫秒间隔。

新增日志格式：

```text
PLOAM ranging diagnostic: flags=... absolute=... positive=... EqD=...
TX_SYNC_READY=x->y ACK=... PLOAMu_TX=before->after ACK_TX=before->after
PLOAMu_FIFO=before->after
tx_late=... tx_resync=... tx_resync_failed=... blocked=...
PLOAM registration diagnostic: seq=... key_index=... submit=...
PLOAMu_FIFO=before->after PLOAMu_TX=before->after registration_irq=...
PLOAM registration diagnostic: Deactivate after ... ms
PLOAMu_TX=... registration_irq=...
```

诊断不输出 SN、Registration-ID、LOID、密钥或其他身份材料。

本次 Registration 专项补丁没有新增：

- 额外的等待或轮询；审阅分支此前已经加入 Ranging ACK 前最多 3000 µs
  的 `TX_SYNC_READY` 有界等待。
- TX resync。
- EqD 算法或数值修改。
- O 状态切换修改。
- XGS-PON 四倍时基。

后续 vendor 顺序对照补丁有意调整了一处行为：

- 首次 O4 Ranging-Time 写入 EqD 后先进入 O5，再等待 `TX_SYNC_READY` 并
  立即提交 Ranging ACK；OMCI link 和数据路径通知移到 ACK 提交之后。该顺序
  与 vendor 的“进入 O5 → Ranging ACK tasklet 中等待 ready → 提交 ACK →
  OMCI/event”一致。旧实现的 ready 采样全部发生在 O5 状态写入之前，不能证明
  O5 切换后的首个上行 grant 已 ready。

## 已完成验证

- `git diff --check` 通过。
- 源码回归测试包含默认 Alloc-ID 必须进入 ACK 路径的契约。
- 本次改动没有新增 `udelay`、`usleep` 或无界轮询。
- 没有加入 `RSP_TIME` 或 `EqD << 2` 行为。
- ACK 调用点已经检查。
- ACK 返回值与 FIFO 状态捕获字段已经检查。

由于本机没有与设备匹配的 OpenWrt SDK、kernel 6.18.52 构建树和工具链，
目前无法完成模块编译，也无法提供经过验证的安装包。

## 项目与参考地址

- 驱动源码项目：
  <https://github.com/pbs05/openwrt-pon-drivers>
- 完整 PonWrt 源码：
  <https://github.com/pbs05/ponwrt>
- 本次创建的 Copilot 项目会话：
  [Xg-pon ranging diagnostics](ghapp://sessions/49c95dd2-6842-4e8e-8063-255c8ecd102e)
- 主排查会话：
  [光猫 ponwrt 排查](ghapp://sessions/aa3ee783-db88-459e-b205-e9d8a3c59526)
- Airoha vendor 行为参考：
  <https://github.com/pbs05/openwrt-pon-drivers/issues/3>
- 相似 ODI/RTL9602C 故障：
  <https://github.com/AndreZiviani/odi-oss/issues/29>
- ODI 参考修复 PR：
  <https://github.com/AndreZiviani/odi-oss/pull/33>

## 下一步

1. 在与设备 PonWrt snapshot、kernel `6.18.52` 和 revision
   `r41558-a57faf93c6` 完全匹配的构建环境中合入诊断补丁。
2. 编译 `airoha-xpon` 包，并核对模块 `vermagic`。
3. 优先安装生成的包，不使用其他内核环境生成的裸 `.ko`。
4. 保持当前身份、OMCC、EqD 和 OLT 配置不变，复现一次激活循环。
5. 采集 registration debugfs、MAC debugfs 和受限范围的内核日志。
6. 根据 Registration submit、PLOAMu TX、Registration-sent IRQ、
   key index 和 Deactivate 间隔，决定是否继续修正 MIC/PIK 或消息布局。

## 安全采集命令

```sh
grep -qs ' /sys/kernel/debug ' /proc/mounts ||
	mount -t debugfs debugfs /sys/kernel/debug

for f in /sys/kernel/debug/airoha-xpon-*/registration \
	 /sys/kernel/debug/airoha-xpon-*/mac; do
	[ ! -r "$f" ] || { echo "### $f"; cat "$f"; }
done

dmesg | grep -E \
	'PLOAM (ranging|registration) diagnostic|PLOAM: absolute EqD|XG-PON MAC error|TX late resync' |
	tail -n 200
```

## 诊断结果判读

- 2026-10-14 刷入事件级诊断后的 HWTC 实测：
  `US_PROF_VLD=0x31313131`，`TX_ERR_STS=0`，ACK 提交返回 0，但
  `TX_PLOAMU_CNT=209→209→209`、`TX_ACK_PLOAMU_CNT=9→9→9`
  （ACK 前、ACK 后、Deactivate 时）。这证明 ACK 已写 FIFO但未实际发送，
  故障位于 O5 切换后的 TX-ready/PLOAMu grant 窗口，而不是 OLT 收到 ACK
  后因 MIC、PIK 或 Burst Profile 拒绝。
- `TX_SYNC_READY=1->1`：EqD 写前后 ready 均未下降。
- `TX_SYNC_READY=1->0`：强烈支持 EqD 写入后需要等待 TX timing ready。
- `ACK=0`：ACK 已成功提交给 PLOAMu FIFO，不代表 OLT 一定收到。
- `ACK=-13`：`-EACCES`，TX gate 未开启。
- `ACK=-28`：`-ENOSPC`，PLOAMu FIFO 可用空间不足。
- `ACK=-75`：`-EOVERFLOW`，PLOAMu FIFO overrun。
- ACK 为 0 但 FIFO 长期不恢复：支持 ACK 已入 FIFO但没有正常发送。
- 总 PLOAMu TX 和 ACK TX 在提交后至 Deactivate 均不增长：支持软件 ACK
  没有获得可用上行 PLOAMu grant。
- 总 PLOAMu TX 增长而 ACK TX 不增长：先核实 ACK 专用计数器语义，不能仅凭
  该计数断定 ACK 未发送。
- `ranging_tx_error_at_deactivate & 0x4` 且 profile-valid 位图在 ACK 前已缺位：
  支持 Burst Profile 未正确生效；若只在 Deactivate 时出现，可能是清表时序。
- `ranging_bwmap_status_at_deactivate & 0x1` 表示 minimum burst interval
  异常；需结合 ACK 前后快照判断是否与本次 grant 同步发生。
- 首次测距后 TX late/resync 计数立即增长：支持首个 burst 时序错误。
- ready 正常、ACK 成功、FIFO 正常且无 TX late：需要转向 Burst Profile、
  protection-path flags 或 OLT 侧策略继续分析。
- `last_registration_submit_ret=0` 且 Deactivate 时 PLOAMu TX 和
  Registration-sent IRQ 均增长：回复已由 MAC 发送，应重点检查 PIK/MIC
  和 Registration-ID 字节布局。
- submit 为 0 但两个发送计数均不增长：Registration 留在 MAC/FIFO
  路径，继续检查 grant 和硬件发送条件。

## 统一故障描述

> Nokia XG-040G-MF（Airoha AN7583）运行 PonWrt snapshot/kernel
> 6.18.52，接入带 `HWTC PON` 标识的华为 XG-PON OLT 后，可以完成
> 下行同步、Burst Profile 接收、ONU-ID 分配和首次绝对测距，也能产生
> 上行响应；但在收到 Request Registration 并提交回复后约 80–110 ms
> 收到 OLT Deactivate，
> 形成约 6 秒一次的 `O2_3 → O4 → O5 → Deactivate` 循环。OMCI 收发
> 始终为 0，密钥交换未开始。测距诊断显示 `TX_SYNC_READY` 始终为 1、
> ACK 返回 0、FIFO 空间充足，且无 TX late/resync/blocked；因此首次
> 测距时序已基本排除。使用相同 LOID/Registration-ID、不同 SN 的中兴
> ONU 可稳定进入 O5、完成 OMCI 和业务 GEM，另一台不同 SN 的 ZNHG603
> 也可凭 LOID 注册，说明光路、OLT 端口和凭据可用，SN 不是首要方向。
> 当前最高可信假设是 AN7583 Registration 回复未真正发送，或其硬件
> PIK/MIC 选择及消息内容不符合 OLT 预期。现已增加只读 Registration
> 提交、FIFO、PLOAMu TX、Registration-sent IRQ、key index 和
> Deactivate 间隔诊断；下一步需要在匹配 kernel 6.18.52 的 PonWrt
> 构建环境编译安装并采集。
