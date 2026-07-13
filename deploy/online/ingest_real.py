"""
실제 매뉴얼 청크(data/chunks.jsonl) → Upstash Vector 업서트 (재개 가능·일별 분할).

⚠️ RESTRICTED_REAL 사내 자료 외부 반출 도구. 공개 데모 접근키는 안전장치가 아니다.
별도 승인된 break-glass 작업에서만 사용하며 진행 오프셋은 .ingest_state에 저장한다.

  # 아래 CLI 플래그와 환경 확인문을 모두 지정해야만 실행된다.
  export PB_ALLOW_REAL_DATA_EGRESS=I_ACKNOWLEDGE_REAL_DATA_EGRESS
  export UPSTASH_PRIVATE_VECTOR_REST_URL=...
  export UPSTASH_PRIVATE_VECTOR_REST_TOKEN=...
  python deploy/online/ingest_real.py --allow-real-data-egress --limit 9000
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
# 상담매뉴얼(parse_counsel_xls.py 산출)은 기존 뒤에 연결 — .ingest_state 오프셋이
# chunks.jsonl 끝에 멈춰 있으므로 다음 실행이 상담분만 증분 업서트한다(기존 불변 전제).
SRC_COUNSEL = ROOT / "data" / "chunks_counsel.jsonl"
# 문서 목차 청크(gen_toc_chunks.py 산출) — 동일한 증분 오프셋 방식으로 뒤에 연결.
SRC_TOC = ROOT / "data" / "chunks_toc.jsonl"
STATE = HERE / ".ingest_state"
BATCH = 100

BREAK_GLASS_FLAG = "--allow-real-data-egress"
BREAK_GLASS_ENV = "PB_ALLOW_REAL_DATA_EGRESS"
BREAK_GLASS_CONFIRMATION = "I_ACKNOWLEDGE_REAL_DATA_EGRESS"
REAL_DATASET_ID = "powerbase-private-real-v1"
REAL_CLASSIFICATION = "RESTRICTED_REAL"

# 공개 합성 index의 자격증명을 재사용하지 못하도록 별도 env를 강제한다.
URL = os.environ.get("UPSTASH_PRIVATE_VECTOR_REST_URL", "").rstrip("/")
TOKEN = os.environ.get("UPSTASH_PRIVATE_VECTOR_REST_TOKEN", "")


def post(path: str, body):
    req = urllib.request.Request(
        f"{URL}{path}", data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())


def require_break_glass(argv: list[str] | None = None,
                        environ: dict[str, str] | None = None) -> None:
    """실데이터 파일을 읽기 전에 명시적 이중 승인을 요구한다."""
    args = list(sys.argv[1:] if argv is None else argv)
    env = os.environ if environ is None else environ
    if (BREAK_GLASS_FLAG not in args
            or env.get(BREAK_GLASS_ENV) != BREAK_GLASS_CONFIRMATION):
        raise SystemExit(
            "[real] 차단됨: 실데이터 외부 반출 승인이 없습니다. "
            f"{BREAK_GLASS_FLAG}와 {BREAK_GLASS_ENV}={BREAK_GLASS_CONFIRMATION}을 "
            "모두 명시해야 합니다.")


def load_chunks() -> list[dict]:
    out = [json.loads(l) for l in open(SRC, encoding="utf-8")]
    if SRC_COUNSEL.exists():
        out += [json.loads(l) for l in open(SRC_COUNSEL, encoding="utf-8")]
    if SRC_TOC.exists():
        out += [json.loads(l) for l in open(SRC_TOC, encoding="utf-8")]
    return out


def main(argv: list[str] | None = None, environ: dict[str, str] | None = None):
    args = list(sys.argv[1:] if argv is None else argv)
    require_break_glass(args, environ)
    if "--static-only" in args:
        raise SystemExit(
            "[real] --static-only는 제거됐습니다. 실데이터는 공개 api/_static.py를 "
            "생성할 수 없습니다.")
    print("[real] BREAK-GLASS 승인 확인 — RESTRICTED_REAL 데이터 처리를 시작합니다.",
          flush=True)
    chunks = load_chunks()
    if not URL or not TOKEN:
        sys.exit("[real] UPSTASH_PRIVATE_VECTOR_REST_URL / TOKEN 필요")
    if "--reset" in args:
        post("/reset", {})
        STATE.write_text("0")
        print("[real] 인덱스 초기화 완료(기존 벡터 전부 삭제)")
        return
    limit = int(args[args.index("--limit") + 1]) if "--limit" in args else 9000
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
                               "dataset_id": REAL_DATASET_ID,
                               "classification": REAL_CLASSIFICATION,
                               "manual": c.get("manual", ""),
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
