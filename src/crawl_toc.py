"""
PowerBASE 매뉴얼 TOC 전수 크롤러 — 부문 매니페스트 생성 (전 부문 확장 P1).

RoboHelp 2022 반응형 TOC(whxdata/toc.new.js)를 재귀 파싱해
브레드크럼 상위 계층(TOC 경로)의 단일 원천을 만든다.

  python src/crawl_toc.py                     # 화면매뉴얼(ST) 전 부문
  python src/crawl_toc.py 계좌 출납           # 지정 부문만
  python src/crawl_toc.py --base PM           # 업무매뉴얼 → manifest_pm.json + topics_pm/

산출:
  data/manifest.json          {"AC110100.html": {"name": "...", "path": "계좌 > 고객관리"}}
  data/topics/<부문>.txt      부문별 토픽 코드 목록 (crawl.py --from-file 입력)
  stdout                      부문/토픽 수 리포트

전부 표준 라이브러리, 사내망(BASE) 필요.
"""
from __future__ import annotations
import io
import re
import sys
import json
import time
import pathlib
import urllib.request

SERVER = "http://211.255.203.234:8080/000"
BASE = f"{SERVER}/ST"          # --base 인자로 교체됨
SUFFIX = ""                    # PM이면 "_pm"
DATA = pathlib.Path("data")
TOPICS_DIR = DATA / "topics"  # main()에서 SUFFIX 반영

_TOC_RE = re.compile(r"var toc\s*=\s*(\[.*\]);", re.S)


def fetch_toc(key: str) -> list[dict]:
    """whxdata/<key>.new.js → 노드 리스트. 실패 시 빈 리스트(경고)."""
    url = f"{BASE}/whxdata/{key}.new.js"
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            body = r.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"[toc] {key}: {e}", file=sys.stderr)
        return []
    m = _TOC_RE.search(body)
    if not m:
        print(f"[toc] {key}: 'var toc =' 패턴 없음", file=sys.stderr)
        return []
    return json.loads(m.group(1))


def walk(key: str, path: list[str], manifest: dict, stats: dict) -> None:
    """book을 재귀 순회하며 item(토픽)을 manifest에 수집."""
    for node in fetch_toc(key):
        name = (node.get("name") or "").strip()
        if node.get("type") == "book" and node.get("key"):
            walk(node["key"], path + [name], manifest, stats)
        elif node.get("type") == "item" and node.get("url"):
            url = node["url"].split("#")[0].strip()
            if not url.endswith(".html"):
                continue
            # 같은 토픽이 여러 경로에 걸리면 첫 경로 유지(중복은 통계로 보고)
            if url in manifest:
                stats["dup"] += 1
                continue
            manifest[url] = {"name": name, "path": " > ".join(path)}
    time.sleep(0.05)  # 서버 예의


def main():
    global BASE, SUFFIX
    args = sys.argv[1:]
    if "--base" in args:
        i = args.index("--base")
        proj = args[i + 1].upper()
        BASE = f"{SERVER}/{proj}"
        SUFFIX = "" if proj == "ST" else f"_{proj.lower()}"
        args = args[:i] + args[i + 2:]
    only = set(args)  # 지정 부문만 (없으면 전 부문)
    root = fetch_toc("toc")
    if not root:
        sys.exit("[toc] 루트 TOC를 읽지 못했습니다 — 사내망 연결 확인")
    sectors = [(n["name"].strip(), n["key"]) for n in root
               if n.get("type") == "book" and n.get("key")]
    if only:
        sectors = [(s, k) for s, k in sectors if s in only]
        missing = only - {s for s, _ in sectors}
        if missing:
            sys.exit(f"[toc] 알 수 없는 부문: {', '.join(missing)}")

    manifest: dict[str, dict] = {}
    per_sector: dict[str, list[str]] = {}
    stats = {"dup": 0}
    for sector, key in sectors:
        before = len(manifest)
        walk(key, [sector], manifest, stats)
        topics = [u.removesuffix(".html") for u, m in manifest.items()
                  if m["path"].split(" > ")[0] == sector]
        per_sector[sector] = topics
        print(f"[toc] {sector:<12} 토픽 {len(manifest) - before:>4}개")

    DATA.mkdir(exist_ok=True)
    with open(DATA / f"manifest{SUFFIX}.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)
    topics_dir = DATA / f"topics{SUFFIX}"
    topics_dir.mkdir(exist_ok=True)
    for sector, topics in per_sector.items():
        safe = sector.replace("/", "_").replace(" ", "")
        (topics_dir / f"{safe}.txt").write_text("\n".join(topics) + "\n", encoding="utf-8")

    print(f"[toc] 합계 부문 {len(per_sector)}개 · 토픽 {len(manifest)}개 "
          f"(중복 경로 {stats['dup']}건) → data/manifest{SUFFIX}.json, data/topics{SUFFIX}/", file=sys.stderr)


if __name__ == "__main__":
    main()
