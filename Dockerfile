# PowerBASE 계좌 매뉴얼 RAG 챗봇 — 컨테이너 이미지 (CPU)
FROM python:3.12-slim

# 런타임 유틸 (curl: 헬스체크)
RUN apt-get update && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 1) 의존성 먼저 (레이어 캐시). torch 는 CPU 휠 인덱스.
COPY requirements.lock.txt requirements.txt ./
RUN pip install --no-cache-dir -r requirements.lock.txt \
        --extra-index-url https://download.pytorch.org/whl/cpu

# 2) 애플리케이션
COPY src/ ./src/
COPY web/ ./web/
COPY tests/ ./tests/
COPY data/account_topics.txt ./data/account_topics.txt

# 색인/모델 캐시는 볼륨으로 주입 (이미지에 사내 데이터 미포함)
#   -v $PWD/data:/app/data           (색인)
#   -v hf-cache:/root/.cache/huggingface  (임베딩 모델 캐시)
ENV HOST=127.0.0.1 PORT=8000 LLM_BACKEND=none HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
  CMD curl -fsS http://localhost:8000/api/meta || exit 1

CMD ["python", "src/webapp.py"]
