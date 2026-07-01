# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

로컬·오픈소스 전용 RAG Q&A 챗봇. 토스증권 원장시스템(PowerBASE)의 Adobe RoboHelp 온라인 매뉴얼 "계좌" 부문 HTML 토픽을 파싱하여 사내 담당자용 매뉴얼 챗봇을 만든다. AC250400 화면을 파일럿으로 파서를 검증하고 동일 파서로 계좌 섹션(`AC*.html`) 전체로 확장하는 구조.

**핵심 제약(필수)**: 임베딩·리랭커·LLM 전부 로컬 오픈소스 모델. 외부 상용 API(Claude/OpenAI/Voyage 등) 일절 사용 금지 — 사내 폐쇄망·데이터 외부 유출 방지 목적. 이 저장소에 상용 API 호출 코드를 추가하면 안 된다.

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
.venv/bin/python tests/test_parse.py
```

파이프라인은 순서대로 실행한다 (각 단계가 다음 단계의 입력을 생성):

```bash
python src/crawl.py AC250400                              # 원본 HTML → data/html/  (파일럿은 이미 캐시됨)
python src/parse.py data/html/AC250400.html              # HTML → 구조화 dict (검증/디버깅용, stderr에 통계)
python src/to_chunks.py data/html/*.html                 # → data/chunks.jsonl
python src/to_xlsx.py data/html/AC250400.html            # → data/xlsx/*.xlsx (샘플 골든 포맷 재현)
python src/build_index.py                                # data/chunks.jsonl → data/index/ (FAISS + BM25)
python src/chatbot.py "질문..."                          # 단발 질의 (인자 없으면 REPL)
python src/webapp.py                                     # 검색품질 QA 콘솔 → http://localhost:8000
```

스크립트는 `src/`를 작업 디렉터리 기준으로 실행하되, 상대 경로(`data/...`)를 그대로 쓰므로 **repo 루트에서 실행**한다. `to_chunks.py`/`to_xlsx.py`는 `from parse import ...`로 형제 모듈을 임포트하므로 `python src/xxx.py` 형태로 호출된다(같은 디렉터리라 동작).

## Configuration (환경변수)

모든 설정은 `os.environ` 기반이며 `.env.example` 참고. `.env`는 스크립트가 자동 로드하지 **않으므로** 셸에서 export 하거나 명령 앞에 붙여야 한다.

- `EMBED_MODEL` — 기본 `jhgan/ko-sroberta-multitask`(경량 ~440MB). 고정밀은 `BAAI/bge-m3`(~2.3GB). **인덱스 빌드 때와 질의 때 모델이 반드시 일치해야 함** (`meta.json`에 기록됨).
- `LLM_BACKEND` — `ollama`(기본) | `none`(추출형 폴백 강제)
- `LLM_MODEL`, `OLLAMA_HOST`, `RAG_TOPK`, `RAG_ALPHA`(0=BM25만, 1=dense만, 0.5=하이브리드)

## Architecture

데이터 흐름: **HTML → 구조화 트리(dict) → 청크(JSONL) → 인덱스(FAISS+BM25) → 챗봇/검색**

핵심은 **브레드크럼(breadcrumb)** 개념이다. 파서가 매뉴얼의 계층 구조를 `{path:[세그먼트...], text}` 리스트로 평탄화하고, 브레드크럼 1개 = 청크 1개 = 검색/출처 단위가 된다. `path`의 루트는 항상 문서 제목으로 통일된다.

- **`src/parse.py`** — 품질의 90%가 결정되는 핵심. RoboHelp HTML의 CSS class 계층을 구조화 트리로 복원한다. 규칙: `div.title_box`(대분류) → `div.Step00_icon`(중분류) → `div.Step1_Nxx`(단계) → `table tr`(th=항목/td=목록). `li.icon01`/`li.icon02`의 깊이로 부모-자식 관계를 복원하고, `td` 텍스트를 첫 콜론(`:`) 기준으로 용어/설명 분리(`split_term`, 오탐 방지로 용어 40자 제한). 무클래스 `li`는 직전 항목 설명의 줄바꿈 연속으로 병합. `table.T_QAbox`의 `.Que`/`.Ans`는 Q&A로 수집. 파싱 규칙 변경 시 반드시 `tests/test_parse.py`의 골든값을 확인할 것.
- **`src/to_chunks.py`** — 브레드크럼 → 청크. `embed_text = "경로 > ... : 설명"` 형태로 전체 경로를 임베딩 텍스트에 보존(검색 정확도·출처 근거 강화). `chunk_type`은 `path[1]` 섹션명으로 결정(overview/description/glossary/related/qa).
- **`src/to_xlsx.py`** — 구조화 트리 → 원본 샘플과 동일 계열 XLSX(B/C 2열). HTML에서 유도 가능한 메타(제목·코드·화면번호·AUP)만 채우고 발행부서·버전·성명 등은 공란(HTML에 없음).
- **`src/build_index.py`** — 청크 → `data/index/`: `dense.faiss`(정규화 내적=코사인), `bm25.pkl`, `chunks.json`, `meta.json`.
- **`src/rag_common.py`** — 공용 헬퍼(임베더 싱글턴, 청크 로딩)와 **한국어 BM25 토크나이저** `tokenize_ko`(한글은 음절 unigram+bigram, 영숫자는 소문자 토큰). 인덱스 빌드와 질의가 같은 토크나이저를 써야 하므로 여기 한 곳에 둔다.
- **`src/chatbot.py`** — 하이브리드 검색(`hybrid_search`: dense+sparse 각각 min-max 정규화 후 `alpha` 가중합) → top-k 청크를 Ollama 프롬프트에 주입. `[S1],[S2]` 인용마커로 출처를 강제하고, 컨텍스트에 근거 없으면 "매뉴얼에서 확인되지 않습니다."로 답하도록 시스템 프롬프트로 억제. **Ollama 미연결 시 추출형(extractive) 폴백**으로 근거 청크를 그대로 반환.
- **`src/webapp.py`** — 벡터DB 도입 전 하이브리드 검색 품질을 사람이 눈으로 검증하는 계측 콘솔. 표준 라이브러리 `http.server`만 사용(무추가 의존). dense/sparse/combined 점수를 각 히트에 노출. `web/index.html`이 프런트.

## Conventions

- **완전 오프라인 실행이 목표**. 모델 가중치 최초 1회 캐싱 후 네트워크 없이 재실행 가능해야 한다. 새 의존성 추가 시 로컬/오픈소스인지 확인.
- 한글 텍스트 정규화는 `parse.norm`(NBSP·개행 정리, `►` 등 의미기호 보존)을 통과시킨다.
- 테스트는 pytest 없이 `python tests/test_parse.py`로 실행되는 assert 기반. 파서 골든값(브레드크럼 경로, glossary/related/qa 개수)이 회귀 방지선이다.
