"""GET /api/answer — 검색 + OpenAI 답변(게이트·일일 상한 가드 포함)."""
import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent))  # Vercel: 형제 모듈 임포트 경로

import time
from http.server import BaseHTTPRequestHandler

from _common import (authorized, search, scope_hint, answer, related_questions,
                     track_chip, parse_qs, common_params, send_json)


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if not authorized(self):
            return send_json(self, {"error": "unauthorized"}, 401)
        p = parse_qs(self.path)
        try:
            q, topk, tau, scope, types = common_params(p)
        except ValueError as exc:
            return send_json(self, {"error": str(exc)}, 400)
        t0 = time.perf_counter()
        try:
            hits, gate = search(q, topk, scope, types, tau,
                                rewrite=p.get("rewrite") != "0")
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
        if p.get("src") == "chip":  # 추천 말풍선 계측(실패 시 조용히 무시)
            try:
                track_chip(gate_ok=not gate["all_low"])
            except Exception:
                pass
        send_json(self, {"query": q, "alpha": 0.5, "topk": topk,
                         "types": sorted(types) if types else [],
                         "scope": scope or [], "scope_hint": scope_hint(hits),
                         "search_ms": search_ms, "gen_ms": gen_ms,
                         "count": len(hits), "gate": gate, "hits": hits,
                         "related": related_questions(q, hits), **ans})

    def log_message(self, *a):
        pass
