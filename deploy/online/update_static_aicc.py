"""api/_static.py 스코프 트리에 상담사례(AICC 녹취) 부문을 반영한다 — 로컬 실행 도구.

⚠️ 배포 제외(Vercel 번들에 포함되지 않아도 무방한 오프라인 전처리 도구). 실데이터
청크(chunks_aicc.jsonl)는 읽기만 하며 네트워크 호출을 하지 않는다.

동작: chunks_aicc.jsonl에서 관측된 상담사례 부문을 모아 SECTORS['tree']에 루트
노드 "상담사례"를 추가/갱신하고, META['count']/META['sectors']에 AICC 청크 수를
반영한다. 기존 화면/업무/상담 서브트리는 바이트 무변경으로 보존한다(_static.py를
import해 값을 읽고 원 직렬화 포맷 그대로 재직렬화 → git diff는 상담사례 추가분만).
재실행 멱등: 이미 상담사례 노드가 있으면 갱신한다.

  python deploy/online/update_static_aicc.py --dry-run   # diff 미리보기(미기록)
  python deploy/online/update_static_aicc.py             # _static.py 갱신
"""
from __future__ import annotations
import argparse
import difflib
import importlib.util
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DEFAULT_STATIC = HERE / "api" / "_static.py"
DEFAULT_CHUNKS = ROOT / "data" / "chunks_aicc.jsonl"

AICC_ROOT = "상담사례"


def load_chunks(path: pathlib.Path) -> list[dict]:
    if not path.exists():
        raise SystemExit(
            f"[aicc-static] 청크 파일이 없습니다: {path}\n"
            "  parse_aicc.py로 data/chunks_aicc.jsonl을 먼저 생성하세요.")
    return [json.loads(l) for l in path.open(encoding="utf-8") if l.strip()]


def load_static(path: pathlib.Path):
    """_static.py를 import해 (원본 텍스트, 첫 줄 docstring, META, SECTORS, QUESTIONS 유무)."""
    if not path.exists():
        raise SystemExit(f"[aicc-static] _static.py가 없습니다: {path}")
    text = path.read_text(encoding="utf-8")
    # 첫 줄(docstring)은 재직렬화 시 그대로 보존한다.
    docstring = text.split("\n", 1)[0]
    spec = importlib.util.spec_from_file_location("_aicc_static_target", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # sys.modules에 등록하지 않아 매 호출 신선
    has_q = hasattr(mod, "QUESTIONS")
    return text, docstring, mod.META, mod.SECTORS, (mod.QUESTIONS if has_q else None)


def observed_sectors(chunks: list[dict]) -> list[str]:
    """상담사례 청크 sector_path에서 관측된 부문을 최초 등장 순으로 수집."""
    seen: dict[str, None] = {}
    for c in chunks:
        sp = c.get("sector_path") or []
        if len(sp) >= 2 and sp[1]:
            seen.setdefault(str(sp[1]), None)
    return list(seen)


def apply_aicc(meta: dict, sectors: dict, chunks: list[dict]) -> dict:
    """META/SECTORS를 in-place 갱신하고 요약을 돌려준다(멱등)."""
    aicc_count = len(chunks)
    sect_names = observed_sectors(chunks)
    children = [{"name": name, "screens": []} for name in sect_names]

    # META['count']: 기존 상담사례분을 뺀 기준값 + 이번 AICC 수(재실행 멱등).
    prev_aicc = int((meta.get("sectors") or {}).get(AICC_ROOT, 0))
    base_count = int(meta.get("count", 0)) - prev_aicc
    meta["count"] = base_count + aicc_count
    # 분포에 상담사례 건수 추가/갱신(dict 삽입 순서 보존 → 신규는 맨 뒤 append).
    meta.setdefault("sectors", {})[AICC_ROOT] = aicc_count

    # SECTORS 트리: 상담사례 루트 노드 추가/갱신(기존 위치 보존, 신규는 맨 뒤 append).
    node = {"name": AICC_ROOT, "count": aicc_count,
            "children": children, "screens": []}
    tree = sectors.setdefault("tree", [])
    for i, r in enumerate(tree):
        if r.get("name") == AICC_ROOT:
            tree[i] = node
            break
    else:
        tree.append(node)

    return {"aicc_count": aicc_count, "meta_count": meta["count"],
            "sectors": sect_names}


def render_static(docstring: str, meta: dict, sectors: dict,
                  questions=None) -> str:
    """원 _static.py 직렬화 포맷 그대로 재직렬화(docstring 보존, repr 라운드트립)."""
    out = f"{docstring}\nMETA = {meta!r}\n\nSECTORS = {sectors!r}\n"
    if questions is not None:
        out += f"\nQUESTIONS = {questions!r}\n"
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="상담사례(AICC) 스코프를 _static.py에 반영")
    ap.add_argument("--chunks", type=pathlib.Path, default=DEFAULT_CHUNKS,
                    help="data/chunks_aicc.jsonl 경로")
    ap.add_argument("--static", type=pathlib.Path, default=DEFAULT_STATIC,
                    help="갱신 대상 api/_static.py 경로")
    ap.add_argument("--dry-run", action="store_true",
                    help="파일을 쓰지 않고 unified diff만 출력")
    args = ap.parse_args(argv)

    chunks = load_chunks(args.chunks)
    text, docstring, meta, sectors, questions = load_static(args.static)
    summary = apply_aicc(meta, sectors, chunks)
    new_text = render_static(docstring, meta, sectors, questions)

    if new_text == text:
        print(f"[aicc-static] 변경 없음(이미 최신) — 상담사례 {summary['aicc_count']}건, "
              f"부문 {summary['sectors']}")
        return 0

    if args.dry_run:
        diff = difflib.unified_diff(
            text.splitlines(keepends=True), new_text.splitlines(keepends=True),
            fromfile=str(args.static), tofile=f"{args.static} (수정 후)")
        sys.stdout.writelines(diff)
        print(f"\n[aicc-static] --dry-run: 미기록. 상담사례 {summary['aicc_count']}건, "
              f"부문 {summary['sectors']}, META.count={summary['meta_count']}")
        return 0

    args.static.write_text(new_text, encoding="utf-8")
    print(f"[aicc-static] {args.static} 갱신 — 상담사례 {summary['aicc_count']}건, "
          f"부문 {summary['sectors']}, META.count={summary['meta_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
