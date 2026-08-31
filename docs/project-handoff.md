# 瑞莎 A7A 六级听力助手：项目交接说明

> 状态快照：2026-08-30。本文件用于把项目交给新的对话或开发者；内容以当前工作区的实际代码、配置和批测结果为准。

## 1. 项目目标

本项目在瑞莎 Cubie A7A 6GB 开发板上运行一个英语六级听力辅助系统。当前主流程读取本地 MP3/WAV 等音频，实时或快速离线地完成：

```text
音频文件 → FFmpeg 解码 → 能量 VAD → whisper.cpp 英文 ASR
         → 材料上下文/问题检测 → Qwen2.5-1.5B 中文作答
         → （可选）远端 gRPC 流式 TTS → ALSA 播放

实时翻译模式：

音频文件 → FFmpeg 解码 → 能量 VAD → whisper.cpp 英文 ASR
         → Qwen2.5-1.5B 中文翻译 → 远端 gRPC 流式 TTS → ALSA 播放
```

系统输出的是便于听题时理解的中文语义答案，不输出 A/B/C/D 选项字母，也不能视为官方标准答案。

### 当前范围

- 支持本地音频文件。
- 默认使用 CPU `whisper.cpp base.en`。
- LLM 使用 CPU `llama.cpp + Qwen2.5-1.5B-Instruct Q4_K_M`。
- TTS 使用远端 gRPC 流式 PCM 服务。
- 支持快速离线盲测、逐套日志、总日志和批测汇总。
- 支持按 VAD 语音段实时翻译并顺序播报，也支持 `--dry-run` 双语日志。
- 已预留 A733 Zipformer NPU 后端，但尚不能投入运行。

### 暂不包含

- 麦克风和 Line-in。
- 扬声器回声消除。
- GUI。
- RAG 或联网检索。
- 自动选择题字母映射。
- 可靠的说话人分离。

## 2. 当前验证状态

| 项目 | 状态 | 说明 |
|---|---|---|
| Poetry/Python 环境 | 可用 | Python 3.11.16，Poetry 2.4.1 |
| FFmpeg 文件解码 | 可用 | 16 kHz、单声道、PCM S16LE、20 ms 帧 |
| whisper.cpp ASR | 可用 | 12 套真实六级听力均跑完 |
| llama.cpp/Qwen | 可用 | 可输出中文答案，但部分题会因超时或格式校验失败被跳过 |
| gRPC TTS 连通性 | 可用 | 2026-08-30 `list-voices` 成功，返回 100 个中文音色 |
| TTS 全量批测 | 未执行 | 最近 12 套批测使用 `--dry-run`，没有播放声音 |
| Zipformer A733 NPU | 暂停 | 缺少三个 A733 `.nb`，官方 demo 也没有项目所需的 `--stdin` 协议 |
| 自动化测试 | 通过 | `56 passed` |
| Git 状态 | 注意 | 当前目录没有 `.git`，不是 Git working tree |

硬件与系统快照：

```text
Board:  Radxa Cubie A7A, 6 GB RAM
Arch:   aarch64
Kernel: Linux 6.6.98-4-aw2511
NPU:    /dev/vipcore 存在，权限 crw-rw-rw-
```

## 3. 工程结构

```text
CET-6/
├── pyproject.toml                  # Poetry 项目及 cet6-listener 入口
├── poetry.lock
├── README.md                       # 面向使用者的中文说明
├── .env.example
├── config/default.yaml             # 默认参数
├── docs/
│   ├── project-handoff.md           # 本交接文档
│   └── historical-listening-patterns.md
├── src/cet6_listener/
│   ├── commands/app.py             # Typer CLI
│   ├── audio/                      # FFmpeg 文件源、PCM 帧、能量 VAD
│   ├── asr/                        # ASR 协议、Whisper、Zipformer 后端
│   ├── transcript/                 # 上下文和重叠文本去重
│   ├── detector/                   # 题组、题号和问句检测
│   ├── llm/                        # llama-server、证据选择、Prompt、清洗
│   ├── tts/                        # gRPC TTS 和 aplay 流式播放
│   ├── protos/tts/                 # TTS proto 与生成代码
│   ├── pipeline/                   # 异步流水线与状态
│   ├── domain/events.py            # 公共事件类型
│   ├── config.py                   # YAML/.env 配置
│   └── logging.py
├── scripts/
│   ├── bootstrap_native.sh         # 固定提交编译 llama.cpp/whisper.cpp
│   ├── download_models.sh          # 下载 Whisper 与 Qwen 模型
│   ├── generate_protos.sh
│   ├── install_zipformer_npu.sh    # 安装满足协议的 NPU runner/模型
│   └── run_all_listening.sh        # 自动运行全部听力并导出日志
├── tests/{unit,integration}/
├── data-bin/audio/                 # 用户音频和答案解析，Git 忽略
├── model-bin/                      # 模型，Git 忽略
├── runtime/                        # 本地二进制/动态库，Git 忽略
├── outputs/                        # 日志和批测结果，Git 忽略
├── third-party/                    # llama.cpp/whisper.cpp，Git 忽略
└── tmp-workspace/                  # NPU 调研临时文件，Git 忽略
```

Poetry 入口：

```toml
cet6-listener = "cet6_listener.commands.app:app"
```

没有根目录 `main.py`，所有操作统一通过 `poetry run cet6-listener ...`。

## 4. Python 与模型环境

Poetry 虚拟环境不在项目内，所以看不到根目录 `.venv`：

```text
/home/radxa/.cache/pypoetry/virtualenvs/cet6-listener-P2qjfY07-py3.11
```

重新绑定和安装依赖：

```bash
poetry env use /usr/local/bin/python3.11
poetry install
```

当前模型：

| 模型 | 路径 | 大小 |
|---|---|---:|
| Whisper base.en | `model-bin/ggml-base.en.bin` | 约 142 MB |
| Qwen2.5-1.5B Q4_K_M | `model-bin/qwen2.5-1.5b-instruct-q4_k_m.gguf` | 约 1.1 GB |

本地服务二进制：

```text
runtime/bin/whisper-server -> third-party/whisper.cpp/build/bin/whisper-server
runtime/bin/llama-server   -> third-party/llama.cpp/build/bin/llama-server
```

`scripts/bootstrap_native.sh` 固定的上游提交：

```text
llama.cpp:   d7bd3bfcad3e29c7e49fd26f38c79ee3e9a3fd6b
whisper.cpp: c4ac0012a8f5a2082dfca6aad4ddfd8b2c02b337
```

## 5. 各模块实际行为

### 5.1 音频与 VAD

`FileAudioSource` 启动 FFmpeg，将输入统一解码为 16 kHz、单声道、PCM S16LE，每帧 20 ms。

- 正常模式按时间戳等待，近似实时读取。
- `--fast` 不等待，用于离线回归。
- VAD 是 RMS 能量阈值实现，不是神经网络 VAD。
- 默认阈值 450，保留 200 ms 语音前缀。
- 连续 600 ms 静音或语音段达到 20 秒时输出一个 `SpeechSegment`。

### 5.2 ASR

默认 `WhisperCppBackend`：

- 自动启动 `whisper-server`，端口 `8178`。
- 模型只在单个音频任务开始时加载一次，不会逐题加载。
- 每个 VAD 语音段封装为 WAV，通过 `/inference` 请求识别。
- 仅发布 final transcript。

另有 `ZipformerNpuBackend`：

- 预期启动支持 `--stdin` 的常驻 `zipformer_demo_a733`。
- stdin 协议为：4 字节小端 PCM 字节数 + PCM；长度 0 表示一句结束。
- runner 应输出 `ASR_READY` 和 `TEXT=<识别结果>`。
- 会检查模型、词表、NPU 设备和 VIPLite 动态库。
- 当前只是接口实现，不能实际使用，详情见第 11 节。

### 5.3 上下文和问题检测

`TranscriptManager`：

- 默认最多保留最近 700 个英文词。
- 使用最长 16 词的首尾重叠消除重复转写。
- 新题组或新 conversation/passage/recording 会重置材料上下文。

`QuestionDetector`：

- 识别 `Question N`、英文数字题号以及典型疑问句式。
- 识别 `Questions X to Y are based on...` 题组提示。
- 问题文本不写回 passage，后续题复用同一材料。
- 无题号时可生成随机 8 位问题 ID。
- `pipeline.question_silence_ms` 虽然存在于配置中，但当前代码没有直接使用；实际边界主要来自 VAD 分段和问句规则。这是一个待清理或补实现的配置项。

### 5.4 LLM 作答

`LlamaCppClient` 自动启动 `llama-server`，端口 `8080`：

- context size 4096。
- 6 CPU 线程。
- `max_tokens=36`，temperature 0.2。
- 请求超时 30 秒。
- 使用流式 Chat Completions，记录首 token 时间。
- 开启 `cache_prompt`。

为了适配 1.5B 小模型，代码在发送 Prompt 前先做通用证据选择：

- 根据问题主题词、轻量词形归一、原因/结果/建议/态度/研究等关系词打分。
- 默认最多选择 8 句、260 词，并保留命中句的相邻句。
- 请求失败后缩到 6 句、180 词重试一次。
- 针对人物主体、原因、结果、建议、趋势、研究发现、主题题等生成通用 guidance。
- 包含有限的条件句和 `second group/former/latter` 指代处理。
- 规则来自跨年份题型规律，不包含某套题号或标准答案硬编码。

输出要求：

- 中文自然短句，理想长度 12～36 个中文字，清洗上限 48 字。
- 去除 Markdown、引号和“答案是”等前缀。
- 检测问题复述、非中文输出、提示泄漏和循环重复。
- 问题复述会重答一次，非中文答案会调用一次“忠实翻译”修复。
- 仍不合格时只跳过当前题，不停止 ASR 或整套测试。

历年题型归纳详见 `docs/historical-listening-patterns.md`。

### 5.5 TTS

服务地址：

```text
39.106.1.132:30032
```

这是 gRPC 服务，不是 HTTP WAV 服务。客户端行为：

- 启动时调用 `ListPresetVoices`。
- 配置 `TTS_VOICE_ID` 时验证音色；未配置时选择排序后的第一个中文音色。
- 根据服务 `serving_mode` 使用 `Synthesize` 或 `DuplexSynthesize`。
- 校验 PCM chunk 序号连续、采样率有效且不在流中变化。
- 第一块 PCM 到达时立即启动 `aplay -q -t raw -f S16_LE -c 1 -r <rate>`。
- 当前连通性检查成功，共返回 100 个中文音色。
- 最近的 12 套批测没有测试播放，因为使用了 `--dry-run`。

建议正式使用时显式配置 `TTS_VOICE_ID`，避免服务端音色排序变化导致声音改变。

### 5.6 异步流水线

公共事件包括：

```text
AudioFrame, SpeechSegment, TranscriptSegment, QuestionEvent,
AnswerEvent, PcmChunk, PlaybackEvent
```

状态分为：

```text
ListeningPhase: IDLE / PASSAGE / QUESTION
AnswerPhase:    IDLE / GENERATING / SPEAKING
```

流水线并行任务：

1. 音频读取。
2. VAD + ASR。
3. 问题检测。
4. LLM 生成。
5. TTS/播放，或 dry-run 打印答案。

默认队列：

| 队列 | 上限 | 满载行为 |
|---|---:|---|
| audio | 3000 帧（约 60 秒） | producer 等待 |
| transcript | 当前无显式上限 | 正常由 detector 持续消费 |
| question | 4 | 丢弃最旧未处理问题并报警 |
| answer | 4 | 丢弃最旧未处理答案并报警 |

12 套批测中没有出现 `[QUEUE]` 丢弃。

### 5.7 实时翻译模式

`cet6-listener translate` 复用文件音频、VAD、ASR、Qwen、gRPC TTS 和 ALSA 播放组件，但不进入题目检测和六级作答流程：

- 每个 VAD 语音段完成 ASR 后立即进入翻译队列。
- 专用翻译 Prompt 要求保留人物、数字、否定、语气和问句形式，不回答原文中的问题。
- 译文允许多句、数字和必要英文专名，不使用六级短答案的 48 字清洗规则。
- TTS 按语音段顺序播放；单段失败只记录错误，不终止后续翻译。
- `--dry-run` 输出 `SOURCE:` 和 `TRANSLATION:`，不连接 TTS。
- `--fast` 取消文件读取的实时等待，用于离线验证；默认模式按音频时间推进。

当前仍只支持本地音频文件，不包含麦克风或 Line-in。

## 6. 默认配置摘要

完整配置以 `config/default.yaml` 为准：

| 配置 | 当前值 |
|---|---|
| audio | 16000 Hz / mono / 20 ms |
| VAD | RMS 450 / prefix 200 ms / silence 600 ms / max 20 s |
| ASR | whisper_cpp / 4 threads / timeout 60 s |
| LLM | Qwen 1.5B Q4 / ctx 4096 / 6 threads / 36 tokens / timeout 30 s |
| passage context | 700 words |
| translation | English → Chinese / 128 tokens / 240 chars / queue 8 |
| TTS | `39.106.1.132:30032` / Chinese / timeout 30 s |
| logs | INFO / `outputs/` |

常用环境变量见 `.env.example`，包括 `ASR_*`、`LLM_*` 和 `TTS_*`。

## 7. CLI 与常用操作

环境检查：

```bash
poetry run cet6-listener check
```

单套快速盲测，不播放 TTS：

```bash
poetry run cet6-listener run \
  --audio data-bin/audio/CET6_2025年6月_第1套_听力.mp3 \
  --fast --dry-run
```

真实节奏并播放答案：

```bash
poetry run cet6-listener run \
  --audio data-bin/audio/CET6_2025年6月_第1套_听力.mp3
```

实时翻译并播放：

```bash
poetry run cet6-listener translate \
  --audio data-bin/audio/CET6_2025年6月_第1套_听力.mp3
```

快速验证翻译但不播放：

```bash
poetry run cet6-listener translate \
  --audio data-bin/audio/CET6_2025年6月_第1套_听力.mp3 \
  --fast --dry-run
```

其他命令：

```bash
poetry run cet6-listener list-voices
poetry run cet6-listener test-tts --text "因为航班延误"
poetry run cet6-listener benchmark-asr --audio <audio.mp3>
poetry run cet6-listener benchmark-llm
poetry run pytest -q
```

`check` 会同时检查 TTS；如果远端 TTS 临时不可用，`check` 会以失败码退出，但 `run --dry-run` 仍可验证 ASR 和 LLM。

## 8. 全量批测脚本

`scripts/run_all_listening.sh` 只匹配：

```text
*_听力.mp3 / *_听力.wav / *_听力.m4a / *_听力.flac
```

它不会读取同目录下的答案解析 Markdown。默认行为：

- 按年份、月份、套题进行自然排序。
- 使用 `whisper-cpp --fast --dry-run`。
- 一套失败后继续下一套。
- 每套保存独立日志，同时保存合并终端日志。
- 使用 `flock` 防止重复启动。
- 支持 `--resume`、`--limit`、`--list`、`--realtime` 和 `--with-tts`。

后台运行：

```bash
nohup bash scripts/run_all_listening.sh > outputs/run-all-launch.log 2>&1 &
```

查看：

```bash
tail -f outputs/run-all-launch.log
cat "$(cat outputs/batch/latest.txt)/summary.tsv"
```

注意：当前批处理会为每个音频重新启动并关闭 Whisper/Qwen。健康检查在 Qwen 加载期间短暂返回 HTTP 503 属正常现象，恢复 200 后继续运行。单套内部模型不会逐题重新加载。

## 9. 2023—2025 全量批测结果

数据范围：2023 年 6 月至 2025 年 12 月，共 12 套、理论 300 道听力题。批测期间不读取标准答案。

输出目录：

```text
outputs/batch/20260830T030945Z/
├── terminal.log
├── summary.tsv
├── cases/*.log
└── .success/*
```

总结果：

| 指标 | 结果 |
|---|---:|
| 套题流程 | 12/12 PASS |
| 总音频时长 | 20154.04 秒（约 5 小时 35 分） |
| 总处理墙钟时间 | 13406 秒（约 3 小时 43 分） |
| 加权 RTF | 0.664 |
| ASR transcript segments | 2541 |
| 检测问题数 | 302 |
| 生成答案数 | 284 |
| 相对检测问题的答案覆盖率 | 94.04% |
| question/answer 队列丢弃 | 0 |
| 单套峰值 RSS | 约 2.50～2.58 GB |

逐套结果：

| 套题 | RTF | 检测问题 | 生成答案 |
|---|---:|---:|---:|
| 2023-06 第1套 | 0.669 | 25 | 25 |
| 2023-06 第2套 | 0.665 | 25 | 22 |
| 2023-12 第1套 | 0.765 | 25 | 20 |
| 2023-12 第2套 | 0.658 | 25 | 24 |
| 2024-06 第1套 | 0.630 | 25 | 24 |
| 2024-06 第2套 | 0.606 | 25 | 25 |
| 2024-12 第1套 | 0.675 | 25 | 24 |
| 2024-12 第2套 | 0.640 | 26 | 24 |
| 2025-06 第1套 | 0.656 | 26 | 23 |
| 2025-06 第2套 | 0.655 | 25 | 24 |
| 2025-12 第1套 | 0.659 | 25 | 25 |
| 2025-12 第2套 | 0.695 | 25 | 24 |

解释：

- `PASS` 只表示该音频的整条流水线正常结束、资源正常关闭，不表示 25 题全部答出，更不表示答案正确。
- 理论应有 300 题，但检测到 302 题；2024-12 第2套和 2025-06 第1套各多触发一次，说明 detector 仍有少量误触发。
- 共有 18 个已检测问题没有产生最终答案。主要原因是严格中文校验、问题复述、夹杂英文、短数字答案和 LLM 请求连续失败。
- 示例：`1981年` 因中文字符不足被当前 `contains_chinese` 规则误判；一些实质上可用但含英文专名的答案也会被拒绝。
- 本次结果只证明稳定性与覆盖率，尚未计算答案准确率。

日志时间说明：批处理 `[BATCH]` 行固定使用 UTC（带 `Z`）；Python 日志使用系统本地时间。如果系统时区在运行中改变，两类时间看起来可能相差 8 小时，但不影响每套 `elapsed_seconds` 和 monotonic latency。

## 10. 测试情况

当前执行：

```text
56 passed in 0.78s
```

测试覆盖：

- 配置加载、环境变量和校验。
- VAD 和 PCM 分段。
- ASR 响应解析、NPU stdin 帧协议。
- transcript 重叠去重和上下文裁剪。
- 问题/题组检测。
- Prompt、证据选择、问题类型 guidance、输出清洗。
- 状态转换。
- TTS 音色选择、流式 PCM 序号和采样率校验。
- fake ASR/LLM/TTS 的异步流水线、队列和安全退出。
- 实时翻译 Prompt、译文清洗和 fake ASR/LLM/TTS 翻译播放流水线。

单元/集成测试不等同于真实答案准确率测试。

## 11. Zipformer NPU 调研状态

用户已经决定暂时不继续 NPU 路线，默认必须保持 `whisper_cpp`。

已完成：

- 下载并解压 Allwinner Model Zoo v1.0.0：
  `tmp-workspace/awnpu_model_zoo-v1.0.0-20260423-f562dd16/`
- 下载官方原始 ONNX：encoder 约 75 MB、decoder 约 14 MB、joiner 约 13 MB。
- 在 A7A 上成功编译官方 ARM64 demo：
  `tmp-workspace/build-zipformer-a733/zipformer_demo_a733`
- A733 VIPLite 库已放到 `runtime/zipformer-a733/lib/`。
- `/dev/vipcore` 可访问。

阻塞项：

1. Model Zoo 压缩包不包含：

   ```text
   encoder_int16_a733.nb
   decoder_int16_a733.nb
   joiner_int16_a733.nb
   ```

2. 官方要求在 x86 Linux 的 `ubuntu-npu:v2.0.10.2` 容器中量化并导出 A733 NBG；当前只有 ARM64 A7A，没有该转换环境。
3. 官方 demo 仅支持 `-i audio.wav`，不支持项目后端要求的常驻 `--stdin`、`ASR_READY`、`TEXT=` 协议。
4. 因此不要执行 `--asr zipformer-npu`，除非先生成 `.nb` 并完成 runner 改造。

## 12. 已知问题和优先级建议

### P0：建立答案正确率评估

当前只有流程覆盖率，没有准确率。建议从每套日志抽取 `QUESTION/ANSWER`，与答案解析的听力部分建立结构化对照。评估至少分成：

- 问题检测是否正确。
- ASR 是否保留关键证据。
- 证据选择是否选中正确句。
- LLM 答案语义是否正确。
- 输出清洗是否错误拒绝正确答案。

答案解析只能用于测试后的评分，不得进入同一次推理的 passage/Prompt。

### P1：降低 18 个答案缺失

优先修改 `llm/output_cleaner.py` 和 `llm/client.py`：

- 允许纯数字、年份、百分比等合法答案。
- 允许少量必要英文专名，而不是要求中文字符数大于等于拉丁字母数。
- 将“问题复述”和“包含问题背景的有效答案”分开判断。
- 请求连续失败时记录完整错误类型、尝试次数和证据长度。
- 考虑在修复失败后保留原始候选并标记低置信度，而不是直接丢题。

### P1：修复 302/300 问题误触发

定位第 8、9 套多出的事件，增强 detector 对材料内部疑问句与正式播报问题的区分。避免加入年份/题号专用规则，应使用题组状态、`Question N` 顺序和播报结构等通用特征。

### P1：减少批测重复加载和 HTTP 503 噪声

批处理当前每套重启 Whisper/Qwen，约 12 次加载。可以新增真正的多文件 batch 命令，让两个 server 在全部音频期间常驻；这会减少启动时间和健康检查 503 日志。

### P2：时延与资源竞争

快速模式下 Whisper（4 线程）和 Qwen（6 线程）会并行争用 A7A CPU，负载较高。应分别测试：

- ASR-only RTF。
- LLM 单题延迟。
- 端到端实时模式下的 Question End → first token。
- 调整 Whisper/Qwen 线程数后的吞吐、温度和答案完整率。

### P2：配置和实现清理

- 实现或删除未使用的 `pipeline.question_silence_ms`。
- 考虑给 transcript queue 设置上限。
- 明确批测日志统一使用 UTC 或 Asia/Shanghai。
- 初始化 Git 仓库或恢复原仓库元数据，避免后续无法审查 diff/提交。

### P2：TTS 实际播放验收

服务当前可列音色，但仍应单独执行一次：

```bash
poetry run cet6-listener test-tts --text "因为航班延误"
```

确认 A7A ALSA 输出设备、首 PCM 延迟、完整播放和进程清理。不要直接用 12 套全量测试做第一次播放验收。

## 13. 继续工作前的最短检查清单

```bash
cd /home/radxa/workspace/CET-6
poetry env info --path
poetry run pytest -q
poetry run cet6-listener check
cat outputs/batch/latest.txt
cat "$(cat outputs/batch/latest.txt)/summary.tsv"
```

如果下一步是优化准确率，先保存当前批测作为基线，不要覆盖：

```text
outputs/batch/20260830T030945Z/
```

新的优化必须保持跨年份通用，不能为某一套听力、某个题号或标准答案写特例。
