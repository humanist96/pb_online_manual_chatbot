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
    with open(INDEX_DIR / "meta.json", "w", encoding="utf-8") as f:
        json.dump({"embed_model": EMBED_MODEL, "dim": dim, "count": len(chunks)}, f, ensure_ascii=False)

    print(f"[build_index] indexed {len(chunks)} chunks  dim={dim}  model={EMBED_MODEL}")
    print(f"[build_index] wrote {INDEX_DIR}/ (dense.faiss, bm25.pkl, chunks.json, meta.json)")


if __name__ == "__main__":
    main()
