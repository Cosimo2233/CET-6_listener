#!/usr/bin/env bash
# 供仓库脚本 source；系统未安装工具时，使用 .tools 下的本地副本。

CET6_PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

for cet6_tool in cmake ffmpeg; do
  cet6_tool_root="${CET6_PROJECT_ROOT}/.tools/${cet6_tool}/usr"
  if ! command -v "$cet6_tool" >/dev/null 2>&1 && [[ -x "${cet6_tool_root}/bin/${cet6_tool}" ]]; then
    export PATH="${cet6_tool_root}/bin:${PATH}"
    for cet6_library_dir in "${cet6_tool_root}/lib/"*-linux-gnu; do
      if [[ -d "$cet6_library_dir" ]]; then
        export LD_LIBRARY_PATH="${cet6_library_dir}${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}"
      fi
    done
  fi
done
unset cet6_tool cet6_tool_root cet6_library_dir

cet6_python() {
  if [[ -x "${CET6_PROJECT_ROOT}/.venv/bin/python" ]]; then
    "${CET6_PROJECT_ROOT}/.venv/bin/python" "$@"
  elif command -v poetry >/dev/null 2>&1; then
    poetry run python "$@"
  else
    printf '找不到项目 Python 环境，请先运行 poetry install。\n' >&2
    return 1
  fi
}
