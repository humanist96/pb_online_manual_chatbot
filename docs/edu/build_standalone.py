"""
교육 슬라이드 단일 HTML 번들러 — css/js/폰트/이미지를 전부 base64로 인라인.

파일 하나만 전달해도 file:// 더블클릭으로 완전 동작(폐쇄망·메일 첨부용).
표준 라이브러리만 사용.

  python docs/edu/build_standalone.py
  → docs/edu/out/PB_RAG_교육_단일본.html
"""
from __future__ import annotations
import re
import base64
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE / "out"
MIME = {".png": "image/png", ".woff2": "font/woff2", ".svg": "image/svg+xml",
        ".jpg": "image/jpeg", ".gif": "image/gif"}


def data_uri(path: pathlib.Path) -> str:
    b64 = base64.b64encode(path.read_bytes()).decode()
    return f"data:{MIME[path.suffix.lower()]};base64,{b64}"


def main():
    html = (HERE / "index.html").read_text(encoding="utf-8")

    # CSS 인라인 (+ CSS 내부 폰트 url()도 데이터 URI로)
    css = (HERE / "edu.css").read_text(encoding="utf-8")
    css = re.sub(r'url\("?(fonts/[^")]+)"?\)',
                 lambda m: f'url("{data_uri(HERE / m.group(1))}")', css)
    html = re.sub(r'<link rel="stylesheet" href="edu\.css[^"]*" />',
                  "<style>\n" + css + "\n</style>", html)

    # JS 인라인
    js = (HERE / "edu.js").read_text(encoding="utf-8")
    assert "</script" not in js, "인라인 안전성: edu.js에 </script 문자열 금지"
    html = re.sub(r'<script src="edu\.js[^"]*"></script>',
                  "<script>\n" + js + "\n</script>", html)

    # 이미지 인라인
    html = re.sub(r'src="(images/[^"]+)"',
                  lambda m: f'src="{data_uri(HERE / m.group(1))}"', html)

    leftover = re.findall(r'(?:href|src)="(?!data:|https?:|#)[^"]+"', html)
    assert not leftover, f"미처리 외부 참조 잔존: {leftover[:3]}"

    OUT.mkdir(exist_ok=True)
    out = OUT / "PB_RAG_교육_단일본.html"
    out.write_text(html, encoding="utf-8")
    print(f"[standalone] {out}  ({out.stat().st_size/1024/1024:.1f} MB)")


if __name__ == "__main__":
    main()
