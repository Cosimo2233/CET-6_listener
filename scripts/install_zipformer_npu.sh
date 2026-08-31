#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE_DIR="${1:-${HOME}/npu_demos/zipformer_demo_linux_a733}"
TARGET_RUNTIME="${PROJECT_ROOT}/runtime/zipformer-a733"
TARGET_MODEL="${PROJECT_ROOT}/model-bin/zipformer-a733"

if [[ ! -f "${SOURCE_DIR}/zipformer_demo_a733" ]]; then
  echo "缺少 ${SOURCE_DIR}/zipformer_demo_a733" >&2
  echo "请先按瑞莎 A7A Zipformer 文档构建并部署 zipformer_demo_linux_a733。" >&2
  exit 1
fi

if ! "${SOURCE_DIR}/zipformer_demo_a733" -h 2>&1 | grep -q -- "--stdin"; then
  echo "该 zipformer_demo_a733 不支持 --stdin，请使用瑞莎离线语音助手要求的新版程序。" >&2
  exit 1
fi

for name in encoder_int16_a733.nb decoder_int16_a733.nb joiner_int16_a733.nb; do
  if [[ ! -f "${SOURCE_DIR}/model/${name}" ]]; then
    echo "缺少 ${SOURCE_DIR}/model/${name}" >&2
    exit 1
  fi
done
if [[ ! -f "${SOURCE_DIR}/model/tokens.txt" ]]; then
  echo "缺少 ${SOURCE_DIR}/model/tokens.txt" >&2
  exit 1
fi

mkdir -p "${TARGET_RUNTIME}/lib" "${TARGET_MODEL}"
cp "${SOURCE_DIR}/zipformer_demo_a733" "${TARGET_RUNTIME}/zipformer_demo_a733"
chmod +x "${TARGET_RUNTIME}/zipformer_demo_a733"
cp "${SOURCE_DIR}/model/encoder_int16_a733.nb" "${TARGET_MODEL}/encoder_int16_a733.nb"
cp "${SOURCE_DIR}/model/decoder_int16_a733.nb" "${TARGET_MODEL}/decoder_int16_a733.nb"
cp "${SOURCE_DIR}/model/joiner_int16_a733.nb" "${TARGET_MODEL}/joiner_int16_a733.nb"
cp "${SOURCE_DIR}/model/tokens.txt" "${TARGET_MODEL}/tokens.txt"
if [[ ! -e "${TARGET_RUNTIME}/model" ]]; then
  ln -s "../../model-bin/zipformer-a733" "${TARGET_RUNTIME}/model"
fi
if [[ -d "${SOURCE_DIR}/lib" ]]; then
  cp "${SOURCE_DIR}/lib/"*.so* "${TARGET_RUNTIME}/lib/" 2>/dev/null || true
fi

echo "Zipformer A733 NPU 已安装到："
echo "  程序：${TARGET_RUNTIME}/zipformer_demo_a733"
echo "  模型：${TARGET_MODEL}"
echo "运行检查：poetry run cet6-listener check --asr zipformer-npu"
