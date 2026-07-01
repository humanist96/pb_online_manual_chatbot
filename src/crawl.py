"""
계좌 섹션 토픽 HTML 수집기.

파일럿은 AC250400 단건이지만, 계좌 섹션 전체로 확장할 때 사용한다.
RoboHelp 정적 토픽(AC*.html)을 HTTP GET 으로 받아 data/html/ 에 캐시.

사용:
  python src/crawl.py AC250400 AC250200 ACA51000 ACA50400   # 명시 목록
  python src/crawl.py --from-file data/account_topics.txt    # 한 줄에 하나
"""
from __future__ import annotations
import sys
import pathlib
import urllib.request

BASE_URL = "http://211.255.203.234:8080/000/ST"
OUT = pathlib.Path("data/html")


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
        print(f"[crawl] {topic}.html  ({len(data)} bytes)")
        return True
    except Exception as e:
        print(f"[crawl] {topic}: {e}", file=sys.stderr)
        return False


def main():
    args = sys.argv[1:]
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
