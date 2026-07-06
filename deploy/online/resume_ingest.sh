#!/usr/bin/env bash
# 실데이터 업서트 일별 재개 — systemd 타이머(pb-ingest.timer)가 매일 호출.
# 자격증명은 .env.local에서 로드(저장소 미포함). 전량 완료되면 아무 것도 하지 않음.
set -euo pipefail
cd "$(dirname "$0")/../.."
set -a; source deploy/online/.env.local; set +a
python3 deploy/online/ingest_real.py --limit 9500
