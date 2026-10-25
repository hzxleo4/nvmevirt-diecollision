#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BUILD="$(mktemp -d /tmp/nvmev-model-tests.XXXXXX)"
trap 'rm -rf "$BUILD"' EXIT
for name in onfi placement; do
    cc -std=c11 -O2 -Wall -Wextra -Werror "$ROOT/tests/test_${name}.c" -o "$BUILD/$name"
    "$BUILD/$name"
done
cc -std=c11 -g -O1 -Wall -Wextra -Wno-unused-variable -fsanitize=address,undefined \
    "$ROOT/tests/test_ftl.c" -o "$BUILD/ftl"
ASAN_OPTIONS=detect_leaks=1 "$BUILD/ftl"
cc -std=c11 -O2 -Wall -Wextra -Werror "$ROOT/evaluation_onfi_fast/read_pass.c" -o "$BUILD/read_pass"
"$BUILD/read_pass" --self-test 1
"$BUILD/read_pass" --self-test 32
make -C "$ROOT" NVMEV_PROFILE=fast24 -j4
