# PowerBASE 계좌 매뉴얼 RAG Q&A 챗봇

토스증권 원장시스템(**PowerBASE**) 온라인 매뉴얼(Adobe RoboHelp 2022)의 **"계좌" 부문**을
파싱·색인하여, 사내 담당자가 자연어로 질문하면 **근거(출처) 포함 답변**을 주는 RAG 챗봇입니다.

- **전부 오픈소스·로컬 실행** — 임베딩·검색은 로컬 모델, 답변 LLM은 로컬 서빙(Ollama) 또는 로컬 Claude Code CLI
- 계좌 섹션 **356개 화면 / 4,443개 청크** 색인 완료 (RoboHelp TOC 재귀 크롤링으로 전량 수집)
- **검색품질 QA 웹콘솔** 제공: 상단 = 최적화 답변(챗봇), 하단 = 근거 슬립(경로·점수·출처)

> ⚠️ 이 저장소에는 **코드/문서만** 포함됩니다. 매뉴얼 원문 HTML·색인·XLSX 등 사내 데이터는
> `.gitignore`로 제외되며, 사내망에서 `crawl.py` → `build_index.py`로 재생성합니다.

---

## 1. 시스템 아키텍처

```
                    ┌──────────────────────── 오프라인 색인 (배치) ───────────────────────┐
  RoboHelp 매뉴얼    │                                                                      │
  (사내 HTTP)        │   crawl.py ──▶ parse.py ──┬─▶ to_xlsx.py ──▶ 화면별 XLSX             │
  211.255.203.234    │   (TOC 재귀    (HTML→구조   │   (샘플 포맷 재현)                      │
        │            │    크롤링)      화 트리)     │                                        │
        ▼            │       │                     └─▶ to_chunks.py ─▶ chunks.jsonl          │
   data/html/*.html  │       │                          (경로보존 청크)      │               │
                     │       ▼                                              ▼               │
                     │   data/html/                              build_index.py             │
                     │                                     (임베딩 + BM25 → data/index/)     │
                     └──────────────────────────────────────────────┬───────────────────────┘
                                                                     │
                    ┌──────────────────────── 온라인 서빙 (상시) ─────┴──────────────────────┐
                    │                                                                        │
   브라우저 ◀──────▶│  web/index.html  ◀── HTTP ──▶  webapp.py (표준 http.server)            │
   (QA 콘솔)        │   · 상단 답변창                  ├─ /api/search  하이브리드 검색         │
                    │   · 하단 근거 슬립               │    (FAISS dense + BM25 sparse)        │
                    │   · 인용 [S#] ↔ 슬립 연결        ├─ /api/answer  검색→LLM 답변 생성      │
                    │                                 │    · claude(로컬 CLI) │ ollama │ 추출  │
                    │                                 └─ /api/meta    인덱스 정보             │
                    └────────────────────────────────────────────────────────────────────────┘
```

**두 단계로 분리**되어 있습니다.

1. **오프라인 색인 (배치)** — 매뉴얼 HTML을 수집·파싱하여 검색 인덱스와 XLSX를 만든다. 매뉴얼이
   바뀔 때만 재실행.
2. **온라인 서빙 (상시)** — 인덱스를 메모리에 로드한 웹서버가 질의에 답한다.

---

## 2. 파이프라인 상세 (오프라인 색인)

| 단계 | 스크립트 | 입력 → 출력 | 핵심 로직 |
|---|---|---|---|
| ① 수집 | `src/crawl.py` | TOC → `data/html/*.html` | RoboHelp `toc147.new.js`(계좌 북)를 **재귀 파싱**해 356개 토픽 URL 발견·다운로드 |
| ② 파싱 | `src/parse.py` | HTML → 구조화 dict | CSS class 기반 계층 복원 (아래 참조) — **품질의 핵심** |
| ③ 엑셀 | `src/to_xlsx.py` | dict → `data/xlsx/*.xlsx` | 수작업 샘플과 동일한 B/C 2열 포맷(메타 + 브레드크럼) 재현 |
| ④ 청크 | `src/to_chunks.py` | dict → `data/chunks.jsonl` | 브레드크럼 1개 = 청크 1개, 경로를 `embed_text`에 보존 |
| ⑤ 색인 | `src/build_index.py` | 청크 → `data/index/` | 로컬 임베딩(FAISS) + BM25(pickle) |

### 파서(`parse.py`)의 계층 복원 규칙

RoboHelp HTML은 CSS class로 의미를 표현합니다. 이를 브레드크럼 트리로 복원합니다.

- `div.title_box` → 대분류(화면알아보기/용어찾기/질문보기)
- `div.Step00_icon` → 중분류(화면개요/화면설명/관련화면)
- `div.Step1_Nxx` → 화면설명 단계(조건입력/조회결과) — **테이블이 자식/형제 어느 쪽으로 파싱돼도 처리**
- `th`=항목명, `td > ul > li` = 항목 리스트
  - `li.icon01`=1레벨, `li.icon02`=콜론 유무로 자식항목/►하위불릿 구분, class 없는 `li`=이전 항목의 줄바꿈 연속
- `bground_blue` 셀은 `"용어 : 설명"`을 첫 콜론 기준 분리
- `table.T_QAbox`(`.Que`/`.Ans`) → Q&A 쌍
- 테이블이 없는 단순 화면은 `div.h2` 블록을 화면설명으로 보존

**출력**: `{screen_id, code, title, screen_no, summary, breadcrumbs:[{path,text}], glossary, related, qa}`

예) 브레드크럼 경로 →
`지점계좌서비스약정등록내역 > 화면설명 > 조건입력 > 상품유형 > 개별계좌 > 위탁계좌`

---

## 3. 검색·답변 (온라인 서빙)

### 하이브리드 검색 (`/api/search`)
- **Dense**: 로컬 임베딩(`jhgan/ko-sroberta-multitask`, 768d) + FAISS 내적(코사인)
- **Sparse**: BM25(`rank_bm25`) + 한국어 토크나이저(음절 unigram+bigram, `rag_common.tokenize_ko`)
- **결합**: `α·dense + (1-α)·sparse` (min-max 정규화). α는 UI 슬라이더로 실시간 조절
- 각 결과에 `dense`/`sparse` 성분을 함께 반환 → **어떤 신호로 매칭됐는지 눈으로 판단** 가능

### 답변 생성 (`/api/answer`)
1. 하이브리드 검색으로 top-k 근거 청크 확보
2. 근거를 `[S1] (화면[번호] · 경로)\n텍스트` 형태로 프롬프트에 주입
3. LLM 백엔드 **자동 선택**: `claude`(로컬 Claude Code CLI) → `ollama`(로컬 서버) → **추출-합성**(LLM 없이 오프라인 폴백)
4. 답변에 `[S1]`,`[S2]` 인용 마커 부착 → UI에서 하단 근거 슬립으로 스크롤·하이라이트
5. 근거에 없으면 "매뉴얼에서 확인되지 않습니다" (할루시네이션 억제)

### 웹 콘솔 (`web/index.html`)
- 외부 리소스 0개(오프라인 단일 파일), KOSCOM 코퍼레이트 테마
- **상단**: 질문 말풍선 + 최적화 답변(인용 칩) + 백엔드/소요시간 배지
- **하단**: 근거 슬립 — 순위 탭 · 유형 배지 · **브레드크럼 경로** · dense↔sparse 대비 바 · 원문 링크
- 좌측 레일: 질의어, α, top-k, 청크 유형 필터

---

## 4. 빠른 시작

### 설치
```bash
# uv (오픈소스 파이썬/패키지 관리자)
curl -LsSf https://astral.sh/uv/install.sh | sh
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt \
    --extra-index-url https://download.pytorch.org/whl/cpu
```
임베딩 모델은 최초 1회 자동 다운로드(약 440MB). 이후 완전 오프라인:
```bash
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
```

### 색인 (사내망에서)
```bash
PY=.venv/bin/python
# 계좌 섹션 전체 토픽 목록은 TOC 크롤러가 생성 (data/account_topics.txt)
$PY src/crawl.py --from-file data/account_topics.txt   # HTML 수집
$PY src/to_chunks.py data/html/*.html                  # 청크 생성
$PY src/build_index.py                                  # FAISS + BM25 색인
$PY src/to_xlsx.py   data/html/*.html                  # (선택) 화면별 XLSX
```

### 실행
```bash
PORT=8000 .venv/bin/python src/webapp.py   # → http://localhost:8000
```

### 답변 백엔드 (택1)
- **Claude Code CLI**(기본, 로컬 설치 시 자동): 품질 최상. `CLAUDE_MODEL=sonnet`
- **Ollama**(폐쇄망 자체완결): `ollama pull qwen2.5:3b-instruct` 후 `LLM_BACKEND=ollama`
- **없으면**: 추출-합성 폴백(근거 요약)으로 자동 동작

---

## 5. 디렉터리 구조

```
src/
  crawl.py        RoboHelp TOC 재귀 크롤러 (계좌 토픽 수집)
  parse.py        HTML → 구조화 트리 (계층/용어/Q&A 복원) ★핵심
  to_xlsx.py      → 샘플 포맷 XLSX
  to_chunks.py    → RAG 청크 JSONL (경로 보존)
  build_index.py  → FAISS(dense) + BM25(sparse) 색인
  rag_common.py   임베딩·한국어 토크나이저 공용
  chatbot.py      CLI 챗봇 (검색+LLM, 웹서버와 로직 공유)
  webapp.py       QA 웹서버 (/api/search·/api/answer·/api/meta)
web/index.html    검색품질 QA 콘솔 (오프라인 단일 파일)
tests/test_parse.py  파서 회귀 테스트(골든값)
data/             (gitignore) html·xlsx·chunks·index — 재생성 대상
기획.md            설계·의사결정 기록
```

---

## 6. 설정 (환경변수)

| 변수 | 기본값 | 설명 |
|---|---|---|
| `EMBED_MODEL` | `jhgan/ko-sroberta-multitask` | 임베딩 모델(경량). 고정밀: `BAAI/bge-m3` |
| `LLM_BACKEND` | `auto` | `auto`(claude→ollama→추출) \| `claude` \| `ollama` \| `none` |
| `CLAUDE_MODEL` | `sonnet` | Claude Code CLI 모델 |
| `LLM_MODEL` | `qwen2.5:7b-instruct` | Ollama 모델명 |
| `RAG_TOPK` / `RAG_ALPHA` | `5` / `0.5` | 검색 상위 k / 혼합 가중치 |
| `PORT` | `8000` | 웹서버 포트 |

---

## 7. 로드맵 (품질·사용성 개선)

측정된 데이터 품질 이슈(보일러플레이트 중복, related 과매칭, 제너릭 라벨)를 기준으로:
데이터 정제 → 답변 스트리밍(SSE) → 로컬 리랭커(`bge-reranker-v2-m3`) → 임베딩 업그레이드 →
쿼리 이해·섹션 필터 → 피드백 수집·자동 평가(Recall@k/MRR). 자세한 계획은 `기획.md` 참조.
