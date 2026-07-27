"""AICC 용어사전 생성 — 로컬 실행 도구(배포 제외).

AICC 상담 녹취 STT 오탈자 보정용 도메인 용어사전(정답 어휘집)을 매뉴얼 코퍼스
(data/chunks.jsonl)에서 추출한다. 상세 배경은 AICC녹취_추가_계획.md §5 L1.
표준 라이브러리만 사용, Upstash·외부 API 호출 없음.

  .venv/bin/python deploy/online/build_aicc_lexicon.py
  .venv/bin/python deploy/online/build_aicc_lexicon.py --chunks data/chunks.jsonl --out data/aicc_lexicon.json

추출 내용:
  · screen_nos — screen_no가 숫자인 청크의 {screen_no: 대표 title} (동일 번호는 첫 값 유지).
  · terms      — chunk_type=="glossary" 청크의 term(공백 제외, 길이 2~40자, dedup).
  · titles     — 고유 화면/업무 title 목록(원문 그대로 dedup — 정규화 없음).
  · seed       — 코드에 고정한 시드 어휘(SEED_TERMS, 확장 가능한 리스트 상수).

산출물은 결정적(같은 입력 → 같은 바이트)이어야 하므로 모든 리스트를 정렬하고
ensure_ascii=False, indent=1로 기록한다.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
DEFAULT_CHUNKS = ROOT / "data" / "chunks.jsonl"
DEFAULT_OUT = ROOT / "data" / "aicc_lexicon.json"

MIN_TERM_LEN = 2
MAX_TERM_LEN = 40

# 확장 가능한 고정 시드 어휘 — 매뉴얼 코퍼스에 드물게 등장하거나 구어체 변형이
# 흔한 핵심 도메인 용어를 수동으로 보강한다.
SEED_TERMS = [
    "PowerBASE",
    "파워베이스",
    "K-Front",
    "케이프론트",
    "코스콤",
    "고객지원센터",
    "미수",
    "반대매매",
    "예탁금이용료",
    "원장",
    "회원사",
]


def load_chunks(path: pathlib.Path):
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


def build_lexicon(chunks_path: pathlib.Path) -> dict:
    screen_nos: dict[str, str] = {}
    terms: set[str] = set()
    titles: set[str] = set()

    for d in load_chunks(chunks_path):
        screen_no = d.get("screen_no") or ""
        if screen_no.isdigit() and screen_no not in screen_nos:
            screen_nos[screen_no] = d.get("title") or ""

        if d.get("chunk_type") == "glossary":
            term = (d.get("term") or "").strip()
            if MIN_TERM_LEN <= len(term) <= MAX_TERM_LEN:
                terms.add(term)

        title = (d.get("title") or "").strip()
        if title:
            titles.add(title)

    screen_nos_sorted = {k: screen_nos[k] for k in sorted(screen_nos, key=int)}

    return {
        "screen_nos": screen_nos_sorted,
        "terms": sorted(terms),
        "titles": sorted(titles),
        "seed": sorted(set(SEED_TERMS)),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--chunks", default=str(DEFAULT_CHUNKS),
                     help="입력 청크 JSONL 경로 (기본: data/chunks.jsonl)")
    ap.add_argument("--out", default=str(DEFAULT_OUT),
                     help="출력 JSON 경로 (기본: data/aicc_lexicon.json)")
    args = ap.parse_args()

    chunks_path = pathlib.Path(args.chunks)
    out_path = pathlib.Path(args.out)

    lexicon = build_lexicon(chunks_path)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(lexicon, f, ensure_ascii=False, indent=1)
        f.write("\n")

    print(
        f"screen_nos={len(lexicon['screen_nos'])} "
        f"terms={len(lexicon['terms'])} "
        f"titles={len(lexicon['titles'])} "
        f"seed={len(lexicon['seed'])}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
