"""GET /api/suggest — 검증된 질문뱅크에서 스코프 연동 추천 질문(정적 조회, 벡터 호출 없음).

파라미터:
  scope  ">" 조인 경로 접두 (예: "화면>계좌", "업무"). 질문 경로 = sp + [sid].
  n      개수 (기본 8, 최대 16)
  seed   회전 시드(정수, 기본 0) — 같은 seed는 같은 결과(캐시 친화 결정적).
"""
import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent))  # Vercel: 형제 모듈 임포트 경로

from http.server import BaseHTTPRequestHandler

from _common import QUESTIONS, authorized, parse_qs, send_json


def _scope_match(entry: dict, scope: list[str]) -> bool:
    """scope 세그먼트 전부가 질문 경로(sp + [sid])의 접두와 일치해야 함."""
    path = list(entry.get("sp") or []) + [entry.get("sid", "")]
    if len(scope) > len(path):
        return False
    return all(path[i] == s for i, s in enumerate(scope))


def _group_key(entry: dict) -> str:
    sp = entry.get("sp") or []
    return sp[1] if len(sp) >= 2 else (sp[0] if sp else "")


def pick(scope: list[str] | None, n: int, seed: int) -> tuple[list[dict], int]:
    """접두 필터 → 부문 그룹핑 → seed 회전 라운드로빈으로 n개 선발(결정적)."""
    pool = [e for e in QUESTIONS if not scope or _scope_match(e, scope)]
    groups: dict[str, list] = {}
    for e in pool:
        groups.setdefault(_group_key(e), []).append(e)
    keys = sorted(groups)
    if not keys:
        return [], 0
    keys = keys[seed % len(keys):] + keys[:seed % len(keys)]  # 그룹 순서 회전
    idx = {k: seed % len(groups[k]) for k in keys}            # 그룹 내 시작점 회전
    taken = {k: 0 for k in keys}
    out: list[dict] = []
    while len(out) < n:
        progressed = False
        for k in keys:
            if len(out) >= n:
                break
            g = groups[k]
            if taken[k] >= len(g):
                continue
            e = g[(idx[k] + taken[k]) % len(g)]
            taken[k] += 1
            out.append({"q": e["q"], "sid": e.get("sid", ""), "t": e.get("t", "")})
            progressed = True
        if not progressed:
            break
    return out, len(pool)


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if not authorized(self):
            return send_json(self, {"error": "unauthorized"}, 401)
        p = parse_qs(self.path)
        scope = [s.strip() for s in (p.get("scope") or "").split(">") if s.strip()] or None
        try:
            n = min(16, max(1, int(p.get("n") or 8)))
        except ValueError:
            n = 8
        try:
            seed = int(p.get("seed") or 0)
        except ValueError:
            seed = 0
        questions, total = pick(scope, n, seed)
        send_json(self, {"questions": questions, "total": total})

    def log_message(self, *a):
        pass
