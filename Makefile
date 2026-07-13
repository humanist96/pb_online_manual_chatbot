# PowerBASE 계좌 매뉴얼 RAG 챗봇 — 편의 명령
# 사용:  make install → make build → make run   (또는 make docker-up)
.PHONY: help install build run test docker-build docker-up docker-down clean video-capture video-render

help:
	@echo "install      의존성 설치 (deploy/install.sh)"
	@echo "build        색인 빌드   (deploy/build.sh, 사내망)"
	@echo "run          서버 실행   (deploy/run.sh → :8000)"
	@echo "test         파서·보안·공개 데이터 경계 회귀 테스트"
	@echo "docker-build 이미지 빌드"
	@echo "docker-up    컨테이너 실행 (data/ 볼륨 필요)"
	@echo "docker-down  컨테이너 중지"
	@echo "video-capture 웹 UI 데모 캡처 (webapp :8010 필요, video/README.md 참고)"
	@echo "video-render  영상 렌더 (Report/Full → video/remotion/out/)"

install:
	bash deploy/install.sh

build:
	bash deploy/build.sh

run:
	bash deploy/run.sh

test:
	.venv/bin/python tests/test_parse.py
	.venv/bin/python tests/test_parse_pm.py
	.venv/bin/python -m unittest -v \
		tests.test_online_data_boundary \
		tests.test_request_validation \
		tests.test_webapp_security \
		tests.test_feedback_security

docker-build:
	docker build -t pb-chatbot:latest .

docker-up:
	docker compose up -d

docker-down:
	docker compose down

clean:
	rm -rf __pycache__ src/__pycache__ tests/__pycache__ data/xlsx/~$$*.xlsx

video-capture:
	@command -v node >/dev/null 2>&1 || { echo "node가 없습니다. Node 22+ 설치 후 다시 실행하세요."; exit 1; }
	@curl -sf -o /dev/null http://127.0.0.1:8010/ || { echo "webapp이 :8010에 없습니다. 먼저 실행: PORT=8010 python src/webapp.py"; exit 1; }
	@CHROME=$$(find video/remotion/node_modules/.remotion -type f -name chrome-headless-shell 2>/dev/null | head -1); \
	if [ -z "$$CHROME" ]; then echo "chrome-headless-shell이 없습니다: cd video/remotion && npx remotion browser ensure"; exit 1; fi; \
	node video/captures/browser/07_webapp.mjs http://127.0.0.1:8010 "$$CHROME" video/captures/out
	@echo "완료 → video/captures/out/07_webapp.webm (video/remotion/public/demo/ 로 복사해 사용)"

video-render:
	@command -v node >/dev/null 2>&1 || { echo "node가 없습니다. Node 22+ 설치 후 다시 실행하세요."; exit 1; }
	cd video/remotion && npx remotion render src/index.ts Report out/report.mp4 --codec h264 --audio-codec aac --enforce-audio-track
	cd video/remotion && npx remotion render src/index.ts Full out/full.mp4 --codec h264 --audio-codec aac --enforce-audio-track

report-pdf: ## 임원 보고 PDF 빌드 (docs/report)
	@command -v node >/dev/null || { echo "✗ node 필요 — video/README.md 참조"; exit 1; }
	@[ -f docs/report/template/PretendardVariable.woff2 ] || cp web/fonts/PretendardVariable.woff2 docs/report/template/
	cd docs/report && node build.mjs "$${CHROME:-$$(ls video/remotion/node_modules/.remotion/chrome-headless-shell/linux64/chrome-headless-shell-linux64/chrome-headless-shell 2>/dev/null)}"
