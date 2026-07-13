#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# 서버 실행 — QA 웹콘솔 (http://<HOST>:<PORT>)
#   환경변수로 조정: HOST PORT EMBED_MODEL LLM_BACKEND LLM_MODEL
#   기본은 완전 오프라인(HF_HUB_OFFLINE=1) — 모델은 최초 build 시 캐시됨.
#
#   사용:  bash deploy/run.sh
#          PORT=9000 LLM_BACKEND=ollama LLM_MODEL=qwen2.5:3b-instruct bash deploy/run.sh
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail
cd "$(dirname "$0")/.."
PY=.venv/bin/python
[ -x "$PY" ]        || { echo "✗ .venv 없음 — deploy/install.sh 먼저";  exit 1; }
[ -f data/index/dense.faiss ] || { echo "✗ 색인 없음 — deploy/build.sh 먼저"; exit 1; }

export HF_HUB_OFFLINE="${HF_HUB_OFFLINE:-1}"
export TRANSFORMERS_OFFLINE="${TRANSFORMERS_OFFLINE:-1}"
export HOST="${HOST:-127.0.0.1}"
export PORT="${PORT:-8000}"
export LLM_BACKEND="${LLM_BACKEND:-none}"

echo "▶ 서버 시작 http://${HOST}:${PORT}  (LLM_BACKEND=${LLM_BACKEND})"
exec "$PY" src/webapp.py
