"""
실제 매뉴얼 청크(data/chunks.jsonl) → Upstash Vector 업서트 (재개 가능·일별 분할).

⚠️ 사내 자료 외부 반출 — 접근키 게이트(DEMO_ACCESS_KEY)와 함께 사용할 것(사용자 승인 2026-07-06).
무료 한도(일 10K 업데이트) 안에서 나눠 올린다. 진행 오프셋은 .ingest_state에 저장.

  export UPSTASH_VECTOR_REST_URL=... UPSTASH_VECTOR_REST_TOKEN=...
  python deploy/online/ingest_real.py --reset          # 최초 1회: 기존(합성) 전부 삭제
  python deploy/online/ingest_real.py --limit 9000     # 오늘 분량 업서트 (기본 9000)
  python deploy/online/ingest_real.py --static-only    # _static.py만 재생성
"""
from __future__ import annotations
import os
import sys
import json
import pathlib
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SRC = ROOT / "data" / "chunks.jsonl"
STATE = HERE / ".ingest_state"
BATCH = 100

URL = os.environ.get("UPSTASH_VECTOR_REST_URL", "").rstrip("/")
TOKEN = os.environ.get("UPSTASH_VECTOR_REST_TOKEN", "")


def post(path: str, body):
    req = urllib.request.Request(
        f"{URL}{path}", data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())


def load_chunks() -> list[dict]:
    return [json.loads(l) for l in open(SRC, encoding="utf-8")]


def write_static(chunks: list[dict]):
    """실데이터 기준 meta/sectors를 api/_static.py로 — webapp의 트리 빌더 로직 이식."""
    tree: dict = {}
    samples, seen = [], set()
    for c in chunks:
        segs = list(c.get("sector_path") or ["미분류"])
        children, node = tree, None
        for s in segs:
            node = children.setdefault(s, {"name": s, "count": 0, "children": {}, "screens": {}})
            node["count"] += 1
            children = node["children"]
        scr = node["screens"].setdefault(c["screen_id"], {"id": c["screen_id"],
                                                          "title": c["title"], "count": 0})
        scr["count"] += 1
        if (c.get("chunk_type") == "qa" and c["screen_id"] not in seen and len(samples) < 8):
            q = (c.get("section_path") or [""])[-1].strip()
            if q.endswith("?") and 10 <= len(q) <= 55:
                samples.append(q)
                seen.add(c["screen_id"])

    def ser(d):
        return [{"name": n["name"], "count": n["count"], "children": ser(n["children"]),
                 "screens": sorted(n["screens"].values(), key=lambda x: x["id"])}
                for n in d.values()]

    meta = {"embed_model": "upstash-hybrid/text-embedding-3-small", "dim": 1536,
            "count": len(chunks), "demo": False, "reranker": None,
            "sectors": {s: t["count"] for s, t in tree.items()},
            "samples": samples,
            "gate": {"mode": "cosine", "tau": 0.70, "tau_rerank": 0.70, "tau_cos": 0.70}}
    out = HERE / "api" / "_static.py"
    out.write_text('"""ingest_real.py가 data/chunks.jsonl에서 생성 — 직접 수정 금지."""\n'
                   f"META = {meta!r}\n\nSECTORS = {{'tree': {ser(tree)!r}}}\n", encoding="utf-8")
    print(f"[real] wrote {out}  (count={len(chunks)}, sectors={len(tree)})")


def main():
    chunks = load_chunks()
    write_static(chunks)
    if "--static-only" in sys.argv:
        return
    if not URL or not TOKEN:
        sys.exit("[real] UPSTASH_VECTOR_REST_URL / TOKEN 필요")
    if "--reset" in sys.argv:
        post("/reset", {})
        STATE.write_text("0")
        print("[real] 인덱스 초기화 완료(기존 벡터 전부 삭제)")
        return
    limit = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else 9000
    start = int(STATE.read_text()) if STATE.exists() else 0
    end = min(start + limit, len(chunks))
    if start >= len(chunks):
        print(f"[real] 이미 완료({start}/{len(chunks)})")
        return
    done = start
    for i in range(start, end, BATCH):
        batch = [{"id": c["id"], "data": c["embed_text"],
                  "metadata": {"screen_id": c["screen_id"], "screen_no": c["screen_no"],
                               "title": c["title"], "source_url": c["source_url"],
                               "sector": c.get("sector", ""),
                               "sector_path": c.get("sector_path", []),
                               "scope_key": ">".join((c.get("sector_path") or []) + [c["screen_id"]]),
                               "chunk_type": c["chunk_type"], "section_path": c["section_path"],
                               "path_str": c["path_str"], "term": c["term"], "text": c["text"]}}
                 for c in chunks[i:i + BATCH]]
        post("/upsert-data", batch)
        done = i + len(batch)
        STATE.write_text(str(done))
        print(f"[real] {done}/{len(chunks)}", end="\r", flush=True)
    info = post("/info", {}).get("result", {})
    print(f"\n[real] 오늘 분량 완료 — 진행 {done}/{len(chunks)}, 콘솔 벡터 {info.get('vectorCount')}"
          f"{' (내일 같은 명령으로 이어서)' if done < len(chunks) else ' — 전량 완료!'}")


if __name__ == "__main__":
    main()
