#!/usr/bin/env bash
# 실데이터 업서트 일별 재개 — systemd 타이머(pb-ingest.timer)가 매일 호출.
# 자격증명은 .env.local에서 로드(저장소 미포함). 전량 완료되면 아무 것도 하지 않음.
set -euo pipefail
cd "$(dirname "$0")/../.."
set -a; source deploy/online/.env.local; set +a
# 무료 한도 일 10K 쓰기 — HYBRID 인덱스는 벡터 1건=2쓰기(dense+sparse)라 실효 5,000건/일
python3 deploy/online/ingest_real.py --limit 4900
