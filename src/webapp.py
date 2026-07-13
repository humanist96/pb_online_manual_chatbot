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
import pickle
import pathlib
import datetime
import threading
import ipaddress
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np
import faiss

from rag_common import (embed, tokenize_ko, INDEX_DIR,
                        rerank_scores, get_reranker, load_gate, RERANK_MODEL)
from request_validation import MAX_REQUEST_TARGET_CHARS, parse_query_params

ROOT = pathlib.Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
QUESTIONS_PATH = ROOT / "data" / "questions.json"     # gen_questions.py --out 산출(질문뱅크)
CHIP_LOG_PATH = ROOT / "data" / "chip_log.jsonl"      # 추천 말풍선(src=chip) 클릭 계측
HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8000"))
NON_LOOPBACK_BIND_ENV = "PB_ALLOW_NON_LOOPBACK_BIND"
NON_LOOPBACK_BIND_CONFIRMATION = "I_ACKNOWLEDGE_REVERSE_PROXY_AUTH"


def _is_loopback_host(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


if (not _is_loopback_host(HOST)
        and os.environ.get(NON_LOOPBACK_BIND_ENV) != NON_LOOPBACK_BIND_CONFIRMATION):
    raise SystemExit(
        f"non-loopback HOST={HOST!r} requires an authenticated reverse proxy and "
        f"{NON_LOOPBACK_BIND_ENV}={NON_LOOPBACK_BIND_CONFIRMATION}")

try:
    MAX_CONCURRENT_QUERIES = int(os.environ.get("PB_MAX_CONCURRENT_QUERIES", "2"))
except ValueError:
    raise SystemExit("PB_MAX_CONCURRENT_QUERIES must be an integer") from None
if not 1 <= MAX_CONCURRENT_QUERIES <= 16:
    raise SystemExit("PB_MAX_CONCURRENT_QUERIES must be between 1 and 16")
_query_slots = threading.BoundedSemaphore(MAX_CONCURRENT_QUERIES)

# 답변 LLM 백엔드: none(기본, 추출-합성) | ollama(명시적 opt-in).
LLM_BACKENDS = ("none", "ollama")
LLM_BACKEND = os.environ.get("LLM_BACKEND", "none").strip().lower()
if LLM_BACKEND not in LLM_BACKENDS:
    raise SystemExit(f"LLM_BACKEND must be one of: {', '.join(LLM_BACKENDS)}")
LLM_MODEL = os.environ.get("LLM_MODEL", "qwen2.5:7b-instruct")
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")

SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; base-uri 'none'; object-src 'none'; "
        "frame-ancestors 'none'; form-action 'self'; script-src 'self'; "
        "style-src 'self' 'unsafe-inline'; font-src 'self'; "
        "img-src 'self' data:; connect-src 'self'"
    ),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
}

SYSTEM_PROMPT = (
    "당신은 코스콤 원장시스템(PowerBASE) 온라인 매뉴얼 도우미다. "
    "아래 [근거]에 있는 내용만 사용해 한국어로 간결하고 정확하게 답한다. "
    "근거에 없으면 '매뉴얼에서 확인되지 않습니다.'라고 답하고 추측하지 않는다. "
    "핵심을 먼저 말하고, 사용한 근거마다 문장 끝에 [S1],[S2] 형태의 출처 마커를 붙인다. "
    "화면번호를 물으면 근거 머리의 '화면번호 NNNN' 표기로만 답한다 — "
    "FA002600·AC110100 같은 영문+숫자 조합은 내부 문서코드이므로 화면번호로 제시하지 않는다."
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


# ─────────────────── 질문뱅크(추천/관련 질문) — 온라인 데모 이식 ───────────────────
# gen_questions.py --out data/questions.json 산출물. 각 엔트리 {q,sid,t,sp,m}.
# 자기-검색 검증을 통과한 질문만 담기므로 추천 시 게이트 적중률이 구조적으로 높다.
# 없으면 빈 리스트로 안전 동작(기존 _sample_questions 폴백 유지).
def _load_question_bank(path: pathlib.Path) -> list[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
    except FileNotFoundError:
        print(f"[webapp] 질문뱅크 없음({path.name}) — 추천은 기본 샘플로 폴백", flush=True)
    except Exception as e:
        print(f"[webapp] 질문뱅크 로드 실패: {e} — 기본 샘플로 폴백", flush=True)
    return []


QUESTIONS = _load_question_bank(QUESTIONS_PATH)


def _q_sector(e: dict) -> str:
    """엔트리의 부문(그룹) 키 — sector_path[1](매뉴얼 다음) 또는 루트."""
    sp = e.get("sp") or []
    return sp[1] if len(sp) >= 2 else (sp[0] if sp else "")


# 사전 인덱스(모듈 로드 1회) — 요청당 O(1) 근처 조회
_BANK_BY_SID: dict[str, list] = {}
_BANK_BY_SECTOR: dict[str, list] = {}
for _e in QUESTIONS:
    _BANK_BY_SID.setdefault(_e.get("sid", ""), []).append(_e)
    _BANK_BY_SECTOR.setdefault(_q_sector(_e), []).append(_e)


def _norm_q(s: str) -> str:
    return "".join((s or "").split())


def _bank_scope_match(entry: dict, scope: list[str]) -> bool:
    """scope 세그먼트 전부가 질문 경로(sp + [sid])의 접두와 일치해야 함."""
    path = list(entry.get("sp") or []) + [entry.get("sid", "")]
    if len(scope) > len(path):
        return False
    return all(path[i] == s for i, s in enumerate(scope))


def suggest_pick(scope: list[str] | None, n: int, seed: int) -> tuple[list[dict], int]:
    """접두 필터 → 부문 그룹핑 → seed 회전 라운드로빈으로 n개 선발(결정적).
    같은 (scope, n, seed)는 항상 같은 결과 — 캐시 친화. 반환: (선발, 풀 크기)."""
    pool = [e for e in QUESTIONS if not scope or _bank_scope_match(e, scope)]
    groups: dict[str, list] = {}
    for e in pool:
        groups.setdefault(_q_sector(e), []).append(e)
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


def related_questions(q: str, hits: list[dict]) -> list[dict]:
    """이번 답변의 근거(hit)에서 이어질 질문을 뱅크에서 최대 3개.
    ① hit 화면과 동일 screen_id → ② 동일 부문 → ③ 동일 매뉴얼 순.
    현재 질문과 동일/포함 관계 및 상호 중복은 제외(막다른 골목 방지로 게이트 턴도 제공)."""
    if not QUESTIONS or not hits:
        return []
    cur = _norm_q(q)
    sids = [h.get("screen_id") for h in hits if h.get("screen_id")]
    top = hits[0]
    sp = top.get("sector_path") or []
    sector = top.get("sector") or (sp[1] if len(sp) >= 2 else "")
    manual = top.get("manual") or (sp[0] if sp else "")

    out: list[dict] = []
    seen_q: set[str] = set()

    def add(entries: list) -> bool:
        for e in entries:
            eq = _norm_q(e.get("q", ""))
            if not eq or eq in seen_q:
                continue
            if eq == cur or eq in cur or cur in eq:   # 현재 질문과 동일/포함 관계 제외
                continue
            seen_q.add(eq)
            out.append({"q": e["q"], "sid": e.get("sid", ""), "t": e.get("t", "")})
            if len(out) >= 3:
                return True
        return False

    for sid in sids:                                  # ① 동일 화면(hit 순서 유지)
        if add(_BANK_BY_SID.get(sid, [])):
            return out
    if sector and add(_BANK_BY_SECTOR.get(sector, [])):  # ② 동일 부문
        return out
    if manual:                                        # ③ 동일 매뉴얼
        add([e for e in QUESTIONS if (e.get("sp") or [None])[0] == manual])
    return out


_chip_lock = threading.Lock()


def track_chip(q: str, gate_ok: bool) -> None:
    """추천 말풍선(src=chip) 클릭 계측 — data/chip_log.jsonl 1줄 append.
    Redis 없는 폐쇄망이므로 파일 로그로 대체. 적중률 = gate_ok 비율.
    실패는 조용히 무시(응답 지연·오류 없음)."""
    try:
        rec = {"ts": datetime.datetime.now().isoformat(timespec="seconds"),
               "q": q, "gate_ok": bool(gate_ok)}
        line = json.dumps(rec, ensure_ascii=False) + "\n"
        with _chip_lock:
            with open(CHIP_LOG_PATH, "a", encoding="utf-8") as f:
                f.write(line)
    except Exception:
        pass


# 첫 화면 추천: 질문뱅크가 있으면 seed 0 라운드로빈 8개(부문 다양성), 없으면 기존 샘플.
if QUESTIONS:
    _bank_samples, _ = suggest_pick(None, 8, 0)
    _samples = [e["q"] for e in _bank_samples] or _samples
print(f"[webapp] 질문뱅크 {len(QUESTIONS)}건 로드", flush=True)


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
            c["screen_id"], {"id": c["screen_id"], "title": c["title"],
                             "no": c.get("screen_no", ""), "count": 0})
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
        f"[S{h['rank']}] ({h['title']}"
        + (f" · 화면번호 {h['screen_no']}" if h.get("screen_no") else "")
        + f" · {h['path_str']})\n{h['text']}"
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


def answer(query: str, hits: list[dict]) -> dict:
    if not hits:
        return {"answer": "매뉴얼에서 확인되지 않습니다.", "used_llm": False, "backend": "none"}
    text, used_llm, backend = None, False, "extractive"
    if LLM_BACKEND == "ollama" and _ollama_up():
        text = call_ollama(build_prompt(query, hits))
        if text:
            used_llm, backend = True, f"ollama:{LLM_MODEL}"
    if not text:
        text = extractive_answer(query, hits)
    return {"answer": text, "used_llm": used_llm, "backend": backend}


class Handler(BaseHTTPRequestHandler):
    def end_headers(self):
        for name, value in SECURITY_HEADERS.items():
            self.send_header(name, value)
        super().end_headers()

    def _send(self, code, body: bytes, ctype="application/json; charset=utf-8",
              cache="no-store"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def log_message(self, *a):  # 조용히
        pass

    def do_GET(self):
        if len(self.path) > MAX_REQUEST_TARGET_CHARS:
            return self._json({"error": "request target too long"}, 414)
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
            # css/js는 배포 즉시 반영되도록 no-cache, 폰트·이미지만 캐시 허용
            cache = "no-cache" if ext in (".css", ".js") else "public, max-age=86400"
            return self._send(200, body, _STATIC_TYPES[ext], cache)
        if path == "/api/sectors":
            return self._json({"tree": _sector_tree})
        if path == "/api/suggest":
            # 스코프 연동 추천 질문(정적 조회, 검색 호출 없음) — 검증된 질문뱅크에서.
            qs = urllib.parse.parse_qs(parsed.query)
            scope = [s.strip() for s in qs.get("scope", [""])[0].split(">") if s.strip()] or None
            try:
                n = min(16, max(1, int(qs.get("n", ["8"])[0])))
            except ValueError:
                n = 8
            try:
                seed = int(qs.get("seed", ["0"])[0])
            except ValueError:
                seed = 0
            questions, total = suggest_pick(scope, n, seed)
            return self._json({"questions": questions, "total": total})
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
            try:
                p = parse_query_params(parsed.query)
            except ValueError as exc:
                return self._json({"error": str(exc)}, 400)
            if not _query_slots.acquire(blocking=False):
                return self._json({"error": "too many concurrent queries"}, 429)
            try:
                t0 = time.perf_counter()
                hits, gate = search(p.q, p.alpha, p.topk, p.types, p.tau,
                                    p.use_rerank, p.scope)
                ms = round((time.perf_counter() - t0) * 1000, 1)
                return self._json({"query": p.q, "alpha": p.alpha, "topk": p.topk,
                                   "types": sorted(p.types) if p.types else [],
                                   "scope": p.scope or [], "scope_hint": _scope_hint(hits),
                                   "elapsed_ms": ms, "count": len(hits),
                                   "gate": gate, "hits": hits})
            finally:
                _query_slots.release()
        if path == "/api/answer":
            try:
                p = parse_query_params(parsed.query)
            except ValueError as exc:
                return self._json({"error": str(exc)}, 400)
            if not _query_slots.acquire(blocking=False):
                return self._json({"error": "too many concurrent queries"}, 429)
            try:
                t0 = time.perf_counter()
                hits, gate = search(p.q, p.alpha, p.topk, p.types, p.tau,
                                    p.use_rerank, p.scope)
                search_ms = round((time.perf_counter() - t0) * 1000, 1)
                t1 = time.perf_counter()
                if gate["all_low"]:
                    ans = {"answer": "매뉴얼에서 확인되지 않습니다. "
                                     "(관련도가 임계치 미만 — 아래 근거는 참고용)",
                           "used_llm": False, "backend": "gated"}
                else:
                    ans = answer(p.q, [h for h in hits if not h["low_conf"]] or hits)
                gen_ms = round((time.perf_counter() - t1) * 1000, 1)
                related = related_questions(p.q, hits)
                if p.src == "chip":
                    track_chip(p.q, not gate["all_low"])
                return self._json({"query": p.q, "alpha": p.alpha, "topk": p.topk,
                                   "types": sorted(p.types) if p.types else [],
                                   "scope": p.scope or [], "scope_hint": _scope_hint(hits),
                                   "search_ms": search_ms, "gen_ms": gen_ms,
                                   "count": len(hits), "gate": gate, "hits": hits,
                                   "related": related, **ans})
            finally:
                _query_slots.release()
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
