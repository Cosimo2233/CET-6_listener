#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
  cat <<'EOF'
用法：scripts/test_translation.sh AUDIO [START_SECONDS] [DURATION_SECONDS]

从本地音频截取一段，按原始节奏翻译，并把原文、译文打印到终端。
默认从第 0 秒开始，测试 120 秒；不调用 TTS。
相对路径以仓库根目录为基准，输出保存在 outputs/translation/ 的独立目录。

示例：
  bash scripts/test_translation.sh data-bin/audio/test.mp3 60 120
EOF
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  usage
  exit 0
fi
if (($# < 1 || $# > 3)); then
  usage >&2
  exit 2
fi

source "$(dirname "${BASH_SOURCE[0]}")/lib/environment.sh"
cd "$CET6_PROJECT_ROOT"

audio="$1"
start_seconds="${2:-0}"
duration_seconds="${3:-120}"
config_file="${CET6_CONFIG:-config/default.yaml}"
[[ -f "$audio" ]] || { printf '音频不存在：%s\n' "$audio" >&2; exit 2; }
[[ -f "$config_file" ]] || { printf '配置不存在：%s\n' "$config_file" >&2; exit 2; }
command -v ffmpeg >/dev/null 2>&1 || { printf '缺少 FFmpeg。\n' >&2; exit 1; }

cet6_python - "$start_seconds" "$duration_seconds" <<'PY'
import math
import sys

try:
    start, duration = map(float, sys.argv[1:])
    if not math.isfinite(start) or not math.isfinite(duration) or start < 0 or duration <= 0:
        raise ValueError
except ValueError:
    raise SystemExit("开始时间必须是非负秒数，时长必须是正秒数。")
PY

mkdir -p outputs/translation
output_dir="$(mktemp -d "${CET6_PROJECT_ROOT}/outputs/translation/$(date -u +%Y%m%dT%H%M%SZ).XXXXXX")"
ffmpeg -nostdin -hide_banner -loglevel error \
  -ss "$start_seconds" -i "$audio" -t "$duration_seconds" \
  -ar 16000 -ac 1 -c:a pcm_s16le "${output_dir}/input.wav"

cet6_python - "$config_file" "$output_dir" "$audio" "$start_seconds" "$duration_seconds" <<'PY'
import json
import shutil
import sys
from pathlib import Path

import yaml

config_path, output, audio, start, duration = sys.argv[1:]
output_dir = Path(output)
config = yaml.safe_load(Path(config_path).read_text(encoding="utf-8")) or {}
config.setdefault("audio", {})["ffmpeg_binary"] = shutil.which("ffmpeg")
config.setdefault("logging", {})["output_dir"] = str(output_dir)
(output_dir / "config.yaml").write_text(
    yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8"
)
(output_dir / "input.json").write_text(
    json.dumps({
        "source_audio": str(Path(audio).resolve()),
        "clip_start_seconds": float(start),
        "requested_duration_seconds": float(duration),
        "realtime_input": True,
        "tts_enabled": False,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
)
PY

export PYTHONUNBUFFERED=1
printf '测试输出目录：%s\n' "$output_dir"
bash scripts/run_listener.sh translate \
  --audio "${output_dir}/input.wav" \
  --config "${output_dir}/config.yaml" \
  --dry-run 2>&1 | tee "${output_dir}/terminal.log"
