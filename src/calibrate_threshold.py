"""
관련도 임계치 τ 보정(calibration) — 데이터로 결정하고 meta.json 에 기록.

원리: 도메인 내(in-domain) 질의와 무관(out-of-domain) 질의의 '최고 신뢰도' 분포를
겹쳐 보고, 무관 질의를 목표 비율(기본 95%) 이상 거부하는 최소 τ 를 고른다.
  - 신뢰도 = 리랭커 점수(sigmoid, 있으면) 또는 코사인 원점수(폴백)
  - 양성(positive): 청크의 용어/Q&A 질문/화면명을 질의로 사용(우리가 이미 보유)
  - 음성(negative): 매뉴얼과 무관한 고정 질의 목록("안녕" 등)

사용:
  python src/calibrate_threshold.py                 # 계산 후 미리보기(쓰기 안 함)
  python src/calibrate_threshold.py --write         # meta.json["gate"] 갱신
  python src/calibrate_threshold.py --target 0.98   # 무관 질의 98% 거부 목표

전부 로컬·오프라인. 외부 API 없음.
"""
from __future__ import annotations
import sys
import json
import pickle

import numpy as np
import faiss

from rag_common import (embed, tokenize_ko, INDEX_DIR, load_gate,
                        rerank_scores, get_reranker)

# 매뉴얼과 무관한 음성 질의 (도메인 밖) — 여기 통과되면 안 됨
OOD_QUERIES = [
    "안녕", "안녕하세요", "반가워", "고마워", "오늘 날씨 어때",
    "점심 뭐 먹지", "라면 끓이는 법", "주말에 뭐 할까", "너 누구야",
    "파이썬으로 웹 크롤러 만드는 법", "축구 경기 결과", "여행 추천해줘",
    "ㅋㅋㅋ", "테스트", "아무거나",
]


def load_index():
    index = faiss.read_index(str(INDEX_DIR / "dense.faiss"))
    with open(INDEX_DIR / "bm25.pkl", "rb") as f:
        bm25 = pickle.load(f)
    with open(INDEX_DIR / "chunks.json", encoding="utf-8") as f:
        chunks = json.load(f)
    with open(INDEX_DIR / "meta.json", encoding="utf-8") as f:
        meta = json.load(f)
    return index, bm25, chunks, meta


def build_positive_queries(chunks: list[dict], limit: int = 120) -> list[str]:
    """도메인 내 질의: Q&A 질문 > 용어(glossary) > 화면명 순으로 골고루 샘플."""
    qa, term, other = [], [], []
    for c in chunks:
        path = c.get("section_path") or []
        if c["chunk_type"] == "qa" and len(path) >= 3:
            qa.append(path[-1])                      # 질문 문장
        elif c["chunk_type"] == "glossary":
            term.append(c.get("term") or (path[-1] if path else ""))
        else:
            other.append(c.get("term") or (path[-1] if path else ""))
    # 균형 샘플 (앞에서부터, 중복 제거)
    seen, out = set(), []
    for bucket in (qa, term, other):
        for s in bucket:
            s = (s or "").strip()
            if len(s) >= 2 and s not in seen:
                seen.add(s); out.append(s)
            if len(out) >= limit:
                return out
    return out


def top_confidence(query, index, bm25, chunks, gate) -> float:
    """질의의 '최고 신뢰도' = 리랭커(있으면) 또는 코사인 상위값. 런타임 search 와 동일 로직."""
    n = len(chunks)
    qv = embed([query])
    dscore, didx = index.search(qv, n)
    dense = np.zeros(n, dtype="float32")
    dense[didx[0]] = dscore[0]
    sparse = np.array(bm25.get_scores(tokenize_ko(query)), dtype="float32")

    def _mm(x):
        lo, hi = float(x.min()), float(x.max())
        return np.zeros_like(x) if hi - lo < 1e-9 else (x - lo) / (hi - lo)

    combined = 0.5 * _mm(dense) + 0.5 * _mm(sparse)
    pool = [int(i) for i in np.argsort(-combined)[:int(gate["rerank_pool"])]]
    rr = rerank_scores(query, [chunks[i]["text"] for i in pool])
    if rr is not None:
        return float(max(rr))
    return float(max(dense[i] for i in pool))


def pick_tau(pos: np.ndarray, neg: np.ndarray, target: float) -> float:
    """음성의 target 비율을 거부하는 최소 τ = 음성 상위(1-target) 분위수 바로 위."""
    if len(neg) == 0:
        return float(np.percentile(pos, 10)) if len(pos) else 0.5
    tau = float(np.quantile(neg, target))          # 음성의 target 분위수
    return round(tau + 1e-3, 4)


def main():
    args = sys.argv[1:]
    write = "--write" in args
    target = 0.95
    if "--target" in args:
        target = float(args[args.index("--target") + 1])

    index, bm25, chunks, meta = load_index()
    gate = load_gate(meta)
    mode = "rerank" if get_reranker() is not None else "cosine"
    print(f"[calibrate] mode={mode}  target(무관 거부율)={target:.0%}", flush=True)

    pos_q = build_positive_queries(chunks)
    print(f"[calibrate] 양성 질의 {len(pos_q)}개, 음성 질의 {len(OOD_QUERIES)}개 평가 중...", flush=True)
    pos = np.array([top_confidence(q, index, bm25, chunks, gate) for q in pos_q])
    neg = np.array([top_confidence(q, index, bm25, chunks, gate) for q in OOD_QUERIES])

    tau = pick_tau(pos, neg, target)
    # 지표
    pos_keep = float((pos >= tau).mean())          # 도메인 내 통과율(재현율)
    neg_reject = float((neg < tau).mean())         # 무관 거부율(정밀도 측면)
    print("\n── 분포 ──")
    print(f"  양성(도메인 내)  min={pos.min():.3f}  중앙={np.median(pos):.3f}  max={pos.max():.3f}")
    print(f"  음성(무관)       min={neg.min():.3f}  중앙={np.median(neg):.3f}  max={neg.max():.3f}")
    print(f"\n  선택 τ = {tau:.4f}  →  도메인 내 통과율 {pos_keep:.0%} · 무관 거부율 {neg_reject:.0%}")
    print("  음성 상위 5 (τ 근처 오탐 후보):",
          ", ".join(f"{q}={s:.2f}" for q, s in
                    sorted(zip(OOD_QUERIES, neg), key=lambda x: -x[1])[:5]))

    if write:
        key = "tau_rerank" if mode == "rerank" else "tau_cos"
        meta.setdefault("gate", {})
        meta["gate"][key] = tau
        with open(INDEX_DIR / "meta.json", "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False)
        print(f"\n[calibrate] meta.json['gate']['{key}'] = {tau} 저장 완료.")
    else:
        print("\n(미리보기 — 적용하려면 --write)")


if __name__ == "__main__":
    main()
