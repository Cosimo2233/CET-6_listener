# Zipformer NPU 部署诊断记录

更新时间：2026-08-31

## 当前结论

Zipformer 的 ONNX、A733 NBG 模型和板端 Demo 已经准备完成，但当前板卡的
Debian 13 / Linux 6.6.98 NPU 内核路径不能正确执行官方要求的 int16 图。
这不是 ASR 流水线、音频输入或解码器造成的。

官方 Zipformer 示例使用 Debian 11 环境，并给出 A733 int16 模型约
`RTF 0.053` 的结果。当前板端测试同一类模型时，Encoder 第一帧在
`VIPDRV_WAIT_TASK` 处硬件超时。

## 已验证项目

- NPU 设备存在：`/dev/vipcore`。
- 当前系统：Debian 13，内核 `6.6.98-4-aw2511`。
- 当前内核 NPU 驱动日志：`2.0.3.4-AW-2025-10-27`。
- 已安装 Radxa Trixie 仓库的 `npu-runtime 2.0.3`；用户态库报告
  `2.0.3.4-AW-2025-05-16`。
- 官方预编译浮点 KWS Encoder 可以在 NPU 上运行。
- 自行转换的微型浮点算子可以运行。
- 自行转换的 uint8 算子、官方 int16 vocoder 和 int16 Zipformer 都会在
  `VIPDRV_WAIT_TASK` 超时。
- Zipformer int16 在 `1008 MHz`、`852 MHz`、`492 MHz` 均出现同样超时，
  已排除 NPU 频率和供电裕量是主要原因。
- 浮点 Zipformer 可以以约 `RTF 0.45` 执行，但三个子模型输出固定异常值，
  最终重复输出 `THAT`；浮点路线不是官方支持的 Zipformer 部署路线。
- 外部句柄缓冲区与运行库自管缓冲区均得到相同结果，已排除应用层缓存或
  缓冲区映射是主要原因。

## 关键日志

- `outputs/zipformer-npu-int16-radxa-runtime.log`
- `outputs/zipformer-npu-int16-852mhz.log`
- `outputs/zipformer-npu-int16-492mhz.log`
- `outputs/zipformer-npu-radxa-runtime.log`
- `outputs/zipformer-npu-default-buffer.log`
- `outputs/zipformer-npu-float-dump.log`

## 已准备的官方兼容内核

已从 Radxa 的 A733 Bullseye 仓库下载但**尚未安装**：

`tmp-workspace/radxa-kernel-5.15/linux-image-5.15.147-21-a733_5.15.147-21_arm64.deb`

SHA-256：

`1d475a303f1a1a618028a4082be5c9dc0fd08f969c09741a5ed990c4abd3b75a`

该包包含 A7A DTB 和对应的 `vipcore.ko`，与官方 Zipformer 的 Debian 11
验证路线一致。当前 6.6.98 内核必须保留为回退启动项。

## 下一步

1. 安装 5.15.147-21 内核，使其与现有 6.6.98 并存。
2. 确认 `/boot/extlinux/extlinux.conf` 同时包含新旧两个启动项，并继续保留
   6.6.98 回退项。
3. 将 5.15.147-21 设为一次性/测试启动项后重启。
4. 确认 SSH、音频、存储和 `/dev/vipcore` 正常。
5. 先运行微型量化算子，再运行官方 int16 Zipformer 测试音频。
6. NPU 验证通过后，再实现 `cet6_listener.asr` 的 Zipformer 后端并接入现有
   文件音频流水线；Whisper 后端继续保留为回退。

内核安装和重启存在失去远程连接的风险，执行前需要用户明确确认，并建议
具备串口、显示器键盘或可操作 U-Boot 菜单中的任一恢复手段。
