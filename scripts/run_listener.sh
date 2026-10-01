#!/usr/bin/env bash
set -Eeuo pipefail

source "$(dirname "${BASH_SOURCE[0]}")/lib/environment.sh"
cd "$CET6_PROJECT_ROOT"

if [[ -x "${CET6_PROJECT_ROOT}/.venv/bin/python" ]]; then
  exec "${CET6_PROJECT_ROOT}/.venv/bin/python" -m cet6_listener.commands.app "$@"
fi
command -v poetry >/dev/null 2>&1 || {
  printf '找不到项目 Python 环境，请先运行 poetry install。\n' >&2
  exit 1
}
exec poetry run python -m cet6_listener.commands.app "$@"
