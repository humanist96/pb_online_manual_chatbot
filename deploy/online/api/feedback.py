"""/api/feedback — 사용자 피드백 등록·조회·공감·상태변경·반응·통계 (Upstash Redis).

※ 이 폴더(deploy/online/)는 공개 데모 전용 예외 구역이다(CLAUDE.md 참고).
   합성 데모 데이터·외부 API 허용 구역. 표준 라이브러리만 사용
   (_common 의 Redis REST 헬퍼 _post 재사용 — 추가 의존성 0).

라우트:
  POST /api/feedback                         등록 {type,content,nick?,ctx?,website(honeypot)}
  GET  /api/feedback?offset=&n=&type=         최신순 목록 (+공감수 병합)
  POST /api/feedback?action=vote&id=          공감 +1
  POST /api/feedback?action=status&id=&to=    상태변경 (x-admin-key 필수)
  POST /api/feedback?action=react&v=up|down   답변 반응 카운터(목록 미오염)
  GET  /api/feedback?action=stats             집계(유형·상태·14일 추이·반응·공감 TOP5)

Redis 키:
  fb:seq                INCR — id 발급
  fb:item:{id}          STRING(JSON) — 본문
  fb:index              ZSET score=epoch member=id — 최신순
  fb:votes:{id}         INCR — 공감 수
  fb:rate:{iph}:{d}     INCR+EXPIRE 1d — 등록 요율 제한
  fb:up:{d} / fb:down:{d}  INCR+EXPIRE 40d — 답변 반응 일별
"""
import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent))  # Vercel: 형제 모듈 임포트 경로

import os
import base64
import binascii
import hmac
import json
import math
import re
import time
import hashlib
from http.server import BaseHTTPRequestHandler

from _common import authorized, parse_qs, send_json, _post

ADMIN_KEY = os.environ.get("FEEDBACK_ADMIN_KEY", "")


def _env_true(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


# 피드백은 사용자 자유 입력을 외부 Redis에 저장하므로 목적별 명시적 opt-in이다.
FEEDBACK_ENABLED = _env_true("FEEDBACK_ENABLED")
FEEDBACK_CONTEXT_ENABLED = _env_true("FEEDBACK_CONTEXT_ENABLED")
FEEDBACK_PUBLIC_BOARD_ENABLED = _env_true("FEEDBACK_PUBLIC_BOARD_ENABLED")
REDIS_URL = os.environ.get("FEEDBACK_REDIS_REST_URL", "").rstrip("/")
REDIS_TOKEN = os.environ.get("FEEDBACK_REDIS_REST_TOKEN", "")

TYPE_ORDER = ["bug", "quality", "outdated", "missing", "idea"]
TYPES = set(TYPE_ORDER)
STATUS_ORDER = ["open", "ack", "done", "hold"]
STATUSES = set(STATUS_ORDER)

MIN_CONTENT, MAX_CONTENT, MAX_NICK = 5, 1000, 20
RATE_LIMIT = int(os.environ.get("FEEDBACK_RATE_LIMIT", "10"))  # 건/일/IP
REACT_TTL = str(40 * 86400)
try:
    FEEDBACK_RETENTION_DAYS = int(os.environ.get("FEEDBACK_RETENTION_DAYS", "90"))
except ValueError:
    FEEDBACK_RETENTION_DAYS = 90
FEEDBACK_RETENTION_DAYS = min(365, max(1, FEEDBACK_RETENTION_DAYS))
FEEDBACK_TTL = str(FEEDBACK_RETENTION_DAYS * 86400)

# 화면 캡처 첨부는 명시적으로 활성화한 배포에서만 허용한다. 기본값은 비활성으로,
# 과거에 저장된 이미지도 API 응답에 노출하지 않는다.
FEEDBACK_IMAGES_ENABLED = FEEDBACK_ENABLED and _env_true("FEEDBACK_IMAGES_ENABLED")
MAX_IMAGES = 3
MAX_IMG_LEN = 420_000          # data URL 문자수(약 300KB)
MAX_IMG_BYTES = 300_000
IMG_PREFIXES = {
    "data:image/png;base64,": "image/png",
    "data:image/jpeg;base64,": "image/jpeg",
    "data:image/webp;base64,": "image/webp",
    "data:image/gif;base64,": "image/gif",
}


# ── 시간(한국 표준시 고정 — Vercel 은 UTC 로 돈다) ──
def _kst():
    return time.gmtime(time.time() + 9 * 3600)


def _now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%S+09:00", _kst())


def _day():
    return time.strftime("%Y%m%d", _kst())


def _recent_days(n):
    """오늘 포함 최근 n일 'YYYY-MM-DD' (과거→현재)."""
    base = time.time() + 9 * 3600
    return [time.strftime("%Y-%m-%d", time.gmtime(base - k * 86400)) for k in range(n - 1, -1, -1)]


# ── Redis 파이프라인 ──
def _redis(cmds):
    """Upstash Redis /pipeline. cmds=[["INCR","k"],...] → 결과 리스트(전송 오류 시 예외)."""
    if not REDIS_URL:
        raise RuntimeError("redis not configured")
    r = _post(f"{REDIS_URL}/pipeline", REDIS_TOKEN, cmds, timeout=8)
    return [x.get("result") if isinstance(x, dict) else x for x in r]


def _ip_hash(handler):
    ip = (handler.headers.get("x-forwarded-for")
          or handler.headers.get("x-real-ip") or "?").split(",")[0].strip()
    return hashlib.sha1(ip.encode("utf-8", "ignore")).hexdigest()[:16]


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _strict_loads(raw):
    def reject_constant(value):
        raise ValueError(f"non-finite JSON number: {value}")

    return json.loads(raw, parse_constant=reject_constant)


def _read_json(handler):
    try:
        ln = int(handler.headers.get("content-length") or 0)
        if ln <= 0 or ln > 4_200_000:   # 화면 캡처 첨부(압축·최대 3장) 여유
            return None
        return _strict_loads(handler.rfile.read(ln).decode("utf-8"))
    except Exception:
        return None


def _clean_ctx(ctx):
    """답변 말풍선에서 첨부된 컨텍스트 — 화이트리스트 필드만, 길이 제한."""
    if not FEEDBACK_CONTEXT_ENABLED or not isinstance(ctx, dict):
        return None
    out = {}
    q = ctx.get("q")
    if isinstance(q, str) and q.strip():
        clean_q = q.strip()[:300]
        out["q"] = ("[민감정보 제거]" if _contains_sensitive_text(clean_q)
                    else clean_q)
    b = ctx.get("backend")
    if isinstance(b, str) and b:
        out["backend"] = b[:60]
    sc = ctx.get("scope")
    if isinstance(sc, str) and sc:
        out["scope"] = sc[:120]
    g = ctx.get("gate")
    if isinstance(g, dict):
        gg = {}
        for k in ("best", "tau"):
            v = g.get(k)
            if (isinstance(v, (int, float)) and not isinstance(v, bool)
                    and math.isfinite(float(v))):
                gg[k] = round(float(v), 4)
        if "all_low" in g:
            gg["all_low"] = bool(g.get("all_low"))
        if gg:
            out["gate"] = gg
    hits = ctx.get("hits")
    if isinstance(hits, list):
        hh = []
        for h in hits[:3]:
            if not isinstance(h, dict):
                continue
            hh.append({"sid": str(h.get("sid", ""))[:20],
                       "no": str(h.get("no", ""))[:12],
                       "path": str(h.get("path", ""))[:160]})
        if hh:
            out["hits"] = hh
    return out or None


_EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
_PHONE_RE = re.compile(r"(?<!\d)(?:01[016789]|0\d{1,2})[- .]?\d{3,4}[- .]?\d{4}(?!\d)")
_LONG_NUMBER_RE = re.compile(r"(?<!\d)\d(?:[- ]?\d){7,18}(?!\d)")


def _contains_sensitive_text(value: str) -> bool:
    return bool(_EMAIL_RE.search(value) or _PHONE_RE.search(value)
                or _LONG_NUMBER_RE.search(value))


def _is_admin(handler) -> bool:
    supplied = handler.headers.get("x-admin-key", "")
    return bool(ADMIN_KEY and supplied and hmac.compare_digest(supplied, ADMIN_KEY))


def _valid_image_magic(mime: str, raw: bytes) -> bool:
    if mime == "image/png":
        return raw.startswith(b"\x89PNG\r\n\x1a\n")
    if mime == "image/jpeg":
        return len(raw) >= 4 and raw.startswith(b"\xff\xd8\xff") and raw.endswith(b"\xff\xd9")
    if mime == "image/gif":
        return raw.startswith((b"GIF87a", b"GIF89a"))
    if mime == "image/webp":
        return (len(raw) >= 12 and raw[:4] == b"RIFF" and raw[8:12] == b"WEBP"
                and int.from_bytes(raw[4:8], "little") == len(raw) - 8)
    return False


def _canonical_image(s: str) -> str:
    """엄격히 검증한 data URL을 정규 Base64 표현으로 다시 만든다."""
    if not isinstance(s, str) or not s or len(s) > MAX_IMG_LEN:
        raise ValueError("invalid image")
    prefix = next((p for p in IMG_PREFIXES if s.startswith(p)), None)
    if prefix is None:
        raise ValueError("invalid image type")
    payload = s[len(prefix):]
    if not payload:
        raise ValueError("empty image")
    try:
        raw = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError):
        raise ValueError("invalid base64") from None
    mime = IMG_PREFIXES[prefix]
    if not raw or len(raw) > MAX_IMG_BYTES or not _valid_image_magic(mime, raw):
        raise ValueError("invalid image data")
    canonical = base64.b64encode(raw).decode("ascii")
    return f"data:{mime};base64,{canonical}"


def _clean_images(body):
    """첨부 이미지를 전부 검증한다. 일부만 조용히 수용하지 않는다."""
    imgs = body.get("images")
    if imgs is None and body.get("image"):
        imgs = [body.get("image")]
    if imgs is None:
        return []
    if not isinstance(imgs, list):
        raise ValueError("images must be a list")
    if not imgs:
        return []
    if not FEEDBACK_IMAGES_ENABLED:
        raise ValueError("image attachments disabled")
    if len(imgs) > MAX_IMAGES:
        raise ValueError("too many images")
    return [_canonical_image(s) for s in imgs]


def _load_items(ids):
    """id 리스트 → 본문 dict 리스트(공감수 병합, 순서 유지, 누락 스킵)."""
    ids = [str(i) for i in (ids or [])]
    if not ids:
        return []
    try:
        raws = _redis([["MGET", *[f"fb:item:{i}" for i in ids]]])[0] or []
        votes = _redis([["MGET", *[f"fb:votes:{i}" for i in ids]]])[0] or []
    except Exception:
        return []
    out = []
    for i, raw in enumerate(raws):
        if not raw:
            continue
        try:
            it = _strict_loads(raw)
        except Exception:
            continue
        if not FEEDBACK_IMAGES_ENABLED:
            it.pop("img", None)
        it["votes"] = int(votes[i]) if i < len(votes) and votes[i] else 0
        out.append(it)
    return out


# ── 라우트 ──
def register(handler):
    if not FEEDBACK_ENABLED or not REDIS_URL:
        return send_json(handler, {"error": "저장소가 설정되지 않아 지금은 등록할 수 없어요."}, 503)
    body = _read_json(handler)
    if not isinstance(body, dict):
        return send_json(handler, {"error": "요청 형식이 올바르지 않아요."}, 400)
    # honeypot — 봇이 채우는 숨은 필드. 채워졌으면 성공한 척(무음 폐기)
    if (body.get("website") or "").strip():
        return send_json(handler, {"ok": True, "item": None}, 200)

    typ = (body.get("type") or "").strip()
    content = (body.get("content") or "").strip()
    nick = (body.get("nick") or "").strip()[:MAX_NICK]
    if typ not in TYPES:
        return send_json(handler, {"error": "피드백 유형을 선택해 주세요."}, 400)
    if not (MIN_CONTENT <= len(content) <= MAX_CONTENT):
        return send_json(handler, {"error": f"내용은 {MIN_CONTENT}~{MAX_CONTENT}자로 적어주세요."}, 400)
    if _contains_sensitive_text(content) or _contains_sensitive_text(nick):
        return send_json(handler, {
            "error": "계좌·전화·이메일 등 민감정보를 제거한 후 다시 등록해 주세요."
        }, 400)

    raw_ctx = body.get("ctx")
    if (FEEDBACK_CONTEXT_ENABLED and isinstance(raw_ctx, dict)
            and _contains_sensitive_text(str(raw_ctx.get("q") or ""))):
        return send_json(handler, {
            "error": "질문 컨텍스트의 민감정보를 제거한 후 다시 등록해 주세요."
        }, 400)
    ctx = _clean_ctx(raw_ctx)
    try:
        imgs = _clean_images(body)
    except ValueError:
        return send_json(handler, {"error": "이미지 첨부 형식이 올바르지 않아요."}, 400)

    # 요율 제한(IP 해시 일별) — Redis 실패해도 등록은 막지 않는다
    iph, day = _ip_hash(handler), _day()
    try:
        cnt = _redis([["INCR", f"fb:rate:{iph}:{day}"],
                      ["EXPIRE", f"fb:rate:{iph}:{day}", "86400"]])[0]
        if isinstance(cnt, int) and cnt > RATE_LIMIT:
            return send_json(handler, {"error": "오늘 등록 한도를 넘었어요. 내일 다시 남겨주세요."}, 429)
    except Exception:
        pass

    ua = "Mobile" if "Mobi" in (handler.headers.get("user-agent") or "") else "Desktop"
    try:
        fid = _redis([["INCR", "fb:seq"]])[0]
        item = {"id": fid, "ts": _now_iso(), "type": typ, "content": content,
                "nick": nick, "status": "open", "ua": ua}
        if ctx:
            item["ctx"] = ctx
        if imgs:
            item["img"] = len(imgs)
        # 인덱스 정렬 점수는 증가 시퀀스 id 자체 — 같은 초 다중 등록도 삽입순 유지
        # (epoch 초를 쓰면 동점 시 member 사전순으로 깨진다: "10" < "2").
        _redis([["SET", f"fb:item:{fid}",
                 json.dumps(item, ensure_ascii=False, allow_nan=False)],
                ["EXPIRE", f"fb:item:{fid}", FEEDBACK_TTL],
                ["ZADD", "fb:index", str(fid), str(fid)]])
        for k, s in enumerate(imgs):   # 이미지는 개별 요청으로 SET(요청당 크기 억제)
            _redis([["SET", f"fb:img:{fid}:{k}", s],
                    ["EXPIRE", f"fb:img:{fid}:{k}", FEEDBACK_TTL]])
    except Exception:
        return send_json(handler, {"error": "등록 중 문제가 있었어요. 잠시 후 다시 시도해 주세요."}, 503)
    item["votes"] = 0
    return send_json(handler, {"ok": True, "item": item}, 200)


def imgs(handler, p):
    """GET action=img&id=N — 카드 펼칠 때 지연 로드하는 첨부 이미지(data URL 리스트)."""
    if not FEEDBACK_IMAGES_ENABLED:
        return send_json(handler, {"images": [], "error": "image attachments disabled"}, 404)
    fid = _int(p.get("id"))
    if fid is None:
        return send_json(handler, {"images": []}, 400)
    try:
        raw = _redis([["GET", f"fb:item:{fid}"]])[0]
        item = _strict_loads(raw) if raw else None
        if (not item or (not _is_admin(handler)
                         and (not FEEDBACK_PUBLIC_BOARD_ENABLED
                              or item.get("status") != "done"))):
            return send_json(handler, {"images": []}, 404)
        cnt = min(MAX_IMAGES, max(0, int(item.get("img", 0) or 0)))
        if not cnt:
            return send_json(handler, {"images": []}, 200)
        vals = _redis([["MGET", *[f"fb:img:{fid}:{k}" for k in range(cnt)]]])[0] or []
        safe = []
        for value in vals:
            try:
                safe.append(_canonical_image(value))
            except ValueError:
                continue
        return send_json(handler, {"images": safe}, 200)
    except Exception:
        return send_json(handler, {"images": [], "error": "이미지를 불러오지 못했어요."}, 200)


def listing(handler, p):
    if not REDIS_URL:
        return send_json(handler, {"items": [], "total": 0}, 200)
    admin = _is_admin(handler)
    if not FEEDBACK_PUBLIC_BOARD_ENABLED and not admin:
        return send_json(handler, {"error": "feedback board is private"}, 403)
    offset = max(0, _int(p.get("offset")) or 0)
    n = min(50, max(1, _int(p.get("n")) or 20))
    typ = (p.get("type") or "").strip()
    try:
        ids = _redis([["ZRANGE", "fb:index", "0", "-1", "REV"]])[0] or []
    except Exception:
        return send_json(handler, {"items": [], "total": 0, "error": "저장소 조회에 실패했어요."}, 200)
    items = _load_items(ids)
    if not admin:
        items = [it for it in items if it.get("status") == "done"]
    if typ in TYPES:
        items = [it for it in items if it.get("type") == typ]
    return send_json(handler, {"items": items[offset:offset + n],
                               "total": len(items)}, 200)


def vote(handler, p):
    fid = _int(p.get("id"))
    if fid is None:
        return send_json(handler, {"error": "bad id"}, 400)
    try:
        raw = _redis([["GET", f"fb:item:{fid}"]])[0]
        item = _strict_loads(raw) if raw else None
        if not item or item.get("status") != "done":
            return send_json(handler, {"error": "not found"}, 404)
        iph, day = _ip_hash(handler), _day()
        rate = _redis([["INCR", f"fb:vote-rate:{iph}:{day}"],
                       ["EXPIRE", f"fb:vote-rate:{iph}:{day}", "86400"]])[0]
        if isinstance(rate, int) and rate > 50:
            return send_json(handler, {"error": "rate limit"}, 429)
        first = _redis([["SET", f"fb:vote-once:{fid}:{iph}", "1",
                         "EX", "86400", "NX"]])[0]
        if first != "OK":
            current = _redis([["GET", f"fb:votes:{fid}"]])[0] or 0
            return send_json(handler, {"ok": True, "votes": int(current)}, 200)
        v = _redis([["INCR", f"fb:votes:{fid}"]])[0]
    except Exception:
        return send_json(handler, {"error": "실패"}, 503)
    return send_json(handler, {"ok": True, "votes": v}, 200)


def status(handler, p):
    if not _is_admin(handler):
        return send_json(handler, {"error": "unauthorized"}, 401)
    fid, to = _int(p.get("id")), (p.get("to") or "").strip()
    if fid is None or to not in STATUSES:
        return send_json(handler, {"error": "bad params"}, 400)
    try:
        raw = _redis([["GET", f"fb:item:{fid}"]])[0]
        if not raw:
            return send_json(handler, {"error": "not found"}, 404)
        it = _strict_loads(raw)
        it["status"] = to
        _redis([["SET", f"fb:item:{fid}",
                 json.dumps(it, ensure_ascii=False, allow_nan=False)]])
    except Exception:
        return send_json(handler, {"error": "실패"}, 503)
    return send_json(handler, {"ok": True, "status": to}, 200)


def react(handler, p):
    v = (p.get("v") or "").strip()
    if v not in ("up", "down"):
        return send_json(handler, {"error": "bad"}, 400)
    key = f"fb:{v}:{_day()}"
    try:
        iph, day = _ip_hash(handler), _day()
        rate = _redis([["INCR", f"fb:react-rate:{iph}:{day}"],
                       ["EXPIRE", f"fb:react-rate:{iph}:{day}", "86400"]])[0]
        if isinstance(rate, int) and rate > 100:
            return send_json(handler, {"error": "rate limit"}, 429)
        _redis([["INCR", key], ["EXPIRE", key, REACT_TTL]])
    except Exception:
        pass
    return send_json(handler, {"ok": True}, 200)


def stats(handler):
    empty = {"total": 0, "by_type": {}, "by_status": {}, "votes": 0,
             "open": 0, "done": 0, "daily": [], "react": [], "top": []}
    admin = _is_admin(handler)
    if not FEEDBACK_PUBLIC_BOARD_ENABLED and not admin:
        return send_json(handler, {"error": "feedback board is private"}, 403)
    if not REDIS_URL:
        return send_json(handler, empty, 200)
    try:
        ids = _redis([["ZRANGE", "fb:index", "0", "-1", "REV"]])[0] or []
    except Exception:
        return send_json(handler, {**empty, "error": "집계 조회에 실패했어요."}, 200)
    items = _load_items(ids)
    if not admin:
        items = [it for it in items if it.get("status") == "done"]

    by_type = {t: 0 for t in TYPE_ORDER}
    by_status = {s: 0 for s in STATUS_ORDER}
    votes_sum, day_counts = 0, {}
    for it in items:
        by_type[it.get("type", "")] = by_type.get(it.get("type", ""), 0) + 1
        by_status[it.get("status", "open")] = by_status.get(it.get("status", "open"), 0) + 1
        votes_sum += int(it.get("votes", 0) or 0)
        d = (it.get("ts", "") or "")[:10]
        if d:
            day_counts[d] = day_counts.get(d, 0) + 1

    days = _recent_days(14)
    daily = [{"d": d[5:], "n": day_counts.get(d, 0)} for d in days]

    try:
        ups = _redis([["MGET", *[f"fb:up:{d.replace('-', '')}" for d in days]]])[0] or []
        dns = _redis([["MGET", *[f"fb:down:{d.replace('-', '')}" for d in days]]])[0] or []
    except Exception:
        ups, dns = [], []
    react = [{"d": days[i][5:],
              "up": int(ups[i]) if i < len(ups) and ups[i] else 0,
              "down": int(dns[i]) if i < len(dns) and dns[i] else 0}
             for i in range(len(days))]

    top = sorted((it for it in items if int(it.get("votes", 0) or 0) > 0),
                 key=lambda x: -int(x.get("votes", 0)))[:5]
    send_json(handler, {
        "total": len(items), "by_type": by_type, "by_status": by_status,
        "votes": votes_sum,
        "open": by_status.get("open", 0) + by_status.get("ack", 0),
        "done": by_status.get("done", 0),
        "daily": daily, "react": react, "top": top}, 200)


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        p = parse_qs(self.path)
        # UI가 기본 숨김 기능을 해제할지 결정하는 비민감 플래그.
        if p.get("action") == "capabilities":
            return send_json(self, {
                "feedback_enabled": FEEDBACK_ENABLED and bool(REDIS_URL),
                "images_enabled": FEEDBACK_IMAGES_ENABLED and bool(REDIS_URL),
                "context_enabled": FEEDBACK_CONTEXT_ENABLED,
                "public_board_enabled": FEEDBACK_PUBLIC_BOARD_ENABLED,
            })
        if not FEEDBACK_ENABLED:
            return send_json(self, {"error": "feedback disabled"}, 404)
        if not authorized(self):
            return send_json(self, {"error": "unauthorized"}, 401)
        if p.get("action") == "stats":
            return stats(self)
        if p.get("action") == "img":
            return imgs(self, p)
        return listing(self, p)

    def do_POST(self):
        if not FEEDBACK_ENABLED:
            return send_json(self, {"error": "feedback disabled"}, 404)
        if not authorized(self):
            return send_json(self, {"error": "unauthorized"}, 401)
        p = parse_qs(self.path)
        action = p.get("action")
        if action == "vote":
            if not FEEDBACK_PUBLIC_BOARD_ENABLED:
                return send_json(self, {"error": "feedback board is private"}, 403)
            return vote(self, p)
        if action == "status":
            return status(self, p)
        if action == "react":
            return react(self, p)
        return register(self)

    def log_message(self, *a):
        pass
