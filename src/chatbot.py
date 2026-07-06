"""
로컬 RAG 챗봇 — 하이브리드 검색(FAISS + BM25) + 로컬 LLM(Ollama).
외부 상용 API 없음. LLM 서버가 없으면 추출형(extractive) 폴백으로 출처 청크를 반환.

환경변수:
  LLM_BACKEND   ollama(기본) | none(추출형 폴백 강제)
  LLM_MODEL     Ollama 모델명 (기본 qwen2.5:7b-instruct; 대안 exaone3.5:7.8b 등)
  OLLAMA_HOST   http://localhost:11434 (기본)
  RAG_TOPK      검색 상위 k (기본 5)
  RAG_ALPHA     하이브리드 가중치 dense↔bm25 (0=BM25만,1=dense만; 기본 0.5)

사용:
  python src/chatbot.py "지점계좌서비스약정등록내역 화면에서 변경사용자 항목은 어디서 확인하나요?"
  python src/chatbot.py            # 대화형(REPL)
"""
from __future__ import annotations
import os
import sys
import json
import pickle

import numpy as np
import faiss

from rag_common import embed, tokenize_ko, INDEX_DIR

TOPK = int(os.environ.get("RAG_TOPK", "5"))
ALPHA = float(os.environ.get("RAG_ALPHA", "0.5"))
LLM_BACKEND = os.environ.get("LLM_BACKEND", "ollama")
LLM_MODEL = os.environ.get("LLM_MODEL", "qwen2.5:7b-instruct")
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")

SYSTEM_PROMPT = (
    "당신은 코스콤 원장시스템(PowerBASE) 온라인 매뉴얼 도우미다. "
    "아래 [컨텍스트]에 있는 내용만 근거로 한국어로 정확히 답한다. "
    "컨텍스트에 근거가 없으면 반드시 '매뉴얼에서 확인되지 않습니다.'라고 답하고 추측하지 않는다. "
    "답변에 사용한 근거마다 문장 끝에 [S1],[S2] 형태의 출처 마커를 붙인다."
)


# ─────────────────────────────── 인덱스 로딩 ─────────────────────────────────

def load_index():
    index = faiss.read_index(str(INDEX_DIR / "dense.faiss"))
    with open(INDEX_DIR / "bm25.pkl", "rb") as f:
        bm25 = pickle.load(f)
    with open(INDEX_DIR / "chunks.json", encoding="utf-8") as f:
        chunks = json.load(f)
    return index, bm25, chunks


def _minmax(x: np.ndarray) -> np.ndarray:
    lo, hi = float(x.min()), float(x.max())
    if hi - lo < 1e-9:
        return np.zeros_like(x)
    return (x - lo) / (hi - lo)


def hybrid_search(query, index, bm25, chunks, k=TOPK, alpha=ALPHA):
    n = len(chunks)
    # dense
    qv = embed([query])
    dscore, didx = index.search(qv, n)
    dense = np.zeros(n, dtype="float32")
    dense[didx[0]] = dscore[0]
    # sparse
    sparse = np.array(bm25.get_scores(tokenize_ko(query)), dtype="float32")
    # 결합 (min-max 정규화 후 가중합)
    combined = alpha * _minmax(dense) + (1 - alpha) * _minmax(sparse)
    order = np.argsort(-combined)[:k]
    return [(chunks[i], float(combined[i])) for i in order]


# ─────────────────────────────── 프롬프트/LLM ───────────────────────────────

def format_source(c: dict) -> str:
    return f"{c['title']}[{c['screen_no']}] · {c['path_str']}"


def build_prompt(query, hits):
    ctx_lines = []
    for i, (c, _) in enumerate(hits, 1):
        ctx_lines.append(f"[S{i}] ({format_source(c)})\n{c['text']}")
    context = "\n\n".join(ctx_lines)
    return (
        f"{SYSTEM_PROMPT}\n\n[컨텍스트]\n{context}\n\n"
        f"[질문] {query}\n\n[답변] (한국어, 근거마다 [S#] 표기)"
    )


def call_ollama(prompt: str) -> str | None:
    try:
        import urllib.request
        req = urllib.request.Request(
            f"{OLLAMA_HOST}/api/generate",
            data=json.dumps({"model": LLM_MODEL, "prompt": prompt, "stream": False}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read()).get("response", "").strip()
    except Exception as e:
        print(f"[chatbot] Ollama 사용 불가({e}) → 추출형 폴백", file=sys.stderr)
        return None


def extractive_answer(hits) -> str:
    """LLM 없이 상위 근거를 출처와 함께 제시(폴백)."""
    lines = ["(로컬 LLM 미연결 — 관련 매뉴얼 근거를 제시합니다.)", ""]
    for i, (c, score) in enumerate(hits, 1):
        lines.append(f"[S{i}] {format_source(c)}")
        lines.append(f"    {c['text']}")
        lines.append("")
    return "\n".join(lines)


# ─────────────────────────────── 응답 파이프라인 ────────────────────────────

def answer(query, index, bm25, chunks):
    hits = hybrid_search(query, index, bm25, chunks)
    body = None
    if LLM_BACKEND == "ollama":
        body = call_ollama(build_prompt(query, hits))
    if not body:
        body = extractive_answer(hits)
    sources = "\n".join(f"  [S{i}] {format_source(c)}" for i, (c, _) in enumerate(hits, 1))
    return f"{body}\n\n[출처]\n{sources}"


def main():
    index, bm25, chunks = load_index()
    if len(sys.argv) > 1:
        q = " ".join(sys.argv[1:])
        print(answer(q, index, bm25, chunks))
        return
    print("PowerBASE 매뉴얼 챗봇 (종료: 빈 줄/Ctrl-D)")
    while True:
        try:
            q = input("\n질문> ").strip()
        except EOFError:
            break
        if not q:
            break
        print(answer(q, index, bm25, chunks))


if __name__ == "__main__":
    main()
