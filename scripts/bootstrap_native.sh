#!/usr/bin/env bash
set -euo pipefail

project_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
third_party_dir="$project_root/third-party"
runtime_bin="$project_root/runtime/bin"
llama_commit=d7bd3bfcad3e29c7e49fd26f38c79ee3e9a3fd6b
whisper_commit=c4ac0012a8f5a2082dfca6aad4ddfd8b2c02b337

command -v cmake >/dev/null || { echo "缺少 cmake，请先安装 cmake 和 build-essential。" >&2; exit 1; }
command -v git >/dev/null || { echo "缺少 git。" >&2; exit 1; }
mkdir -p "$third_party_dir" "$runtime_bin"

checkout_pinned_commit() {
  local repository_url=$1
  local destination=$2
  local commit=$3
  if [[ ! -d "$destination/.git" ]]; then
    mkdir -p "$destination"
    git -C "$destination" init
    git -C "$destination" remote add origin "$repository_url"
  fi
  git -C "$destination" fetch --depth 1 origin "$commit"
  git -C "$destination" checkout --detach FETCH_HEAD
}

checkout_pinned_commit https://github.com/ggml-org/llama.cpp.git "$third_party_dir/llama.cpp" "$llama_commit"
cmake -S "$third_party_dir/llama.cpp" -B "$third_party_dir/llama.cpp/build" -DCMAKE_BUILD_TYPE=Release -DLLAMA_CURL=OFF
cmake --build "$third_party_dir/llama.cpp/build" --config Release -j"$(nproc)" --target llama-server
ln -sfn "$third_party_dir/llama.cpp/build/bin/llama-server" "$runtime_bin/llama-server"

checkout_pinned_commit https://github.com/ggml-org/whisper.cpp.git "$third_party_dir/whisper.cpp" "$whisper_commit"
cmake -S "$third_party_dir/whisper.cpp" -B "$third_party_dir/whisper.cpp/build" -DCMAKE_BUILD_TYPE=Release
cmake --build "$third_party_dir/whisper.cpp/build" --config Release -j"$(nproc)" --target whisper-server
ln -sfn "$third_party_dir/whisper.cpp/build/bin/whisper-server" "$runtime_bin/whisper-server"

echo "原生服务已安装到 $runtime_bin"
