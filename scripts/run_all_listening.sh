#!/usr/bin/env bash
set -Eeuo pipefail

source "$(dirname "${BASH_SOURCE[0]}")/lib/environment.sh"
PROJECT_ROOT="$CET6_PROJECT_ROOT"
AUDIO_DIR="${PROJECT_ROOT}/data-bin/audio"
CONFIG_FILE="${PROJECT_ROOT}/config/default.yaml"
OUTPUT_DIR=""
ASR_BACKEND="whisper-cpp"
FAST_MODE=1
DRY_RUN=1
RESUME=0
LIST_ONLY=0
LIMIT=0

usage() {
  cat <<'EOF'
用法：scripts/run_all_listening.sh [选项]

自动按 年份 -> 月份 -> 套题 顺序运行所有 *_听力 音频，并保存完整终端日志。
脚本只读取音频文件，不读取同目录中的答案解析 Markdown。

选项：
  --audio-dir DIR      音频目录（默认：data-bin/audio）
  --config FILE        配置文件（默认：config/default.yaml）
  --output-dir DIR     本次输出目录（默认：outputs/batch/<UTC时间>）
  --asr BACKEND        ASR 后端（默认：whisper-cpp）
  --realtime           按音频真实时间运行（默认使用 --fast）
  --with-tts           启用 TTS 和 ALSA 播放（默认使用 --dry-run）
  --resume             跳过输出目录中已经成功完成的套题
  --limit N            只运行排序后的前 N 套；0 表示全部
  --list               只打印运行顺序，不执行
  -h, --help           显示帮助

推荐后台运行：
  nohup bash scripts/run_all_listening.sh > outputs/run-all-launch.log 2>&1 &
EOF
}

die() {
  printf '错误：%s\n' "$*" >&2
  exit 2
}

while (($#)); do
  case "$1" in
    --audio-dir)
      (($# >= 2)) || die "--audio-dir 缺少参数"
      AUDIO_DIR="$2"
      shift 2
      ;;
    --config)
      (($# >= 2)) || die "--config 缺少参数"
      CONFIG_FILE="$2"
      shift 2
      ;;
    --output-dir)
      (($# >= 2)) || die "--output-dir 缺少参数"
      OUTPUT_DIR="$2"
      shift 2
      ;;
    --asr)
      (($# >= 2)) || die "--asr 缺少参数"
      ASR_BACKEND="$2"
      shift 2
      ;;
    --realtime)
      FAST_MODE=0
      shift
      ;;
    --with-tts)
      DRY_RUN=0
      shift
      ;;
    --resume)
      RESUME=1
      shift
      ;;
    --limit)
      (($# >= 2)) || die "--limit 缺少参数"
      [[ "$2" =~ ^[0-9]+$ ]] || die "--limit 必须是非负整数"
      LIMIT="$2"
      shift 2
      ;;
    --list)
      LIST_ONLY=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      die "未知参数：$1"
      ;;
  esac
done

[[ -d "$AUDIO_DIR" ]] || die "音频目录不存在：$AUDIO_DIR"
[[ -f "$CONFIG_FILE" ]] || die "配置文件不存在：$CONFIG_FILE"
command -v sort >/dev/null 2>&1 || die "找不到 sort"
command -v flock >/dev/null 2>&1 || die "找不到 flock（通常由 util-linux 提供）"

AUDIO_DIR="$(cd "$AUDIO_DIR" && pwd)"
CONFIG_FILE="$(cd "$(dirname "$CONFIG_FILE")" && pwd)/$(basename "$CONFIG_FILE")"

mapfile -d '' AUDIO_FILES < <(
  find "$AUDIO_DIR" -maxdepth 1 -type f \
    \( -iname '*_听力.mp3' -o -iname '*_听力.wav' -o -iname '*_听力.m4a' -o -iname '*_听力.flac' \) \
    -print0 | sort -zV
)

((${#AUDIO_FILES[@]} > 0)) || die "没有找到 *_听力 音频：$AUDIO_DIR"
if ((LIMIT > 0 && LIMIT < ${#AUDIO_FILES[@]})); then
  AUDIO_FILES=("${AUDIO_FILES[@]:0:LIMIT}")
fi

printf '共发现 %d 套听力，运行顺序：\n' "${#AUDIO_FILES[@]}"
for index in "${!AUDIO_FILES[@]}"; do
  printf '  %02d. %s\n' "$((index + 1))" "$(basename "${AUDIO_FILES[$index]}")"
done

((LIST_ONLY == 0)) || exit 0

if [[ -z "$OUTPUT_DIR" ]]; then
  OUTPUT_DIR="${PROJECT_ROOT}/outputs/batch/$(date -u +%Y%m%dT%H%M%SZ)"
fi
mkdir -p "$OUTPUT_DIR/cases"
OUTPUT_DIR="$(cd "$OUTPUT_DIR" && pwd)"

LOCK_FILE="${PROJECT_ROOT}/outputs/.run-all-listening.lock"
mkdir -p "$(dirname "$LOCK_FILE")"
exec 9>"$LOCK_FILE"
flock -n 9 || die "已有一个全量听力测试正在运行"

MASTER_LOG="${OUTPUT_DIR}/terminal.log"
SUMMARY_FILE="${OUTPUT_DIR}/summary.tsv"
SUCCESS_DIR="${OUTPUT_DIR}/.success"
mkdir -p "$SUCCESS_DIR"

if [[ ! -s "$SUMMARY_FILE" ]]; then
  printf 'index\tcase\tstatus\texit_code\telapsed_seconds\tlog\n' > "$SUMMARY_FILE"
fi
mkdir -p "${PROJECT_ROOT}/outputs/batch"
printf '%s\n' "$OUTPUT_DIR" > "${PROJECT_ROOT}/outputs/batch/latest.txt"

log() {
  printf '%s %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$*" | tee -a "$MASTER_LOG"
}

INTERRUPTED=0
on_signal() {
  INTERRUPTED=1
  log "[BATCH] 收到终止信号，将停止测试"
}
trap on_signal INT TERM

log "[BATCH] 开始；套题数=${#AUDIO_FILES[@]} asr=${ASR_BACKEND} fast=${FAST_MODE} dry_run=${DRY_RUN}"
log "[BATCH] 输出目录：${OUTPUT_DIR}"

passed=0
failed=0
skipped=0

for index in "${!AUDIO_FILES[@]}"; do
  ((INTERRUPTED == 0)) || break

  number="$((index + 1))"
  audio="${AUDIO_FILES[$index]}"
  filename="$(basename "$audio")"
  case_name="${filename%.*}"
  case_log="${OUTPUT_DIR}/cases/$(printf '%02d' "$number")_${case_name}.log"
  success_marker="${SUCCESS_DIR}/$(printf '%02d' "$number")_${case_name}"

  if ((RESUME == 1)) && [[ -f "$success_marker" ]]; then
    log "[BATCH] [${number}/${#AUDIO_FILES[@]}] 跳过已成功套题：${filename}"
    ((skipped += 1))
    continue
  fi

  log "[BATCH] [${number}/${#AUDIO_FILES[@]}] 开始：${filename}"
  started_epoch="$(date +%s)"
  command_args=(
    bash "${PROJECT_ROOT}/scripts/run_listener.sh" run
    --audio "$audio"
    --config "$CONFIG_FILE"
    --asr "$ASR_BACKEND"
  )
  ((FAST_MODE == 0)) || command_args+=(--fast)
  ((DRY_RUN == 0)) || command_args+=(--dry-run)

  set +e
  (
    cd "$PROJECT_ROOT"
    PYTHONUNBUFFERED=1 "${command_args[@]}"
  ) 2>&1 | tee -a "$case_log" "$MASTER_LOG"
  exit_code="${PIPESTATUS[0]}"
  set -e

  ended_epoch="$(date +%s)"
  elapsed="$((ended_epoch - started_epoch))"
  if ((exit_code == 0)); then
    status="PASS"
    : > "$success_marker"
    ((passed += 1))
  else
    status="FAIL"
    ((failed += 1))
  fi
  printf '%s\t%s\t%s\t%s\t%s\t%s\n' \
    "$number" "$case_name" "$status" "$exit_code" "$elapsed" "$case_log" >> "$SUMMARY_FILE"
  log "[BATCH] [${number}/${#AUDIO_FILES[@]}] ${status}；exit=${exit_code} elapsed=${elapsed}s"
done

log "[BATCH] 完成；成功=${passed} 失败=${failed} 跳过=${skipped} 中断=${INTERRUPTED}"
log "[BATCH] 汇总：${SUMMARY_FILE}"

if ((INTERRUPTED != 0)); then
  exit 130
fi
if ((failed != 0)); then
  exit 1
fi
