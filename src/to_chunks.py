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


SECTION_TO_TYPE = {
    "화면개요": "overview",
    "화면설명": "description",
    "용어찾기": "glossary",
    "관련화면": "related",
    "질문보기": "qa",
}


def doc_to_chunks(doc: dict) -> list[dict]:
    chunks = []
    for i, bc in enumerate(doc["breadcrumbs"]):
        path = bc["path"]
        text = bc["text"]
        section = path[1] if len(path) > 1 else ""
        ctype = SECTION_TO_TYPE.get(section, "description")
        path_str = " > ".join(path)
        term = path[-1] if len(path) > 2 else section
        chunk = {
            "id": f"{doc['screen_id']}#{i:04d}",
            "screen_id": doc["screen_id"],
            "code": doc["code"],
            "aup": doc["aup"],
            "screen_no": doc["screen_no"],
            "title": doc["title"],
            "source_url": doc["source_url"],
            "chunk_type": ctype,
            "section_path": path,
            "path_str": path_str,
            "term": term,
            "text": text,
            # 경로 보존 임베딩 텍스트 (질문보기는 질문이 path 말단에 포함됨)
            "embed_text": f"{path_str} : {text}",
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
        doc = parse_html(f)
        cs = doc_to_chunks(doc)
        all_chunks.extend(cs)
        print(f"{pathlib.Path(f).name}: {len(cs)} chunks", file=sys.stderr)

    pathlib.Path(out).parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        for c in all_chunks:
            fh.write(json.dumps(c, ensure_ascii=False) + "\n")
    print(f"wrote {out} ({len(all_chunks)} chunks from {len(files)} file(s))", file=sys.stderr)


if __name__ == "__main__":
    main()
