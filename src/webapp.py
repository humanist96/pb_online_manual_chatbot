"""
원장 검색 콘솔 — 로컬 검색품질 QA 웹서버 (표준 라이브러리 http.server, 무추가의존).

벡터DB 임포트 전에 하이브리드 검색(FAISS dense + BM25 sparse)의 품질을
사람이 직접 눈으로 검증하기 위한 계측 콘솔. 전부 로컬/오프라인.

  python src/webapp.py            # http://localhost:8000
  PORT=9000 python src/webapp.py

API:
  GET /               → web/index.html
  GET /api/meta       → 인덱스 메타(모델/차원/건수)
  GET /api/search?q=&alpha=&topk=&types=
        → {query, alpha, topk, elapsed_ms, hits:[{..., combined, dense, sparse, rank}]}
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

from rag_common import embed, tokenize_ko, INDEX_DIR

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
    "당신은 토스증권 원장시스템(PowerBASE) '계좌' 온라인 매뉴얼 도우미다. "
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
print(f"[webapp] ready: {len(_chunks)} chunks, model={_meta.get('embed_model')}", flush=True)


def _minmax(x: np.ndarray) -> np.ndarray:
    lo, hi = float(x.min()), float(x.max())
    if hi - lo < 1e-9:
        return np.zeros_like(x)
    return (x - lo) / (hi - lo)


def search(query: str, alpha: float, topk: int, types: set[str] | None):
    n = len(_chunks)
    qv = embed([query])
    dscore, didx = _index.search(qv, n)
    dense = np.zeros(n, dtype="float32")
    dense[didx[0]] = dscore[0]
    sparse = np.array(_bm25.get_scores(tokenize_ko(query)), dtype="float32")
    dn, sn = _minmax(dense), _minmax(sparse)
    combined = alpha * dn + (1 - alpha) * sn

    order = np.argsort(-combined)
    hits = []
    for i in order:
        c = _chunks[i]
        if types and c["chunk_type"] not in types:
            continue
        hits.append({
            **c,
            "combined": round(float(combined[i]), 4),
            "dense": round(float(dn[i]), 4),
            "sparse": round(float(sn[i]), 4),
        })
        if len(hits) >= topk:
            break
    for r, h in enumerate(hits, 1):
        h["rank"] = r
    return hits


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
        if path == "/api/meta":
            return self._json({**_meta, "count": len(_chunks)})
        if path == "/api/search":
            qs = urllib.parse.parse_qs(parsed.query)
            q = (qs.get("q", [""])[0]).strip()
            if not q:
                return self._json({"error": "empty query"}, 400)
            alpha = float(qs.get("alpha", ["0.5"])[0])
            topk = int(qs.get("topk", ["5"])[0])
            t = qs.get("types", [""])[0]
            types = set(x for x in t.split(",") if x) or None
            t0 = time.perf_counter()
            hits = search(q, alpha, topk, types)
            ms = round((time.perf_counter() - t0) * 1000, 1)
            return self._json({"query": q, "alpha": alpha, "topk": topk,
                               "types": sorted(types) if types else [],
                               "elapsed_ms": ms, "count": len(hits), "hits": hits})
        if path == "/api/answer":
            qs = urllib.parse.parse_qs(parsed.query)
            q = (qs.get("q", [""])[0]).strip()
            if not q:
                return self._json({"error": "empty query"}, 400)
            alpha = float(qs.get("alpha", ["0.5"])[0])
            topk = int(qs.get("topk", ["5"])[0])
            t = qs.get("types", [""])[0]
            types = set(x for x in t.split(",") if x) or None
            t0 = time.perf_counter()
            hits = search(q, alpha, topk, types)
            search_ms = round((time.perf_counter() - t0) * 1000, 1)
            t1 = time.perf_counter()
            ans = answer(q, hits)
            gen_ms = round((time.perf_counter() - t1) * 1000, 1)
            return self._json({"query": q, "alpha": alpha, "topk": topk,
                               "types": sorted(types) if types else [],
                               "search_ms": search_ms, "gen_ms": gen_ms,
                               "count": len(hits), "hits": hits, **ans})
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
