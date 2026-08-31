# CET-6 Listener

在瑞莎 A7A 6GB 开发板上本地运行的英语听力辅助系统。程序既可以从本地音频文件持续转写英文，在识别到六级题目后生成中文答案，也可以把每个英语语音段实时翻译成中文，并通过 gRPC TTS 流式播放。

当前版本默认使用 CPU 上的 whisper.cpp，也支持瑞莎 Cubie A7A 的 Vivante VIP9000 NPU Zipformer 后端。GUI、麦克风、Line-in 和 RAG 暂未包含。答案生成包含基于历年题型归纳的问题意图提示和证据窗口，但仍不能代替正式答案。

## 工作流程

```text
音频文件 → FFmpeg → VAD → whisper.cpp / Zipformer NPU → 题目检测
                                      ↓
ALSA ← gRPC 流式 TTS ← 中文答案 ← llama.cpp/Qwen

音频文件 → FFmpeg → VAD → whisper.cpp → Qwen 中文翻译
                                            ↓
                             ALSA ← gRPC 流式 TTS
```

音频/ASR、问题/LLM 和 TTS 分别运行在异步任务中。上下文和任务队列均有固定上限，LLM 或 TTS 不会阻塞文件音频读取。

## 环境要求

- ARM64 Linux（当前测试环境为 Debian 13）
- Python 3.11
- Poetry 2.x
- FFmpeg、ALSA 工具、Git、CMake 和 C/C++ 工具链
- 约 2GB 模型存储空间

安装系统依赖：

```bash
sudo apt update
sudo apt install -y build-essential cmake git curl ffmpeg alsa-utils
```

初始化 Python 环境：

```bash
poetry env use /usr/local/bin/python3.11
poetry install
./scripts/generate_protos.sh
```

## 构建推理服务和下载模型

脚本会将固定提交的 llama.cpp、whisper.cpp 编译到 `runtime/bin/`：

```bash
./scripts/bootstrap_native.sh
./scripts/download_models.sh
```

默认模型路径：

```text
model-bin/ggml-base.en.bin
model-bin/qwen2.5-1.5b-instruct-q4_k_m.gguf
```

`model-bin/`、`data-bin/`、`runtime/` 和 `outputs/` 不提交 Git。

## A7A NPU Zipformer（可选）

Cubie A7A 使用 Allwinner A733 的 Vivante VIP9000，不使用 RKNN。NPU 后端依赖瑞莎官方 A733 Zipformer 示例中的 `zipformer_demo_a733 --stdin`、VIPLite 库，以及 encoder、decoder、joiner 三个 INT16 NBG 模型。

先按瑞莎官方文档构建并部署 `zipformer_demo_linux_a733`，然后安装到本项目：

```bash
./scripts/install_zipformer_npu.sh ~/npu_demos/zipformer_demo_linux_a733
poetry run cet6-listener check --asr zipformer-npu
```

运行和基准测试：

```bash
poetry run cet6-listener benchmark-asr --asr zipformer-npu --audio data-bin/audio/test.mp3
poetry run cet6-listener run --asr zipformer-npu --audio data-bin/audio/test.mp3 --dry-run
```

默认仍是 `whisper_cpp`，只有显式传入 `--asr zipformer-npu` 或设置 `ASR_BACKEND=zipformer_npu` 才会启用 NPU。这样可以对同一份六级音频做盲测，也可以在 NPU 资源缺失时继续使用 Whisper。

## 配置

复制环境变量示例：

```bash
cp .env.example .env
```

完整默认值在 `config/default.yaml`。环境变量可覆盖常用地址和模型路径：

```dotenv
CET6_CONFIG=config/default.yaml
ASR_MODEL_PATH=model-bin/ggml-base.en.bin
ASR_BACKEND=whisper_cpp
LLM_MODEL_PATH=model-bin/qwen2.5-1.5b-instruct-q4_k_m.gguf
TTS_TARGET=39.106.1.132:30032
TTS_VOICE_ID=
TTS_LANGUAGE=Chinese
```

未配置 `TTS_VOICE_ID` 时，程序从服务返回的可用音色中选择第一个中文音色。模型路径、线程数、VAD 阈值、超时、上下文长度和队列容量都可以在 YAML 中调整。

## 使用

先检查环境：

```bash
poetry run cet6-listener check
```

将测试音频放入 `data-bin/audio/` 后运行：

```bash
poetry run cet6-listener run --audio data-bin/audio/test.mp3 --dry-run
poetry run cet6-listener run --audio data-bin/audio/test.mp3
```

`--dry-run` 仍会执行 ASR 和 LLM，但只在终端输出答案，不调用 TTS。`--fast` 会尽快读取音频，用于离线回归，不保持真实播放速度。

### 实时翻译并播报

按音频原始时间播放英语输入；每个 VAD 语音段识别完成后立即翻译为中文并调用 TTS：

```bash
poetry run cet6-listener translate --audio data-bin/audio/test.mp3
```

只检查英语转写和中文译文，不连接 TTS：

```bash
poetry run cet6-listener translate --audio data-bin/audio/test.mp3 --dry-run
```

快速离线跑完整个文件：

```bash
poetry run cet6-listener translate --audio data-bin/audio/test.mp3 --fast --dry-run
```

翻译模式保持语音段原始顺序，日志使用 `SOURCE:` 和 `TRANSLATION:` 输出双语文本。默认每段最长 20 秒，遇到 600 ms 静音后开始识别；可通过 `vad.max_speech_seconds` 和 `vad.silence_ms` 调整粒度。`translation.max_tokens`、`max_characters` 和 `queue_size` 控制译文长度与队列容量。

其他命令：

```bash
poetry run cet6-listener list-voices
poetry run cet6-listener test-tts --text "因为航班延误"
poetry run cet6-listener benchmark-asr --audio data-bin/audio/test.mp3
poetry run cet6-listener benchmark-asr --asr zipformer-npu --audio data-bin/audio/test.mp3
poetry run cet6-listener benchmark-llm
poetry run pytest
```

### 批量运行全部听力

默认按年份、月份和套题顺序，以快速离线模式运行 `data-bin/audio` 下所有
`*_听力` 音频。该模式会输出 ASR、问题和中文答案，但不会调用 TTS，也不会读取答案解析文件：

```bash
bash scripts/run_all_listening.sh
```

让任务脱离当前终端自动运行：

```bash
nohup bash scripts/run_all_listening.sh > outputs/run-all-launch.log 2>&1 &
```

查看实时进度和最终汇总：

```bash
tail -f outputs/run-all-launch.log
cat "$(cat outputs/batch/latest.txt)/summary.tsv"
```

每套题的独立日志保存在本次输出目录的 `cases/` 下，合并终端日志为
`terminal.log`。指定同一个输出目录并添加 `--resume` 可以跳过已成功完成的套题。

## 日志和性能数据

终端和 `outputs/cet6-listener.log` 会记录：

- ASR 时间戳与转写文本
- 听力状态和回答状态
- 检测到的问题及上下文词数
- 每题完整上下文到候选证据窗口的词数变化
- LLM 原始输出和清洗结果
- LLM 首 token、生成、TTS 首播和播放耗时
- 音频时长、总运行时长、实时率、问题数和答案数

当前版本会对主体、答案类型、逻辑方向和相关证据做约束，但不把答案正确率或三秒延迟作为硬门槛。

## 测试

```bash
poetry run pytest -q
```

单元测试不要求模型或远端服务。集成测试使用 fake ASR、LLM 和 TTS 验证异步管线、队列、超时及清理行为。真实音频测试需要先完成原生程序构建和模型下载。

## 常见问题

### `MISSING whisper-server` 或 `MISSING llama-server`

运行 `./scripts/bootstrap_native.sh`。如果提示没有 CMake，先安装系统构建依赖。

### TTS 显示 `UNAVAILABLE` 或 `Socket closed`

确认 `TTS_TARGET`、服务运行状态、防火墙和当前设备访问权限。TTS 不可用时可以先用 `--dry-run` 验证 ASR 与 LLM。

### 没有检测到问题

先检查 `[ASR]` 日志是否包含 `Question 1` 或完整英文问句，再调整 `vad.rms_threshold` 和 `vad.silence_ms`。首版检测依赖转写题号、疑问句式和静音边界。

### ASR 跟不上音频

运行 `benchmark-asr` 查看实时率。优先减少 ASR 线程竞争、检查 CPU 温度和频率，或继续使用 `base.en`；不要在没有基准数据时直接切换到 `small.en`。

### 内存持续上升

检查日志中的队列满载警告。上下文默认限制为700词，问题和答案队列默认最多4项；若修改这些值，应重新做长时间运行测试。LLM 首次请求会从长材料中抽取问题相关句及邻句，失败后再使用更小的证据窗口重试。日志中的 `[EVIDENCE]` 会显示裁剪前后的词数。
