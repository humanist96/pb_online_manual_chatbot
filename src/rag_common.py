"""
RAG 공용 헬퍼 (로컬·오픈소스 전용).
  - 로컬 임베딩 모델 로딩 (기본 BGE-M3, EMBED_MODEL 로 교체 가능)
  - 한국어 친화 토크나이저 (BM25용: 음절 unigram + bigram)
  - 청크 로딩

환경변수:
  EMBED_MODEL   임베딩 모델 (기본 BAAI/bge-m3; 경량 대안: jhgan/ko-sroberta-multitask)
  EMBED_DEVICE  cpu(기본) | cuda
"""
from __future__ import annotations
import os
import re
import json
import pathlib

INDEX_DIR = pathlib.Path("data/index")
CHUNKS_PATH = "data/chunks.jsonl"
# 기본은 경량 한국어 모델(약 440MB). 고정밀이 필요하면 EMBED_MODEL=BAAI/bge-m3 로 교체.
EMBED_MODEL = os.environ.get("EMBED_MODEL", "jhgan/ko-sroberta-multitask")
EMBED_DEVICE = os.environ.get("EMBED_DEVICE", "cpu")


def load_chunks(path: str = CHUNKS_PATH) -> list[dict]:
    return [json.loads(l) for l in open(path, encoding="utf-8")]


_embedder = None


def get_embedder():
    global _embedder
    if _embedder is None:
        from sentence_transformers import SentenceTransformer
        print(f"[rag] loading embedder: {EMBED_MODEL} ({EMBED_DEVICE})", flush=True)
        _embedder = SentenceTransformer(EMBED_MODEL, device=EMBED_DEVICE)
    return _embedder


def embed(texts, normalize: bool = True):
    """텍스트 → (N, d) float32 정규화 임베딩 (코사인=내적)."""
    model = get_embedder()
    vecs = model.encode(
        list(texts),
        normalize_embeddings=normalize,
        convert_to_numpy=True,
        show_progress_bar=False,
        batch_size=32,
    )
    return vecs.astype("float32")


_TOK = re.compile(r"[0-9A-Za-z]+|[가-힣]+")


def tokenize_ko(text: str) -> list[str]:
    """한국어 BM25 토크나이저: 한글은 음절 unigram+bigram, 영숫자는 소문자 토큰."""
    toks: list[str] = []
    for run in _TOK.findall(text):
        if "가" <= run[0] <= "힣":  # 한글 음절
            toks.append(run)
            for i in range(len(run) - 1):
                toks.append(run[i:i + 2])
        else:
            toks.append(run.lower())
    return toks
