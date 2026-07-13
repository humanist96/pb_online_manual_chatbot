"""검증된 질문뱅크 생성 도구 (로컬 실행 전용 — Vercel 배포 대상 아님).

data/chunks.jsonl 에서 질문 후보를 추출하고, 로컬 하이브리드 검색(FAISS+BM25)으로
자기-검색(self-retrieval) 검증을 통과한 후보만 채택해 deploy/online/api/_questions.py 를
생성한다. 온라인 임베더(text-embedding-3-small)와 다른 로컬 임베더(ko-sroberta)를 쓰므로
대리(proxy) 검증이며, 실데이터 재검증은 계획 2단계에서 수행한다.

실행(repo 루트에서):
    .venv/bin/python deploy/online/gen_questions.py                    # 온라인 _questions.py 생성
    .venv/bin/python deploy/online/gen_questions.py --out data/questions.json  # 사내 webapp용 JSON

검증 기준(둘 다 통과):
  ① 후보 질문으로 하이브리드 검색(alpha=0.5, top-5) 시 top-3 안에 자기 screen_id 존재
  ② top-1 dense 코사인 ≥ τ  (data/index/meta.json gate.tau_cos, 없으면 0.55)
"""
from __future__ import annotations
import os
import sys
import json
import argparse
import pathlib

# repo 루트로 이동(상대경로 data/... 관례) + src 임포트 경로
ROOT = pathlib.Path(__file__).resolve().parents[2]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT / "src"))

import numpy as np  # noqa: E402

from rag_common import embed, tokenize_ko, INDEX_DIR  # noqa: E402
from chatbot import load_index, _minmax  # noqa: E402

ALPHA = 0.5
OUT_PATH = ROOT / "deploy" / "online" / "api" / "_questions.py"


def _load_tau() -> float:
    """meta.json gate 의 cosine τ. tau_cos 없으면 0.55."""
    try:
        meta = json.load(open(INDEX_DIR / "meta.json", encoding="utf-8"))
        gate = meta.get("gate") or {}
        v = gate.get("tau_cos")
        if v is not None:
            return float(v)
    except Exception:
        pass
    return 0.55


def build_candidates(chunks: list[dict]) -> list[dict]:
    """qa 청크 + 업무매뉴얼 템플릿 질문 후보."""
    cands: list[dict] = []
    seen_q: set[str] = set()

    # ① qa 청크 (화면매뉴얼)
    for c in chunks:
        if c.get("chunk_type") != "qa":
            continue
        sp = c.get("section_path") or []
        if not sp:
            continue
        q = (sp[-1] or "").strip()
        if not q.endswith("?"):
            continue
        if not (10 <= len(q) <= 60):
            continue
        if q in seen_q:
            continue
        seen_q.add(q)
        cands.append({"q": q, "sid": c.get("screen_id", ""), "t": c.get("title", ""),
                      "sp": c.get("sector_path") or [], "m": c.get("manual", "화면")})

    # ② 업무매뉴얼 보충 — 문서(screen_id)당 템플릿 질문 1개
    seen_pm: set[str] = set()
    for c in chunks:
        if c.get("manual") != "업무":
            continue
        sid = c.get("screen_id", "")
        if not sid or sid in seen_pm:
            continue
        seen_pm.add(sid)
        title = (c.get("title") or "").strip()
        if not title or len(title) > 25:
            continue
        q = f"{title} 업무 처리 절차를 알려줘"
        if q in seen_q:
            continue
        seen_q.add(q)
        cands.append({"q": q, "sid": sid, "t": title,
                      "sp": c.get("sector_path") or [], "m": "업무"})
    return cands


def validate(cands: list[dict], tau: float) -> list[dict]:
    """배치 임베딩 후 후보별 자기-검색 검증."""
    index, bm25, chunks = load_index()
    n = len(chunks)
    sid_of = [c.get("screen_id", "") for c in chunks]

    print(f"[gen] 임베딩 {len(cands)}건 (배치)…", flush=True)
    qvecs = embed([c["q"] for c in cands])  # (N,768) 정규화

    passed: list[dict] = []
    for i, cand in enumerate(cands):
        qv = qvecs[i:i + 1]
        dscore, didx = index.search(qv, n)
        dense = np.zeros(n, dtype="float32")
        dense[didx[0]] = dscore[0]
        dense_top = float(dscore[0][0])  # top-1 dense 코사인
        sparse = np.array(bm25.get_scores(tokenize_ko(cand["q"])), dtype="float32")
        combined = ALPHA * _minmax(dense) + (1 - ALPHA) * _minmax(sparse)
        top3 = np.argsort(-combined)[:3]
        top3_sids = {sid_of[j] for j in top3}
        if cand["sid"] in top3_sids and dense_top >= tau:
            passed.append(cand)
        if (i + 1) % 200 == 0:
            print(f"[gen]   {i + 1}/{len(cands)} 검증…", flush=True)
    return passed


def write_output(entries: list[dict], out_path: pathlib.Path):
    """.json 확장자면 JSON 배열, 아니면 온라인 배포용 파이썬 모듈(QUESTIONS)로 저장."""
    recs = [{"q": e["q"], "sid": e["sid"], "t": e["t"], "sp": e["sp"], "m": e["m"]}
            for e in entries]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.suffix.lower() == ".json":
        out_path.write_text(json.dumps(recs, ensure_ascii=False, indent=1),
                            encoding="utf-8")
        return
    lines = ['"""gen_questions.py가 생성 — 직접 수정 금지."""', "", "QUESTIONS = ["]
    for r in recs:
        lines.append("    " + repr(r) + ",")
    lines.append("]")
    lines.append("")
    out_path.write_text("\n".join(lines), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description="검증된 질문뱅크 생성")
    ap.add_argument("--out", default=str(OUT_PATH),
                    help="산출 경로(.json이면 JSON 배열, 그 외 파이썬 모듈). "
                         "기본은 온라인 배포용 _questions.py")
    args = ap.parse_args()
    out_path = pathlib.Path(args.out)
    if not out_path.is_absolute():
        out_path = ROOT / out_path

    tau = _load_tau()
    print(f"[gen] cosine τ = {tau}", flush=True)
    chunks = [json.loads(l) for l in open("data/chunks.jsonl", encoding="utf-8")]
    cands = build_candidates(chunks)
    n_screen = sum(1 for c in cands if c["m"] == "화면")
    n_biz = sum(1 for c in cands if c["m"] == "업무")
    print(f"[gen] 후보 {len(cands)}건 (화면 {n_screen} / 업무 {n_biz})", flush=True)

    passed = validate(cands, tau)
    write_output(passed, out_path)

    p_screen = sum(1 for c in passed if c["m"] == "화면")
    p_biz = sum(1 for c in passed if c["m"] == "업무")

    def pct(a, b):
        return f"{(100.0 * a / b):.1f}%" if b else "n/a"

    print("\n===== 질문뱅크 생성 결과 =====")
    print(f" 전체 : {len(passed)}/{len(cands)} 통과 ({pct(len(passed), len(cands))})")
    print(f" 화면 : {p_screen}/{n_screen} 통과 ({pct(p_screen, n_screen)})")
    print(f" 업무 : {p_biz}/{n_biz} 통과 ({pct(p_biz, n_biz)})")
    print(f" 산출 : {out_path}")


if __name__ == "__main__":
    main()
