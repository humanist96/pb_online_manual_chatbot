# PowerBASE 계좌 매뉴얼 RAG 챗봇 — 편의 명령
# 사용:  make install → make build → make run   (또는 make docker-up)
.PHONY: help install build run test docker-build docker-up docker-down clean

help:
	@echo "install      의존성 설치 (deploy/install.sh)"
	@echo "build        색인 빌드   (deploy/build.sh, 사내망)"
	@echo "run          서버 실행   (deploy/run.sh → :8000)"
	@echo "test         파서 회귀 테스트"
	@echo "docker-build 이미지 빌드"
	@echo "docker-up    컨테이너 실행 (data/ 볼륨 필요)"
	@echo "docker-down  컨테이너 중지"

install:
	bash deploy/install.sh

build:
	bash deploy/build.sh

run:
	bash deploy/run.sh

test:
	.venv/bin/python tests/test_parse.py

docker-build:
	docker build -t pb-chatbot:latest .

docker-up:
	docker compose up -d

docker-down:
	docker compose down

clean:
	rm -rf __pycache__ src/__pycache__ tests/__pycache__ data/xlsx/~$$*.xlsx
