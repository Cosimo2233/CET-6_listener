#!/usr/bin/env bash
set -euo pipefail

project_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
model_dir="$project_root/model-bin"
mkdir -p "$model_dir"

download() {
  local url=$1
  local destination=$2
  if [[ -s "$destination" ]]; then
    echo "已存在：$destination"
    return
  fi
  curl --fail --location --continue-at - --output "$destination.part" "$url"
  mv "$destination.part" "$destination"
}

download \
  "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.en.bin" \
  "$model_dir/ggml-base.en.bin"
download \
  "https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/qwen2.5-1.5b-instruct-q4_k_m.gguf" \
  "$model_dir/qwen2.5-1.5b-instruct-q4_k_m.gguf"

echo "模型下载完成：$model_dir"
