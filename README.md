<div align="center">

![PowerBASE 계좌 매뉴얼 RAG 챗봇](assets/banner.svg)

# PowerBASE 계좌 매뉴얼 RAG Q&A 챗봇

**사내 원장시스템 매뉴얼을 자연어로 질문하고, 근거(출처)와 함께 답을 받는 100% 로컬 RAG 챗봇**

[![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Local](https://img.shields.io/badge/100%25-Local_·_Offline-2EC4B6)](#)
[![Open Source](https://img.shields.io/badge/Stack-Open_Source-brightgreen)](#)
[![Screens](https://img.shields.io/badge/화면-356-f5821f)](#)
[![Chunks](https://img.shields.io/badge/청크-4%2C443-f5821f)](#)
[![Search](https://img.shields.io/badge/Search-Hybrid_Dense%2BBM25-8A2BE2)](#)
[![LLM](https://img.shields.io/badge/LLM-Ollama_|_Claude_CLI-e4670a)](#)
[![Deploy](https://img.shields.io/badge/Deploy-Docker_|_systemd-2496ED?logo=docker&logoColor=white)](#)

[⚡ 빠른 시작](#-quick-start-로컬) · [🎬 실전 시나리오](#-실전-시나리오-실측) · [🧭 UI/UX](#-uiux--매뉴얼-데스크) · [🐧 서버 배포](#-리눅스-서버-배포-프로덕션) · [❓ FAQ](#-faq)

</div>

---

## 🎯 Why RAG 챗봇?

토스증권 원장시스템(**PowerBASE**)의 온라인 매뉴얼(Adobe RoboHelp)은 **수백 개 화면**이
트리 메뉴로 흩어져 있어, 담당자가 필요한 항목을 찾으려면 매번 클릭·스크롤·검색을 반복해야 합니다.

| 기존 방식 (RoboHelp GUI) | 이 도구 (RAG 챗봇) |
|---|---|
| 트리 메뉴를 열어 화면을 하나씩 탐색 | **자연어 한 줄**로 질문 |
| 어느 화면에 있는지 알아야 찾음 | 의미로 검색 → **화면·항목 자동 매칭** |
| 답을 직접 읽고 종합 | **근거 포함 답변**을 즉시 생성 |
| 화면 간 관계 파악 어려움 | 관련화면·용어·Q&A까지 **한 번에** |
| 데이터 외부 유출 우려 | **완전 로컬·오프라인** (폐쇄망 OK) |

> **핵심:** 매뉴얼 원문을 그대로 검색 인덱스로 만들고, 검색된 근거만으로 답하게 하여
> **할루시네이션 없이 출처가 검증 가능한** 답변을 제공합니다.

---

## ✨ Key Features

- 🔎 **하이브리드 검색 + 관련도 게이트** — 의미(Dense) + 키워드(BM25) 결합, 리랭커/코사인 임계치 τ로 무관 질의 차단
- 🧭 **계층 경로 보존** — `화면 > 화면설명 > 조건입력 > 상품유형 > 위탁계좌` 브레드크럼을 문맥·출처로 활용
- 💬 **대화형 매뉴얼 데스크** — 스레드형 Q&A + 질문 이력 + 후속질문 제안, 인용 `[S1]` ↔ 근거 카드 양방향 하이라이트
- 🗺️ **근거 지도** — 답변 근거들의 브레드크럼 경로를 병합한 트리로 "매뉴얼 어디에서 왔는지"를 한눈에
- 🗂️ **계좌 섹션 전량** — RoboHelp TOC 재귀 크롤링으로 **356화면 / 4,443청크** 자동 색인
- 🔒 **100% 로컬·오프라인** — 임베딩·검색·LLM·폰트 모두 로컬, 외부 상용 API 불필요(폐쇄망 대응)
- 🎛️ **QA 모드** — `Q` 키(또는 `?qa=1`)로 계측 레이어 토글: α·τ·top-k 슬라이더, dense/sparse 기여도, 게이트 상태
- 🚀 **원클릭 배포** — 설치·색인·실행 스크립트 + Docker + systemd

---

## 🖥️ Demonstration

<div align="center">

![PB 매뉴얼 데스크](assets/console.png)

*중앙 = 대화 스레드(인용 포함 답변) · 우측 = 근거 지도 + 근거 카드 · QA 모드에서 검색 계측 노출*

</div>

---

## 🎬 실전 시나리오 (실측)

실제 색인(계좌 4,443청크)에 실제 질의를 넣어 받은 **무편집 결과**입니다.
환경: CPU 전용(WSL2) · `ko-sroberta` 임베딩 · `bge-reranker-v2-m3` 게이트(τ=0.506, 자동 보정).

| # | 시나리오 | 질문 | 결과 |
|---|---|---|---|
| ① | **항목 위치 찾기** | "변경사용자 항목은 어디서 확인하나요?" | 화면·항목 특정: `지점계좌서비스약정등록내역[0878]` + 인용 2건 (신뢰도 0.73) |
| ② | **업무 절차** | "고객신분 이상 등록된 내역의 해지는 어느 화면에서 처리하나요?" | 처리 화면 `[2473]` 안내 + 조회 전용 `[2474]`와의 구분까지 근거 5건으로 답변 |
| ③ | **원인 설명** | "2007년 이전 개설 계좌는 개설자ID가 조회되지 않는 이유는?" | 매뉴얼 Q&A 근거로 원인(PB 도입일 2007-10-15 이전 데이터 부재) 설명 |
| ④ | **무관 질의 차단** | "오늘 점심 뭐 먹지" | 게이트 차단(best 0.50 < τ 0.506) — **LLM 미호출**, "매뉴얼에서 확인되지 않습니다" |

**② 업무 절차 — 실제 응답**

> **Q.** 고객신분 이상 등록된 내역의 해지는 어느 화면에서 처리하나요?
>
> **A.** 고객신분 이상 등록 내역의 해지는 **고객신분이상등록/해지[2473]** 화면에서 처리합니다 `[S1][S3][S4][S5]`.
> 참고로 고객신분이상등록내역[2474] 화면은 2473 화면에서 처리된 등록·해지 내역을 **조회만** 하는 화면입니다 `[S2]`.
>
> `S1` AC110700 › 관련화면 › 고객신분이상등록/해지[2473] (신뢰도 0.73) · `S2` 고객신분이상등록내역 › 화면개요 (0.73) · AI 생성

**④ 무관 질의 차단 — 할루시네이션 방지 실측**

> **Q.** 오늘 점심 뭐 먹지
>
> **A.** 매뉴얼에서 확인되지 않습니다. *(관련도가 임계치 미만 — 근거는 참고용 표시)*
>
> `gate: {mode: rerank, best: 0.50, tau: 0.506, all_low: true}` → LLM을 호출하지 않아 지어낸 답이 원천 차단됩니다.
> τ는 도메인 내 질의 120개 / 무관 질의 15개 분포로 자동 보정(도메인 내 통과 95% · 무관 거부 93%).

> ⏱️ **지연 시간 트레이드오프** — 리랭커 게이트는 CPU에서 검색에 +10~15초를 더합니다(정밀 판정 비용).
> 속도가 우선이면 `RERANK_ENABLE=off`로 코사인 게이트(수십 ms)로 전환할 수 있습니다. 답변 생성은 백엔드에 따라 5~15초(LLM) 또는 즉시(발췌 폴백).

---

## 🧭 UI/UX — 매뉴얼 데스크

하나의 화면이 두 사용자를 위한 **두 모드**로 동작합니다.

| | 상담 모드 (기본) | QA 모드 (`Q` 키 · `?qa=1`) |
|---|---|---|
| 대상 | 업무 담당자 | 검색품질 튜닝 엔지니어 |
| 화면 | 질문 이력 · 대화 스레드 · 근거 패널 | + 계측 패널(α·τ·top-k·유형 필터) |
| 근거 카드 | 유형·경로·본문·출처만 | + dense/sparse 기여도 · 신뢰도 · 게이트 상태 |

**핵심 인터랙션**

- **근거 지도** — 답변 근거들의 브레드크럼 경로를 병합한 트리. 인용 `[S1]` ↔ 근거 카드 ↔ 지도 경로가 hover/클릭으로 **양방향 하이라이트**되어, 답이 매뉴얼 어디에서 왔는지 즉시 보입니다.
- **근거 선노출** — 검색(`/api/search`)이 끝나면 근거가 먼저 뜨고, 답변(`/api/answer`)이 뒤따라 채워집니다. 로딩은 "매뉴얼 검색 중 → 근거 n건 확보 → 답변 작성 중" 단계로 표시.
- **대화 경험** — 질문 이력(localStorage, 오늘/어제 그룹) · 추천 질문 칩(매뉴얼 Q&A에서 자동 추출) · 후속질문 제안 · 답변 복사/재생성 · 화면코드 클릭 복사.
- **게이트 안내** — 근거가 전부 임계치 미만이면 LLM을 호출하지 않고 "매뉴얼에서 확인되지 않았어요" 카드와 대안 질문을 제시합니다(할루시네이션 차단).
- **딥링크** — `/?q=질문` 으로 질문 상태를 공유, `/?qa=1` 로 QA 모드 진입.

**단축키** — `Enter` 전송 · `Shift+Enter` 줄바꿈 · `/` 또는 `Ctrl(⌘)+K` 입력창 포커스 · `Q` QA 모드 · `Esc` 시트 닫기

> 프런트는 `web/`의 바닐라 3파일(index.html·styles.css·app.js) + Pretendard 로컬 번들 — 외부 CDN·프레임워크 없이 폐쇄망에서 동일하게 동작합니다. 반응형(모바일 시트)·`prefers-reduced-motion`·키보드 접근성 지원.

---

## 🏗️ Architecture

**오프라인 색인(배치)** 과 **온라인 서빙(상시)** 의 2단계 구조입니다.

```
┌──────────────────── 오프라인 색인 (매뉴얼 변경 시) ────────────────────┐
│  crawl.py ─▶ parse.py ─┬─▶ to_xlsx.py ──▶ 화면별 XLSX                 │
│  (TOC 재귀   (HTML→구조 │   (샘플 포맷 재현)                            │
│   크롤링)     화 트리)   └─▶ to_chunks.py ─▶ chunks.jsonl              │
│                              (경로보존 청크)     │                     │
│                                                 ▼                     │
│                                        build_index.py                 │
│                                 (임베딩 + BM25 → data/index/)          │
└──────────────────────────────────────────┬───────────────────────────┘
                                            │
┌──────────────────── 온라인 서빙 (상시) ────┴───────────────────────────┐
│  web/ (index.html·styles.css·app.js·fonts) ◀── HTTP ──▶ webapp.py     │
│   · 대화 스레드 + 이력       ├─ /api/search  하이브리드(FAISS+BM25)     │
│   · 근거 지도 + 근거 카드    ├─ /api/answer  검색→LLM(claude|ollama|추출)│
│   · 인용 [S#] ↔ 카드 ↔ 지도  └─ /api/meta    메타 + 추천 질문           │
└────────────────────────────────────────────────────────────────────────┘
```

### 파이프라인

| 단계 | 스크립트 | 입력 → 출력 | 핵심 |
|---|---|---|---|
| ① 수집 | `crawl.py` | TOC → `data/html/` | RoboHelp `toc147.new.js` **재귀 파싱**으로 356토픽 발견 |
| ② 파싱 | `parse.py` | HTML → 구조화 dict | CSS class 기반 **계층 복원** (품질의 핵심) |
| ③ 엑셀 | `to_xlsx.py` | dict → `data/xlsx/` | 수작업 샘플과 동일 B/C 2열 포맷 |
| ④ 청크 | `to_chunks.py` | dict → `chunks.jsonl` | 브레드크럼 1개 = 청크 1개, 경로 보존 |
| ⑤ 색인 | `build_index.py` | 청크 → `data/index/` | 로컬 임베딩(FAISS) + BM25 |

### 파서 계층 복원 규칙 (`parse.py`)

- `div.title_box`(대분류) → `div.Step00_icon`(중분류) → `div.Step1_Nxx`(단계)
- `th`=항목명, `td>ul>li` = 항목 · `li.icon01/icon02` 중첩 깊이로 부모-자식 복원
- `bground_blue` 셀은 `"용어 : 설명"` 첫 콜론 분리 · `table.T_QAbox` → Q&A
- 테이블이 **자식/형제 어느 쪽으로 파싱돼도** 처리, 테이블 없는 화면은 `div.h2` 보존

---

## ⚡ Quick Start (로컬)

```bash
# 1) 설치 (uv 오픈소스 파이썬/패키지 관리자 자동 사용)
curl -LsSf https://astral.sh/uv/install.sh | sh
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt \
    --extra-index-url https://download.pytorch.org/whl/cpu

# 2) 색인 (사내망; 최초 1회 임베딩 모델 ~440MB 다운로드 후 오프라인)
PY=.venv/bin/python
$PY src/crawl.py --from-file data/account_topics.txt
$PY src/to_chunks.py data/html/*.html
$PY src/build_index.py

# 3) 실행
PORT=8000 $PY src/webapp.py        # → http://localhost:8000
```

---

## 🐧 리눅스 서버 배포 (프로덕션)

일반 리눅스 서버(Ubuntu/Debian/RHEL, x86_64)에 **3단계**로 배포합니다. root 불필요.

### 방식 A — 스크립트 + systemd (권장)

```bash
git clone https://github.com/humanist96/pb_online_manual_chatbot.git
cd pb_online_manual_chatbot

bash deploy/install.sh     # ① venv + 의존성 부트스트랩
bash deploy/build.sh       # ② 색인 빌드 (사내망)
bash deploy/run.sh         # ③ 실행 → http://<서버IP>:8000
```

상시 실행(부팅 자동시작·크래시 재시작):

```bash
sudo cp deploy/pb-chatbot.service /etc/systemd/system/   # User/경로 수정 후
sudo systemctl daemon-reload && sudo systemctl enable --now pb-chatbot
journalctl -u pb-chatbot -f
```

> `make install && make build && make run` 으로도 동일하게 실행됩니다.

### 방식 B — Docker

```bash
bash deploy/build.sh        # 호스트에서 data/(색인) 준비
docker compose up -d        # → http://<서버IP>:8000
```

> 이미지에는 **코드만** 포함되고, 색인(`./data`)·모델 캐시는 볼륨으로 주입됩니다(사내 데이터 보호).
> 폐쇄망 자체완결 답변이 필요하면 `docker-compose.yml`의 **Ollama 서비스** 주석을 해제하세요.

| 배포 파일 | 용도 |
|---|---|
| `deploy/install.sh` · `build.sh` · `run.sh` | 설치 · 색인 · 실행 |
| `deploy/pb-chatbot.service` | systemd 유닛(자동 재시작) |
| `Dockerfile` · `docker-compose.yml` | 컨테이너 배포 |
| `requirements.lock.txt` · `Makefile` | 고정버전 설치 · 편의 명령 |

---

## 🔧 설정 (환경변수)

| 변수 | 기본값 | 설명 |
|---|---|---|
| `EMBED_MODEL` | `jhgan/ko-sroberta-multitask` | 임베딩 모델(경량). 고정밀: `BAAI/bge-m3` |
| `LLM_BACKEND` | `auto` | `auto`(claude→ollama→추출) · `claude` · `ollama` · `none` |
| `CLAUDE_MODEL` / `LLM_MODEL` | `sonnet` / `qwen2.5:7b-instruct` | Claude CLI / Ollama 모델 |
| `RAG_TOPK` / `RAG_ALPHA` | `5` / `0.5` | 검색 상위 k / 혼합 가중치 |
| `RERANK_ENABLE` | `auto` | 관련도 게이트 리랭커: `auto`(모델 있으면 사용) · `on` · `off`(코사인 폴백) |
| `RERANK_MODEL` | `BAAI/bge-reranker-v2-m3` | 로컬 CrossEncoder 리랭커(최초 1회 ~600MB 캐시) |
| `HOST` / `PORT` | `0.0.0.0` / `8000` | 바인딩 주소·포트 |

---

## 🧰 Tech Stack

| 영역 | 기술 |
|---|---|
| 파싱 | `beautifulsoup4` · `lxml` |
| 임베딩 | `sentence-transformers` (`ko-sroberta`, 옵션 `bge-m3`) |
| 검색 | `faiss-cpu`(dense) · `rank-bm25`(sparse) · 한국어 토크나이저 |
| 관련도 게이트 | `bge-reranker-v2-m3` CrossEncoder + τ 자동 보정(`calibrate_threshold.py`) |
| LLM | 로컬 **Ollama** / 로컬 **Claude Code CLI** / 추출-합성 폴백 |
| 서버·UI | Python 표준 `http.server` · 바닐라 JS/CSS 3파일 + Pretendard 로컬 번들(KOSCOM 테마, 무프레임워크) |
| 배포 | uv · Docker · systemd |
| **외부 상용 API** | **없음** (완전 오프라인 실행 가능) |

---

## ❓ FAQ

**Q. 인터넷 없이 되나요?**
A. 네. 임베딩·리랭커 모델만 최초 1회 캐시하면 `HF_HUB_OFFLINE=1`로 완전 오프라인 동작합니다.

**Q. 왜 저장소에 매뉴얼 데이터가 없나요?**
A. 사내 금융시스템 원문 유출 방지를 위해 `data/`(HTML·색인·XLSX)는 `.gitignore`로 제외합니다.
사내망에서 `crawl.py` → `build_index.py`로 재생성합니다.

**Q. LLM 없이도 답하나요?**
A. 네. Ollama/Claude CLI가 없으면 **추출-합성 폴백**이 상위 근거를 출처와 함께 제시합니다.

**Q. 매뉴얼과 무관한 질문을 하면?**
A. 관련도 게이트(리랭커/코사인 임계치 τ)가 근거 신뢰도를 판정해, 전부 임계치 미만이면
LLM을 호출하지 않고 "매뉴얼에서 확인되지 않았어요"로 답합니다. τ는 `calibrate_threshold.py`가
도메인 내/외 질의 분포로 자동 보정합니다.

**Q. GPU가 필요한가요?**
A. 아니요. CPU 전용으로 동작합니다(경량 3B 모델 권장, RAM 8GB면 충분).

---

## 🗺️ 로드맵

~~로컬 **리랭커**(`bge-reranker-v2-m3`) + 관련도 게이트~~ ✅ → 데이터 정제(중복·보일러플레이트 제거)
→ 답변 **스트리밍(SSE)** → 임베딩 업그레이드 → 쿼리 이해·섹션 필터 → 피드백 수집·자동 평가(Recall@k/MRR).
상세는 [`기획.md`](기획.md) 참조.

---

## 📄 License

사내 이용(Internal Use). 매뉴얼 콘텐츠 저작권은 코스콤(KOSCOM)에 있습니다.

<div align="center">
<sub>Built for PowerBASE 원장시스템 · 100% Local RAG</sub>
</div>
