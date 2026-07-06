"""
PowerBASE 청크 → Upstash Vector 업서트 + api/_static.py 생성.

전제: Upstash 콘솔에서 인덱스를 다음 설정으로 생성해 둘 것 —
  Type: Hybrid  ·  Dense: BAAI/bge-m3(내장 임베딩)  ·  Sparse: BM25

  export UPSTASH_VECTOR_REST_URL=... UPSTASH_VECTOR_REST_TOKEN=...
  python deploy/online/ingest.py            # 업서트 + _static.py
  python deploy/online/ingest.py --static   # _static.py만 재생성(업서트 생략)
"""
from __future__ import annotations
import os
import sys
import json
import pathlib
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
DATA = HERE / "demo_data"
BATCH = 100

URL = os.environ.get("UPSTASH_VECTOR_REST_URL", "").rstrip("/")
TOKEN = os.environ.get("UPSTASH_VECTOR_REST_TOKEN", "")


def post(path: str, body):
    req = urllib.request.Request(
        f"{URL}{path}", data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def write_static():
    meta = json.load(open(DATA / "meta.json", encoding="utf-8"))
    sectors = json.load(open(DATA / "sectors.json", encoding="utf-8"))
    out = HERE / "api" / "_static.py"
    out.write_text(
        '"""ingest.py가 demo_data에서 생성 — 직접 수정 금지."""\n'
        f"META = {meta!r}\n\nSECTORS = {sectors!r}\n", encoding="utf-8")
    print(f"[ingest] wrote {out}")


def main():
    write_static()
    if "--static" in sys.argv:
        return
    if not URL or not TOKEN:
        sys.exit("[ingest] UPSTASH_VECTOR_REST_URL / TOKEN 환경변수가 필요합니다")
    chunks = [json.loads(l) for l in open(DATA / "chunks.jsonl", encoding="utf-8")]
    total = 0
    for i in range(0, len(chunks), BATCH):
        batch = [{"id": c["id"], "data": c["embed_text"],
                  "metadata": {k: c[k] for k in
                               ("screen_id", "screen_no", "title", "source_url", "sector",
                                "sector_path", "scope_key", "chunk_type", "section_path",
                                "path_str", "term", "text")}}
                 for c in chunks[i:i + BATCH]]
        post("/upsert-data", batch)
        total += len(batch)
        print(f"[ingest] {total}/{len(chunks)}", end="\r", flush=True)
    info = post("/info", {})
    print(f"\n[ingest] 완료 — 콘솔 벡터 수: {info.get('result', {}).get('vectorCount')}")


if __name__ == "__main__":
    main()
