#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
args=()
if [[ "${PLAN_ONLY:-0}" == 1 ]]; then args+=(--plan-only); fi
exec python3 "$ROOT/evaluation_onfi_fast/runner.py" "${args[@]}" "$@"
