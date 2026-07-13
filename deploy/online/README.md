# 온라인 공개 데모 — Vercel + Upstash Vector + OpenAI

> ⚠️ **이 폴더는 공개 데모 전용 예외 구역**입니다. PowerBASE 명칭의 **합성 데모 데이터**만 다루며
> 사내 폐쇄망 배포(코어)와 완전히 분리됩니다. 사내 매뉴얼 원문을 절대 올리지 마세요.

## 구성 (전부 무료 티어 + OpenAI 종량)

- **Vercel Hobby** — 정적 프런트(`public/`, 기존 웹 UI 사본) + Python 서버리스 6함수(`api/`: meta·search·sectors·answer·suggest·feedback)
- **Upstash Vector 무료** — 하이브리드 인덱스: 내장 **BGE-M3**(dense) + **BM25**(sparse), DBSF 융합.
  임베딩 연산이 Upstash 서버에서 수행되므로 Vercel 함수는 표준 라이브러리만 사용(모델 0MB)
- **OpenAI** — 명시적 opt-in일 때만 답변 생성. 키·Redis 비용 가드가 없거나 장애이면 추출형으로 강등
- **일일 상한 가드** — Redis 카운터가 있어야 OpenAI를 호출하며, 가드 장애 시 추출형으로 강등

## 배포 절차

```bash
# 0) 데모 데이터 생성(이미 커밋돼 있으면 생략) — 832청크, 결정적
python deploy/online/gen_demo_data.py

# 1) Upstash 콘솔(console.upstash.com)에서 Vector 인덱스 생성
#    Type: Hybrid · Dense: 내장 임베딩 모델(현 인덱스: text-embedding-3-small) · Sparse: BM25

# 2) 업서트 (일 10K 한도 내 1회, 832건)
export UPSTASH_VECTOR_REST_URL=... UPSTASH_VECTOR_REST_TOKEN=...
export PB_APPROVE_PUBLIC_DEPLOY=I_ACKNOWLEDGE_PUBLIC_SYNTHETIC_DEPLOY
python deploy/online/ingest.py --approve-public-deploy

# 3) Vercel 배포 (프로젝트 루트 = deploy/online)
cd deploy/online
vercel link
vercel env add UPSTASH_VECTOR_REST_URL
vercel env add UPSTASH_VECTOR_REST_TOKEN
vercel env add PUBLIC_DEMO              # 익명 합성 데모를 명시할 때만 true
vercel env add DEMO_ACCESS_KEY          # PUBLIC_DEMO 미설정 시 헤더 키 방식(권장)
vercel env add OPENAI_API_KEY          # 선택. Redis 비용 가드가 없으면 사용하지 않음
vercel env add UPSTASH_REDIS_REST_URL
vercel env add UPSTASH_REDIS_REST_TOKEN
vercel deploy --prod
```

### 배포 전 승인 게이트

`ingest.py` 자체가 `--approve-public-deploy` 플래그와 `PB_APPROVE_PUBLIC_DEPLOY=I_ACKNOWLEDGE_PUBLIC_SYNTHETIC_DEPLOY`를 모두 받지 않으면 외부 업로드를 시작하지 않는다. 정상 완료 메시지와 원격 smoke verification이 통과하기 전에는 Vercel을 배포하지 않는다.

공개 질문에 실계좌·고객정보·전화·이메일을 입력하지 말 것. 이 경로의 질문과 피드백은 외부 Vector/LLM에 전송될 수 있으며, 실데이터는 `ingest_real.py`의 break-glass 승인 없이 읽기·전송할 수 없다.

## 로컬 확인

```bash
cd deploy/online && vercel dev     # http://localhost:3000
curl "localhost:3000/api/search?q=약정 해지&topk=5"                 # scope_hint.ambiguous 기대
curl "localhost:3000/api/search?q=약정 해지&scope=화면%3E계좌"       # 계좌만
```

## 게이트 τ 보정 (배포 후 1회)

DBSF 융합 점수 분포는 인덱스에 따라 다르므로, 배포 후 무관 질의("안녕", "점심 뭐 먹지")와
정상 질의 몇 개의 `gate.best`를 비교해 `GATE_TAU` env를 조정한다(기본 0.70 — 2026-07 실측 보정: 무관 0.61~0.66 vs 정상 0.73+).

## 사용자 피드백 (버그·품질·매뉴얼 보강)

테스터가 데모 페이지 안에서 피드백을 **등록·조회**하고, 관리자가 **통계**로 현황을 본다.
저장은 기존 Upstash Redis 재사용(추가 인프라·의존성 0). 함수는 `api/feedback.py` 1개.

- **진입점** — 헤더 「피드백」 버튼(둘러보기·통계·남기기 탭), 답변 하단 👍/👎·「피드백」(질문·근거 자동 첨부),
  게이트 차단 답변의 "보강 요청하기" 링크.
- **유형 5종** — 버그 / 답변 품질 / 매뉴얼 최신화 / 매뉴얼 보강 / 제안·기타. 유형별 작성 가이드·예시가 폼에 표시.
- **통계** — 유형·상태 분포, 14일 등록 추이, 답변 👍 반응 추이, 공감 TOP 5 (인라인 SVG, 무의존).
- **안전장치** — `FEEDBACK_ENABLED=true` 및 전용 Redis 설정 시에만 활성화된다. 기본은 저장·목록·컨텍스트·이미지가 비활성이며, PII 패턴 차단, IP 해시 요율 제한, honeypot, XSS 이스케이프를 적용한다.

```bash
# 환경변수(Vercel + .env.local)
vercel env add FEEDBACK_ADMIN_KEY    # 상태변경(접수→반영) 권한 키. 비우면 상태변경 비활성
vercel env add FEEDBACK_RATE_LIMIT   # 선택, 기본 10 (건/일/IP)
vercel env add FEEDBACK_ENABLED       # true에서만 저장을 시작
vercel env add FEEDBACK_REDIS_REST_URL
vercel env add FEEDBACK_REDIS_REST_TOKEN
vercel env add FEEDBACK_PUBLIC_BOARD_ENABLED # true일 때만 done 피드백 공개
vercel env add FEEDBACK_CONTEXT_ENABLED      # 기본 false
vercel env add FEEDBACK_IMAGES_ENABLED       # 기본 false

# 관리자 상태변경: 데모 URL 에 ?admin=1 → 모달의 "🔑 관리자" 로 키 입력(sessionStorage, 서버 검증)

# 주간 리뷰·백업 — 피드백 전량 내려받기 + 보강 요청 목록(마크다운)
export FEEDBACK_REDIS_REST_URL=... FEEDBACK_REDIS_REST_TOKEN=...
python deploy/online/export_feedback.py --md 매뉴얼보강요청.md   # → data/feedback.jsonl
```

빠른 점검(vercel dev):
```bash
curl -XPOST "localhost:3000/api/feedback" -d '{"type":"bug","content":"테스트 등록 내용입니다"}'   # {ok,item}
curl "localhost:3000/api/feedback?n=5"                 # 최신순 목록
curl "localhost:3000/api/feedback?action=stats"        # 집계
```

## 무료 한도 요약 (2026-07 검증)

| 서비스 | 한도 | 데모 사용량 |
|---|---|---|
| Vercel Hobby | 월 100만 호출 · Python 함수 500MB/300s | 함수 <1MB, 요청당 <2s |
| Upstash Vector | 200M 차원 · 일 10K 쿼리 | 832×1024 ≈ 85만 차원(0.4%) |
| OpenAI | 종량 | 질문당 ≈ $0.0003 (일 300건 상한 가드) |
