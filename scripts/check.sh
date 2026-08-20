#!/usr/bin/env sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"

python3 -m compileall -q "${ROOT_DIR}/server/app"

if [ ! -d "${ROOT_DIR}/web/node_modules" ]; then
  echo "web/node_modules is missing; run 'cd web && npm ci' first." >&2
  exit 1
fi

cd "${ROOT_DIR}/web"
npm exec tsc -- --noEmit
