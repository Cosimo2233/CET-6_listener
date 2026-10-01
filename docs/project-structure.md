# 项目结构与目录约定

本文描述当前工程结构。历史部署和硬件记录单独放在 `docs/archive/`，不能直接作为当前环境可用性的证明。

## 核心代码

Python 包位于 `src/cet6_listener/`，通过 `commands/app.py` 的 Typer 应用提供 `cet6-listener` 命令。保留现有模块边界，新增功能优先接入对应模块。

| 模块 | 职责 |
|---|---|
| `commands/` | CLI 参数解析、配置加载和组件组装 |
| `audio/` | FFmpeg 文件解码、PCM 音频帧、能量 VAD |
| `asr/` | ASR 接口、Whisper HTTP 客户端、可选 Zipformer NPU 客户端 |
| `transcript/` | 转写重叠去重、材料上下文和词数裁剪 |
| `detector/` | 题组、题号和问句检测，生成问题事件 |
| `llm/` | llama-server 生命周期、证据选择、Prompt、作答与翻译、输出清洗 |
| `tts/` | 远端 gRPC TTS、PCM 流校验和 ALSA 播放 |
| `protos/tts/` | TTS 协议及生成的 Python 代码；修改协议后运行生成脚本 |
| `pipeline/` | 作答与翻译两条异步流水线、状态和性能统计 |
| `domain/events.py` | 模块间传递的音频、转写、问题、答案、译文与播放事件 |
| `config.py` | YAML、`.env` 与环境变量加载、类型转换、参数校验 |
| `logging.py` | 终端和文件日志 |

两条流程：

```text
run:
文件 → FFmpeg → VAD → ASR → 上下文/题目检测 → 证据选择/Qwen → 答案 → 可选 TTS

translate:
文件 → FFmpeg → VAD → ASR → Qwen 翻译 → 中文译文 → 可选 TTS
```

默认只接收本地文件，按文件时间推进输入；`--fast` 取消时间等待，`--dry-run` 保留模型推理但跳过 TTS。实时输入节奏不保证实时输出，见 [真实翻译测试](translation-smoke-test.md)。

## 本地资源

| 目录 | 内容 | 恢复方式 |
|---|---|---|
| `data-bin/audio/` | MP3、WAV、M4A、FLAC 听力音频 | 手动放入；批测默认读取此目录 |
| `data-bin/answers/` | PDF、Markdown 等答案解析 | 手动放入，仅用于核对与评估，不进入推理上下文 |
| `model-bin/` | Whisper、Qwen 模型和可选 NPU 模型 | `bash scripts/download_models.sh`；NPU 需单独准备 |
| `runtime/bin/` | whisper-server、llama-server 的本地链接 | `bash scripts/bootstrap_native.sh` |
| `runtime/zipformer-a733/` | 可选 NPU runner 与 VIPLite 库 | `scripts/install_zipformer_npu.sh` |
| `third-party/` | 固定提交的 llama.cpp/whisper.cpp 源码及构建产物 | 构建脚本自动获取 |
| `outputs/` | 日志、批测汇总、测试音频、临时配置和结果 | 各运行脚本自动生成 |
| `.tools/` | 系统工具缺失时的本地工具副本 | 自行准备，不随 Git 分发 |
| `.venv/` | 项目 Python 环境 | `poetry install`，建议启用项目内虚拟环境 |

模型与原生服务路径沿用 `config/default.yaml` 和 `.env.example`，运行时相对路径基于仓库根目录。已经存在的模型不会因为目录整理而重新下载。

Git 只跟踪资源目录的 `.gitkeep`，不跟踪资源本身。新克隆的仓库有完整目录骨架，但没有音频、模型、原生程序、第三方源码或运行日志。`.env`、本机 `poetry.toml` 和 `.tools/` 也被忽略。

## 脚本职责

| 脚本 | 用途 |
|---|---|
| `scripts/bootstrap_native.sh` | 获取固定上游提交，编译并部署两个 CPU 推理服务 |
| `scripts/download_models.sh` | 下载默认 Whisper 与 Qwen 模型 |
| `scripts/generate_protos.sh` | 根据 TTS proto 生成客户端代码 |
| `scripts/install_zipformer_npu.sh` | 安装满足 stdin 协议的 A733 runner、模型及库 |
| `scripts/run_listener.sh` | 加载本地工具环境，进入根目录，启动任意 CLI 子命令 |
| `scripts/run_all_listening.sh` | 按自然顺序批测 `data-bin/audio/`，支持续跑与单套日志 |
| `scripts/test_translation.sh` | 截取指定片段，按实时节奏翻译并打印、保存终端输出 |
| `scripts/lib/environment.sh` | 共用的项目根目录、Python 环境及可选本地工具加载 |

`run_listener.sh` 优先使用 `.venv/bin/python`，否则使用 `poetry run python`。共用环境脚本只在 PATH 找不到对应工具时，尝试 `.tools/cmake/usr/` 或 `.tools/ffmpeg/usr/`；同时加载其中的架构动态库目录。系统依赖安装仍以 README 为准。

## 测试、配置和文档

- `tests/unit/` 测试配置、VAD、ASR 协议、检测、证据选择、输出清洗、状态和 TTS。
- `tests/integration/` 使用模拟组件验证两条异步流水线，不需要真实模型或远端服务。
- `config/default.yaml` 保存默认参数，`.env.example` 列出可覆盖的环境变量。
- `.vscode/launch.json` 提供作答、翻译、Pytest 调试入口；音频路径通过输入框指定。
- `docs/historical-listening-patterns.md` 保存通用题型和证据规则。
- `docs/translation-smoke-test.md` 保存最近一次真实翻译验证的范围、结果和限制。
- `docs/archive/` 保存带日期的历史交接与 NPU 诊断。

从仓库根目录执行：

```bash
poetry run pytest -q
bash scripts/run_all_listening.sh --list
bash scripts/run_listener.sh translate --audio data-bin/audio/test.mp3 --dry-run
bash scripts/test_translation.sh data-bin/audio/test.mp3 60 120
```

批测输出使用 `outputs/batch/`；翻译片段测试使用 `outputs/translation/`。之前的 `outputs/translation-smoke/` 保留为本地测试基线，不覆盖。
