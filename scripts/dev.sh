#!/usr/bin/env bash
# 一键起后端 + 前端。Ctrl-C 一起退出。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [ ! -d "$ROOT/renderer/node_modules" ]; then
  echo "渲染层依赖未安装：cd renderer && npm install" >&2
  exit 1
fi

cleanup() { kill 0; }
trap cleanup EXIT INT TERM

(cd "$ROOT/backend" && uvicorn app.main:app --port 8000 --reload) &
(cd "$ROOT/web" && npm run dev) &

echo "后端 http://127.0.0.1:8000   前端 http://localhost:5173"
wait
