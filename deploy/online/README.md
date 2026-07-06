# 온라인 공개 데모 — Vercel + Upstash Vector + OpenAI

> ⚠️ **이 폴더는 공개 데모 전용 예외 구역**입니다. 합성 데이터(DemoBASE)만 다루며
> 사내 폐쇄망 배포(코어)와 완전히 분리됩니다. 사내 매뉴얼 원문을 절대 올리지 마세요.

## 구성 (전부 무료 티어 + OpenAI 종량)

- **Vercel Hobby** — 정적 프런트(`public/`, 기존 웹 UI 사본) + Python 서버리스 4함수(`api/`)
- **Upstash Vector 무료** — 하이브리드 인덱스: 내장 **BGE-M3**(dense) + **BM25**(sparse), DBSF 융합.
  임베딩 연산이 Upstash 서버에서 수행되므로 Vercel 함수는 표준 라이브러리만 사용(모델 0MB)
- **OpenAI** — `gpt-4o-mini` 답변 생성(질문당 ≈$0.0003). 키 없으면 추출형 폴백으로도 동작
- **일일 상한 가드** — Upstash Redis(선택) 카운터로 AI 답변 일 300건 초과 시 추출형 전환

## 배포 절차

```bash
# 0) 데모 데이터 생성(이미 커밋돼 있으면 생략) — 832청크, 결정적
python deploy/online/gen_demo_data.py

# 1) Upstash 콘솔(console.upstash.com)에서 Vector 인덱스 생성
#    Type: Hybrid · Dense: 내장 임베딩 모델(현 인덱스: text-embedding-3-small) · Sparse: BM25

# 2) 업서트 (일 10K 한도 내 1회, 832건)
export UPSTASH_VECTOR_REST_URL=... UPSTASH_VECTOR_REST_TOKEN=...
python deploy/online/ingest.py

# 3) Vercel 배포 (프로젝트 루트 = deploy/online)
cd deploy/online
vercel link
vercel env add UPSTASH_VECTOR_REST_URL
vercel env add UPSTASH_VECTOR_REST_TOKEN
vercel env add OPENAI_API_KEY          # 선택(없으면 추출형)
vercel deploy --prod
```

## 로컬 확인

```bash
cd deploy/online && vercel dev     # http://localhost:3000
curl "localhost:3000/api/search?q=약정 해지&topk=5"                 # scope_hint.ambiguous 기대
curl "localhost:3000/api/search?q=약정 해지&scope=계좌"              # 계좌만
```

## 게이트 τ 보정 (배포 후 1회)

DBSF 융합 점수 분포는 인덱스에 따라 다르므로, 배포 후 무관 질의("안녕", "점심 뭐 먹지")와
정상 질의 몇 개의 `gate.best`를 비교해 `GATE_TAU` env를 조정한다(기본 0.70 — 2026-07 실측 보정: 무관 0.61~0.66 vs 정상 0.73+).

## 무료 한도 요약 (2026-07 검증)

| 서비스 | 한도 | 데모 사용량 |
|---|---|---|
| Vercel Hobby | 월 100만 호출 · Python 함수 500MB/300s | 함수 <1MB, 요청당 <2s |
| Upstash Vector | 200M 차원 · 일 10K 쿼리 | 832×1024 ≈ 85만 차원(0.4%) |
| OpenAI | 종량 | 질문당 ≈ $0.0003 (일 300건 상한 가드) |
