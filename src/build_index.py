"""
청크(JSONL) → 로컬 벡터 인덱스(FAISS) + BM25 (하이브리드 검색용).
전부 로컬·오픈소스. 외부 API 없음.

사용:
  python src/build_index.py                 # data/chunks.jsonl → data/index/
"""
from __future__ import annotations
import json
import pickle

import faiss
from rank_bm25 import BM25Okapi

from rag_common import load_chunks, embed, tokenize_ko, INDEX_DIR, EMBED_MODEL


def main():
    chunks = load_chunks()
    if not chunks:
        raise SystemExit("no chunks — run to_chunks.py first")
    texts = [c["embed_text"] for c in chunks]

    # 1) 밀집 임베딩 → FAISS (정규화 내적 = 코사인 유사도)
    vecs = embed(texts)
    dim = int(vecs.shape[1])
    index = faiss.IndexFlatIP(dim)
    index.add(vecs)

    # 2) 희소 BM25 (한국어 토크나이저)
    bm25 = BM25Okapi([tokenize_ko(t) for t in texts])

    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    faiss.write_index(index, str(INDEX_DIR / "dense.faiss"))
    with open(INDEX_DIR / "bm25.pkl", "wb") as f:
        pickle.dump(bm25, f)
    with open(INDEX_DIR / "chunks.json", "w", encoding="utf-8") as f:
        json.dump(chunks, f, ensure_ascii=False)
    # 매뉴얼(화면/업무)·부문 분포 통계 + 기존 게이트(τ) 보존 — τ는 코퍼스 변경 시
    # calibrate_threshold.py --write 재보정이 릴리스 게이트
    manuals: dict[str, int] = {}
    sectors: dict[str, int] = {}
    for c in chunks:
        m = c.get("manual") or "화면"
        manuals[m] = manuals.get(m, 0) + 1
        if c.get("sector"):
            sectors[c["sector"]] = sectors.get(c["sector"], 0) + 1
    meta = {"embed_model": EMBED_MODEL, "dim": dim, "count": len(chunks),
            "manuals": manuals, "sectors": sectors}
    meta_path = INDEX_DIR / "meta.json"
    if meta_path.exists():
        with open(meta_path, encoding="utf-8") as f:
            prev = json.load(f)
        if "gate" in prev:
            meta["gate"] = prev["gate"]
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False)

    print(f"[build_index] indexed {len(chunks)} chunks  dim={dim}  model={EMBED_MODEL}")
    print(f"[build_index] wrote {INDEX_DIR}/ (dense.faiss, bm25.pkl, chunks.json, meta.json)")


if __name__ == "__main__":
    main()
