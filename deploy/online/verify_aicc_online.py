"""상담사례(AICC) 업서트 후 자동 검증 — 로컬 실행 도구(배포 제외, 표준 라이브러리만).

⚠️ 업서트 완료 후에만 의미가 있다. 실데이터 Upstash Vector 인덱스
(공개 UPSTASH_VECTOR_REST_URL/TOKEN — sweep_search.py가 실데이터 질의 평가에 쓰는
그 인덱스)에 질의만 보내며 쓰기는 하지 않는다. .env.local 자격증명은 출력하지 않는다.

검증 5종(각각 PASS/FAIL, 전체 요약·exit code):
 1. /info 벡터 수 == --expect(기본 57957+AICC수)
 2. 자기-검색: 각 AICC 카드 핵심질문 → 자기 id top-3 (통과율 >= --min-selfhit)
 3. 교차 오염: 화면매뉴얼 대표 질의 10개 top-3에 manual=='상담사례' 0건
 4. τ 게이트: AICC 자기-검색 best score >= 0.70 통과율 + 무관 질의 5개 best < 0.70
 5. scope GLOB: filter scope_key GLOB '상담사례*' 질의가 상담사례 청크만 반환

결과: stdout 요약 + data/aicc_verify_report.json(git 자동제외).

  python deploy/online/verify_aicc_online.py --expect 58500     # 업서트 후 실행
"""
from __future__ import annotations
import argparse
import json
import pathlib
import random
import re
import sys
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DEFAULT_CHUNKS = ROOT / "data" / "chunks_aicc.jsonl"
DEFAULT_QUESTIONS = ROOT / "data" / "questions.json"
DEFAULT_OUT = ROOT / "data" / "aicc_verify_report.json"
ENV_LOCAL = HERE / ".env.local"

BASE_COUNT = 57957            # AICC 이전 실데이터 벡터 수(.ingest_state 기준)
GATE_TAU = 0.70
AICC_MANUAL = "상담사례"

# 교차 오염/게이트 기본 질의(questions.json 부재 시 폴백).
FALLBACK_SCREEN_QUERIES = [
    "고객 신분 이상 등록된 내역 조회하고 해지하는 화면은?",
    "투자성향을 공격투자형으로 수정한 내역을 조회하려면?",
    "해외 채권 이자와 세금 자동계산이 가능한가요?",
    "증거금 징수 정정은 개별계좌만 가능한가요?",
    "계좌 폐쇄일자를 확인하는 방법은?",
    "고객확인정보 CDD 등록 화면은 어디인가요?",
    "펀드 환매 대금 입금일을 조회하는 화면은?",
    "미수금이 발생했을 때 처리하는 화면은?",
    "예탁금 이용료 지급 내역을 조회하려면?",
    "반대매매 예정 종목을 확인하는 화면은?",
]
IRRELEVANT_QUERIES = [
    "오늘 날씨 알려줘",
    "김치찌개 맛있게 끓이는 법",
    "주말에 갈 만한 여행지 추천",
    "파이썬으로 웹서버 만드는 법",
    "가장 좋아하는 영화가 뭐야?",
]


# ── Upstash 질의(읽기 전용) ──────────────────────────────────────────────
def parse_env_local(path: pathlib.Path) -> tuple[str, str]:
    if not path.exists():
        raise SystemExit(f"[aicc-verify] .env.local이 없습니다: {path}")
    env = path.read_text(encoding="utf-8")

    def grab(key: str) -> str:
        m = re.search(rf"^{key}=(.*)$", env, re.M)
        if not m:
            raise SystemExit(f"[aicc-verify] .env.local에 {key} 없음")
        return m.group(1).strip().strip("'\"")

    return grab("UPSTASH_VECTOR_REST_URL"), grab("UPSTASH_VECTOR_REST_TOKEN")


def post(url: str, token: str, path: str, body: dict) -> dict:
    req = urllib.request.Request(
        f"{url.rstrip('/')}{path}", data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def query_data(url, token, q, topk=5, filter_expr=None, dense=False) -> list[dict]:
    body = {"data": q, "topK": topk, "includeMetadata": True}
    if dense:
        body["queryMode"] = "DENSE"
    if filter_expr:
        body["filter"] = filter_expr
    return post(url, token, "/query-data", body).get("result", [])


# ── 질의 소재 ────────────────────────────────────────────────────────────
def card_query(chunk: dict) -> str:
    """카드 text의 Q줄(없으면 embed_text의 이슈부)을 질의로."""
    text = chunk.get("text") or ""
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("Q."):
            return s[2:].strip() or s
        if s.startswith("Q"):
            return s.lstrip("Q.").strip() or s
    embed = chunk.get("embed_text") or ""
    # embed_text = "[상담사례/부문] 화면번호 NNNN {핵심질문} : {정답}" → 콜론 앞 이슈부
    body = embed.split("]", 1)[-1]
    return (body.split(":", 1)[0]).strip() or (text[:120] or chunk.get("id", ""))


def screen_queries(qpath: pathlib.Path, n: int = 10) -> list[str]:
    if not qpath.exists():
        return FALLBACK_SCREEN_QUERIES[:n]
    data = json.loads(qpath.read_text(encoding="utf-8"))
    screen = [e["q"] for e in data
              if isinstance(e, dict) and e.get("m") == "화면" and e.get("q")]
    if len(screen) < n:
        return (screen + FALLBACK_SCREEN_QUERIES)[:n]
    rng = random.Random(20260727)   # seed 고정 → 재현 가능한 대표 샘플
    return rng.sample(screen, n)


# ── 검증 항목 ────────────────────────────────────────────────────────────
def check_vector_count(url, token, expect: int) -> dict:
    info = post(url, token, "/info", {}).get("result", {})
    got = info.get("vectorCount")
    ok = got == expect
    return {"name": "vector_count", "pass": ok, "expect": expect, "got": got}


def check_self_hit(url, token, chunks, min_rate) -> dict:
    hits, scores, fails = 0, [], []
    for c in chunks:
        res = query_data(url, token, card_query(c), topk=5)
        ids = [r.get("id") for r in res[:3]]
        if c["id"] in ids:
            hits += 1
        else:
            fails.append(c["id"])
        if res:
            scores.append((c["id"], res[0].get("score", 0.0)))
    total = len(chunks) or 1
    rate = hits / total
    return {"name": "self_hit", "pass": rate >= min_rate, "rate": round(rate, 4),
            "min": min_rate, "hits": hits, "total": len(chunks),
            "misses": fails[:20], "best_scores": scores}


def check_cross_contamination(url, token, queries) -> dict:
    leaks = []
    for q in queries:
        res = query_data(url, token, q, topk=3)
        for r in res[:3]:
            if (r.get("metadata") or {}).get("manual") == AICC_MANUAL:
                leaks.append({"q": q, "id": r.get("id")})
    return {"name": "cross_contamination", "pass": not leaks,
            "queries": len(queries), "leaks": leaks}


def check_tau_gate(url, token, self_scores, irrelevant) -> dict:
    # AICC 자기-검색 best score(dense) >= τ 통과율.
    above = sum(1 for _id, s in self_scores if s >= GATE_TAU)
    self_total = len(self_scores) or 1
    self_rate = above / self_total
    # 무관 질의 best(dense) < τ 전부 유지.
    bad = []
    for q in irrelevant:
        res = query_data(url, token, q, topk=1, dense=True)
        best = res[0].get("score", 0.0) if res else 0.0
        if best >= GATE_TAU:
            bad.append({"q": q, "score": best})
    return {"name": "tau_gate", "pass": not bad,
            "self_above_tau_rate": round(self_rate, 4),
            "self_above": above, "self_total": len(self_scores),
            "irrelevant_leaks": bad, "tau": GATE_TAU}


def check_scope_glob(url, token) -> dict:
    res = query_data(url, token, "상담 문의 사례",
                     topk=10, filter_expr="scope_key GLOB '상담사례*'")
    off = [{"id": r.get("id"),
            "manual": (r.get("metadata") or {}).get("manual")}
           for r in res
           if (r.get("metadata") or {}).get("manual") != AICC_MANUAL]
    return {"name": "scope_glob", "pass": not off,
            "returned": len(res), "off_scope": off}


# ── 실행 ─────────────────────────────────────────────────────────────────
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="상담사례(AICC) 온라인 업서트 검증")
    ap.add_argument("--chunks", type=pathlib.Path, default=DEFAULT_CHUNKS)
    ap.add_argument("--questions", type=pathlib.Path, default=DEFAULT_QUESTIONS)
    ap.add_argument("--expect", type=int, default=None,
                    help="기대 벡터 수(기본 57957+AICC 청크 수)")
    ap.add_argument("--min-selfhit", type=float, default=0.8,
                    help="자기-검색 top-3 통과율 기준(기본 0.8)")
    ap.add_argument("--out", type=pathlib.Path, default=DEFAULT_OUT)
    args = ap.parse_args(argv)

    if not args.chunks.exists():
        raise SystemExit(f"[aicc-verify] 청크 파일이 없습니다: {args.chunks}")
    chunks = [json.loads(l) for l in args.chunks.open(encoding="utf-8") if l.strip()]
    expect = args.expect if args.expect is not None else BASE_COUNT + len(chunks)

    url, token = parse_env_local(ENV_LOCAL)
    scr_q = screen_queries(args.questions, 10)

    results = []
    results.append(check_vector_count(url, token, expect))
    self_res = check_self_hit(url, token, chunks, args.min_selfhit)
    results.append(self_res)
    results.append(check_cross_contamination(url, token, scr_q))
    results.append(check_tau_gate(url, token, self_res.get("best_scores", []),
                                  IRRELEVANT_QUERIES))
    results.append(check_scope_glob(url, token))

    all_pass = all(r["pass"] for r in results)
    report = {"aicc_chunks": len(chunks), "expect_vectors": expect,
              "all_pass": all_pass, "checks": results}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                        encoding="utf-8")

    print(f"\n[aicc-verify] AICC {len(chunks)}건, 기대 벡터 {expect}")
    for r in results:
        print(f"  {'PASS' if r['pass'] else 'FAIL'}  {r['name']}")
    print(f"→ {args.out}")
    print(f"{'전체 PASS' if all_pass else '일부 FAIL'}")
    return 0 if all_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
