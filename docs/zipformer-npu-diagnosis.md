# Zipformer NPU 部署诊断记录

更新时间：2026-08-31

## 当前结论

Zipformer 的 ONNX、A733 NBG 模型和板端 Demo 已经准备完成。板卡目前启动在
Radxa 官方 `5.15.147-21-a733` 内核，NPU 设备及驱动可以初始化，但量化网络
仍会在 `VIPDRV_WAIT_TASK` 处硬件超时。

同样的超时已经在 AI-SDK 自带的、目标 CID 与 A733 相符的 v3 ShuffleNetV2
量化 NBG 上复现，因此问题并非只由本项目的 Zipformer 模型转换造成。日志还
显示 NPU 驱动请求 `1008 MHz / 960 mV` 时，供电仍为 `800 mV`，并报告
`Get NPU Regulator Control FAIL!`。尝试通过 devfreq 将目标频率限制到
`852 MHz` 后，`target_freq` 虽然改变，但实际时钟和 `cur_freq` 仍保持
`1008 MHz`。当前重点应转为核对 A7A 的 DTB、PMIC 调压及 NPU 驱动组合。

## 当前系统状态

- 根文件系统：Debian 13 (Trixie)。
- 默认启动内核：`5.15.147-21-a733`，原 `6.6.98-4-aw2511` 仍保留在 U-Boot
  菜单中作为 `l0` 回退项。
- NPU 设备：`/dev/vipcore`。
- NPU 内核驱动：`2.0.3.0-AW-2024-05-29`。
- NPU 用户态库：`2.0.3.4-AW-2025-05-16`。
- Wi-Fi：AIC8800 DKMS 模块已针对 5.15 内核安装，NetworkManager 可自动连接。
- HDMI：sunxi DRM/HDMI 驱动已加载，但本次检查时 HPD 为 `out`、DRM connector
  为 `disconnected`，没有 EDID 和显示模式。
- 图形桌面：5.15 内核下只有 `/dev/dri/card0`，没有 render node；SDDM 启动
  Xorg 失败，Xorg 日志停在加载 `glamoregl` 后。除物理连接外，还需处理该内核
  与当前 Debian 13 Mesa/Xorg 用户态的兼容问题。

## 已验证项目

- 官方预编译浮点 KWS Encoder 和自行转换的微型浮点算子曾可在 NPU 上运行。
- 自行转换的 uint8 算子、官方 int16 vocoder、int16 Zipformer，以及 AI-SDK
  自带的 v3 量化 ShuffleNetV2 都发生硬件等待超时。
- AI-SDK v2 样例的目标 CID 为 `0x10000016`，与本机 A733 CID
  `0x1000003b` 不匹配；v3 样例 CID 匹配且可完成网络创建和输入准备，但执行
  时硬件超时。
- 浮点 Zipformer 可以以约 `RTF 0.45` 执行，但子模型输出固定异常值，最终
  重复输出 `THAT`；这不是可用的 ASR 路线。
- 外部句柄缓冲区与运行库自管缓冲区结果相同，应用层缓存或映射不是首要嫌疑。

## 关键文件与日志

- `outputs/npu-official-ai-sdk-v3-kernel-5.15.log`
- `outputs/npu-official-ai-sdk-v3-kernel-5.15-852mhz.log`
- `outputs/npu-mul-add-uint8-kernel-5.15.log`
- `outputs/npu-mul-add-uint8-kernel-5.15-runtime-2.0.3.2.log`
- `outputs/zipformer-npu-int16-radxa-runtime.log`
- `outputs/zipformer-npu-radxa-runtime.log`
- `tmp-workspace/ai-sdk/examples/vpm_run/operator/v3/network_binary.nb`

## 内核与恢复信息

已安装并验证：

- `linux-image-5.15.147-21-a733`，SHA-256
  `1d475a303f1a1a618028a4082be5c9dc0fd08f969c09741a5ed990c4abd3b75a`
- `linux-headers-5.15.147-21-a733`，SHA-256
  `88f161b57c6055c7a467bb2c08df423373f04a045a3632e47092c8926a5a9574`

U-Boot 菜单保留 10 秒：`l1` 是 5.15，`l0` 是 6.6。配置备份位于：

- `/boot/extlinux/extlinux.conf.before-cet6-npu`
- `/etc/default/u-boot.before-cet6-npu`

## 后续建议

1. 对照 Radxa A7A 官方可工作的 5.15 镜像，比较实际 DTB 中 `npu-supply`、
   OPP 表和 PMIC regulator 配置；优先解决调压失败及实际时钟不降频的问题。
2. 调压/时钟正常后先重跑 AI-SDK v3 ShuffleNetV2，再跑微型 uint8 算子，最后
   才测试 int16 Zipformer。
3. 若官方完整 Debian 11/5.15 镜像能运行量化样例，应将当前“Debian 13 根文件
   系统 + 5.15 内核”的混合环境视为不受支持组合，而不是继续修改模型。
4. NPU 量化验证通过后，再实现 `cet6_listener.asr` 的 Zipformer 后端；现有
   Whisper 后端继续作为稳定回退。
5. 显示器需求与 NPU 验证分开处理：6.6 内核适合当前桌面环境；5.15 可保留为
   NPU 专用测试项。不要在没有完整备份和本地恢复手段时删除任一内核。
