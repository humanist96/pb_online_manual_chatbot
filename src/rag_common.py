"""
RAG 공용 헬퍼 (로컬·오픈소스 전용).
  - 로컬 임베딩 모델 로딩 (기본 BGE-M3, EMBED_MODEL 로 교체 가능)
  - 한국어 친화 토크나이저 (BM25용: 음절 unigram + bigram)
  - 청크 로딩

환경변수:
  EMBED_MODEL    임베딩 모델 (기본 BAAI/bge-m3; 경량 대안: jhgan/ko-sroberta-multitask)
  EMBED_DEVICE   cpu(기본) | cuda
  RERANK_ENABLE  auto(기본, 모델 있으면 사용)|on|off — 관련도 게이트용 리랭커
  RERANK_MODEL   BAAI/bge-reranker-v2-m3 (기본)
"""
from __future__ import annotations
import os
import re
import json
import math
import pathlib

INDEX_DIR = pathlib.Path("data/index")
CHUNKS_PATH = "data/chunks.jsonl"
# 기본은 경량 한국어 모델(약 440MB). 고정밀이 필요하면 EMBED_MODEL=BAAI/bge-m3 로 교체.
EMBED_MODEL = os.environ.get("EMBED_MODEL", "jhgan/ko-sroberta-multitask")
EMBED_DEVICE = os.environ.get("EMBED_DEVICE", "cpu")
RERANK_MODEL = os.environ.get("RERANK_MODEL", "BAAI/bge-reranker-v2-m3")
RERANK_ENABLE = os.environ.get("RERANK_ENABLE", "auto")  # auto|on|off

# ── 관련도 게이트 기본값 (calibrate_threshold.py 로 재보정 → meta.json["gate"]) ──
# "안녕"처럼 무관한 질의를 걸러내기 위한 임계치. 절대(원)점수 기준이라 의미가 있음.
DEFAULT_GATE = {
    "tau_rerank": 0.50,   # 리랭커 신뢰도 임계 (sigmoid 0..1) — 리랭커 사용 시
    "tau_cos": 0.42,      # 코사인 임계 — 리랭커 없을 때 폴백
    "cos_floor": 0.30,    # 코사인 후보 컷(coarse): 이 미만은 리랭크 대상에서도 제외
    "rerank_pool": 12,    # 코사인 상위 몇 개를 리랭크할지
}


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


_reranker = None


def get_reranker():
    """CrossEncoder 리랭커 로드 (실패 시 None → 코사인 폴백). RERANK_ENABLE=off 면 비활성.
    bge-reranker-v2-m3 는 sentence-transformers CrossEncoder 로 로딩 — 추가 패키지 불필요."""
    global _reranker
    if RERANK_ENABLE == "off":
        return None
    if _reranker is None:
        try:
            from sentence_transformers import CrossEncoder
            print(f"[rag] loading reranker: {RERANK_MODEL} ({EMBED_DEVICE})", flush=True)
            _reranker = CrossEncoder(RERANK_MODEL, device=EMBED_DEVICE, max_length=512)
        except Exception as e:  # 미다운로드/오프라인 → 폴백
            print(f"[rag] reranker 사용 불가({e}) → 코사인 게이트로 폴백", flush=True)
            _reranker = False
    return _reranker or None


def rerank_scores(query: str, texts: list[str]):
    """(query, text) 쌍의 보정 관련도 점수 [0..1] (sigmoid). 리랭커 없으면 None.
    calibrate 와 런타임이 동일 변환(sigmoid)을 쓰므로 임계치가 일관됨."""
    ce = get_reranker()
    if not ce or not texts:
        return None
    raw = ce.predict([(query, t) for t in texts], show_progress_bar=False)
    return [1.0 / (1.0 + math.exp(-float(s))) for s in raw]


def load_gate(meta: dict | None = None) -> dict:
    """DEFAULT_GATE 에 meta.json['gate'] 오버라이드를 병합한 게이트 설정."""
    g = dict(DEFAULT_GATE)
    if meta and isinstance(meta.get("gate"), dict):
        g.update(meta["gate"])
    return g


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
