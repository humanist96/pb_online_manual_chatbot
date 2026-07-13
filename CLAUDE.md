# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

로컬·오픈소스 전용 RAG Q&A 챗봇. 코스콤 원장시스템(PowerBASE)의 Adobe RoboHelp 온라인 매뉴얼 HTML 토픽을 파싱해 사내 담당자용 매뉴얼 챗봇을 만든다. AC250400 화면을 파일럿으로 파서를 검증하고 동일 파서로 계좌 섹션(`AC*.html`)→전 부문으로 확장한 구조. 사내 배포용 로컬 서버(`src/webapp.py`+`web/`)와, 합성/공개 데이터만 다루는 별도 온라인 데모(`deploy/online/`)가 같은 UX를 공유한다.

**핵심 제약(필수)**: 사내(로컬) 경로의 임베딩·리랭커·LLM은 전부 로컬 오픈소스 모델. 외부 상용 API(Claude/OpenAI/Voyage 등) 일절 사용 금지 — 사내 폐쇄망·데이터 외부 유출 방지 목적. 저장소 본체에 상용 API 호출 코드를 추가하면 안 된다. **예외는 둘뿐**: ① webapp.py의 개발기 전용 claude CLI 백엔드(로컬 CLI 서브프로세스, 폐쇄망 자동 비활성) ② **`deploy/online/` 공개 데모 구역** — Upstash Vector·OpenAI 등 외부 API 허용(사내 원문·사내 배포와 완전 분리). 이 예외들을 구역 밖으로 확장하지 말 것.
설계 배경·의사결정 맥락은 루트의 계획 문서에 있다: `기획.md`(전체 설계), 그리고 기능별 `*_계획.md`/`*_기획.md`(전부문확장·질문추천_고도화·상담매뉴얼_온라인추가·사용자피드백·온보딩_도움말·품질사용성_고도화 등). **새 기능 작업 전 해당 계획 문서를 먼저 읽을 것** — 코드에 안 드러나는 제약·수용 기준이 거기 있다.

2026-07 안전 계약: 위의 과거 설계 메모에 포함된 `webapp.py` Claude CLI 예외는 폐기되었다. 현재 코드의 웹 백엔드는 `none|ollama`만 허용한다. VLM은 Terra의 식별자·서빙·라이선스·해시 확정 및 승인 전에 변경·배포하지 말 것. 온라인 데모(`deploy/online/`)의 공식 운영 모드는 접근키 게이트 실데이터다 — 익명 접근 불가이며 `DEMO_ACCESS_KEY` 미설정 시 전면 fail-closed; `PUBLIC_DEMO=true`일 때만 sha256 고정 합성 데이터셋 전용 fail-closed가 강제된다(경계 회귀선은 `tests/test_online_data_boundary.py`).

## Setup & Commands

```bash
# 환경 (uv 권장, Python 3.12)
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt \
    --extra-index-url https://download.pytorch.org/whl/cpu

# LLM 서빙 (별도 설치, https://ollama.com) — 없어도 추출형 폴백으로 동작
ollama pull qwen2.5:7b-instruct

# 테스트 (pytest 불필요)
.venv/bin/python -m unittest discover -s tests -p 'test_*.py'
```

`Makefile`이 자주 쓰는 흐름을 감싼다: `make install` → `make build`(수집→청크→색인, 사내망 필요) → `make run`(loopback 기본 서버). `make test`는 파서·요청 검증·데이터 경계·보안 회귀를 모두 실행한다.

로컬 파이프라인(순서대로 — 각 단계가 다음 입력 생성, **repo 루트에서 실행**):

```bash
python src/crawl_toc.py [--base PM]                       # TOC 재귀 → data/manifest*.json + data/topics*/  (사내망)
python src/crawl.py --from-file data/topics/계좌.txt      # 원본 HTML → data/html/ (업무는 --base PM → data/html_pm/ + data/img_pm/)
python src/parse.py    data/html/AC250400.html           # 화면매뉴얼 파서 (검증·디버깅용, stderr 통계)
python src/parse_pm.py data/html_pm/ACP01010.html        # 업무매뉴얼 파서 (템플릿 상이 — 별도 모듈)
python src/extract_pm_images.py --ocr | --vlm            # PM 이미지 텍스트화(OCR 전량 → VLM 도식) → data/pm_image_text.json
python src/to_chunks.py data/html/*.html data/html_pm/*.html   # → data/chunks.jsonl (디렉터리로 화면/업무 자동 판별)
python src/build_index.py                                # data/chunks.jsonl → data/index/ (FAISS+BM25)
python src/calibrate_threshold.py [--write]              # 게이트 τ 데이터 보정 → meta.json["gate"]
python src/webapp.py                                     # 매뉴얼 데스크 서버 → http://localhost:8000
python src/eval_scope.py                                 # 교차 오염 평가 (Recall@5·부문 정확도·동음이의·매뉴얼 교차)
```

`to_chunks.py`/`to_xlsx.py`는 `from parse import ...`로 형제 모듈을 임포트하므로 `python src/xxx.py` 형태로 호출한다(같은 디렉터리라 동작).

## Configuration (환경변수)

`os.environ` 기반, `.env.example` 참고. `.env`는 자동 로드하지 **않으므로** 셸 export 하거나 명령 앞에 붙인다.

- `EMBED_MODEL` — 기본 `jhgan/ko-sroberta-multitask`(경량 ~440MB). 고정밀 대안 `BAAI/bge-m3`(~2.3GB). **빌드 때와 질의 때 모델이 반드시 일치**(`meta.json`에 기록·검사). 정밀도는 리랭커 `BAAI/bge-reranker-v2-m3`가 담당하는 구조라 bi-encoder 교체 실익 낮음(분석 결론: `품질사용성_고도화_기획.md`).
- `LLM_BACKEND` — `chatbot.py`: `ollama`(명시적)|`none`. `webapp.py`: `none`(기본)|`ollama`(명시적 opt-in). `RERANK_ENABLE`, `RAG_ALPHA`, `RAG_TOPK`, `LLM_MODEL`, `OLLAMA_HOST`.
- `HOST`/`PORT`(기본 127.0.0.1:8000), `PB_MAX_CONCURRENT_QUERIES`, `INDEX_DIR`, `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1`. 비루프백 바인딩은 인증 proxy와 확인문이 필요하다.

## Architecture

데이터 흐름: **원본(HTML/이미지/xls) → 구조화 트리(dict) → 청크(JSONL) → 인덱스 → 챗봇/검색**

핵심은 **브레드크럼(breadcrumb)**: 파서가 계층 구조를 `{path:[세그먼트...], text}` 리스트로 평탄화 → 브레드크럼 1개 = 청크 1개 = 검색/출처 단위. `path` 루트는 항상 문서 제목.

**매뉴얼 삼원 구조**: 화면매뉴얼(`/ST/`, 조작법) · 업무매뉴얼(`/PM/`, 절차) · 상담매뉴얼(고객지원센터 Q&A, **온라인 데모 전용**). 청크의 `manual` 필드("화면"|"업무"|"상담")가 1차 구분이고 `sector_path` 루트가 매뉴얼 레벨(`["화면","계좌",...]`/`["업무",...]`/`["상담",업무]`). 스코프 필터·셀렉터·근거 지도·모호성 배너가 무수정으로 매뉴얼 차원까지 동작하는 근거. 청크 id 접두: 업무 `pm:`, 상담 `cs:`.

**화면 식별 표기 규칙(중요)**: `screen_no`(예 2150·4045 — 단말에 입력하는 화면번호)가 UI·LLM 답변의 주인공. `screen_id`(예 AC110100·FA002600 — RoboHelp 내부 문서코드)는 **UI에 절대 노출하지 않고** scope_key·source_url 같은 내부 기능값으로만 쓴다. screen_no가 빈 값(업무·상담·일부 화면)이면 표기 자체를 생략(제목 폴백). LLM 답변 컨텍스트에도 '화면번호 NNNN'을 주입해야 모델이 문서코드를 화면번호로 오답하지 않는다.

### 사내(로컬) 경로 — `src/` + `web/`

- **`src/parse.py`** — 품질의 90%가 결정되는 핵심. RoboHelp HTML의 CSS class 계층 복원: `div.title_box`→`div.Step00_icon`→`div.Step1_Nxx`→`table tr`(th=항목/td=목록). `li.icon01/02` 깊이로 부모-자식 복원, `td`를 첫 콜론 기준 용어/설명 분리(`split_term`, 용어 40자 제한), 무클래스 `li`는 직전 설명에 병합, `table.T_QAbox`의 `.Que/.Ans`는 Q&A. 규칙 변경 시 `tests/test_parse.py` 골든 필수 확인.
- **`src/parse_pm.py`** — 업무매뉴얼 전용 파서(템플릿 완전 상이 — 별도 모듈이라 parse.py 골든 무위험). 이미지 도식이 본체인 문서(ACP02010류)는 `data/pm_image_text.json` 캐시를 파싱 시점에 브레드크럼으로 병합("(도식 텍스트화: 파일명)" 마커). 골든 `tests/test_parse_pm.py`.
- **`src/extract_pm_images.py`** — PM 이미지 OCR 전처리만 수행하고 VLM은 `PB_VLM_APPROVAL` 및 Terra adapter 승인 전까지 fail-closed한다. Ollama VLM을 사용하지 않으며 승인 전 배포하지 않는다.
- **`src/to_chunks.py`** — 브레드크럼 → 청크. `embed_text = "[화면/부문] 경로 > ... : 설명"`로 매뉴얼·부문·경로를 임베딩 텍스트에 보존. 입력 디렉터리로 파서·`manual` 자동 판별, `manifest*.json` 조인해 `sector`/`sector_path` 부여. `chunk_type`은 `path[1]`로 결정(overview/description/glossary/related/qa).
- **`src/build_index.py`** — 청크 → `data/index/`: `dense.faiss`(정규화 내적=코사인)·`bm25.pkl`·`chunks.json`·`meta.json`. **로컬 인덱스는 `data/chunks.jsonl`만 읽는다**(상담 청크 `data/chunks_counsel.jsonl`은 온라인 전용).
- **`src/rag_common.py`** — 공용 헬퍼(임베더 싱글턴, 청크 로딩, 리랭커)와 **한국어 BM25 토크나이저** `tokenize_ko`(한글 음절 unigram+bigram, 영숫자 소문자). 빌드·질의가 같은 토크나이저를 써야 하므로 여기 한 곳. `INDEX_DIR`·`EMBED_MODEL`·`RERANK_MODEL` 정의처.
- **`src/chatbot.py`** — CLI. 하이브리드 검색(`hybrid_search`: dense+sparse min-max 정규화 후 `alpha` 가중합)→top-k를 Ollama 프롬프트 주입, `[S1]` 인용 강제, 근거 없으면 거부, Ollama 미연결 시 추출형 폴백. **webapp.py와 검색·프롬프트 로직이 별도 구현으로 중복** — 한쪽 수정 시 양쪽 확인.
- **`src/webapp.py`** — 답변 서버 겸 계측 콘솔. 기본 loopback 바인딩, `none|ollama` allowlist, q/topk/score/scope/type 검증, 동시성 상한, 보안 헤더를 적용한다. 프런트 `web/`은 화이트리스트 정적 라우트로 서빙하고 `/api/search`→`/api/answer` 흐름을 사용한다.

### 공개 온라인 데모 — `deploy/online/` (예외 구역)

Vercel 서버리스(Python `http.server` 핸들러, 표준 라이브러리만 — 콜드스타트 최소화) + Upstash Vector(HYBRID, 내장 임베딩 `text-embedding-3-small`+BM25 — **관리형이라 임베더 교체 대상 아님**) + OpenAI 답변(`OPENAI_MODEL`, 현재 gpt-5.4). `api/_common.py`가 검색·게이트·답변 공용 로직(로컬 webapp과 동형이나 독립 구현 — 양쪽 수정 유의). 게이트는 dense 코사인 단일 τ(0.70). 주요 확장:

- **검증된 질문뱅크**: `gen_questions.py`가 qa 청크에서 후보 추출 → 자기-검색 검증 통과분만 `api/_questions.py`(온라인, Upstash 재검증 881건) / `data/questions.json`(`--out`, 로컬 검증 1,039건). `/api/suggest`(scope·seed 라운드로빈)·답변 `related`(화면→부문→매뉴얼)·말풍선 UI의 재료.
- **계측**: `src=chip`(추천 클릭)·피드백을 온라인은 Upstash Redis(`demo:chip`/`chipok`), 로컬은 파일(`data/chip_log.jsonl`)에 적재. 적중률 = chipok/chip.
- **`api/feedback.py`**: 사용자 피드백 등록/조회/공감/상태변경/화면캡처, Upstash Redis. 상태변경은 `FEEDBACK_ADMIN_KEY` 필수(빈 값이면 전면 401 = 비활성).
- **상담매뉴얼**: `parse_counsel_xls.py`(구형 BIFF .xls → **xlrd 필요**, openpyxl 불가)가 Q&A쌍을 `data/chunks_counsel.jsonl`로 청킹 → `ingest_real.py`가 `chunks.jsonl` 뒤에 연결해 업서트.
- **배포/자격증명**: Vercel CLI는 Windows 설치 → WSL에서 `cmd.exe /c "cd /d C:\... && vercel --prod"`로 호출. ⚠️ **Vercel Sensitive env는 WSL→cmd 파이프로 stdin 전달이 안 됨(빈 문자열로 저장)** — 반드시 Vercel REST API(PATCH `/v9/projects/{proj}/env/{id}`)로 설정. 자격증명은 `deploy/online/.env.local`(git 미포함)과 Vercel env에만.

## Deployment (사내 리눅스 서버)

두 방식, 상세는 `README.md` 배포 섹션: **A) venv+systemd** — `deploy/install.sh`→`deploy/build.sh`(수집→청크→색인)→`deploy/run.sh`(오프라인 실행), 상시 실행은 `deploy/pb-chatbot.service`. **B) Docker** — 이미지엔 코드만, **`data/`(색인)·HF 캐시는 볼륨 주입**(사내 데이터 미포함 설계), 헬스체크 `/api/meta`.

`requirements.lock.txt`가 고정 버전 재현용(install.sh/Dockerfile 우선 사용) — 의존성 변경 시 `requirements.txt`와 lock 둘 다 갱신, torch는 항상 CPU 휠(`--extra-index-url https://download.pytorch.org/whl/cpu`).

## Conventions

- **완전 오프라인 실행이 목표**(사내 경로). 모델 가중치 최초 1회 캐싱 후 네트워크 없이 재실행 가능. 새 의존성은 로컬/오픈소스인지 확인.
- 한글 텍스트 정규화는 `parse.norm`(NBSP·개행 정리, `►` 등 의미기호 보존) 통과.
- 파서 테스트는 pytest 없이 assert 기반. 골든값(브레드크럼 경로, glossary/related/qa 개수)이 회귀 방지선.
- 프런트가 `web/`와 `deploy/online/public/`로 분기(형제 코드) — 공통 기능은 양쪽에 반영하되 QA 모드 등 로컬 전용 분기를 깨지 말 것. 정적 자산 변경 시 index.html의 `?v=` 캐시버스팅 올릴 것.
- 스코프 경로 스키마를 바꾸면 프런트 localStorage 마이그레이션을 반드시 동반(구형 저장 스코프가 새 필터와 안 맞아 근거 0건이 되는 회귀 발생 이력).
