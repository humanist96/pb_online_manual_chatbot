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
import hashlib

HERE = pathlib.Path(__file__).resolve().parent
DATA = HERE / "demo_data"
BATCH = 100
PUBLIC_DATASET_ID = "powerbase-public-synthetic-v2"
PUBLIC_CLASSIFICATION = "PUBLIC_SYNTHETIC"
PUBLIC_SCHEMA_VERSION = 2
PUBLIC_CORPUS_SHA256 = "450c97fefdc004fc1620850e6c99a90c2204dbc7ffa2f9a40bd7a7a50fcdb469"
PUBLIC_CHUNK_COUNT = 832
PUBLIC_SCREEN_COUNT = 64
PUBLIC_DEPLOY_FLAG = "--approve-public-deploy"
PUBLIC_DEPLOY_ENV = "PB_APPROVE_PUBLIC_DEPLOY"
PUBLIC_DEPLOY_CONFIRMATION = "I_ACKNOWLEDGE_PUBLIC_SYNTHETIC_DEPLOY"

URL = os.environ.get("UPSTASH_VECTOR_REST_URL", "").rstrip("/")
TOKEN = os.environ.get("UPSTASH_VECTOR_REST_TOKEN", "")


def post(path: str, body):
    req = urllib.request.Request(
        f"{URL}{path}", data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def require_public_deploy(argv: list[str] | None = None,
                          environ: dict[str, str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    env = os.environ if environ is None else environ
    if (PUBLIC_DEPLOY_FLAG not in args
            or env.get(PUBLIC_DEPLOY_ENV) != PUBLIC_DEPLOY_CONFIRMATION):
        raise SystemExit(
            "[ingest] 공개 index 업로드 중단: "
            f"{PUBLIC_DEPLOY_FLAG} 및 {PUBLIC_DEPLOY_ENV}={PUBLIC_DEPLOY_CONFIRMATION}이 필요합니다.")


def _bundle_sha256(chunks: bytes, sectors: bytes, questions: bytes) -> str:
    framed = (b"chunks.jsonl\0" + chunks
              + b"sectors.json\0" + sectors
              + b"questions.json\0" + questions)
    return hashlib.sha256(framed).hexdigest()


def _collect_screen_ids(nodes: list[dict]) -> set[str]:
    ids: set[str] = set()
    for node in nodes:
        ids.update(str(screen.get("id")) for screen in node.get("screens", [])
                   if screen.get("id"))
        ids.update(_collect_screen_ids(node.get("children", [])))
    return ids


def load_public_data(data_dir: pathlib.Path | None = None):
    data = DATA if data_dir is None else pathlib.Path(data_dir)
    meta = json.loads((data / "meta.json").read_text(encoding="utf-8"))
    sectors_raw = (data / "sectors.json").read_bytes()
    questions_raw = (data / "questions.json").read_bytes()
    chunks_raw = (data / "chunks.jsonl").read_bytes()
    sectors = json.loads(sectors_raw)
    questions = json.loads(questions_raw)
    chunks = [json.loads(line) for line in chunks_raw.decode("utf-8").splitlines() if line]

    if (meta.get("demo") is not True
            or meta.get("dataset_id") != PUBLIC_DATASET_ID
            or meta.get("classification") != PUBLIC_CLASSIFICATION
            or meta.get("schema_version") != PUBLIC_SCHEMA_VERSION):
        raise SystemExit("[ingest] 공개 경로에는 PUBLIC_SYNTHETIC 데이터만 허용됩니다")
    if (len(chunks) != PUBLIC_CHUNK_COUNT
            or meta.get("count") != PUBLIC_CHUNK_COUNT):
        raise SystemExit("[ingest] 승인된 합성 청크 건수와 다릅니다")
    actual_corpus_sha256 = hashlib.sha256(chunks_raw).hexdigest()
    if (actual_corpus_sha256 != PUBLIC_CORPUS_SHA256
            or meta.get("corpus_sha256") != PUBLIC_CORPUS_SHA256):
        raise SystemExit("[ingest] corpus_sha256 불일치 — demo_data를 다시 생성하세요")
    if (hashlib.sha256(sectors_raw).hexdigest() != meta.get("sectors_sha256")
            or hashlib.sha256(questions_raw).hexdigest() != meta.get("questions_sha256")
            or _bundle_sha256(chunks_raw, sectors_raw, questions_raw)
            != meta.get("bundle_sha256")):
        raise SystemExit("[ingest] 정적 산출물 번들 해시가 불일치합니다")

    screen_ids = {c.get("screen_id") for c in chunks}
    if (None in screen_ids or len(screen_ids) != PUBLIC_SCREEN_COUNT
            or _collect_screen_ids(sectors.get("tree", [])) != screen_ids):
        raise SystemExit("[ingest] 화면 allowlist가 승인된 합성 corpus와 다릅니다")
    for c in chunks:
        if (c.get("dataset_id") != PUBLIC_DATASET_ID
                or c.get("classification") != PUBLIC_CLASSIFICATION
                or c.get("schema_version") != PUBLIC_SCHEMA_VERSION
                or c.get("source_url") != "#demo"
                or c.get("manual") != "화면"
                or (c.get("sector_path") or [None])[0] != "화면"):
            raise SystemExit(f"[ingest] 허용되지 않은 청크: {c.get('id', '?')}")
    if len(questions) != PUBLIC_SCREEN_COUNT:
        raise SystemExit("[ingest] 승인된 합성 질문 건수와 다릅니다")
    for q in questions:
        if (q.get("dataset_id") != PUBLIC_DATASET_ID
                or q.get("classification") != PUBLIC_CLASSIFICATION
                or q.get("schema_version") != PUBLIC_SCHEMA_VERSION
                or q.get("corpus_sha256") != PUBLIC_CORPUS_SHA256
                or q.get("m") != "화면"
                or (q.get("sp") or [None])[0] != "화면"
                or q.get("sid") not in screen_ids):
            raise SystemExit("[ingest] 질문뱅크 데이터셋 불일치")
    return meta, sectors, questions, chunks


def build_batch(chunks: list[dict], meta: dict) -> list[dict]:
    return [{"id": c["id"], "data": c["embed_text"],
             "metadata": {
                 **{k: c[k] for k in
                    ("dataset_id", "classification", "schema_version", "manual",
                     "screen_id", "screen_no", "title", "source_url", "sector",
                     "sector_path", "scope_key", "chunk_type", "section_path",
                     "path_str", "term", "text")},
                 "corpus_sha256": meta["corpus_sha256"],
             }} for c in chunks]


def verify_remote(meta: dict, sample_question: str) -> None:
    expected = {
        "dataset_id": PUBLIC_DATASET_ID,
        "classification": PUBLIC_CLASSIFICATION,
        "schema_version": PUBLIC_SCHEMA_VERSION,
        "corpus_sha256": PUBLIC_CORPUS_SHA256,
        "source_url": "#demo",
        "manual": "화면",
    }
    filter_expr = " AND ".join(
        f"{key} = '{value}'" if isinstance(value, str) else f"{key} = {value}"
        for key, value in expected.items())
    result = post("/query-data", {
        "data": sample_question, "topK": 1, "includeMetadata": True,
        "queryMode": "DENSE", "filter": filter_expr,
    }).get("result", [])
    metadata = result[0].get("metadata", {}) if result else {}
    if not result or any(metadata.get(key) != value for key, value in expected.items()):
        raise SystemExit("[ingest] 원격 합성 index 검증 실패 — 배포하지 마세요")


def write_static(meta, sectors, questions):
    out = HERE / "api" / "_static.py"
    out.write_text(
        '"""ingest.py가 demo_data에서 생성 — 직접 수정 금지."""\n'
        f"META = {meta!r}\n\nSECTORS = {sectors!r}\n\nQUESTIONS = {questions!r}\n",
        encoding="utf-8")
    print(f"[ingest] wrote {out}")


def main():
    meta, sectors, questions, chunks = load_public_data()
    write_static(meta, sectors, questions)
    if "--static" in sys.argv:
        return
    require_public_deploy()
    if not URL or not TOKEN:
        sys.exit("[ingest] UPSTASH_VECTOR_REST_URL / TOKEN 환경변수가 필요합니다")
    total = 0
    for i in range(0, len(chunks), BATCH):
        batch = build_batch(chunks[i:i + BATCH], meta)
        post("/upsert-data", batch)
        total += len(batch)
        print(f"[ingest] {total}/{len(chunks)}", end="\r", flush=True)
    verify_remote(meta, questions[0]["q"])
    info = post("/info", {})
    print(f"\n[ingest] 완료 — 콘솔 벡터 수: {info.get('result', {}).get('vectorCount')}")


if __name__ == "__main__":
    main()
