"""
원장 검색 콘솔 — 로컬 검색품질 QA 웹서버 (표준 라이브러리 http.server, 무추가의존).

벡터DB 임포트 전에 하이브리드 검색(FAISS dense + BM25 sparse)의 품질을
사람이 직접 눈으로 검증하기 위한 계측 콘솔. 전부 로컬/오프라인.

  python src/webapp.py            # http://localhost:8000
  PORT=9000 python src/webapp.py

API:
  GET /               → web/index.html
  GET /styles.css 등  → web/ 하위 정적 자산(화이트리스트 확장자만)
  GET /api/meta       → 인덱스 메타(모델/차원/건수) + 추천 질문 samples + sectors 통계
  GET /api/sectors    → 브레드크럼 스코프 셀렉터용 TOC 트리(부문→중분류→화면, 청크 수)
  GET /api/search?q=&alpha=&topk=&types=&scope=계좌>고객관리
        → {query, ..., scope, scope_hint:{ambiguous,sectors}, hits:[...]}
    scope: 브레드크럼 경로 접두(">" 구분) — 부문/중분류/화면 단위로 검색 범위 제한
"""
from __future__ import annotations
import os
import json
import time
import shutil
import pickle
import pathlib
import subprocess
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np
import faiss

from rag_common import (embed, tokenize_ko, INDEX_DIR,
                        rerank_scores, get_reranker, load_gate, RERANK_MODEL)

ROOT = pathlib.Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8000"))

# 답변 LLM 백엔드: claude(로컬 Claude Code CLI) | ollama | none(추출-합성)
# 자동 선택: claude CLI가 있으면 claude, 아니면 ollama, 둘 다 없으면 추출-합성.
LLM_BACKEND = os.environ.get("LLM_BACKEND", "auto")
LLM_MODEL = os.environ.get("LLM_MODEL", "qwen2.5:7b-instruct")
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
CLAUDE_BIN = os.environ.get("CLAUDE_BIN", "claude")
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "sonnet")  # 빠른 응답용

SYSTEM_PROMPT = (
    "당신은 코스콤 원장시스템(PowerBASE) 온라인 매뉴얼 도우미다. "
    "아래 [근거]에 있는 내용만 사용해 한국어로 간결하고 정확하게 답한다. "
    "근거에 없으면 '매뉴얼에서 확인되지 않습니다.'라고 답하고 추측하지 않는다. "
    "핵심을 먼저 말하고, 사용한 근거마다 문장 끝에 [S1],[S2] 형태의 출처 마커를 붙인다."
)

# ── 인덱스 1회 로딩 ──
print("[webapp] loading index & embedder ...", flush=True)
_index = faiss.read_index(str(INDEX_DIR / "dense.faiss"))
with open(INDEX_DIR / "bm25.pkl", "rb") as f:
    _bm25 = pickle.load(f)
with open(INDEX_DIR / "chunks.json", encoding="utf-8") as f:
    _chunks = json.load(f)
with open(INDEX_DIR / "meta.json", encoding="utf-8") as f:
    _meta = json.load(f)
# 임베더 워밍업
embed(["워밍업"])
# 관련도 게이트 설정 + 리랭커 워밍(없으면 코사인 폴백)
_gate = load_gate(_meta)
_RERANK_ON = get_reranker() is not None


def _sample_questions(chunks: list[dict], limit: int = 8) -> list[str]:
    """첫 화면 추천 질문 — qa 청크의 실제 질문(section_path 말단)에서 추출.
    화면당 1개씩, 짧고 물음표로 끝나는 것만. 결정적 순서(청크 순서).
    업무매뉴얼 청크가 있으면 끝 2슬롯은 업무 문서 제목 기반 질문으로 채운다."""
    out, seen = [], set()
    for c in chunks:
        if c.get("chunk_type") != "qa" or c["screen_id"] in seen:
            continue
        q = (c.get("section_path") or [""])[-1].strip()
        if q.endswith("?") and 10 <= len(q) <= 55:
            out.append(q)
            seen.add(c["screen_id"])
        if len(out) >= limit:
            break
    pm, pm_seen = [], set()
    for c in chunks:
        if len(pm) >= 2:
            break
        if c.get("manual") != "업무":
            continue
        t = (c.get("title") or "").strip()
        if t and t not in pm_seen and 4 <= len(t) <= 30:
            pm.append(t + ("를 알려주세요" if t.endswith("절차")
                           else " 절차를 알려주세요"))
            pm_seen.add(t)
    return (out[:limit - len(pm)] + pm) if pm else out


_samples = _sample_questions(_chunks)


def _build_sector_tree(chunks: list[dict]) -> list[dict]:
    """스코프 셀렉터용 TOC 트리 — sector_path 체인 + 말단 화면 목록(청크 수 포함)."""
    root: dict[str, dict] = {}
    for c in chunks:
        segs = list(c.get("sector_path") or []) or ["미분류"]
        children = root
        node = None
        for s in segs:
            node = children.setdefault(s, {"name": s, "count": 0,
                                           "children": {}, "screens": {}})
            node["count"] += 1
            children = node["children"]
        scr = node["screens"].setdefault(
            c["screen_id"], {"id": c["screen_id"], "title": c["title"], "count": 0})
        scr["count"] += 1

    def ser(d: dict) -> list[dict]:
        out = []
        for n in d.values():
            out.append({"name": n["name"], "count": n["count"],
                        "children": ser(n["children"]),
                        "screens": sorted(n["screens"].values(), key=lambda x: x["id"])})
        return out
    return ser(root)


_sector_tree = _build_sector_tree(_chunks)
_sector_counts = {t["name"]: t["count"] for t in _sector_tree}

# 정적 자산 서빙 화이트리스트 (web/ 하위, 경로 탈출 방지)
_STATIC_TYPES = {
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".woff2": "font/woff2",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
}
print(f"[webapp] ready: {len(_chunks)} chunks, model={_meta.get('embed_model')}, "
      f"rerank={'on' if _RERANK_ON else 'off'}", flush=True)


def _minmax(x: np.ndarray) -> np.ndarray:
    lo, hi = float(x.min()), float(x.max())
    if hi - lo < 1e-9:
        return np.zeros_like(x)
    return (x - lo) / (hi - lo)


def _scope_match(chunk: dict, scope: list[str]) -> bool:
    """브레드크럼 스코프 매칭 — TOC 경로+화면ID에 대한 세그먼트 단위 접두 비교."""
    full = list(chunk.get("sector_path") or []) + [chunk["screen_id"]]
    return len(scope) <= len(full) and all(a == b for a, b in zip(scope, full))


def _scope_hint(hits: list[dict]) -> dict:
    """근거 분포 — 교차 오염 감지 2단계: ① 매뉴얼(화면/업무) ② 부문.
    각 항목에 scope(재검색용 경로)를 실어 UI가 원클릭 재스코프하게 한다."""
    secs: dict[str, dict] = {}
    mans: dict[str, dict] = {}
    for h in hits:
        sp = h.get("sector_path") or []
        man = h.get("manual") or (sp[0] if sp else "")
        s = h.get("sector") or "미분류"
        d = secs.setdefault(s, {"sector": s, "count": 0, "best": 0.0,
                                "scope": sp[:2] if len(sp) >= 2 else [s]})
        d["count"] += 1
        d["best"] = max(d["best"], h["confidence"])
        if man:
            m = mans.setdefault(man, {"manual": man, "count": 0, "best": 0.0,
                                      "scope": [man]})
            m["count"] += 1
            m["best"] = max(m["best"], h["confidence"])
    sec_l = sorted(secs.values(), key=lambda x: -x["best"])
    man_l = sorted(mans.values(), key=lambda x: -x["best"])
    return {"ambiguous": len(sec_l) >= 2 and (sec_l[0]["best"] - sec_l[1]["best"]) < 0.08,
            "sectors": sec_l,
            "ambiguous_manual": len(man_l) >= 2 and (man_l[0]["best"] - man_l[1]["best"]) < 0.10,
            "manuals": man_l}


def search(query: str, alpha: float, topk: int, types: set[str] | None,
           tau: float | None = None, use_rerank: bool = True,
           scope: list[str] | None = None):
    """하이브리드 검색 + 관련도 게이트.
    1) 하이브리드(정규화 combined)로 후보 정렬 → 코사인 원점수(cos_floor)로 coarse 컷
    2) 통과 후보를 리랭커로 정밀 재순위(있으면), 최종 신뢰도(confidence) 산출
    3) confidence < τ 는 low_conf 로 '표시'(소프트 모드) — 결과는 보여주되 저신뢰 플래그
    반환: (hits, gate). gate = {mode, tau, best, all_low}"""
    n = len(_chunks)
    qv = embed([query])
    dscore, didx = _index.search(qv, n)
    dense_raw = np.zeros(n, dtype="float32")
    dense_raw[didx[0]] = dscore[0]                      # 코사인 원점수 (절대 관련도)
    sparse = np.array(_bm25.get_scores(tokenize_ko(query)), dtype="float32")
    dn, sn = _minmax(dense_raw), _minmax(sparse)
    combined = alpha * dn + (1 - alpha) * sn

    # 1) 후보 풀: 하이브리드 상위 + 코사인 coarse 컷 (유형 필터 적용)
    pool_size = max(topk, int(_gate["rerank_pool"]))
    floor = float(_gate["cos_floor"])
    pool = []
    for i in np.argsort(-combined):
        c = _chunks[i]
        if scope and not _scope_match(c, scope):
            continue
        if types and c["chunk_type"] not in types:
            continue
        if float(dense_raw[i]) < floor and len(pool) >= topk:
            continue  # coarse 컷: 최소 topk 는 채우되 그 이하는 바닥 미만 제외
        pool.append(int(i))
        if len(pool) >= pool_size:
            break

    # 2) 리랭크 → 최종 신뢰도 (use_rerank=False 면 코사인 게이트로 강등 — 웹 '정밀' 토글)
    rr = rerank_scores(query, [_chunks[i]["text"] for i in pool]) if (pool and use_rerank) else None
    mode = "rerank" if rr is not None else "cosine"
    tau_default = float(_gate["tau_rerank"] if mode == "rerank" else _gate["tau_cos"])
    tau_eff = tau_default if tau is None else float(tau)

    rows = []
    for j, i in enumerate(pool):
        cos = float(dense_raw[i])
        conf = float(rr[j]) if rr is not None else cos
        rows.append((i, conf, cos))
    if mode == "rerank":
        rows.sort(key=lambda x: -x[1])                 # 리랭커 점수로 최종 재순위
    rows = rows[:topk]

    hits = []
    for r, (i, conf, cos) in enumerate(rows, 1):
        c = _chunks[i]
        hits.append({
            **c,
            "combined": round(float(combined[i]), 4),
            "dense": round(float(dn[i]), 4),
            "sparse": round(float(sn[i]), 4),
            "cos": round(cos, 4),                      # 코사인 원점수
            "confidence": round(conf, 4),              # 게이트 판단 신뢰도
            "low_conf": bool(conf < tau_eff),
            "rank": r,
        })
    best = max((h["confidence"] for h in hits), default=0.0)
    gate = {"mode": mode, "tau": round(tau_eff, 4), "tau_default": round(tau_default, 4),
            "best": round(best, 4),
            "all_low": bool(hits and all(h["low_conf"] for h in hits))}
    return hits, gate


# ─────────────────────────── 답변 생성 (로컬) ───────────────────────────

def _ollama_up() -> bool:
    try:
        import urllib.request
        urllib.request.urlopen(f"{OLLAMA_HOST}/api/tags", timeout=1.5).read()
        return True
    except Exception:
        return False


def _claude_up() -> bool:
    return shutil.which(CLAUDE_BIN) is not None


def call_claude(prompt: str) -> str | None:
    """로컬 Claude Code CLI 를 헤드리스(-p)로 호출해 답변 생성."""
    try:
        cmd = [CLAUDE_BIN, "-p"]
        if CLAUDE_MODEL:
            cmd += ["--model", CLAUDE_MODEL]
        r = subprocess.run(cmd, input=prompt, capture_output=True,
                           text=True, timeout=120, cwd=str(ROOT))
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except Exception:
        return None
    return None


def call_ollama(prompt: str) -> str | None:
    try:
        import urllib.request
        req = urllib.request.Request(
            f"{OLLAMA_HOST}/api/generate",
            data=json.dumps({"model": LLM_MODEL, "prompt": prompt, "stream": False}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read()).get("response", "").strip()
    except Exception:
        return None


def build_prompt(query: str, hits: list[dict]) -> str:
    ctx = "\n\n".join(
        f"[S{h['rank']}] ({h['title']}[{h['screen_no']}] · {h['path_str']})\n{h['text']}"
        for h in hits
    )
    return f"{SYSTEM_PROMPT}\n\n[근거]\n{ctx}\n\n[질문] {query}\n\n[답변]"


_QUERY_STOP = {"무엇", "무엇인가", "무엇인가요", "어디서", "어디", "어떻게", "방법",
               "인가요", "하나요", "확인", "항목", "관련", "대해", "대한", "은", "는", "이", "가"}


def extractive_answer(query: str, hits: list[dict]) -> str:
    """LLM 없이 상위 근거로 최적화 답변 합성 (오프라인).
    - Q&A 근거가 상위(≤3)면 그 답을 우선 사용(가장 직접적)
    - 아니면 최상위 근거 텍스트를 핵심 답으로, 다른 화면의 근거를 보조로 첨부."""
    if not hits:
        return "매뉴얼에서 확인되지 않습니다."
    primary = hits[0]
    for h in hits[:3]:
        if h["chunk_type"] == "qa":
            primary = h
            break
    core = primary["text"].strip()
    parts = [f"{core} [S{primary['rank']}]"]
    # 다른 화면의 보조 근거 1건
    for h in hits:
        if h["screen_id"] != primary["screen_id"] and h["chunk_type"] != "related":
            snippet = h["text"].strip()
            if len(snippet) > 140:
                snippet = snippet[:140].rstrip() + "…"
            parts.append(f"관련 근거 — {snippet} [S{h['rank']}]")
            break
    return "\n\n".join(parts)


def _resolve_backend() -> str:
    if LLM_BACKEND != "auto":
        return LLM_BACKEND
    if _claude_up():
        return "claude"
    if _ollama_up():
        return "ollama"
    return "none"


def answer(query: str, hits: list[dict]) -> dict:
    if not hits:
        return {"answer": "매뉴얼에서 확인되지 않습니다.", "used_llm": False, "backend": "none"}
    be = _resolve_backend()
    text, used_llm, backend = None, False, "extractive"
    prompt = build_prompt(query, hits)
    if be == "claude" and _claude_up():
        text = call_claude(prompt)
        if text:
            used_llm, backend = True, f"claude-cli:{CLAUDE_MODEL}"
    elif be == "ollama" and _ollama_up():
        text = call_ollama(prompt)
        if text:
            used_llm, backend = True, f"ollama:{LLM_MODEL}"
    if not text:
        text = extractive_answer(query, hits)
    return {"answer": text, "used_llm": used_llm, "backend": backend}


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body: bytes, ctype="application/json; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def log_message(self, *a):  # 조용히
        pass

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path in ("/", "/index.html"):
            html = (WEB / "index.html").read_bytes()
            return self._send(200, html, "text/html; charset=utf-8")
        ext = pathlib.PurePosixPath(path).suffix.lower()
        if ext in _STATIC_TYPES:
            try:
                f = (WEB / path.lstrip("/")).resolve()
                f.relative_to(WEB.resolve())          # 경로 탈출 방지
                body = f.read_bytes()
            except (ValueError, OSError):
                return self._send(404, b"not found", "text/plain; charset=utf-8")
            self.send_response(200)
            self.send_header("Content-Type", _STATIC_TYPES[ext])
            self.send_header("Content-Length", str(len(body)))
            # css/js는 배포 즉시 반영되도록 no-cache, 폰트·이미지만 캐시 허용
            cache = "no-cache" if ext in (".css", ".js") else "public, max-age=86400"
            self.send_header("Cache-Control", cache)
            self.end_headers()
            return self.wfile.write(body)
        if path == "/api/sectors":
            return self._json({"tree": _sector_tree})
        if path == "/api/meta":
            return self._json({**_meta, "count": len(_chunks),
                               "samples": _samples,
                               "sectors": _sector_counts,
                               "reranker": RERANK_MODEL if _RERANK_ON else None,
                               "gate": {"mode": "rerank" if _RERANK_ON else "cosine",
                                        "tau": _gate["tau_rerank"] if _RERANK_ON else _gate["tau_cos"],
                                        "tau_rerank": _gate["tau_rerank"],
                                        "tau_cos": _gate["tau_cos"]}})
        if path == "/api/search":
            qs = urllib.parse.parse_qs(parsed.query)
            q = (qs.get("q", [""])[0]).strip()
            if not q:
                return self._json({"error": "empty query"}, 400)
            alpha = float(qs.get("alpha", ["0.5"])[0])
            topk = int(qs.get("topk", ["5"])[0])
            tau = qs.get("tau", [None])[0]
            tau = float(tau) if tau not in (None, "") else None
            t = qs.get("types", [""])[0]
            types = set(x for x in t.split(",") if x) or None
            use_rr = qs.get("rerank", ["1"])[0] not in ("0", "false", "off")
            scope = [s.strip() for s in qs.get("scope", [""])[0].split(">") if s.strip()] or None
            t0 = time.perf_counter()
            hits, gate = search(q, alpha, topk, types, tau, use_rr, scope)
            ms = round((time.perf_counter() - t0) * 1000, 1)
            return self._json({"query": q, "alpha": alpha, "topk": topk,
                               "types": sorted(types) if types else [],
                               "scope": scope or [], "scope_hint": _scope_hint(hits),
                               "elapsed_ms": ms, "count": len(hits),
                               "gate": gate, "hits": hits})
        if path == "/api/answer":
            qs = urllib.parse.parse_qs(parsed.query)
            q = (qs.get("q", [""])[0]).strip()
            if not q:
                return self._json({"error": "empty query"}, 400)
            alpha = float(qs.get("alpha", ["0.5"])[0])
            topk = int(qs.get("topk", ["5"])[0])
            tau = qs.get("tau", [None])[0]
            tau = float(tau) if tau not in (None, "") else None
            t = qs.get("types", [""])[0]
            types = set(x for x in t.split(",") if x) or None
            use_rr = qs.get("rerank", ["1"])[0] not in ("0", "false", "off")
            scope = [s.strip() for s in qs.get("scope", [""])[0].split(">") if s.strip()] or None
            t0 = time.perf_counter()
            hits, gate = search(q, alpha, topk, types, tau, use_rr, scope)
            search_ms = round((time.perf_counter() - t0) * 1000, 1)
            t1 = time.perf_counter()
            # 게이트: 전부 저신뢰면 LLM 호출 없이 '확인되지 않음' (할루시네이션 차단)
            if gate["all_low"]:
                ans = {"answer": "매뉴얼에서 확인되지 않습니다. (관련도가 임계치 미만 — 아래 근거는 참고용)",
                       "used_llm": False, "backend": "gated"}
            else:
                ans = answer(q, [h for h in hits if not h["low_conf"]] or hits)
            gen_ms = round((time.perf_counter() - t1) * 1000, 1)
            return self._json({"query": q, "alpha": alpha, "topk": topk,
                               "types": sorted(types) if types else [],
                               "scope": scope or [], "scope_hint": _scope_hint(hits),
                               "search_ms": search_ms, "gen_ms": gen_ms,
                               "count": len(hits), "gate": gate, "hits": hits, **ans})
        return self._send(404, b"not found", "text/plain; charset=utf-8")


def main():
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"[webapp] 원장 검색 콘솔 → http://{HOST}:{PORT}", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        srv.shutdown()


if __name__ == "__main__":
    main()
