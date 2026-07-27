"""api/_questions.py 질문뱅크에 상담사례(AICC 녹취) 카드 질문을 합류시킨다 — 로컬 실행 도구.

⚠️ 배포 제외(Vercel 번들에 포함되지 않아도 무방한 오프라인 전처리 도구). 실데이터
청크(chunks_aicc.jsonl)와 검증 리포트를 읽기만 하며 네트워크 호출을 하지 않는다.

동작(AICC녹취_추가_계획.md §7-3): chunks_aicc.jsonl의 카드에서 핵심질문(text의 첫
"Q." 줄 — verify_aicc_online.card_query 재사용)을 뽑아 QUESTIONS 엔트리로 만들되,
aicc_verify_report.json의 self_hit 검증에서 miss로 기록된 id는 제외한다(검증 통과분만
편입). 리포트가 없으면 검증 전 편입을 막기 위해 에러로 중단한다.

기존 화면/업무 엔트리는 순서·바이트 무변경으로 보존한다(_questions.py를 import해 값을
읽고 gen_questions.py와 동일한 직렬화 포맷 — 엔트리별 repr 한 줄 — 으로 재기록 →
git diff는 상담사례 추가분만). 재실행 멱등: 기존 m=='상담사례' 엔트리를 모두 제거한
뒤 새 엔트리를 맨 뒤에 append한다.

  python deploy/online/update_questions_aicc.py --dry-run   # 요약만(미기록)
  python deploy/online/update_questions_aicc.py             # _questions.py 갱신
"""
from __future__ import annotations
import argparse
import importlib.util
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DEFAULT_QUESTIONS = HERE / "api" / "_questions.py"
DEFAULT_CHUNKS = ROOT / "data" / "chunks_aicc.jsonl"
DEFAULT_REPORT = ROOT / "data" / "aicc_verify_report.json"

sys.path.insert(0, str(HERE))
from verify_aicc_online import card_query  # noqa: E402  (질문 추출 로직 단일 출처)

AICC_MANUAL = "상담사례"
TITLE_PREFIX = "상담사례: "


def load_chunks(path: pathlib.Path) -> list[dict]:
    if not path.exists():
        raise SystemExit(
            f"[aicc-questions] 청크 파일이 없습니다: {path}\n"
            "  parse_aicc.py로 data/chunks_aicc.jsonl을 먼저 생성하세요.")
    return [json.loads(l) for l in path.open(encoding="utf-8") if l.strip()]


def load_misses(path: pathlib.Path) -> set[str]:
    """검증 리포트의 self_hit miss id 집합. 리포트·검증 부재는 편입 금지(중단)."""
    if not path.exists():
        raise SystemExit(
            f"[aicc-questions] 검증 리포트가 없습니다: {path}\n"
            "  verify_aicc_online.py로 자기-검색 검증을 먼저 통과시키세요"
            "(검증 전 질문뱅크 편입 금지).")
    report = json.loads(path.read_text(encoding="utf-8"))
    for check in report.get("checks") or []:
        if check.get("name") == "self_hit":
            misses = [str(m) for m in (check.get("misses") or [])]
            # verify_aicc_online은 misses를 20건까지만 기록한다 — 잘린 목록으로
            # 편입하면 미검증 카드가 섞이므로 hits/total과 어긋나면 중단.
            hits, total = check.get("hits"), check.get("total")
            if isinstance(hits, int) and isinstance(total, int) \
                    and total - hits != len(misses):
                raise SystemExit(
                    f"[aicc-questions] self_hit misses 목록이 불완전합니다"
                    f"(miss {total - hits}건 중 {len(misses)}건만 기록). "
                    "verify_aicc_online.py를 다시 실행하세요.")
            if not check.get("pass", True):
                print("[aicc-questions] 경고: self_hit 검증이 FAIL 상태입니다 — "
                      "miss 제외분만 편입합니다.", file=sys.stderr)
            return set(misses)
    raise SystemExit(
        f"[aicc-questions] 리포트에 self_hit 검증 결과가 없습니다: {path}")


def load_questions(path: pathlib.Path) -> tuple[str, str, list[dict]]:
    """_questions.py를 import해 (원본 텍스트, 선두 docstring 블록, QUESTIONS)."""
    if not path.exists():
        raise SystemExit(f"[aicc-questions] _questions.py가 없습니다: {path}")
    text = path.read_text(encoding="utf-8")
    docstring = split_docstring(text)
    spec = importlib.util.spec_from_file_location("_aicc_questions_target", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # sys.modules에 등록하지 않아 매 호출 신선
    if not hasattr(mod, "QUESTIONS"):
        raise SystemExit(f"[aicc-questions] QUESTIONS가 없습니다: {path}")
    return text, docstring, list(mod.QUESTIONS)


def split_docstring(text: str) -> str:
    """선두 \"\"\" ... \"\"\" 블록 전체(여러 줄 가능)를 그대로 돌려준다."""
    stripped = text.lstrip()
    if not stripped.startswith('"""'):
        raise SystemExit("[aicc-questions] 선두 docstring(\"\"\")을 찾지 못했습니다.")
    start = text.index('"""')
    end = text.index('"""', start + 3)
    return text[start:end + 3]


def to_entry(chunk: dict) -> dict:
    """AICC 청크 → 질문뱅크 엔트리(키 순서는 gen_questions.py와 동일)."""
    title = str(chunk.get("title") or "")
    if title.startswith(TITLE_PREFIX):
        title = title[len(TITLE_PREFIX):]
    return {"q": card_query(chunk),
            "sid": chunk.get("screen_id") or "",
            "t": title,
            "sp": list(chunk.get("sector_path") or []),
            "m": AICC_MANUAL}


def build_entries(chunks: list[dict], misses: set[str]) -> tuple[list[dict], int]:
    """miss id를 제외한 청크만 엔트리로. (엔트리, 제외 수)"""
    kept = [c for c in chunks if str(c.get("id")) not in misses]
    return [to_entry(c) for c in kept], len(chunks) - len(kept)


def merge(existing: list[dict], entries: list[dict]) -> tuple[list[dict], int]:
    """기존 상담사례 엔트리를 전부 걷어내고 새 엔트리를 맨 뒤에 append(멱등)."""
    others = [e for e in existing if e.get("m") != AICC_MANUAL]
    return others + entries, len(existing) - len(others)


def render_questions(docstring: str, questions: list[dict]) -> str:
    """gen_questions.py와 동일한 직렬화(docstring 보존, 엔트리별 repr 한 줄)."""
    lines = [docstring, "", "QUESTIONS = ["]
    lines += ["    " + repr(e) + "," for e in questions]
    lines += ["]", ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="상담사례(AICC) 카드 질문을 _questions.py 질문뱅크에 편입")
    ap.add_argument("--chunks", type=pathlib.Path, default=DEFAULT_CHUNKS,
                    help="data/chunks_aicc.jsonl 경로")
    ap.add_argument("--report", type=pathlib.Path, default=DEFAULT_REPORT,
                    help="data/aicc_verify_report.json 경로(self_hit misses 제외용)")
    ap.add_argument("--questions", type=pathlib.Path, default=DEFAULT_QUESTIONS,
                    help="갱신 대상 api/_questions.py 경로")
    ap.add_argument("--dry-run", action="store_true",
                    help="파일을 쓰지 않고 요약만 출력")
    args = ap.parse_args(argv)

    chunks = load_chunks(args.chunks)
    misses = load_misses(args.report)
    text, docstring, existing = load_questions(args.questions)

    entries, excluded = build_entries(chunks, misses)
    merged, removed = merge(existing, entries)
    new_text = render_questions(docstring, merged)

    head = "[aicc-questions] --dry-run:" if args.dry_run else "[aicc-questions]"
    print(f"{head} {args.questions}")
    print(f"  카드 {len(chunks)}건 → 편입 {len(entries)}건"
          f"(검증 miss 제외 {excluded}건)")
    print(f"  기존 상담사례 엔트리 제거 {removed}건")
    print(f"  엔트리 수 {len(existing)} → {len(merged)}")

    if new_text == text:
        print("  변경 없음(이미 최신)")
        return 0
    if args.dry_run:
        print("  미기록(--dry-run)")
        return 0

    args.questions.write_text(new_text, encoding="utf-8")
    print("  갱신 완료")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
