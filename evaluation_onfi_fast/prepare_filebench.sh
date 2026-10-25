#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
COMMIT=1263cb180c48a63253345a12e2b842cd9f85fa26
CACHE="$ROOT/evaluation_onfi_fast/.cache"
ARCHIVE="$CACHE/filebench-1.5-alpha3.tar.gz"
mkdir -p "$CACHE"
if [[ ! -s "$ARCHIVE" ]]; then
    wget -q "https://codeload.github.com/filebench/filebench/tar.gz/$COMMIT" -O "$ARCHIVE"
fi
echo "ff955c6477f49debf5e343a069bcb02d9d7fbfd3dfd499ef998548454a00103a  $ARCHIVE" | sha256sum -c -
if [[ ! -d "$CACHE/filebench-$COMMIT" ]]; then
    tar -xzf "$ARCHIVE" -C "$CACHE"
fi
cd "$CACHE/filebench-$COMMIT"
autoreconf -fi
./configure --prefix="$CACHE/filebench-install"
make -j4
make install
echo "Filebench binary: $PWD/filebench"
