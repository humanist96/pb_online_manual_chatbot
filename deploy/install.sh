#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# PowerBASE 계좌 매뉴얼 RAG 챗봇 — 리눅스 서버 설치 스크립트
#
#   일반 리눅스 서버(Ubuntu/Debian/RHEL 등, x86_64)에서 한 번 실행하면
#   파이썬 3.12 가상환경 + 의존성이 준비된다. (root 불필요, sudo 불필요)
#
#   사용:  bash deploy/install.sh
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail
cd "$(dirname "$0")/.."          # 프로젝트 루트로 이동
ROOT="$(pwd)"
echo "▶ 프로젝트: $ROOT"

# 1) uv (오픈소스 파이썬/패키지 관리자) 설치 — 이미 있으면 생략
if ! command -v uv >/dev/null 2>&1; then
  export PATH="$HOME/.local/bin:$PATH"
  if ! command -v uv >/dev/null 2>&1; then
    echo "▶ uv 설치 중..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
  fi
fi
echo "▶ uv: $(uv --version)"

# 2) 파이썬 3.12 가상환경
if [ ! -d .venv ]; then
  echo "▶ .venv 생성 (Python 3.12)"
  uv venv --python 3.12 .venv
fi

# 3) 의존성 설치 (torch 는 CPU 휠 인덱스)
echo "▶ 의존성 설치 (torch CPU 휠 포함, 수 분 소요)"
REQ="requirements.lock.txt"; [ -f "$REQ" ] || REQ="requirements.txt"
uv pip install --python .venv/bin/python -r "$REQ" \
    --extra-index-url https://download.pytorch.org/whl/cpu

# 4) 검증
echo "▶ 설치 검증"
.venv/bin/python - <<'PY'
import bs4, lxml, openpyxl, sentence_transformers, faiss, rank_bm25, torch
print("  OK — sentence-transformers", sentence_transformers.__version__,
      "| torch", torch.__version__, "| faiss ok")
PY

cat <<'NEXT'

✅ 설치 완료.

다음 단계:
  1) 색인 생성(사내망 필요):   bash deploy/build.sh
     - 최초 1회 임베딩 모델(~440MB) 다운로드 후 오프라인 동작
  2) 서버 실행:                bash deploy/run.sh
     → http://<서버IP>:8000

  systemd 등록(상시 실행)은  deploy/pb-chatbot.service  참조.
NEXT
