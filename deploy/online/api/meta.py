"""GET /api/meta — 데모 인덱스 메타(정적, ingest 시 생성)."""
import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent))  # Vercel: 형제 모듈 임포트 경로

from http.server import BaseHTTPRequestHandler

from _common import authorized, public_meta, send_json


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if not authorized(self):
            return send_json(self, {"error": "unauthorized"}, 401)
        send_json(self, public_meta())

    def log_message(self, *a):
        pass
