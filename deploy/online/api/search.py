"""GET /api/search — 하이브리드 검색 + scope_hint (온라인 데모)."""
import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent))  # Vercel: 형제 모듈 임포트 경로

import time
from http.server import BaseHTTPRequestHandler

from _common import authorized, search, scope_hint, parse_qs, common_params, send_json


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if not authorized(self):
            return send_json(self, {"error": "unauthorized"}, 401)
        p = parse_qs(self.path)
        q, topk, tau, scope, types = common_params(p)
        if not q:
            return send_json(self, {"error": "empty query"}, 400)
        t0 = time.perf_counter()
        try:
            hits, gate = search(q, topk, scope, types, tau)
        except Exception as e:
            return send_json(self, {"error": f"vector store: {e}"}, 502)
        ms = round((time.perf_counter() - t0) * 1000, 1)
        send_json(self, {"query": q, "alpha": 0.5, "topk": topk,
                         "types": sorted(types) if types else [],
                         "scope": scope or [], "scope_hint": scope_hint(hits),
                         "elapsed_ms": ms, "count": len(hits),
                         "gate": gate, "hits": hits})

    def log_message(self, *a):
        pass
