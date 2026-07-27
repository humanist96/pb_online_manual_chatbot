"""AICC 상담 녹취 정제·카드 생성 — 로컬 실행 도구(배포 제외, 표준 라이브러리만).

AICC녹취_추가_계획.md §4~§6·§8·§9 1단계 구현. 처리 흐름:

  aicc/{id8}.v3.txt (교정 전사) + aicc/{id8}.v3det.json (role/logprob/타임스탬프)
    → 자동 게이트(결정적)         : stt_short / stt_lowconf 탈락 → LLM 없이 excluded
    → L1 결정적 보정              : 패턴표(aicc_fixes.json) · 화면번호 검증(lexicon 대조) · PII 마스킹
    → L2 정제(Claude Code CLI)   : role 재판정·오탈자 보정·사례 카드 생성(엄격 JSON)
    → 산출물:
        data/aicc_cards.json      : recording_id(8자) 키 캐시(cards·corrections·verdict)
        data/aicc_ledger.jsonl    : 판정 대장(통화 1건=1행, upsert)
        data/aicc_refined/{id8}.json : 2층 아카이브(보정 전사·원 전사·corrections·세그먼트)
        data/aicc_pilot_report.html  : 반영/미반영 집계·건별 diff·카드 미리보기·PII 집계

경계: 이 도구는 deploy/online/ "로컬 실행 도구 — 배포 제외" 전처리 전용이다. 런타임
답변 경로(none|ollama)에는 일절 관여하지 않는다. 산출물은 전부 data/ 하위(git 제외).

  .venv/bin/python deploy/online/refine_aicc.py --pilot
  .venv/bin/python deploy/online/refine_aicc.py --ids 0272e64a,0b9b3bb6 --force
  .venv/bin/python deploy/online/refine_aicc.py --report-only
"""
from __future__ import annotations

import argparse
import html
import json
import pathlib
import re
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
from parse_counsel_xls import mask_pii  # noqa: E402 — PII 마스킹 재사용(수정 금지)

AICC_DIR = ROOT / "aicc"
DATA_DIR = ROOT / "data"
LEXICON_PATH = DATA_DIR / "aicc_lexicon.json"
FIXES_PATH = DATA_DIR / "aicc_fixes.json"
CARDS_PATH = DATA_DIR / "aicc_cards.json"
LEDGER_PATH = DATA_DIR / "aicc_ledger.jsonl"
REFINED_DIR = DATA_DIR / "aicc_refined"
REPORT_PATH = DATA_DIR / "aicc_pilot_report.html"

DEFAULT_TAU_LOGPROB = -0.35
MIN_CHARS = 200
LOWCONF_LINE_TAU = -0.35  # 프롬프트에 저신뢰로 표시할 세그먼트 임계
LLM_MODEL = "opus"
LLM_TIMEOUT = 180
LLM_RETRY = 1

# L1 초기 반복 오류 패턴표(파일 없으면 이 값으로 생성 — 검수에서 발견 시 축적)
DEFAULT_FIXES = {
    "친절하겠습니다": "친절하게 모시겠습니다",
}

VALID_REASONS = {
    "stt_short", "stt_lowconf", "role_unresolved",  # 결정적 게이트
    "unresolved", "no_value", "ambiguous",          # LLM 판정
    "llm_error",                                    # LLM 호출 실패
}

# ── PII 마스킹(발화체 확장) ─────────────────────────────────────────────────
_NAME_SUFFIX = r"입니다|이었습니다|였습니다|이에요|예요|이라고요|이라고|이구요|이고요|인데요|이요"
# 인사말 실명: "고객(지원)센터[의] OOO입니다" → 성만 남기고 마스킹("홍길순"→"홍**")
RE_GREET_NAME = re.compile(
    rf"(고객(?:지원)?센터[의]?\s*)([가-힣]{{2,4}})({_NAME_SUFFIX})")
# 소속(회사·부서·상품) 뒤 자기소개: "삼성자산운용 홍길동입니다", "감사부의(이)몽입니다"
# 소속 토큰은 단독('베이스 홍길동')·병합('감사부의이몽') 모두 허용(STT 띄어쓰기 편차).
RE_INTRO_NAME = re.compile(
    r"([가-힣A-Za-z0-9]*(?:운용|증권|은행|캐피탈|베이스|투자|금융|본부|지점|부의|팀의|실의|과의|센터의|센터|"
    rf"상담원|상담사))\s*([가-힣]{{2,4}})({_NAME_SUFFIX})")
# 통화 중 인명 + 직함/호칭: "홍길동 대리님", "김철수 과장", "김미소 차장님과"(조사 허용) 등.
# -님 형태는 뒤에 조사가 붙어도 매칭, 무-님 형태만 합성어 방지 lookahead 유지("대리점" 등).
RE_HON_NAME = re.compile(
    r"([가-힣]{2,4})\s*((?:대리|과장|차장|부장|팀장|주임|사원)님|(?:대리|과장|차장|부장|팀장|주임)(?![가-힣]))")
# 자기소개 실명: "성함/이름/상담원 ... OOO입니다", "저는 OOO입니다"
RE_SELF_NAME = re.compile(
    rf"(성함|이름|저는|제가|담당자|상담원|상담사)([은는이가]?\s*)([가-힣]{{2,4}})({_NAME_SUFFIX})")
# 문장 첫머리 맨이름 자기소개: "예 성춘향입니다", "감사합니다. 홍길순입니다"
# (비서비스 아카이브 방어용 — 일부 서술형 명사 과마스킹은 허용)
RE_BARE_NAME = re.compile(
    rf"(^|[.!?]\s+|네[,. ]\s*|예[,. ]\s*|감사합니다[.]?\s+)([가-힣]{{2,4}})({_NAME_SUFFIX})")
# 전화번호 구어 낭독: 010-xxxx-xxxx / 010 xxxx xxxx 등
RE_PHONE = re.compile(r"01[016789][-.\s]?\d{3,4}[-.\s]?\d{4}")

# 문장 첫머리 맨이름 마스킹에서 제외할 서술형 명사(과마스킹 방지)
_BARE_STOP = {
    "확인", "예정", "과제", "사원", "예전", "가능", "처리", "조회", "동일",
    "전체", "이용료", "안내", "말씀", "감사", "그렇습", "맞습",
}
# 소속 토큰 뒤에 올 수 있는 도메인 합성어(인명 아님) — intro 마스킹에서 제외
_INTRO_STOP = _BARE_STOP | {
    "신탁", "상품", "계좌", "거래", "서비스", "시스템", "회사", "업무",
    "화면", "내역", "현황", "계정", "고객", "여기", "관련", "상태", "구분",
}

# 직함/호칭 앞에 올 수 있는 일반명사(인명 아님) — 호칭 마스킹에서 제외
_HON_STOP = {
    "담당", "저희", "우리", "해당", "관련", "여기", "거기", "지점", "본사",
    "본부", "부서", "센터", "그쪽", "이쪽", "전산", "영업",
}

# 상담사례 카드에 인명이 남았는지 최종 재스캔용(자가점검)
RE_NAME_RESIDUAL = re.compile(r"[가-힣]{2,3}(입니다|대리님|과장님|차장님)")


def _mask_name(name: str) -> str:
    """성 1자만 남기고 나머지를 *로."""
    if len(name) <= 1:
        return name
    return name[0] + "*" * (len(name) - 1)


def mask_speech_names(t: str) -> tuple[str, int]:
    """발화체 인명·전화번호 마스킹. 반환: (마스킹 텍스트, 이벤트 수)."""
    n = 0

    def greet(m):
        nonlocal n
        n += 1
        return f"{m.group(1)}{_mask_name(m.group(2))}{m.group(3)}"

    def hon(m):
        nonlocal n
        name = m.group(1)
        # 직함 앞 일반명사 오마스킹 방지("담당 대리님", "저희 과장님" 등)
        if name in _HON_STOP or name[:2] in _HON_STOP:
            return m.group(0)
        n += 1
        return f"{_mask_name(name)} {m.group(2)}"

    def self_(m):
        nonlocal n
        n += 1
        return f"{m.group(1)}{m.group(2)}{_mask_name(m.group(3))}{m.group(4)}"

    def intro(m):
        nonlocal n
        name = m.group(2)
        if name in _INTRO_STOP or name[:2] in _INTRO_STOP:
            return m.group(0)
        n += 1
        return f"{m.group(1)} {_mask_name(name)}{m.group(3)}"

    def bare(m):
        nonlocal n
        name = m.group(2)
        if name in _BARE_STOP or name[:2] in _BARE_STOP:
            return m.group(0)
        n += 1
        return f"{m.group(1)}{_mask_name(name)}{m.group(3)}"

    def phone(m):
        nonlocal n
        n += 1
        return "010-****-****"

    t = RE_GREET_NAME.sub(greet, t)
    t = RE_INTRO_NAME.sub(intro, t)
    t = RE_SELF_NAME.sub(self_, t)
    t = RE_HON_NAME.sub(hon, t)
    t = RE_BARE_NAME.sub(bare, t)
    t = RE_PHONE.sub(phone, t)
    return t, n


def mask_all(t: str) -> tuple[str, int]:
    """발화체 인명·전화 + mask_pii(카드/계좌/식별번호). 반환: (마스킹, 이벤트 수)."""
    t, n = mask_speech_names(t)
    before = t
    t = mask_pii(t)
    if t != before:
        n += 1
    return t, n


# ── 입력 로딩 ───────────────────────────────────────────────────────────────
RE_ROLE_LINE = re.compile(r"^\[([^\]]+)\]\s*(.*)$")


def load_call(id8: str) -> dict | None:
    """v3.txt(교정 전사)와 v3det.json(세그먼트)을 읽어 통화 dict 반환.

    반환: {id8, recording_id, lines:[{role,text}], text, segments, metrics}.
    metrics = {chars, avg_logprob, segments, role_resolved}.
    """
    txt_path = AICC_DIR / f"{id8}.v3.txt"
    det_path = AICC_DIR / f"{id8}.v3det.json"
    if not txt_path.exists() or not det_path.exists():
        return None

    raw = txt_path.read_text(encoding="utf-8")
    lines = []
    for ln in raw.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        m = RE_ROLE_LINE.match(ln)
        if m:
            lines.append({"role": m.group(1), "text": m.group(2)})
        else:
            lines.append({"role": "", "text": ln})

    det = json.loads(det_path.read_text(encoding="utf-8"))
    segs = det.get("segments", [])
    lps = [s.get("avg_logprob") for s in segs if isinstance(s.get("avg_logprob"), (int, float))]
    avg = round(sum(lps) / len(lps), 4) if lps else 0.0
    chars = len(raw.strip())

    return {
        "id8": id8,
        "recording_id": det.get("recording_id", id8),
        "lines": lines,
        "text": raw.strip(),
        "segments": segs,
        "metrics": {
            "chars": chars,
            "avg_logprob": avg,
            "segments": len(segs),
            "role_resolved": bool(det.get("role_resolved", False)),
        },
    }


# ── 자동 게이트(결정적, LLM 이전) ────────────────────────────────────────────
def gate(metrics: dict, tau_logprob: float = DEFAULT_TAU_LOGPROB) -> list[str]:
    """결정적 게이트. 탈락 사유코드 리스트(빈 리스트=통과)."""
    reasons = []
    if metrics.get("chars", 0) < MIN_CHARS:
        reasons.append("stt_short")
    if metrics.get("avg_logprob", 0.0) < tau_logprob:
        reasons.append("stt_lowconf")
    return reasons


# ── L1 결정적 보정 ──────────────────────────────────────────────────────────
def ensure_fixes_file(path: pathlib.Path = FIXES_PATH) -> dict:
    """패턴표 로드. 없으면 DEFAULT_FIXES로 생성."""
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(DEFAULT_FIXES, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    return dict(DEFAULT_FIXES)


def apply_fixes(text: str, fixes: dict) -> tuple[str, list[dict]]:
    """패턴표 적용. 반환: (보정 텍스트, corrections[{from,to,reason}])."""
    corrections = []
    for src, dst in fixes.items():
        if src and src in text:
            cnt = text.count(src)
            text = text.replace(src, dst)
            corrections.append({"from": src, "to": dst,
                                "reason": f"L1 패턴표 x{cnt}"})
    return text, corrections


# 화면번호 문맥 패턴: 숫자 뒤 "번"/"화면", 앞 "화면"
RE_SCREEN_CTX = re.compile(
    r"화면\s*(?:번호)?\s*(\d{4})"          # 앞 "화면 (번호) NNNN"
    r"|(\d{4})\s*(?:번(?:을|이|화면)?|화면)")  # 뒤 "NNNN 번" / "NNNN 화면"


def extract_screen_nos(text: str, lexicon: dict) -> list[str]:
    """4자리 화면번호 후보를 문맥 패턴으로 추출 → lexicon screen_nos 실존분만 verified."""
    known = lexicon.get("screen_nos", {})
    found = []
    for m in RE_SCREEN_CTX.finditer(text):
        cand = m.group(1) or m.group(2)
        if cand and cand in known and cand not in found:
            found.append(cand)
    return found


def lexicon_candidates(text: str, lexicon: dict, top: int = 30) -> list[str]:
    """전사와 2자 이상 부분일치하는 terms/titles/seed 상위 N개(스코어·명칭 정렬)."""
    pool = []
    seen = set()
    for key in ("terms", "titles", "seed"):
        for term in lexicon.get(key, []):
            if len(term) >= 2 and term not in seen:
                seen.add(term)
                pool.append(term)

    scored = []
    for term in pool:
        if term in text:                       # 전체 일치 우선
            scored.append((len(term), term))
        else:                                   # 2자 부분일치
            grams = {term[i:i + 2] for i in range(len(term) - 1)}
            if any(g in text for g in grams):
                scored.append((2, term))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [t for _, t in scored[:top]]


# ── L2 정제(Claude Code CLI) ────────────────────────────────────────────────
def build_prompt(masked_lines: list[str], verified_screen_nos: list[str],
                 lex_cands: list[str], lowconf_lines: list[str]) -> str:
    sn = ", ".join(verified_screen_nos) if verified_screen_nos else "(없음)"
    lc = "\n".join(f"  - {x}" for x in lowconf_lines) if lowconf_lines else "  (없음)"
    lex = ", ".join(lex_cands) if lex_cands else "(없음)"
    transcript = "\n".join(masked_lines)
    return f"""너는 코스콤 원장시스템(PowerBASE) 고객지원센터 상담 녹취를 정제하는 도구다.
아래 role 태깅 전사(이미 PII 마스킹됨)를 읽고, STT 오류를 문맥에 맞게 보정하고 화자
역할을 재판정한 뒤, 검색용 "사례 카드"를 생성한다.

[검증된 화면번호(verified) — 이 목록의 부분집합만 카드 screen_nos에 사용]
{sn}

[용어사전 관련 후보 — 오탈자 보정 참고용, 표준 어휘]
{lex}

[저신뢰(avg_logprob < {LOWCONF_LINE_TAU}) 발화 — 오류 가능성 높음, 집중 검토]
{lc}

[전사 — 마스킹 완료]
{transcript}

절대 규칙:
- 사실 창작 금지. 전사에 없는 내용을 지어내지 마라.
- 인명(실명) 금지. 카드·보정 전사 어디에도 사람 이름을 넣지 마라.
- screen_nos는 위 verified 목록의 부분집합만. 목록에 없는 4자리 숫자(에러코드·펀드번호 등)는 넣지 마라.
- 정답이 통화 내에서 상담사가 명시적으로 확인해 준 내용이 아니면 그 카드는 indexable=false.
- 미해결·모호·단순 콜백/인사만 있는 통화는 카드를 만들지 말고 verdict.indexable=false.

오직 아래 형식의 엄격한 JSON 하나만 출력하라(코드블록·설명 금지):
{{"role_fixed_lines": ["[상담사] ...보정된 전사 전체를 role 태깅 줄 단위로..."],
 "corrections": [{{"from": "오류 어절", "to": "보정 어절", "reason": "근거"}}],
 "cards": [{{"issue": "표준어 핵심질문 1문장",
             "issue_colloquial": "고객 구어 표현",
             "answer": "명확한 정답(상담사가 명시 확인한 내용만)",
             "screen_nos": [],
             "sector_guess": "계좌|주문|펀드|수신|기타 중 하나 또는 빈 문자열",
             "resolved": true,
             "clarity": "clear 또는 ambiguous",
             "evidence": "근거 발화 인용 1~2줄"}}],
 "verdict": {{"indexable": true, "reason": "unresolved|no_value|ambiguous|ok 중 하나"}}}}"""


def _claude_cli(prompt: str, model: str = LLM_MODEL, timeout: int = LLM_TIMEOUT) -> dict:
    """claude -p --output-format json 서브프로세스 호출. 반환: 파싱된 dict.

    실패 시 예외를 던진다(호출부에서 재시도·llm_error 처리)."""
    proc = subprocess.run(
        ["claude", "-p", "--model", model, "--output-format", "json"],
        input=prompt, capture_output=True, text=True, timeout=timeout,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"claude CLI exit {proc.returncode}: {proc.stderr[:300]}")
    envelope = json.loads(proc.stdout)
    result_text = envelope.get("result", "")
    return _extract_json(result_text)


def _extract_json(text: str) -> dict:
    """모델 출력 텍스트에서 첫 최상위 JSON 객체를 추출."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # 중괄호 균형으로 첫 객체 추출
    start = text.find("{")
    if start < 0:
        raise ValueError("JSON 객체 없음")
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        c = text[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        else:
            if c == '"':
                in_str = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    return json.loads(text[start:i + 1])
    raise ValueError("JSON 객체 미완결")


def call_llm(prompt: str, llm_fn=_claude_cli, model: str = LLM_MODEL,
             timeout: int = LLM_TIMEOUT, retry: int = LLM_RETRY) -> dict:
    """LLM 호출 + 재시도. 실패하면 마지막 예외를 올림."""
    last = None
    for _ in range(retry + 1):
        try:
            return llm_fn(prompt, model=model, timeout=timeout)
        except Exception as e:  # noqa: BLE001 — 재시도 후 상위에서 llm_error 처리
            last = e
    raise last if last else RuntimeError("LLM 호출 실패")


# ── 카드 정규화(방어) ───────────────────────────────────────────────────────
def normalize_cards(raw_cards: list, id8: str, verified_screen_nos: list[str],
                    sector_of_screen: dict) -> list[dict]:
    """LLM 카드 → 표준 카드. screen_nos를 verified 부분집합으로 제한(방어)."""
    cards = []
    verified = set(verified_screen_nos)
    for i, c in enumerate(raw_cards or []):
        if not isinstance(c, dict):
            continue
        sn = [s for s in (c.get("screen_nos") or []) if str(s) in verified]
        sn = [str(s) for s in sn]
        card_id = f"cc:{id8}:{i + 1:04d}"
        sector = c.get("sector_guess") or ""
        # 화면번호가 있으면 해당 화면 sector 상속 우선
        for s in sn:
            if sector_of_screen.get(s):
                sector = sector_of_screen[s]
                break
        cards.append({
            "id": card_id,
            "issue": (c.get("issue") or "").strip(),
            "issue_colloquial": (c.get("issue_colloquial") or "").strip(),
            "answer": (c.get("answer") or "").strip(),
            "screen_nos": sn,
            "sector_guess": sector,
            "resolved": bool(c.get("resolved", False)),
            "clarity": c.get("clarity") or "",
            "evidence": (c.get("evidence") or "").strip(),
        })
    return cards


# ── 대장 upsert ─────────────────────────────────────────────────────────────
def system_date() -> str:
    """`date` 시스템 시각(ISO)."""
    try:
        out = subprocess.run(["date", "-Iseconds"], capture_output=True,
                             text=True, timeout=10)
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except Exception:  # noqa: BLE001
        pass
    import datetime
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def load_ledger(path: pathlib.Path = LEDGER_PATH) -> dict:
    rows = {}
    if path.exists():
        for ln in path.read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if not ln:
                continue
            r = json.loads(ln)
            rows[r["recording_id"]] = r
    return rows


def write_ledger(rows: dict, path: pathlib.Path = LEDGER_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for rid in sorted(rows):
            f.write(json.dumps(rows[rid], ensure_ascii=False) + "\n")


def ledger_row(id8: str, status: str, reasons: list[str], metrics: dict,
               card_ids: list[str]) -> dict:
    return {
        "recording_id": id8,
        "status": status,
        "reason": reasons,
        "metrics": metrics,
        "card_ids": card_ids,
        "masked": True,
        "refined_at": system_date(),
    }


# ── 통화 처리 ───────────────────────────────────────────────────────────────
def process_call(id8: str, lexicon: dict, fixes: dict, sector_of_screen: dict,
                 tau_logprob: float, llm_fn=_claude_cli, model: str = LLM_MODEL):
    """단일 통화 처리. 반환: (ledger_row, card_entry|None, refined_archive)."""
    call = load_call(id8)
    if call is None:
        return None, None, None
    metrics = call["metrics"]

    # 1) 자동 게이트
    gate_reasons = gate(metrics, tau_logprob)

    # L1 마스킹 + 보정 준비(게이트 탈락도 아카이브는 마스킹 보존)
    fixed_text, l1_corr = apply_fixes(call["text"], fixes)
    masked_text, mask_events = mask_all(fixed_text)
    verified = extract_screen_nos(fixed_text, lexicon)

    # 마스킹된 role 태깅 줄
    masked_lines = []
    for ln in call["lines"]:
        line_fixed, _ = apply_fixes(ln["text"], fixes)
        line_masked, _ = mask_all(line_fixed)
        role = ln["role"] or "미상"
        masked_lines.append(f"[{role}] {line_masked}")

    archive = {
        "recording_id": id8,
        "full_recording_id": call["recording_id"],
        "metrics": metrics,
        "verified_screen_nos": verified,
        "mask_events": mask_events,
        "original_masked": masked_lines,
        "corrections": list(l1_corr),
        "segments": [
            {"start_ms": s.get("start_ms"), "end_ms": s.get("end_ms"),
             "role": s.get("role"), "avg_logprob": s.get("avg_logprob"),
             "text": mask_all(apply_fixes(s.get("text", ""), fixes)[0])[0]}
            for s in call["segments"]
        ],
        "refined_lines": None,
    }

    if gate_reasons:
        row = ledger_row(id8, "excluded", gate_reasons, metrics, [])
        return row, None, archive

    # 2) L2 정제(LLM)
    lowconf = [s.get("text", "") for s in call["segments"]
               if isinstance(s.get("avg_logprob"), (int, float))
               and s["avg_logprob"] < LOWCONF_LINE_TAU]
    lowconf = [mask_all(apply_fixes(x, fixes)[0])[0] for x in lowconf]
    prompt = build_prompt(masked_lines, verified,
                          lexicon_candidates(fixed_text, lexicon), lowconf)

    try:
        out = call_llm(prompt, llm_fn=llm_fn, model=model)
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"[llm_error] {id8}: {e}\n")
        row = ledger_row(id8, "excluded", ["llm_error"], metrics, [])
        return row, None, archive

    verdict = out.get("verdict") or {}
    indexable = bool(verdict.get("indexable", False))
    llm_corr = [c for c in (out.get("corrections") or []) if isinstance(c, dict)]
    archive["corrections"] = list(l1_corr) + llm_corr
    archive["refined_lines"] = out.get("role_fixed_lines") or []

    all_cards = normalize_cards(out.get("cards"), id8, verified, sector_of_screen)
    # 색인 자격: verdict.indexable & 카드 resolved & clarity=clear & answer 존재
    idx_cards = [c for c in all_cards
                 if indexable and c["resolved"] and c["clarity"] == "clear" and c["answer"]]

    card_entry = {
        "recording_id": id8,
        "cards": all_cards,
        "corrections": archive["corrections"],
        "verdict": {"indexable": indexable,
                    "reason": verdict.get("reason", "")},
    }

    if idx_cards:
        row = ledger_row(id8, "indexed", ["ok"], metrics,
                         [c["id"] for c in idx_cards])
        card_entry["indexed_card_ids"] = [c["id"] for c in idx_cards]
    else:
        reason = [verdict.get("reason") or "unresolved"]
        reason = [r if r in VALID_REASONS else "unresolved" for r in reason]
        row = ledger_row(id8, "excluded", reason, metrics, [])
        card_entry["indexed_card_ids"] = []

    return row, card_entry, archive


# ── 파일럿 선정(결정적) ──────────────────────────────────────────────────────
def all_ids() -> list[str]:
    return sorted(p.name[:8] for p in AICC_DIR.glob("*.v3det.json"))


def select_pilot(tau_logprob: float = DEFAULT_TAU_LOGPROB) -> list[str]:
    """대표 20건 결정적 선정: 게이트 탈락 예상 5 + role_false 3 + 장통화 4 + 중간 8."""
    calls = []
    for id8 in all_ids():
        c = load_call(id8)
        if c:
            calls.append((id8, c["metrics"]))

    picked: list[str] = []

    def take(pool, n):
        """pool에서 아직 안 뽑힌 항목을 앞에서부터 최대 n개 추가."""
        added = 0
        for id8 in pool:
            if added >= n:
                break
            if id8 not in picked:
                picked.append(id8)
                added += 1

    # 버킷1: 게이트 탈락 예상(chars<200 or avg<tau) 5건 — id 정렬 앞순
    gate_fail = sorted(id8 for id8, m in calls
                       if m["chars"] < MIN_CHARS or m["avg_logprob"] < tau_logprob)
    take(gate_fail, 5)
    # 버킷2: role_resolved=false 3건
    role_false = sorted(id8 for id8, m in calls if not m["role_resolved"])
    take(role_false, 3)
    # 버킷3: 장통화 상위 4건(segments desc, tie: id asc)
    long_calls = [id8 for id8, m in sorted(calls, key=lambda x: (-x[1]["segments"], x[0]))]
    take(long_calls, 4)
    # 버킷4: 중간 길이 8건(chars 중앙 대역, id 정렬)
    by_chars = sorted(calls, key=lambda x: x[1]["chars"])
    lo = len(by_chars) // 2 - 8
    mid = sorted(id8 for id8, _ in by_chars[max(0, lo):lo + 16])
    take(mid, 8)

    # 20건 미달 시 나머지에서 id 정렬로 채움
    if len(picked) < 20:
        for id8, _ in sorted(calls):
            if id8 not in picked:
                picked.append(id8)
            if len(picked) >= 20:
                break
    return picked[:20]


# ── 리포트 ──────────────────────────────────────────────────────────────────
def _esc(s) -> str:
    return html.escape(str(s if s is not None else ""))


def build_report(ledger: dict, cards: dict, out_path: pathlib.Path = REPORT_PATH) -> dict:
    from collections import Counter
    ids = sorted(ledger)
    indexed = [i for i in ids if ledger[i]["status"] == "indexed"]
    excluded = [i for i in ids if ledger[i]["status"] == "excluded"]
    reason_counts = Counter()
    for i in excluded:
        for r in ledger[i]["reason"]:
            reason_counts[r] += 1
    total_cards = sum(len(cards.get(i, {}).get("cards", [])) for i in ids)
    indexed_cards = sum(len(ledger[i]["card_ids"]) for i in indexed)
    total_masks = 0  # 마스킹 집계는 아카이브 기준(리포트 재생성시 근사)

    rows = []
    for i in ids:
        L = ledger[i]
        c = cards.get(i, {})
        corr = c.get("corrections", [])
        corr_html = "".join(
            f"<tr><td>{_esc(x.get('from'))}</td><td>{_esc(x.get('to'))}</td>"
            f"<td>{_esc(x.get('reason'))}</td></tr>" for x in corr
        ) or "<tr><td colspan=3 class=dim>보정 없음</td></tr>"
        cards_html = ""
        for cd in c.get("cards", []):
            badge = "indexed" if cd["id"] in L["card_ids"] else "excluded"
            cards_html += (
                f"<div class='card {badge}'><div class='cid'>{_esc(cd['id'])} "
                f"<span class='pill'>{badge}</span></div>"
                f"<div><b>Q.</b> {_esc(cd.get('issue'))}</div>"
                f"<div class='dim'>구어: {_esc(cd.get('issue_colloquial'))}</div>"
                f"<div><b>A.</b> {_esc(cd.get('answer'))}</div>"
                f"<div class='meta'>화면 {_esc(', '.join(cd.get('screen_nos') or []) or '-')} · "
                f"부문 {_esc(cd.get('sector_guess') or '-')} · "
                f"{_esc(cd.get('clarity'))} · resolved={_esc(cd.get('resolved'))}</div>"
                f"<div class='ev'>근거: {_esc(cd.get('evidence'))}</div></div>"
            )
        m = L["metrics"]
        rows.append(
            f"<details class='call {L['status']}'><summary>"
            f"<span class='pill {L['status']}'>{L['status']}</span> "
            f"<b>{_esc(i)}</b> · {_esc(','.join(L['reason']))} · "
            f"{m['chars']}자 · logprob {m['avg_logprob']} · seg {m['segments']} · "
            f"role_resolved={m['role_resolved']}</summary>"
            f"<div class='body'><table class='diff'><tr><th>from</th><th>to</th><th>근거</th></tr>"
            f"{corr_html}</table>{cards_html or '<div class=dim>카드 없음</div>'}</div></details>"
        )

    reason_html = "".join(
        f"<tr><td>{_esc(r)}</td><td>{n}</td></tr>"
        for r, n in sorted(reason_counts.items(), key=lambda x: -x[1])
    ) or "<tr><td colspan=2 class=dim>-</td></tr>"

    doc = f"""<!doctype html><html lang=ko><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>AICC 파일럿 정제 리포트</title><style>
:root{{color-scheme:light dark}}
body{{font:14px/1.6 system-ui,'Malgun Gothic',sans-serif;margin:0;padding:24px;
 background:#0f1115;color:#e6e8eb}}
@media(prefers-color-scheme:light){{body{{background:#f6f7f9;color:#1a1d22}}}}
h1{{font-size:20px;margin:0 0 4px}}.sub{{color:#8b93a1;margin-bottom:20px}}
.grid{{display:flex;flex-wrap:wrap;gap:12px;margin-bottom:20px}}
.kpi{{background:#1a1e26;border:1px solid #2a2f3a;border-radius:10px;padding:12px 16px;min-width:120px}}
@media(prefers-color-scheme:light){{.kpi{{background:#fff;border-color:#e2e5ea}}}}
.kpi .n{{font-size:24px;font-weight:700}}.kpi .l{{color:#8b93a1;font-size:12px}}
table{{border-collapse:collapse;width:100%;margin:8px 0;font-size:13px}}
th,td{{border:1px solid #2a2f3a;padding:5px 8px;text-align:left;vertical-align:top}}
@media(prefers-color-scheme:light){{th,td{{border-color:#e2e5ea}}}}
th{{background:#1a1e26}}@media(prefers-color-scheme:light){{th{{background:#eef1f5}}}}
.dim{{color:#8b93a1}}
.call{{border:1px solid #2a2f3a;border-radius:8px;margin:8px 0;padding:8px 12px;background:#161a21}}
@media(prefers-color-scheme:light){{.call{{background:#fff;border-color:#e2e5ea}}}}
.call summary{{cursor:pointer}}.call .body{{padding-top:10px}}
.pill{{font-size:11px;padding:1px 7px;border-radius:10px;background:#333}}
.pill.indexed{{background:#1f7a3f;color:#fff}}.pill.excluded{{background:#8a3b3b;color:#fff}}
.card{{border-left:3px solid #2a2f3a;padding:6px 10px;margin:8px 0;background:#12151b;border-radius:0 6px 6px 0}}
@media(prefers-color-scheme:light){{.card{{background:#f2f4f7}}}}
.card.indexed{{border-left-color:#1f7a3f}}.card.excluded{{border-left-color:#8a3b3b}}
.cid{{font-family:monospace;font-size:12px;color:#8b93a1;margin-bottom:4px}}
.meta,.ev{{font-size:12px;color:#8b93a1;margin-top:3px}}
</style></head><body>
<h1>AICC 상담 녹취 파일럿 정제 리포트</h1>
<div class=sub>생성 {_esc(system_date())} · 판정 대장 {len(ids)}건 · PII 마스킹 적용(masked=true)</div>
<div class=grid>
 <div class=kpi><div class=n>{len(ids)}</div><div class=l>처리 통화</div></div>
 <div class=kpi><div class=n>{len(indexed)}</div><div class=l>indexed(반영)</div></div>
 <div class=kpi><div class=n>{len(excluded)}</div><div class=l>excluded(미반영)</div></div>
 <div class=kpi><div class=n>{total_cards}</div><div class=l>생성 카드</div></div>
 <div class=kpi><div class=n>{indexed_cards}</div><div class=l>색인 카드</div></div>
</div>
<h2>미반영 사유별 집계</h2>
<table><tr><th>사유코드</th><th>건수</th></tr>{reason_html}</table>
<h2>통화별 상세 (보정 diff · 카드 미리보기)</h2>
{''.join(rows)}
</body></html>"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(doc, encoding="utf-8")
    return {"total": len(ids), "indexed": len(indexed), "excluded": len(excluded),
            "reason_counts": dict(reason_counts), "total_cards": total_cards,
            "indexed_cards": indexed_cards}


# ── 메인 ────────────────────────────────────────────────────────────────────
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="AICC 상담 녹취 정제·카드 생성(로컬 전용)")
    ap.add_argument("--limit", type=int, default=None, help="처리 통화 수 제한")
    ap.add_argument("--ids", default=None, help="특정 id8 콤마구분")
    ap.add_argument("--pilot", action="store_true", help="대표 20건 결정적 선정 처리")
    ap.add_argument("--force", action="store_true", help="캐시 존재해도 재정제")
    ap.add_argument("--report-only", action="store_true",
                    help="캐시·대장만으로 리포트 재생성")
    ap.add_argument("--tau-logprob", type=float, default=DEFAULT_TAU_LOGPROB)
    ap.add_argument("--model", default=LLM_MODEL)
    args = ap.parse_args(argv)

    ledger = load_ledger()
    cards = json.loads(CARDS_PATH.read_text(encoding="utf-8")) if CARDS_PATH.exists() else {}

    if args.report_only:
        summary = build_report(ledger, cards)
        print(f"[report-only] {json.dumps(summary, ensure_ascii=False)}", file=sys.stderr)
        print(f"리포트: {REPORT_PATH}")
        return 0

    if not LEXICON_PATH.exists():
        print(f"용어사전 없음: {LEXICON_PATH} — build_aicc_lexicon.py 먼저 실행",
              file=sys.stderr)
        return 2
    lexicon = json.loads(LEXICON_PATH.read_text(encoding="utf-8"))
    sector_of_screen = {}  # screen_no → sector (lexicon엔 title만 — 상속은 title 기반 생략)
    fixes = ensure_fixes_file()

    # 대상 선정
    if args.ids:
        targets = [x.strip() for x in args.ids.split(",") if x.strip()]
    elif args.pilot:
        targets = select_pilot(args.tau_logprob)
    else:
        targets = all_ids()
        if args.limit:
            targets = targets[:args.limit]

    REFINED_DIR.mkdir(parents=True, exist_ok=True)
    processed, skipped, llm_calls = 0, 0, 0
    for id8 in targets:
        if id8 in cards and not args.force and id8 in ledger:
            skipped += 1
            continue
        call = load_call(id8)
        will_call = call is not None and not gate(call["metrics"], args.tau_logprob)
        row, card_entry, archive = process_call(
            id8, lexicon, fixes, sector_of_screen, args.tau_logprob, model=args.model)
        if row is None:
            print(f"[skip] {id8}: 입력 파일 없음", file=sys.stderr)
            continue
        if will_call:
            llm_calls += 1
        ledger[row["recording_id"]] = row
        if card_entry is not None:
            cards[id8] = card_entry
        if archive is not None:
            (REFINED_DIR / f"{id8}.json").write_text(
                json.dumps(archive, ensure_ascii=False, indent=1), encoding="utf-8")
        processed += 1
        print(f"[{row['status']}] {id8} reason={row['reason']} "
              f"cards={len(card_entry['cards']) if card_entry else 0}", file=sys.stderr)

    CARDS_PATH.write_text(json.dumps(cards, ensure_ascii=False, indent=1), encoding="utf-8")
    write_ledger(ledger)
    summary = build_report(ledger, cards)

    print(f"\n처리 {processed} · 스킵 {skipped} · LLM호출 {llm_calls}", file=sys.stderr)
    print(f"대장 집계: {json.dumps(summary, ensure_ascii=False)}")
    print(f"산출물: {CARDS_PATH.name}, {LEDGER_PATH.name}, "
          f"aicc_refined/, {REPORT_PATH.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
