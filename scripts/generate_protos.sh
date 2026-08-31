#!/usr/bin/env bash
set -euo pipefail

project_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$project_root"

poetry run python -m grpc_tools.protoc \
  -I src \
  --python_out=src \
  --grpc_python_out=src \
  src/cet6_listener/protos/tts/tts.proto \
  src/cet6_listener/protos/tts/preset_voice.proto
