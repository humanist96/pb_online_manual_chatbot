"""
구조화 트리(parse.py) → RAG용 청크 JSONL.

브레드크럼 1개 = 청크 1개. 경로를 임베딩 텍스트(embed_text)에 보존하여
검색 정확도와 출처 표기를 강화한다.

사용:
  python src/to_chunks.py data/html/*.html            # -> data/chunks.jsonl
  python src/to_chunks.py data/html/AC250400.html -o data/chunks.jsonl
"""
from __future__ import annotations
import sys
import json
import glob
import pathlib

from parse import parse_html
from parse_pm import parse_html as parse_html_pm

# 매뉴얼별 부문 매니페스트(crawl_toc.py 산출) — TOC 경로가 브레드크럼 상위 계층
# 전 매뉴얼 확장: sector_path 루트에 매뉴얼 레벨("화면"/"업무")을 둔다
def _load(p):
    f = pathlib.Path(p)
    return json.load(open(f, encoding="utf-8")) if f.exists() else {}

_manifest = _load("data/manifest.json")        # 화면(ST)
_manifest_pm = _load("data/manifest_pm.json")  # 업무(PM)


def sector_of(screen_id: str, manual: str) -> tuple[str, list[str], str]:
    """(부문, [매뉴얼, ...TOC 경로], 문서명). 매니페스트에 없으면 ('', [매뉴얼], '')."""
    mf = _manifest_pm if manual == "업무" else _manifest
    m = mf.get(f"{screen_id}.html")
    if not m:
        return "", [manual], ""
    segs = [s.strip() for s in m["path"].split(">")]
    return segs[0], [manual] + segs, m.get("name", "")


SECTION_TO_TYPE = {
    "화면개요": "overview",
    "화면설명": "description",
    "용어찾기": "glossary",
    "관련화면": "related",
    "질문보기": "qa",
}


def doc_to_chunks(doc: dict, manual: str = "화면") -> list[dict]:
    chunks = []
    sector, sector_path, toc_name = sector_of(doc["screen_id"], manual)
    if manual == "업무" and toc_name:
        doc = {**doc, "title": doc["title"] if len(doc["title"]) > 3 else toc_name}
    for i, bc in enumerate(doc["breadcrumbs"]):
        path = bc["path"]
        text = bc["text"]
        section = path[1] if len(path) > 1 else ""
        ctype = SECTION_TO_TYPE.get(section, "description")
        path_str = " > ".join(path)
        term = path[-1] if len(path) > 2 else section
        chunk = {
            "id": ("pm:" if manual == "업무" else "") + f"{doc['screen_id']}#{i:04d}",
            "screen_id": doc["screen_id"],
            "code": doc["code"],
            "aup": doc["aup"],
            "screen_no": doc["screen_no"],
            "title": doc["title"],
            "source_url": doc["source_url"],
            "manual": manual,                 # 매뉴얼 종류: 화면 | 업무
            "sector": sector,                 # 부문 (scope_hint 분포용)
            "sector_path": sector_path,       # [매뉴얼, ...TOC 경로] — 스코프 루트
            "chunk_type": ctype,
            "section_path": path,
            "path_str": path_str,
            "term": term,
            "text": text,
            # 경로 보존 임베딩 텍스트 — 매뉴얼/부문을 접두해 상위 문맥까지 주입
            "embed_text": (f"[{manual}/{sector}] " if sector else f"[{manual}] ")
                          + f"{path_str} : {text}",
        }
        chunks.append(chunk)
    return chunks


def main():
    args = sys.argv[1:]
    out = "data/chunks.jsonl"
    files = []
    it = iter(args)
    for a in it:
        if a in ("-o", "--out"):
            out = next(it)
        else:
            files.extend(glob.glob(a))
    if not files:
        print("usage: python src/to_chunks.py <html...> [-o out.jsonl]", file=sys.stderr)
        sys.exit(1)

    all_chunks = []
    for f in sorted(files):
        is_pm = "html_pm" in pathlib.Path(f).parts   # 입력 디렉터리로 매뉴얼 판별
        doc = (parse_html_pm if is_pm else parse_html)(f)
        cs = doc_to_chunks(doc, manual="업무" if is_pm else "화면")
        all_chunks.extend(cs)
        print(f"{pathlib.Path(f).name}: {len(cs)} chunks", file=sys.stderr)

    pathlib.Path(out).parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        for c in all_chunks:
            fh.write(json.dumps(c, ensure_ascii=False) + "\n")
    print(f"wrote {out} ({len(all_chunks)} chunks from {len(files)} file(s))", file=sys.stderr)


if __name__ == "__main__":
    main()
