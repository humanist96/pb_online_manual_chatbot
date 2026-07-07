"""
계좌 섹션 토픽 HTML 수집기.

파일럿은 AC250400 단건이지만, 계좌 섹션 전체로 확장할 때 사용한다.
RoboHelp 정적 토픽(AC*.html)을 HTTP GET 으로 받아 data/html/ 에 캐시.

사용:
  python src/crawl.py AC250400 AC250200 ACA51000 ACA50400   # 명시 목록
  python src/crawl.py --from-file data/account_topics.txt    # 한 줄에 하나
  python src/crawl.py --base PM --from-file data/topics_pm/계좌관리.txt
      # 업무매뉴얼 → data/html_pm/ + 본문 이미지 data/img_pm/
"""
from __future__ import annotations
import re
import sys
import pathlib
import urllib.request

SERVER = "http://211.255.203.234:8080/000"
BASE_URL = f"{SERVER}/ST"
OUT = pathlib.Path("data/html")
IMG_OUT = None  # PM이면 data/img_pm


def fetch(topic: str) -> bool:
    topic = topic.strip().removesuffix(".html")
    if not topic:
        return False
    url = f"{BASE_URL}/{topic}.html"
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            if r.status != 200:
                print(f"[crawl] {topic}: HTTP {r.status}", file=sys.stderr)
                return False
            data = r.read()
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / f"{topic}.html").write_bytes(data)
        n_img = fetch_images(data) if IMG_OUT else 0
        print(f"[crawl] {topic}.html  ({len(data)} bytes{f', img {n_img}' if n_img else ''})")
        return True
    except Exception as e:
        print(f"[crawl] {topic}: {e}", file=sys.stderr)
        return False


def fetch_images(html_bytes: bytes) -> int:
    """본문 참조 이미지 다운로드(assets/images/ 하위만, 템플릿·로고 제외). 캐시 존중."""
    html = html_bytes.decode("utf-8", errors="replace")
    n = 0
    for src in set(re.findall(r'<img[^>]+src="([^"]+)"', html)):
        if "assets/images/" not in src or "template" in src:
            continue
        name = src.rsplit("/", 1)[-1]
        dst = IMG_OUT / name
        if dst.exists():
            continue
        try:
            with urllib.request.urlopen(f"{BASE_URL}/{src}", timeout=20) as r:
                IMG_OUT.mkdir(parents=True, exist_ok=True)
                dst.write_bytes(r.read())
                n += 1
        except Exception as e:
            print(f"[crawl] img {name}: {e}", file=sys.stderr)
    return n


def main():
    global BASE_URL, OUT, IMG_OUT
    args = sys.argv[1:]
    if "--base" in args:
        i = args.index("--base")
        proj = args[i + 1].upper()
        BASE_URL = f"{SERVER}/{proj}"
        if proj != "ST":
            OUT = pathlib.Path(f"data/html_{proj.lower()}")
            IMG_OUT = pathlib.Path(f"data/img_{proj.lower()}")
        args = args[:i] + args[i + 2:]
    topics: list[str] = []
    it = iter(args)
    for a in it:
        if a == "--from-file":
            topics += pathlib.Path(next(it)).read_text(encoding="utf-8").splitlines()
        else:
            topics.append(a)
    if not topics:
        print("usage: python src/crawl.py <TOPIC...> | --from-file list.txt", file=sys.stderr)
        sys.exit(1)
    ok = sum(fetch(t) for t in topics)
    print(f"[crawl] {ok}/{len(topics)} fetched → {OUT}/", file=sys.stderr)


if __name__ == "__main__":
    main()
