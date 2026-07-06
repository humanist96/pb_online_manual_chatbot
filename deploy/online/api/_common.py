"""
온라인 데모 공용 로직 — Upstash Vector 하이브리드 검색 + OpenAI 답변.

※ 이 폴더(deploy/online/)는 공개 데모 전용 예외 구역이다(CLAUDE.md 참고).
   합성 데이터(PowerBASE)만 다루며, 사내 폐쇄망 배포와 무관하다.
   외부 의존 없이 표준 라이브러리만 사용(Vercel 콜드스타트 최소화).

환경변수(Vercel env):
  UPSTASH_VECTOR_REST_URL / UPSTASH_VECTOR_REST_TOKEN   필수
  OPENAI_API_KEY                                        답변 생성(없으면 추출형)
  OPENAI_MODEL           기본 gpt-4o-mini
  GATE_TAU               게이트 임계(기본 0.35 — DBSF 융합 점수 기준, D5에서 보정)
  ANSWER_DAILY_LIMIT     일일 AI 답변 상한(기본 300, 초과 시 추출형 폴백)
  UPSTASH_REDIS_REST_URL / UPSTASH_REDIS_REST_TOKEN     상한 카운터(선택)
"""
from __future__ import annotations
import os
import json
import time
import urllib.parse
import urllib.request

from _static import META, SECTORS  # ingest.py가 demo_data에서 생성

VEC_URL = os.environ.get("UPSTASH_VECTOR_REST_URL", "").rstrip("/")
VEC_TOKEN = os.environ.get("UPSTASH_VECTOR_REST_TOKEN", "")
OPENAI_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
GATE_TAU = float(os.environ.get("GATE_TAU", "0.70"))  # dense 코사인 보정치(무관 0.61~0.66 vs 정상 0.73+)
DAILY_LIMIT = int(os.environ.get("ANSWER_DAILY_LIMIT", "300"))
REDIS_URL = os.environ.get("UPSTASH_REDIS_REST_URL", "").rstrip("/")
REDIS_TOKEN = os.environ.get("UPSTASH_REDIS_REST_TOKEN", "")

SYSTEM_PROMPT = (
    "당신은 증권 원장시스템(PowerBASE) 온라인 매뉴얼 도우미다(공개 데모: 합성 데이터). "
    "아래 [근거]에 있는 내용만 사용해 한국어로 간결하고 정확하게 답한다. "
    "근거에 없으면 '매뉴얼에서 확인되지 않습니다.'라고 답하고 추측하지 않는다. "
    "핵심을 먼저 말하고, 사용한 근거마다 문장 끝에 [S1],[S2] 형태의 출처 마커를 붙인다."
)


def _post(url: str, token: str, body: dict | list, timeout: int = 20):
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _filter_expr(scope: list[str] | None, types: set[str] | None) -> str:
    parts = []
    if scope:
        key = ">".join(scope).replace("'", "")
        parts.append(f"scope_key GLOB '{key}*'")
    if types:
        ors = " OR ".join(f"chunk_type = '{t}'" for t in sorted(types) if t.isalnum())
        parts.append(f"({ors})")
    return " AND ".join(parts)


def search(q: str, topk: int, scope: list[str] | None, types: set[str] | None,
           tau: float | None = None):
    """Upstash 하이브리드 질의 → UI 호환 hits.

    랭킹: 하이브리드(내장 임베딩 + BM25, DBSF 융합).
    게이트: DBSF 점수는 무관/유관 분포가 겹쳐 부적합 → 별도 dense 전용 쿼리의
    코사인(0..1)으로 판정. 두 쿼리는 스레드로 병렬 실행."""
    import threading
    f = _filter_expr(scope, types)
    body = {"data": q, "topK": max(topk, 5), "includeMetadata": True,
            "fusionAlgorithm": "DBSF"}
    gate_body = {"data": q, "topK": 1, "queryMode": "DENSE"}
    if f:
        body["filter"] = f
        gate_body["filter"] = f
    out: dict = {}

    def run(key, b):
        try:
            out[key] = _post(f"{VEC_URL}/query-data", VEC_TOKEN, b).get("result", [])
        except Exception as e:
            out[key] = e

    ts = [threading.Thread(target=run, args=("main", body)),
          threading.Thread(target=run, args=("gate", gate_body))]
    for t in ts: t.start()
    for t in ts: t.join()
    if isinstance(out["main"], Exception):
        raise out["main"]
    res = out["main"]
    dense_top = 0.0
    if not isinstance(out["gate"], Exception) and out["gate"]:
        dense_top = float(out["gate"][0].get("score", 0.0))

    tau_eff = GATE_TAU if tau is None else float(tau)
    all_low = bool(res) and dense_top < tau_eff
    top = max((r.get("score", 0.0) for r in res), default=0.0) or 1.0
    hits = []
    for rank, r in enumerate(res[:topk], 1):
        m = r.get("metadata", {})
        raw = float(r.get("score", 0.0))
        conf = round(raw / top, 4)                     # 표시용 상대 정규화(top=1.0)
        hits.append({**m, "rank": rank,
                     "confidence": conf, "cos": round(raw, 4),
                     "dense": conf, "sparse": 0.0, "combined": conf,
                     "low_conf": all_low})
    gate = {"mode": "cosine", "tau": round(tau_eff, 4), "tau_default": round(GATE_TAU, 4),
            "best": round(dense_top, 4), "all_low": all_low}
    return hits, gate


def scope_hint(hits: list[dict]) -> dict:
    by: dict[str, dict] = {}
    for h in hits:
        s = h.get("sector") or "미분류"
        d = by.setdefault(s, {"sector": s, "count": 0, "best": 0.0})
        d["count"] += 1
        d["best"] = max(d["best"], h["confidence"])
    secs = sorted(by.values(), key=lambda x: -x["best"])
    return {"ambiguous": len(secs) >= 2 and (secs[0]["best"] - secs[1]["best"]) < 0.08,
            "sectors": secs}


def _daily_count() -> int | None:
    """일일 답변 카운터(Redis 미설정 시 None → 가드 생략)."""
    if not REDIS_URL:
        return None
    day = time.strftime("%Y%m%d")
    try:
        r = _post(f"{REDIS_URL}/pipeline", REDIS_TOKEN,
                  [["INCR", f"demo:ans:{day}"], ["EXPIRE", f"demo:ans:{day}", "90000"]],
                  timeout=5)
        return int(r[0]["result"])
    except Exception:
        return None


def extractive_answer(hits: list[dict]) -> str:
    lines = []
    for h in hits[:3]:
        lines.append(f"{h['text']} [S{h['rank']}]")
    return "\n\n".join(lines) if lines else "매뉴얼에서 확인되지 않습니다."


def answer(q: str, hits: list[dict]) -> dict:
    if not hits:
        return {"answer": "매뉴얼에서 확인되지 않습니다.", "used_llm": False, "backend": "none"}
    cnt = _daily_count()
    if cnt is not None and cnt > DAILY_LIMIT:
        return {"answer": extractive_answer(hits), "used_llm": False, "backend": "limit-extractive"}
    if not OPENAI_KEY:
        return {"answer": extractive_answer(hits), "used_llm": False, "backend": "extractive"}
    ctx = "\n".join(f"[S{h['rank']}] ({h['path_str']}) {h['text']}" for h in hits)
    try:
        r = _post("https://api.openai.com/v1/chat/completions", OPENAI_KEY, {
            "model": OPENAI_MODEL, "temperature": 0.2, "max_tokens": 600,
            "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                         {"role": "user", "content": f"[근거]\n{ctx}\n\n[질문]\n{q}"}],
        }, timeout=30)
        text = r["choices"][0]["message"]["content"].strip()
        return {"answer": text, "used_llm": True, "backend": f"openai:{OPENAI_MODEL}"}
    except Exception:
        return {"answer": extractive_answer(hits), "used_llm": False, "backend": "extractive"}


def parse_qs(path: str) -> dict:
    qs = urllib.parse.parse_qs(urllib.parse.urlparse(path).query)
    return {k: v[0] for k, v in qs.items()}


def common_params(p: dict):
    q = (p.get("q") or "").strip()
    topk = min(30, max(1, int(p.get("topk") or 5)))
    tau = p.get("tau")
    tau = float(tau) if tau not in (None, "") else None
    scope = [s.strip() for s in (p.get("scope") or "").split(">") if s.strip()] or None
    types = set(t for t in (p.get("types") or "").split(",") if t) or None
    return q, topk, tau, scope, types


def send_json(handler, obj: dict, code: int = 200):
    body = json.dumps(obj, ensure_ascii=False).encode()
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)
