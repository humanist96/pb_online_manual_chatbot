"""GET /api/answer — 검색 + OpenAI 답변(게이트·일일 상한 가드 포함)."""
import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent))  # Vercel: 형제 모듈 임포트 경로

import time
from http.server import BaseHTTPRequestHandler

from _common import search, scope_hint, answer, parse_qs, common_params, send_json


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        p = parse_qs(self.path)
        q, topk, tau, scope, types = common_params(p)
        if not q:
            return send_json(self, {"error": "empty query"}, 400)
        t0 = time.perf_counter()
        try:
            hits, gate = search(q, topk, scope, types, tau)
        except Exception as e:
            return send_json(self, {"error": f"vector store: {e}"}, 502)
        search_ms = round((time.perf_counter() - t0) * 1000, 1)
        t1 = time.perf_counter()
        if gate["all_low"]:
            ans = {"answer": "매뉴얼에서 확인되지 않습니다. (관련도가 임계치 미만 — 아래 근거는 참고용)",
                   "used_llm": False, "backend": "gated"}
        else:
            ans = answer(q, [h for h in hits if not h["low_conf"]] or hits)
        gen_ms = round((time.perf_counter() - t1) * 1000, 1)
        send_json(self, {"query": q, "alpha": 0.5, "topk": topk,
                         "types": sorted(types) if types else [],
                         "scope": scope or [], "scope_hint": scope_hint(hits),
                         "search_ms": search_ms, "gen_ms": gen_ms,
                         "count": len(hits), "gate": gate, "hits": hits, **ans})

    def log_message(self, *a):
        pass
