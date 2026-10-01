# 真实翻译测试记录

验证日期：2026-10-01。测试使用实际 Whisper、Qwen 模型，无模拟 ASR/LLM，不调用 TTS。

## 范围与结果

音频为 `CET6_2025年6月_第1套_听力.mp3`，截取原文件第 60～180 秒，按原始时间输入。目录整理后，原音频位于 `data-bin/audio/`。

| 指标 | 结果 |
|---|---:|
| 音频时长 | 120.00 秒 |
| 总运行时间（含模型加载） | 204.83 秒 |
| 实时率 RTF（总运行时间 / 音频时长） | 1.707 |
| ASR 语音段 | 16 |
| 产生译文的段数 | 16 |
| 单段 LLM 翻译耗时中位数 | 5.35 秒 |
| 单段 LLM 翻译最大耗时 | 49.24 秒 |
| 主进程及其子进程峰值 RSS | 2359.5 MiB |
| 运行退出码 | 0 |

原文和译文以 `SOURCE:`、`TRANSLATION:` 打印到终端。两个模型完成加载，测试结束后两个本地服务端口均关闭。

## 结论与限制

本次证明文件识别、逐段中文翻译、顺序输出及资源清理可以实际运行。16 段有输出不等于 16 段翻译正确：其中 `Question 1.` 被误译为“好的，请提供需要翻译的英语内容。”，输出校验没有拦截。

RTF 大于 1，本次处理慢于实时输入，出现积压；单段翻译耗时不包含等待队列和 ASR 的时间。这不是麦克风验证、完整套题准确率评估或 TTS 播放验收。

## 本地基线与复跑

原始输出保留在 Git 忽略的 `outputs/translation-smoke/`：

```text
input.wav         原始测试片段
config.yaml       测试使用的配置
terminal.log      完整终端日志
cet6-listener.log 程序日志
translations.txt  16 段双语文本
results.json      指标与双语结果
run.sh            当时的本地复跑入口
```

这些文件不随 Git 分发；只有本文记录进入版本控制。旧 `results.json` 中的音频路径是整理前的 `data-bin/` 根目录路径，原文件现已归入 `data-bin/audio/`。

使用仓库内的通用脚本重新测试：

```bash
bash scripts/test_translation.sh \
  data-bin/audio/CET6_2025年6月_第1套_听力.mp3 60 120
```

每次生成独立的 `outputs/translation/<UTC时间戳>.<随机后缀>/`，包含 `input.wav`、`input.json`、`config.yaml`、`cet6-listener.log` 与 `terminal.log`。输入不足指定时长时只截取实际可用部分，实际时长以最终 `[TRANSLATION_METRICS]` 为准。
