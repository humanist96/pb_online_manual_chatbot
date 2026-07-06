# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

로컬·오픈소스 전용 RAG Q&A 챗봇. 코스콤 원장시스템(PowerBASE)의 Adobe RoboHelp 온라인 매뉴얼 "계좌" 부문 HTML 토픽을 파싱하여 사내 담당자용 매뉴얼 챗봇을 만든다. AC250400 화면을 파일럿으로 파서를 검증하고 동일 파서로 계좌 섹션(`AC*.html`) 전체로 확장하는 구조.

**핵심 제약(필수)**: 임베딩·리랭커·LLM 전부 로컬 오픈소스 모델. 외부 상용 API(Claude/OpenAI/Voyage 등) 일절 사용 금지 — 사내 폐쇄망·데이터 외부 유출 방지 목적. 이 저장소에 상용 API 호출 코드를 추가하면 안 된다. 예외는 둘뿐: ① webapp.py의 개발기 전용 claude CLI 백엔드(로컬 CLI 서브프로세스, 폐쇄망 자동 비활성) ② **`deploy/online/` 공개 데모 구역** — 합성 데이터(DemoBASE)만 다루는 온라인 데모로 Upstash Vector·OpenAI 등 외부 API 허용(사내 매뉴얼 원문·사내 배포와 완전 분리). 이 예외들을 구역 밖으로 확장하지 말 것.

배경·설계 결정의 전체 맥락은 `기획.md`에 있다.

## Setup & Commands

```bash
# 환경 (uv 권장, Python 3.12)
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt \
    --extra-index-url https://download.pytorch.org/whl/cpu

# LLM 서빙 (별도 설치, https://ollama.com) — 없어도 추출형 폴백으로 동작
ollama pull qwen2.5:7b-instruct

# 테스트 (pytest 불필요, assert 기반 단일 스크립트)
.venv/bin/python tests/test_parse.py   # = make test
```

`Makefile`이 자주 쓰는 흐름을 감싼다: `make install`(deploy/install.sh) → `make build`(deploy/build.sh: 수집→청크→색인 원스텝, 사내망 필요) → `make run`(deploy/run.sh: 오프라인 기본 서버 실행). Docker는 `make docker-build` / `docker-up`.

파이프라인은 순서대로 실행한다 (각 단계가 다음 단계의 입력을 생성):

```bash
python src/crawl_toc.py                                   # TOC 재귀 → data/manifest.json + data/topics/<부문>.txt (사내망)
python src/crawl.py AC250400                              # 원본 HTML → data/html/
python src/crawl.py --from-file data/topics/계좌.txt      # 부문 단위 수집 (사내망 211.255.203.234 필요)
python src/parse.py data/html/AC250400.html              # HTML → 구조화 dict (검증/디버깅용, stderr에 통계)
python src/to_chunks.py data/html/*.html                 # → data/chunks.jsonl
python src/to_xlsx.py data/html/AC250400.html            # → data/xlsx/*.xlsx (샘플 골든 포맷 재현)
python src/build_index.py                                # data/chunks.jsonl → data/index/ (FAISS + BM25)
python src/chatbot.py "질문..."                          # 단발 질의 (인자 없으면 REPL)
python src/webapp.py                                     # 매뉴얼 데스크(챗 UI+QA 모드) → http://localhost:8000
python src/eval_scope.py                                 # 교차 오염 평가 (Recall@5·부문 정확도·동음이의)
```

스크립트는 `src/`를 작업 디렉터리 기준으로 실행하되, 상대 경로(`data/...`)를 그대로 쓰므로 **repo 루트에서 실행**한다. `to_chunks.py`/`to_xlsx.py`는 `from parse import ...`로 형제 모듈을 임포트하므로 `python src/xxx.py` 형태로 호출된다(같은 디렉터리라 동작).

## Configuration (환경변수)

모든 설정은 `os.environ` 기반이며 `.env.example` 참고. `.env`는 스크립트가 자동 로드하지 **않으므로** 셸에서 export 하거나 명령 앞에 붙여야 한다.

- `EMBED_MODEL` — 기본 `jhgan/ko-sroberta-multitask`(경량 ~440MB). 고정밀은 `BAAI/bge-m3`(~2.3GB). **인덱스 빌드 때와 질의 때 모델이 반드시 일치해야 함** (`meta.json`에 기록됨).
- `LLM_BACKEND` — `chatbot.py`는 `ollama`(기본) | `none`(추출형 폴백 강제). `webapp.py`는 기본 `auto`(claude CLI → ollama → 추출형 순 자동 선택)이며 `claude` 값도 받는다(아래 Architecture 참고).
- `LLM_MODEL`, `OLLAMA_HOST`, `RAG_TOPK`, `RAG_ALPHA`(0=BM25만, 1=dense만, 0.5=하이브리드)
- `HOST`(기본 0.0.0.0)/`PORT`(기본 8000) — webapp 바인딩. `CLAUDE_BIN`/`CLAUDE_MODEL` — webapp의 claude CLI 백엔드용.
- `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1` — 모델 캐시 후 완전 오프라인 강제. deploy/run.sh·Docker는 기본으로 켠다.

## Architecture

데이터 흐름: **HTML → 구조화 트리(dict) → 청크(JSONL) → 인덱스(FAISS+BM25) → 챗봇/검색**

핵심은 **브레드크럼(breadcrumb)** 개념이다. 파서가 매뉴얼의 계층 구조를 `{path:[세그먼트...], text}` 리스트로 평탄화하고, 브레드크럼 1개 = 청크 1개 = 검색/출처 단위가 된다. `path`의 루트는 항상 문서 제목으로 통일된다.

- **`src/parse.py`** — 품질의 90%가 결정되는 핵심. RoboHelp HTML의 CSS class 계층을 구조화 트리로 복원한다. 규칙: `div.title_box`(대분류) → `div.Step00_icon`(중분류) → `div.Step1_Nxx`(단계) → `table tr`(th=항목/td=목록). `li.icon01`/`li.icon02`의 깊이로 부모-자식 관계를 복원하고, `td` 텍스트를 첫 콜론(`:`) 기준으로 용어/설명 분리(`split_term`, 오탐 방지로 용어 40자 제한). 무클래스 `li`는 직전 항목 설명의 줄바꿈 연속으로 병합. `table.T_QAbox`의 `.Que`/`.Ans`는 Q&A로 수집. 파싱 규칙 변경 시 반드시 `tests/test_parse.py`의 골든값을 확인할 것.
- **`src/to_chunks.py`** — 브레드크럼 → 청크. `embed_text = "[부문] 경로 > ... : 설명"` 형태로 부문·전체 경로를 임베딩 텍스트에 보존(검색 정확도·출처 근거 강화). `data/manifest.json`(crawl_toc.py 산출)을 조인해 `sector`/`sector_path`(TOC 경로)를 부여. `chunk_type`은 `path[1]` 섹션명으로 결정(overview/description/glossary/related/qa).
- **`src/to_xlsx.py`** — 구조화 트리 → 원본 샘플과 동일 계열 XLSX(B/C 2열). HTML에서 유도 가능한 메타(제목·코드·화면번호·AUP)만 채우고 발행부서·버전·성명 등은 공란(HTML에 없음).
- **`src/build_index.py`** — 청크 → `data/index/`: `dense.faiss`(정규화 내적=코사인), `bm25.pkl`, `chunks.json`, `meta.json`.
- **`src/rag_common.py`** — 공용 헬퍼(임베더 싱글턴, 청크 로딩)와 **한국어 BM25 토크나이저** `tokenize_ko`(한글은 음절 unigram+bigram, 영숫자는 소문자 토큰). 인덱스 빌드와 질의가 같은 토크나이저를 써야 하므로 여기 한 곳에 둔다.
- **`src/chatbot.py`** — 하이브리드 검색(`hybrid_search`: dense+sparse 각각 min-max 정규화 후 `alpha` 가중합) → top-k 청크를 Ollama 프롬프트에 주입. `[S1],[S2]` 인용마커로 출처를 강제하고, 컨텍스트에 근거 없으면 "매뉴얼에서 확인되지 않습니다."로 답하도록 시스템 프롬프트로 억제. **Ollama 미연결 시 추출형(extractive) 폴백**으로 근거 청크를 그대로 반환.
- **`src/webapp.py`** — 하이브리드 검색 품질 검증용 계측 콘솔이자 답변 서버. 표준 라이브러리 `http.server`만 사용(무추가 의존). API: `/api/meta`(인덱스 메타, Docker 헬스체크 대상), `/api/search`(dense/sparse/combined 점수 노출), `/api/answer`(검색+답변 생성). 답변 백엔드는 `LLM_BACKEND=auto` 시 claude CLI(개발기 편의, 헤드리스 `claude -p` 서브프로세스) → Ollama → 추출형 합성(`extractive_answer`) 순으로 자동 폴백 — 폐쇄망 배포에서는 claude CLI가 없으므로 자연히 ollama/추출형만 쓰인다. 프런트는 `web/`(index.html·styles.css·app.js·fonts/PretendardVariable.woff2)이며 정적 자산은 webapp.py의 화이트리스트 확장자 라우트로 서빙(경로 탈출 방지). UI는 대화 스레드(상담 모드 기본) + 근거 지도/카드 패널 구조이고, `Q` 키 또는 `?qa=1`로 QA 계측 모드(α·τ·top-k, dense/sparse) 토글, `?q=`로 질문 딥링크, 컴포저 '정밀' 토글이 요청당 `rerank=0/1`로 게이트 모드(코사인/리랭커)를 전환. 프런트는 `/api/search`(근거 선노출)→`/api/answer` 2단 호출. `/api/meta`의 `samples`(qa 청크에서 추출한 추천 질문)를 첫 화면 칩으로 사용. 전 부문 스코프: `scope=계좌>고객관리` 경로 접두 필터(`_scope_match`), 응답의 `scope_hint`가 근거 부문 분포·모호성(상위 두 부문 best 차 <0.08)을 알려 UI 배너를 띄운다. `/api/sectors`가 스코프 셀렉터용 TOC 트리 제공. chatbot.py와 검색·프롬프트 로직이 별도 구현으로 중복되어 있는 점에 유의(수정 시 양쪽 확인).

## Deployment (리눅스 서버)

두 가지 방식, 상세 절차는 `README.md`의 배포 섹션 참고:

- **방식 A (venv + systemd)** — `deploy/install.sh`(uv 부트스트랩+의존성, root 불필요) → `deploy/build.sh`(수집→청크→색인; 인자 없으면 `data/account_topics.txt` 전체, 토픽 코드 인자로 부분 빌드) → `deploy/run.sh`(오프라인 기본으로 webapp 실행). 상시 실행은 `deploy/pb-chatbot.service` systemd 유닛.
- **방식 B (Docker)** — 이미지에는 코드만 담고 **`data/`(색인)와 HF 모델 캐시는 볼륨으로 주입**(사내 데이터를 이미지에 넣지 않는 설계). `docker-compose.yml`에 선택적 ollama 서비스가 주석으로 준비되어 있다. 헬스체크는 `/api/meta`.

`requirements.lock.txt`가 고정 버전 재현 설치용이며 install.sh/Dockerfile은 lock 파일을 우선 사용한다. 의존성 변경 시 `requirements.txt`와 lock 둘 다 갱신할 것. torch는 항상 CPU 휠 인덱스(`--extra-index-url https://download.pytorch.org/whl/cpu`)로 설치한다.

## Conventions

- **완전 오프라인 실행이 목표**. 모델 가중치 최초 1회 캐싱 후 네트워크 없이 재실행 가능해야 한다. 새 의존성 추가 시 로컬/오픈소스인지 확인.
- 한글 텍스트 정규화는 `parse.norm`(NBSP·개행 정리, `►` 등 의미기호 보존)을 통과시킨다.
- 테스트는 pytest 없이 `python tests/test_parse.py`로 실행되는 assert 기반. 파서 골든값(브레드크럼 경로, glossary/related/qa 개수)이 회귀 방지선이다.
