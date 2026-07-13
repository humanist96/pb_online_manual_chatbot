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
import hashlib
import hmac
import json
import math
import re
import time
import urllib.parse
import urllib.request

import _static as _public_static  # ingest.py가 demo_data에서 생성

META = _public_static.META
SECTORS = _public_static.SECTORS
# 합성 공개 모드: 합성 정적 산출물에 포함된 질문만 사용.
# 실데이터 운영(_static에 QUESTIONS 없음): 검증 질문뱅크 _questions.py 폴백.
QUESTIONS = list(getattr(_public_static, "QUESTIONS", []))
if not QUESTIONS:
    try:
        from _questions import QUESTIONS as _bank_questions
        QUESTIONS = list(_bank_questions)
    except ImportError:
        QUESTIONS = []

PUBLIC_DATASET_ID = "powerbase-public-synthetic-v2"
PUBLIC_CLASSIFICATION = "PUBLIC_SYNTHETIC"
PUBLIC_SCHEMA_VERSION = 2
PUBLIC_CORPUS_SHA256 = "450c97fefdc004fc1620850e6c99a90c2204dbc7ffa2f9a40bd7a7a50fcdb469"
PUBLIC_SECTORS_SHA256 = "e5a5609d80b9d0a27ba0148ecf07cc9890dc20e5e3d9940a16e77f9eacaa7cef"
PUBLIC_QUESTIONS_SHA256 = "631e620a5bfb2469abed03981f36a9bca3e8666b35a3b58397b2473a6fb2c8d6"
PUBLIC_BUNDLE_SHA256 = "55b1d4aa2fb92603c15a3a47d9d5a745660a2f22b00309aff1ee295649e6d594"
PUBLIC_CHUNK_COUNT = 832
PUBLIC_SCREEN_COUNT = 64


class PublicDatasetBoundaryError(RuntimeError):
    """공개 합성 데이터셋 경계가 확인되지 않았을 때의 fail-closed 오류."""


def _collect_screen_ids(nodes: list[dict]) -> set[str]:
    out: set[str] = set()
    for node in nodes:
        out.update(str(s.get("id")) for s in (node.get("screens") or []) if s.get("id"))
        out.update(_collect_screen_ids(node.get("children") or []))
    return out


_PUBLIC_SCREEN_IDS = frozenset(_collect_screen_ids(SECTORS.get("tree") or []))


def _collect_scope_paths(nodes: list[dict], prefix: tuple[str, ...] = ()) -> set[tuple[str, ...]]:
    out: set[tuple[str, ...]] = set()
    for node in nodes:
        name = node.get("name")
        if not isinstance(name, str) or not name:
            continue
        path = prefix + (name,)
        out.add(path)
        out.update(_collect_scope_paths(node.get("children") or [], path))
        out.update(path + (str(screen["id"]),) for screen in (node.get("screens") or [])
                   if screen.get("id"))
    return out


_PUBLIC_SCOPE_PATHS = frozenset(_collect_scope_paths(SECTORS.get("tree") or []))
_EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
_PHONE_RE = re.compile(r"(?<!\d)(?:01[016789]|0\d{1,2})[- .]?\d{3,4}[- .]?\d{4}(?!\d)")
_LONG_NUMBER_RE = re.compile(r"(?<!\d)\d(?:[- ]?\d){7,18}(?!\d)")


def _artifact_sha256(value) -> str:
    body = (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":")) + "\n").encode("utf-8")
    return hashlib.sha256(body).hexdigest()


def _public_questions_ready() -> bool:
    return (len(QUESTIONS) == PUBLIC_SCREEN_COUNT
            and all(isinstance(e, dict)
                    and e.get("dataset_id") == PUBLIC_DATASET_ID
                    and e.get("classification") == PUBLIC_CLASSIFICATION
                    and e.get("schema_version") == PUBLIC_SCHEMA_VERSION
                    and e.get("corpus_sha256") == PUBLIC_CORPUS_SHA256
                    and e.get("m") == "화면"
                    and (e.get("sp") or [None])[0] == "화면"
                    and e.get("sid") in _PUBLIC_SCREEN_IDS
                    for e in QUESTIONS))


def public_dataset_ready() -> bool:
    """정적 산출물이 승인된 합성 데이터셋인지 매 요청 시 확인한다."""
    return (META.get("demo") is True
            and META.get("dataset_id") == PUBLIC_DATASET_ID
            and META.get("classification") == PUBLIC_CLASSIFICATION
            and META.get("schema_version") == PUBLIC_SCHEMA_VERSION
            and META.get("corpus_sha256") == PUBLIC_CORPUS_SHA256
            and META.get("sectors_sha256") == PUBLIC_SECTORS_SHA256
            and META.get("questions_sha256") == PUBLIC_QUESTIONS_SHA256
            and META.get("bundle_sha256") == PUBLIC_BUNDLE_SHA256
            and _artifact_sha256(SECTORS) == PUBLIC_SECTORS_SHA256
            and _artifact_sha256(QUESTIONS) == PUBLIC_QUESTIONS_SHA256
            and META.get("count") == PUBLIC_CHUNK_COUNT
            and META.get("manuals") == {"화면": PUBLIC_CHUNK_COUNT}
            and len(_PUBLIC_SCREEN_IDS) == PUBLIC_SCREEN_COUNT
            and _public_questions_ready())


def require_public_dataset() -> None:
    # 합성 공개 모드(PUBLIC_DEMO=true)에서만 강제 — 실데이터 운영(기본)은 통과.
    if not PUBLIC_DEMO:
        return
    if not public_dataset_ready():
        raise PublicDatasetBoundaryError(
            "public API is disabled: approved synthetic dataset identity is missing")


def public_meta() -> dict:
    """META의 추가·변조 필드를 버리고 검증된 값만 공개한다.
    실데이터 운영(기본)은 ingest가 생성한 META를 그대로 서빙."""
    if not PUBLIC_DEMO:
        return META
    require_public_dataset()
    roots = SECTORS.get("tree") or []
    manual = next((node for node in roots if node.get("name") == "화면"), None)
    sector_counts = {
        node.get("name"): node.get("count")
        for node in (manual or {}).get("children", [])
        if isinstance(node.get("name"), str) and isinstance(node.get("count"), int)
    }
    return {
        "embed_model": "upstash-hybrid/text-embedding-3-small",
        "dim": 1536,
        "count": PUBLIC_CHUNK_COUNT,
        "demo": True,
        "reranker": None,
        "dataset_id": PUBLIC_DATASET_ID,
        "classification": PUBLIC_CLASSIFICATION,
        "schema_version": PUBLIC_SCHEMA_VERSION,
        "corpus_sha256": PUBLIC_CORPUS_SHA256,
        "bundle_sha256": PUBLIC_BUNDLE_SHA256,
        "manuals": {"화면": PUBLIC_CHUNK_COUNT},
        "sectors": sector_counts,
        "samples": [entry["q"] for entry in QUESTIONS[:8]],
        "gate": {"mode": "cosine", "tau": GATE_TAU,
                 "tau_rerank": GATE_TAU, "tau_cos": GATE_TAU},
    }


def _validate_public_results(results, source: str) -> list[dict]:
    """Vector filter 오작동까지 가정해 반환 metadata를 다시 검증한다(합성 공개 모드 전용)."""
    if not isinstance(results, list):
        raise PublicDatasetBoundaryError(f"{source}: malformed vector response")
    if not PUBLIC_DEMO:
        return results
    for row in results:
        meta = row.get("metadata") if isinstance(row, dict) else None
        if (not isinstance(meta, dict)
                or meta.get("dataset_id") != PUBLIC_DATASET_ID
                or meta.get("classification") != PUBLIC_CLASSIFICATION
                or meta.get("schema_version") != PUBLIC_SCHEMA_VERSION
                or meta.get("corpus_sha256") != PUBLIC_CORPUS_SHA256
                or meta.get("source_url") != "#demo"
                or meta.get("manual") != "화면"
                or (meta.get("sector_path") or [None])[0] != "화면"
                or meta.get("screen_id") not in _PUBLIC_SCREEN_IDS):
            raise PublicDatasetBoundaryError(
                f"{source}: vector result crossed the public synthetic boundary")
    return results

VEC_URL = os.environ.get("UPSTASH_VECTOR_REST_URL", "").rstrip("/")
VEC_TOKEN = os.environ.get("UPSTASH_VECTOR_REST_TOKEN", "")
OPENAI_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
ACCESS_KEY = os.environ.get("DEMO_ACCESS_KEY", "")
PUBLIC_DEMO = os.environ.get("PUBLIC_DEMO", "").strip().lower() in {
    "1", "true", "yes", "on",
}
try:
    GATE_TAU = float(os.environ.get("GATE_TAU", "0.70"))
except ValueError:
    raise RuntimeError("GATE_TAU must be a finite number between 0 and 1") from None
if not math.isfinite(GATE_TAU) or not 0.0 <= GATE_TAU <= 1.0:
    raise RuntimeError("GATE_TAU must be a finite number between 0 and 1")
try:
    DAILY_LIMIT = int(os.environ.get("ANSWER_DAILY_LIMIT", "300"))
except ValueError:
    raise RuntimeError("ANSWER_DAILY_LIMIT must be an integer") from None
if not 1 <= DAILY_LIMIT <= 100_000:
    raise RuntimeError("ANSWER_DAILY_LIMIT must be between 1 and 100000")
REDIS_URL = os.environ.get("UPSTASH_REDIS_REST_URL", "").rstrip("/")
REDIS_TOKEN = os.environ.get("UPSTASH_REDIS_REST_TOKEN", "")

_PROMPT_BASE = (
    "당신은 증권 원장시스템(PowerBASE) 온라인 매뉴얼 도우미다{mode}. "
    "아래 [근거]에 있는 내용만 사용해 한국어로 간결하고 정확하게 답한다. "
    "근거에 없으면 '매뉴얼에서 확인되지 않습니다.'라고 답하고 추측하지 않는다. "
    "핵심을 먼저 말하고, 사용한 근거마다 문장 끝에 [S1],[S2] 형태의 출처 마커를 붙인다. "
    "화면번호를 물으면 근거 머리의 '화면번호 NNNN' 표기로만 답한다 — "
    "FA002600·AC110100 같은 영문+숫자 조합은 내부 문서코드이므로 화면번호로 제시하지 않는다. "
)
SYSTEM_PROMPT = (
    _PROMPT_BASE.format(mode="(공개 데모: 합성 데이터)")
    + "모든 근거는 공개 데모용 합성 데이터이며 실제 고객·회원사 사례를 포함하지 않는다."
) if PUBLIC_DEMO else (
    _PROMPT_BASE.format(mode="")
    + "상담사례 근거(경로가 '상담 > …'이고 본문이 Q./A. 형식)로 답할 때는 검증된 정답이므로 "
    "A.의 원문 문장을 가급적 그대로 옮겨 답한다 — 요약·의역·재구성으로 표현이나 조건을 바꾸지 말고, "
    "원문에 없는 내용을 덧붙이지 않는다. 질문에 가장 부합하는 사례 하나의 원문을 우선하고, "
    "원문 말미의 고객사·비고는 해당 회원사 한정 사례임을 알리는 맥락으로만 언급한다."
)


# ── 질문뱅크 사전 인덱스(모듈 로드 1회) — 요청당 O(1) 근처 조회 ──
def _entry_sector(e: dict) -> str:
    sp = e.get("sp") or []
    return sp[1] if len(sp) >= 2 else (sp[0] if sp else "")


_BANK_BY_SID: dict[str, list] = {}
_BANK_BY_SECTOR: dict[str, list] = {}
for _e in QUESTIONS:
    _BANK_BY_SID.setdefault(_e.get("sid", ""), []).append(_e)
    _BANK_BY_SECTOR.setdefault(_entry_sector(_e), []).append(_e)


def _norm_q(s: str) -> str:
    return "".join((s or "").split())


def related_questions(q: str, hits: list[dict]) -> list[dict]:
    """이번 답변의 근거(hit)에서 이어질 질문을 뱅크에서 최대 3개.
    ① hit 화면과 동일 screen_id → ② 동일 부문 → ③ 동일 매뉴얼 순.
    현재 질문과 동일/포함 관계 및 상호 중복은 제외."""
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
            # 현재 질문과 동일/포함 관계 제외
            if eq == cur or eq in cur or cur in eq:
                continue
            seen_q.add(eq)
            out.append({"q": e["q"], "sid": e.get("sid", ""), "t": e.get("t", "")})
            if len(out) >= 3:
                return True
        return False

    # ① 동일 화면(hit 순서 유지)
    for sid in sids:
        if add(_BANK_BY_SID.get(sid, [])):
            return out
    # ② 동일 부문
    if sector and add(_BANK_BY_SECTOR.get(sector, [])):
        return out
    # ③ 동일 매뉴얼
    if manual:
        add([e for e in QUESTIONS if (e.get("sp") or [None])[0] == manual])
    return out


def _post(url: str, token: str, body: dict | list, timeout: int = 20):
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _filter_expr(scope: list[str] | None, types: set[str] | None) -> str:
    # 합성 공개 모드에서만 공개 namespace를 강제 — 실데이터 운영은 scope/types만.
    parts = ([f"dataset_id = '{PUBLIC_DATASET_ID}'",
              f"classification = '{PUBLIC_CLASSIFICATION}'",
              f"schema_version = {PUBLIC_SCHEMA_VERSION}",
              f"corpus_sha256 = '{PUBLIC_CORPUS_SHA256}'",
              "source_url = '#demo'", "manual = '화면'"] if PUBLIC_DEMO else [])
    if scope:
        key = ">".join(scope).replace("'", "")
        parts.append(f"scope_key GLOB '{key}*'")
    if types:
        ors = " OR ".join(f"chunk_type = '{t}'" for t in sorted(types) if t.isalnum())
        parts.append(f"({ors})")
    return " AND ".join(parts)


# ── 질의 재작성(Query Rewrite) — 검색리콜개선_계획.md ① ──
# 실측(2026-07-13, 240문항): 항상-재작성은 -12.1%p 유해(매뉴얼 문체 질문의 어휘 정합 훼손)
# → **rescue 모드**: 원질의가 게이트에 실패했을 때만 재작성 후 재검색(정상 질문 무접촉·회귀 불가).
REWRITE_ENABLE = os.environ.get("REWRITE_ENABLE", "1") != "0"
REWRITE_MODEL = os.environ.get("OPENAI_REWRITE_MODEL", "gpt-4o-mini")
REWRITE_PROMPT = (
    "증권 원장시스템(PowerBASE) 매뉴얼 검색용으로 사용자 질문을 정규화하라. "
    "오탈자 교정, 구어체·축약어를 매뉴얼 문어체로(예: 비번→비밀번호), 핵심 명사 보존. "
    "질문에 없는 의미를 추가하거나 추측하지 마라. "
    'JSON 한 개만 출력: {"rewritten":"...", "keywords":["..."]}')


def _rewrite_cache(key: str, val: str | None = None) -> str | None:
    """Redis 캐시(rw:*, TTL 7일) — 미설정/실패 시 조용히 무시."""
    if not REDIS_URL:
        return None
    try:
        if val is None:
            r = _post(f"{REDIS_URL}/pipeline", REDIS_TOKEN, [["GET", key]], timeout=2)
            return (r[0] or {}).get("result")
        _post(f"{REDIS_URL}/pipeline", REDIS_TOKEN,
              [["SET", key, val, "EX", "604800"]], timeout=2)
    except Exception:
        return None


def rewrite_query(q: str) -> dict | None:
    """질의 재작성 — {'rewritten', 'cached'} 또는 None(비활성/실패 → 원질의 사용)."""
    if not REWRITE_ENABLE or not OPENAI_KEY or len(q.strip()) < 6:
        return None
    import hashlib as _hl
    key = "rw:" + _hl.sha1("".join(q.split()).encode()).hexdigest()[:20]
    cached = _rewrite_cache(key)
    if cached:
        return {"rewritten": cached, "cached": True}
    body = {"model": REWRITE_MODEL,
            "messages": [{"role": "system", "content": REWRITE_PROMPT},
                         {"role": "user", "content": q}]}
    if REWRITE_MODEL.startswith(("gpt-4", "gpt-3.5")):
        body.update(temperature=0, max_tokens=200, response_format={"type": "json_object"})
    else:
        body["max_completion_tokens"] = 400
    try:
        r = _post("https://api.openai.com/v1/chat/completions", OPENAI_KEY, body, timeout=4)
        out = json.loads(r["choices"][0]["message"]["content"])
        rw = (out.get("rewritten") or "").strip()
        if not rw or "".join(rw.split()) == "".join(q.split()):
            return None
        _rewrite_cache(key, rw)
        return {"rewritten": rw, "cached": False}
    except Exception:
        return None


# ── 정확매치 부스트(검색 후처리 재랭킹) — 검색리콜개선_계획.md ② ──
# 스윕 실측(2026-07-13, 240문항): DBSF 92.1%→부스트 93.8%, 심층(T2) 60%→80%, RRF 기각(70.4%).
# 전역 사전 없이 검색된 topK 메타(title·screen_no)와 질문 신호를 직접 대조 — 완전 일치만(보수).
FUSION_ALG = "RRF" if os.environ.get("FUSION_ALG", "DBSF").upper() == "RRF" else "DBSF"
BOOST_ENABLE = os.environ.get("BOOST_ENABLE", "1") != "0"
RERANK_POOL = 10   # 재랭킹 후보 풀(반환·LLM 컨텍스트는 topk 그대로)


def _q_numbers(q: str) -> set[str]:
    """질문 속 화면번호 신호 — TR표기는 무조건, 단독 4자리는 화면/TR 문맥어 동반 시만."""
    import re as _re
    nums = set(_re.findall(r"TR-?(\d{3,4})", q, _re.I))
    if _re.search(r"화면|TR|티알", q, _re.I):
        nums |= set(_re.findall(r"(?<![\d.])(\d{4})(?![\d.])", q))
    return nums


def boost_exact(q: str, res: list[dict]) -> list[dict]:
    """질문에 화면번호/완전 화면명이 명시된 경우 해당 문서를 상위로 승격(안정 정렬)."""
    if not BOOST_ENABLE or not res:
        return res
    nums, qz = _q_numbers(q), q.replace(" ", "")

    def match(r):
        m = r.get("metadata", {}) or {}
        no = str(m.get("screen_no") or "")
        if no and no in nums:
            return True
        title = (m.get("title") or "").replace(" ", "")
        return len(title) >= 6 and title in qz

    hit = [r for r in res if match(r)]
    if not hit:
        return res
    return hit + [r for r in res if r not in hit]


def search(q: str, topk: int, scope: list[str] | None, types: set[str] | None,
           tau: float | None = None, rewrite: bool = True):
    """Upstash 하이브리드 질의 → UI 호환 hits.

    전처리: 질의 재작성(경량 LLM, 실패 시 원질의) — 본검색·게이트 모두 재작성 기준.
    랭킹: 하이브리드(내장 임베딩 + BM25, DBSF 융합 — 스윕 실측으로 확정) + 정확매치 부스트.
    게이트: DBSF 점수는 무관/유관 분포가 겹쳐 부적합 → 별도 dense 전용 쿼리의
    코사인(0..1)으로 판정. 두 쿼리는 스레드로 병렬 실행."""
    require_public_dataset()
    import threading
    f = _filter_expr(scope, types)
    tau_eff = GATE_TAU if tau is None else float(tau)

    def run_pass(q_text: str):
        """하이브리드 본검색 + dense 게이트 병렬 1회전 → (res, dense_top)."""
        body = {"data": q_text, "topK": max(topk, RERANK_POOL), "includeMetadata": True,
                "fusionAlgorithm": FUSION_ALG}
        gate_body = {"data": q_text, "topK": 1, "queryMode": "DENSE",
                     "includeMetadata": True}
        if f:
            body["filter"] = f
            gate_body["filter"] = f
        out: dict = {}

        def run(key, b):
            # Upstash 질의가 간헐 지연/실패(평시 <0.5s) — 짧은 타임아웃 + 1회 재시도로 흡수
            for attempt in (1, 2):
                try:
                    out[key] = _post(f"{VEC_URL}/query-data", VEC_TOKEN, b,
                                     timeout=8).get("result", [])
                    return
                except Exception as e:
                    if attempt == 2:
                        out[key] = e

        ts = [threading.Thread(target=run, args=("main", body)),
              threading.Thread(target=run, args=("gate", gate_body))]
        for t in ts: t.start()
        for t in ts: t.join()
        if isinstance(out["main"], Exception):
            raise out["main"]
        res = _validate_public_results(out["main"], "hybrid")
        dense_top = 0.0
        if not isinstance(out["gate"], Exception):
            gate_res = _validate_public_results(out["gate"], "dense-gate")
            if gate_res:
                dense_top = float(gate_res[0].get("score", 0.0))
        return res, dense_top

    res, dense_top = run_pass(q)
    rw = None
    # rescue 재작성: 원질의가 게이트 실패 시에만 — 정상 질문 무접촉.
    # 채택엔 여유폭(+0.02) 요구: 무관 질의가 문체 정규화만으로 τ에 턱걸이하는 구제 차단(실측 0.700 사례).
    if rewrite and dense_top < tau_eff:
        rw = rewrite_query(q)
        if rw:
            res2, dense_top2 = run_pass(rw["rewritten"])
            if dense_top2 >= tau_eff + 0.02:   # 뚜렷한 구제만 채택
                res, dense_top = res2, dense_top2
            else:
                rw["rescued"] = False
    res = boost_exact(q, res)   # 정확매치 승격 후 상위 topk만 반환

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
    if rw:
        gate["rewrite"] = {"original": q, "rewritten": rw["rewritten"],
                           "cached": rw.get("cached", False),
                           "rescued": rw.get("rescued", True)}
    return hits, gate


def scope_hint(hits: list[dict]) -> dict:
    """근거 분포 — 2단계 모호성: ① 매뉴얼(화면/업무) ② 부문 (webapp과 동일 로직)."""
    secs: dict[str, dict] = {}
    mans: dict[str, dict] = {}
    for h in hits:
        sp = h.get("sector_path") or []
        man = h.get("manual") or (sp[0] if sp and sp[0] in ("화면", "업무") else "")
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


def _daily_count() -> int | None:
    """일일 답변 카운터. None은 외부 LLM을 호출하면 안 되는 가드 장애다."""
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


def track_chip(gate_ok: bool) -> None:
    """추천 말풍선(src=chip) 계측 — 클릭 수·게이트 통과 수 일별 INCR.
    Redis 미설정/실패 시 조용히 무시(응답 지연·오류 없음)."""
    if not REDIS_URL:
        return
    day = time.strftime("%Y%m%d")
    ttl = str(40 * 86400)  # 40일
    cmds = [["INCR", f"demo:chip:{day}"], ["EXPIRE", f"demo:chip:{day}", ttl]]
    if gate_ok:
        cmds += [["INCR", f"demo:chipok:{day}"], ["EXPIRE", f"demo:chipok:{day}", ttl]]
    try:
        _post(f"{REDIS_URL}/pipeline", REDIS_TOKEN, cmds, timeout=5)
    except Exception:
        pass


def extractive_answer(hits: list[dict]) -> str:
    lines = []
    for h in hits[:3]:
        lines.append(f"{h['text']} [S{h['rank']}]")
    return "\n\n".join(lines) if lines else "매뉴얼에서 확인되지 않습니다."


def answer(q: str, hits: list[dict]) -> dict:
    if not hits:
        return {"answer": "매뉴얼에서 확인되지 않습니다.", "used_llm": False, "backend": "none"}
    if not OPENAI_KEY:
        return {"answer": extractive_answer(hits), "used_llm": False, "backend": "extractive"}
    cnt = _daily_count()
    if cnt is None:
        return {"answer": extractive_answer(hits), "used_llm": False,
                "backend": "guard-unavailable-extractive"}
    if cnt > DAILY_LIMIT:
        return {"answer": extractive_answer(hits), "used_llm": False, "backend": "limit-extractive"}
    ctx = "\n".join(
        f"[S{h['rank']}] ({h.get('title', '')}"
        + (f" · 화면번호 {h['screen_no']}" if h.get("screen_no") else "")
        + f" · {h['path_str']}) {h['text']}" for h in hits)
    body = {"model": OPENAI_MODEL,
            "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                         {"role": "user", "content": f"[근거]\n{ctx}\n\n[질문]\n{q}"}]}
    if OPENAI_MODEL.startswith(("gpt-4", "gpt-3.5")):
        body.update(temperature=0.2, max_tokens=600)
    else:  # gpt-5 계열 reasoning 모델 — max_tokens·temperature 미지원
        body["max_completion_tokens"] = 700
    try:
        r = _post("https://api.openai.com/v1/chat/completions", OPENAI_KEY, body, timeout=30)
        text = r["choices"][0]["message"]["content"].strip()
        return {"answer": text, "used_llm": True, "backend": f"openai:{OPENAI_MODEL}"}
    except Exception:
        return {"answer": extractive_answer(hits), "used_llm": False, "backend": "extractive"}


def authorized(handler) -> bool:
    """접근 검증 — 합성 공개 모드는 데이터셋 검증까지, 실데이터 운영은 헤더 키 필수."""
    if PUBLIC_DEMO and not public_dataset_ready():
        return False
    if not ACCESS_KEY:
        return PUBLIC_DEMO   # 키 미설정 익명 공개는 합성 모드에서만 허용
    supplied = handler.headers.get("x-demo-key", "")
    return bool(supplied) and hmac.compare_digest(supplied, ACCESS_KEY)


def parse_qs(path: str) -> dict:
    qs = urllib.parse.parse_qs(urllib.parse.urlparse(path).query)
    return {k: v[0] for k, v in qs.items()}


def common_params(p: dict):
    q = (p.get("q") or "").strip()
    if not q or len(q) > 500 or any(ord(ch) < 32 and ch not in "\t\n\r" for ch in q):
        raise ValueError("invalid query")
    if _EMAIL_RE.search(q) or _PHONE_RE.search(q) or _LONG_NUMBER_RE.search(q):
        raise ValueError("query contains sensitive-looking data")
    try:
        topk = int(p.get("topk") or 5)
    except (TypeError, ValueError):
        raise ValueError("invalid topk") from None
    if not 1 <= topk <= 30:
        raise ValueError("topk out of range")
    tau = p.get("tau")
    if tau not in (None, ""):
        try:
            tau = float(tau)
        except (TypeError, ValueError):
            raise ValueError("invalid tau") from None
        if not math.isfinite(tau) or not 0.0 <= tau <= 1.0:
            raise ValueError("tau out of range")
    else:
        tau = None
    scope = [s.strip() for s in (p.get("scope") or "").split(">") if s.strip()] or None
    if scope and tuple(scope) not in _PUBLIC_SCOPE_PATHS:
        raise ValueError("invalid scope")
    raw_types = [t for t in (p.get("types") or "").split(",") if t]
    types = set(raw_types) or None
    allowed_types = {"overview", "description", "glossary", "related", "qa"}
    if types and (len(raw_types) != len(types) or not types <= allowed_types):
        raise ValueError("invalid chunk type")
    return q, topk, tau, scope, types


def send_json(handler, obj: dict, code: int = 200):
    try:
        body = json.dumps(obj, ensure_ascii=False, allow_nan=False).encode()
    except (TypeError, ValueError):
        code = 500
        body = b'{"error":"invalid response"}'
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)
