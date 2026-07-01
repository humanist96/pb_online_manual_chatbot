#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# 색인 빌드 — 매뉴얼 HTML 수집 → 청크 → FAISS/BM25 인덱스
#   사내망(211.255.203.234 접근 가능)에서 실행.
#   최초 실행 시 임베딩 모델을 1회 다운로드, 이후 오프라인 재실행 가능.
#
#   사용:  bash deploy/build.sh          # 계좌 전체(account_topics.txt)
#          bash deploy/build.sh AC250400 # 특정 화면만
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail
cd "$(dirname "$0")/.."
PY=.venv/bin/python
[ -x "$PY" ] || { echo "✗ .venv 없음 — 먼저 deploy/install.sh 실행"; exit 1; }

mkdir -p data/html

# 1) 수집
if [ "$#" -gt 0 ]; then
  echo "▶ 지정 토픽 수집: $*"
  "$PY" src/crawl.py "$@"
elif [ -f data/account_topics.txt ]; then
  echo "▶ 계좌 전체 토픽 수집 (data/account_topics.txt)"
  "$PY" src/crawl.py --from-file data/account_topics.txt
else
  echo "✗ data/account_topics.txt 없음 — 토픽 코드를 인자로 주거나 목록 파일을 배치하세요"; exit 1
fi

# 2) 청크
echo "▶ 청크 생성"
"$PY" src/to_chunks.py data/html/*.html

# 3) 색인 (오프라인)
echo "▶ 색인 빌드"
HF_HUB_OFFLINE=${HF_HUB_OFFLINE:-0} TRANSFORMERS_OFFLINE=${TRANSFORMERS_OFFLINE:-0} \
  "$PY" src/build_index.py

echo "✅ 색인 완료 → data/index/  (서버 실행: bash deploy/run.sh)"
