"""문서 목차(TOC) 청크 생성 — 검색리콜개선_계획.md ③ (온라인 데모 전용, 로컬 실행 도구).

"X화면 사용법을 단계별로" 같은 문서 단위 질의의 착지점: 화면/업무 문서당 1청크
(제목 + 화면번호·TR 별칭 + 섹션/단계 목차). 상담은 Q&A 단위라 대상 아님.

  .venv/bin/python deploy/online/gen_toc_chunks.py          # → data/chunks_toc.jsonl + 통계
  .venv/bin/python deploy/online/gen_toc_chunks.py --stats  # 미기록

업서트는 ingest_real.py 연결 로드(증분 오프셋)로 — 실데이터 반출 승인(break-glass) 필요.
"""
from __future__ import annotations
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SRC = ROOT / "data" / "chunks.jsonl"
OUT = ROOT / "data" / "chunks_toc.jsonl"
EMBED_CAP = 2000


def build_docs() -> dict:
    """chunks.jsonl → 문서별 {meta, outline} (화면/업무만, 원본 순서 유지)."""
    docs: dict[str, dict] = {}
    for line in open(SRC, encoding="utf-8"):
        c = json.loads(line)
        if c.get("manual") not in ("화면", "업무"):
            continue
        d = docs.setdefault(c["screen_id"], {
            "screen_id": c["screen_id"], "title": c.get("title", ""),
            "screen_no": c.get("screen_no", ""), "manual": c["manual"],
            "sector": c.get("sector", ""), "sector_path": c.get("sector_path", []),
            "source_url": c.get("source_url", ""),
            "sections": {},          # 1레벨 섹션 → [2레벨 항목...] (등장순)
        })
        sp = c.get("section_path") or []
        if len(sp) >= 2:
            sec = d["sections"].setdefault(sp[1], [])
            if len(sp) >= 3 and sp[2] not in sec:
                sec.append(sp[2])
    return docs


def toc_chunk(d: dict) -> dict | None:
    if not d["sections"]:
        return None
    no = str(d["screen_no"] or "").strip()
    alias = f" (화면번호 {no} · TR{no} · TR-{no})" if no else ""
    parts = []
    for sec, subs in d["sections"].items():
        parts.append(sec + (": " + ", ".join(subs[:12]) if subs else ""))
    outline = " / ".join(parts)
    head = f"[{d['manual']}/{d['sector']}] " if d["sector"] else f"[{d['manual']}] "
    embed = f"{head}{d['title']}{alias} 목차: {outline}"
    text = (f"{d['title']}{alias} — 이 문서의 구성\n" +
            "\n".join(f"► {p}" for p in parts))
    return {
        "id": f"toc:{d['screen_id']}",
        "manual": d["manual"], "sector": d["sector"], "sector_path": d["sector_path"],
        "screen_id": d["screen_id"], "screen_no": d["screen_no"],
        "title": d["title"], "source_url": d["source_url"],
        "chunk_type": "overview",
        "section_path": ["문서 목차"],
        "path_str": f"{d['manual']} > {d['sector']} > {d['title']} 목차",
        "term": "",
        "text": text[:3000],
        "embed_text": embed[:EMBED_CAP],
    }


def main():
    docs = build_docs()
    chunks = [t for t in (toc_chunk(d) for d in docs.values()) if t]
    by_man = {}
    for c in chunks:
        by_man[c["manual"]] = by_man.get(c["manual"], 0) + 1
    print(f"문서 {len(docs)}건 → 목차 청크 {len(chunks)}건 {by_man}")
    lens = sorted(len(c["embed_text"]) for c in chunks)
    print(f"embed 길이 p50={lens[len(lens)//2]} max={lens[-1]}")
    # 골든 스모크 — 스윕 실패 사례(Q32) 화면이 목차 청크를 갖는지
    vip = [c for c in chunks if "VIP수수료율지정" in c["title"]]
    assert vip and "화면번호 1613" in vip[0]["embed_text"], "VIP수수료율지정 목차 골든 불일치"
    assert all(c["id"].startswith("toc:") and c["sector_path"] for c in chunks)
    print("\n[표본] " + vip[0]["embed_text"][:180])
    if "--stats" in sys.argv:
        print("(--stats: 미기록)")
        return
    with OUT.open("w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    print(f"\n[toc] {len(chunks)}청크 → {OUT}")


if __name__ == "__main__":
    main()
