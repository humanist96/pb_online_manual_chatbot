"""AICC 상담 녹취 판정 대장·정제 캐시 → 표준 청크(JSONL) — 온라인 데모 전용 로컬 도구(배포 제외).

AICC녹취_추가_계획.md §3(스키마)·§4(청킹)·§4.3(재현율 장치)·§8(파이프라인) 2단계 구현.
LLM 불요·**결정적**(같은 입력 → 같은 바이트). refine_aicc.py가 만든 대장·캐시만 읽는다.

  data/aicc_ledger.jsonl (판정 대장: 통화 1건=1행)
  data/aicc_cards.json   (정제 캐시: recording_id 키, cards[])
    → status=="indexed" 행의 card_ids 카드만 → 표준 청크
    → data/chunks_aicc.jsonl  (`--out`, id 정렬)

경계: 표준 라이브러리만. 이 도구는 deploy/online/ "로컬 실행 도구 — 배포 제외" 전처리
전용이며 런타임 답변 경로(none|ollama)에는 일절 관여하지 않는다. 산출물은 data/ 하위(git 제외).

  .venv/bin/python deploy/online/parse_aicc.py
  .venv/bin/python deploy/online/parse_aicc.py --out /tmp/preview.jsonl
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
from parse_counsel_xls import mask_pii  # noqa: E402 — PII 마스킹 재사용(수정 금지)
import refine_aicc as R  # noqa: E402 — 발화체 마스킹(mask_all) 재사용(수정 금지)

DATA_DIR = ROOT / "data"
LEDGER_PATH = DATA_DIR / "aicc_ledger.jsonl"
CARDS_PATH = DATA_DIR / "aicc_cards.json"
CHUNKS_PATH = DATA_DIR / "chunks.jsonl"        # 로컬 코퍼스(부문명 대조 소스)
OUT_DEFAULT = DATA_DIR / "chunks_aicc.jsonl"

MANUAL = "상담사례"
EMBED_CAP = 2000            # 임베딩 입력 절단 관례(parse_counsel_xls와 동일)
TITLE_CAP = 40              # 제목에 담는 이슈 앞부분 길이
SECTION_CAP = 120           # section_path 이슈 요약 길이


def one_line(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


def remask(s: str) -> str:
    """발화체 인명·전화(refine_aicc) + 카드/계좌/식별번호(mask_pii) 재적용."""
    masked, _ = R.mask_all(s or "")
    return masked


# ── 로컬 코퍼스 부문명 로딩 ──────────────────────────────────────────────────
def load_corpus_sectors(path: pathlib.Path = CHUNKS_PATH) -> set[str]:
    """로컬 청크에 실존하는 부문명 집합. sector_guess 검증에 사용(없으면 빈 집합)."""
    sectors: set[str] = set()
    if not path.exists():
        return sectors
    with path.open(encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                c = json.loads(ln)
            except json.JSONDecodeError:
                continue
            s = c.get("sector")
            if s:
                sectors.add(s)
    return sectors


# ── 카드 → 청크 ──────────────────────────────────────────────────────────────
def card_to_chunk(card: dict, valid_sectors: set[str],
                  warn: bool = True) -> dict | None:
    """정제 카드 → 표준 15필드 청크. 이중 방어(resolved·clarity) 실패 시 None.

    출력 직전 PII 마스킹을 재적용해 무변화를 확인한다(변화 시 stderr 경고 + 마스킹본 출력).
    """
    # 이중 방어: 대장이 indexed여도 카드 레벨에서 재확인(§4.1-1)
    if not card.get("resolved") or card.get("clarity") != "clear":
        return None
    answer = (card.get("answer") or "").strip()
    if not answer:
        return None

    cid = card["id"]
    issue = (card.get("issue") or "").strip()
    issue_colloquial = (card.get("issue_colloquial") or "").strip()
    screen_nos = [str(s) for s in (card.get("screen_nos") or []) if str(s).strip()]

    # 부문: sector_guess가 실제 로컬 코퍼스 부문명과 일치할 때만 사용
    sector = card.get("sector_guess") or ""
    if sector not in valid_sectors:
        sector = ""
    sector_path = ["상담사례", sector] if sector else ["상담사례"]

    screen_no = screen_nos[0] if screen_nos else ""
    issue_summary = one_line(issue)[:SECTION_CAP]
    section_path = ["상담사례", issue_summary]

    title = "상담사례: " + one_line(issue)[:TITLE_CAP]

    text = f"Q. {issue}\nA. {answer}"

    prefix = f"[상담사례/{sector}] " if sector else "[상담사례] "
    embed = prefix
    if screen_nos:
        embed += "화면번호 " + " ".join(screen_nos) + " "
    embed += f"{one_line(issue)} : {one_line(answer)}"
    if issue_colloquial:
        embed += f" (고객 표현: {one_line(issue_colloquial)})"

    # ── PII 방어: 출력 직전 재마스킹 무변화 확인 ──
    text_m = remask(text)
    if text_m != text:
        if warn:
            sys.stderr.write(f"[pii] {cid}: text 잔존 마스킹 발생 — 마스킹본 출력\n")
        text = text_m
    embed_m = remask(embed)
    if embed_m != embed:
        if warn:
            sys.stderr.write(f"[pii] {cid}: embed_text 잔존 마스킹 발생 — 마스킹본 출력\n")
        embed = embed_m

    return {
        "id": cid,
        "screen_id": "",                       # 내부 문서코드 미상 — 빈 값(억지 매핑 금지)
        "code": "",
        "aup": "",
        "screen_no": screen_no,                # 카드 screen_nos 첫 값(단말 입력 화면번호)
        "title": title,
        "source_url": "",
        "manual": MANUAL,                      # 제4 콘텐츠: 상담사례
        "sector": sector,
        "sector_path": sector_path,
        "chunk_type": "qa",
        "section_path": section_path,
        "path_str": " > ".join(section_path),
        "term": "",
        "text": text,
        "embed_text": embed[:EMBED_CAP],
    }


# ── 대장 + 캐시 → 청크 ──────────────────────────────────────────────────────
def build_chunks(ledger: dict, cards: dict, valid_sectors: set[str],
                 warn: bool = True) -> tuple[list[dict], dict]:
    """status=="indexed" 행의 card_ids 카드만 청크로. 반환: (청크 정렬본, 통계)."""
    stats = {"indexed_rows": 0, "cards_seen": 0, "chunks": 0, "card_excluded": 0}
    chunks: list[dict] = []
    for rid in sorted(ledger):
        row = ledger[rid]
        if row.get("status") != "indexed":
            continue
        stats["indexed_rows"] += 1
        by_id = {c["id"]: c for c in cards.get(rid, {}).get("cards", [])}
        for cid in row.get("card_ids", []):
            card = by_id.get(cid)
            if card is None:
                sys.stderr.write(f"[warn] {rid}: 대장 card_id {cid} 캐시에 없음 — 건너뜀\n")
                continue
            stats["cards_seen"] += 1
            chunk = card_to_chunk(card, valid_sectors, warn=warn)
            if chunk is None:
                stats["card_excluded"] += 1
                continue
            chunks.append(chunk)
    chunks.sort(key=lambda c: c["id"])
    stats["chunks"] = len(chunks)
    return chunks, stats


def load_ledger(path: pathlib.Path = LEDGER_PATH) -> dict:
    rows: dict = {}
    if not path.exists():
        return rows
    for ln in path.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        r = json.loads(ln)
        rows[r["recording_id"]] = r
    return rows


def load_cards(path: pathlib.Path = CARDS_PATH) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="AICC 판정 대장·정제 캐시 → 표준 청크(결정적·LLM 불요)")
    ap.add_argument("--out", default=str(OUT_DEFAULT), help="출력 JSONL 경로")
    ap.add_argument("--ledger", default=str(LEDGER_PATH))
    ap.add_argument("--cards", default=str(CARDS_PATH))
    ap.add_argument("--chunks", default=str(CHUNKS_PATH),
                    help="부문명 대조용 로컬 코퍼스")
    args = ap.parse_args(argv)

    ledger = load_ledger(pathlib.Path(args.ledger))
    cards = load_cards(pathlib.Path(args.cards))
    valid_sectors = load_corpus_sectors(pathlib.Path(args.chunks))

    chunks, stats = build_chunks(ledger, cards, valid_sectors)

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")

    print(f"대장 indexed {stats['indexed_rows']}행 · 대상 카드 {stats['cards_seen']} · "
          f"색인 청크 {stats['chunks']} · 카드 레벨 제외 {stats['card_excluded']} · "
          f"부문명 대조 {len(valid_sectors)}종", file=sys.stderr)
    print(f"[aicc] {len(chunks)}청크 → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
