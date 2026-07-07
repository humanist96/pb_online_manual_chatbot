"""
업무매뉴얼(PM) 파서 — /000/PM 템플릿 전용 (화면매뉴얼 parse.py와 별도 모듈).

템플릿(2026-07 전수 390문서 실측 — 단일 계열):
  div#content
    ├─ p(무클래스)                     : 개요 문단
    ├─ p.s-01/.h-01/.h-02/.h3         : 섹션 헤딩(문서에 따라)
    └─ ol > li.c-01/.c-02/...          : 섹션 — 선두 텍스트가 제목, 이하 p가 본문
         ├─ table.box_style1           : th 헤더 + (항목, 설명) 행
         └─ img (assets/images/...)    : 도식 — pm_image_text.json 캐시로 텍스트화 병합

산출 dict: parse.py와 동일 계열 {screen_id, title, breadcrumbs:[{path,text}], images:[...]}
이미지 텍스트화 캐시(data/pm_image_text.json)가 있으면 해당 위치에 브레드크럼으로 삽입.
"""
from __future__ import annotations
import re
import json
import pathlib
import warnings

from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

BASE_URL = "http://211.255.203.234:8080/000/PM"
IMG_CACHE_PATH = pathlib.Path("data/pm_image_text.json")

HEADING_CLASSES = {"s-01", "h-01", "h-02", "h3"}
SECTION_LI = re.compile(r"^c-\d+$")


def norm(s: str) -> str:
    s = s.replace("\xa0", " ").replace("\r", " ").replace("\n", " ")
    return re.sub(r"\s+", " ", s).strip()


def _img_cache() -> dict:
    if IMG_CACHE_PATH.exists():
        with open(IMG_CACHE_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {}


def _li_title_and_body(li) -> tuple[str, list[str]]:
    """li 텍스트를 줄 단위로 — 첫 줄 = 섹션 제목, 나머지 = 본문(병합 1청크)."""
    lines = [norm(x) for x in li.get_text("\n").split("\n") if norm(x)]
    if not lines:
        return "", []
    title = lines[0]
    body = [" ".join(lines[1:])] if len(lines) > 1 else []
    return title, body


def _table_rows(table) -> list[tuple[str, str]]:
    """box_style1 → (항목, 설명) 목록. 헤더행(th)은 라벨로만 사용."""
    rows = []
    header = [norm(th.get_text(" ")) for th in table.find_all("th")]
    for tr in table.find_all("tr"):
        tds = tr.find_all("td")
        if not tds:
            continue
        if len(tds) >= 2:
            item = norm(tds[0].get_text(" "))
            desc = " ".join(norm(td.get_text(" ")) for td in tds[1:])
            if item and desc:
                rows.append((item, desc))
        elif len(tds) == 1 and header:
            rows.append((header[0], norm(tds[0].get_text(" "))))
    # 비교표(헤더 2열 + 셀들이 컬럼 대응): 행 분해가 비면 컬럼 단위로
    if not rows and header:
        tds = table.find_all("td")
        if len(tds) == len(header):
            rows = [(h, norm(td.get_text(" "))) for h, td in zip(header, tds)]
    return rows


def parse_html(path: str) -> dict:
    html = pathlib.Path(path).read_text(encoding="utf-8", errors="replace")
    soup = BeautifulSoup(html, "lxml")
    screen_id = pathlib.Path(path).stem
    h1 = soup.find("h1")
    title = norm(h1.get_text(" ")) if h1 else screen_id

    doc = {
        "screen_id": screen_id, "code": screen_id, "aup": screen_id,
        "title": title, "screen_no": "", "topic_id": "",
        "source_url": f"{BASE_URL}/#t={screen_id}.html",
        "summary": "", "breadcrumbs": [], "images": [],
        "glossary": [], "related": [], "qa": [],
    }
    cache = _img_cache()

    def add(path_segs: list[str], text: str):
        text = norm(text)
        if text and len(text) > 2:
            doc["breadcrumbs"].append({"path": [title] + path_segs, "text": text})

    def add_img(img, section: str):
        src = img.get("src", "")
        if "assets/images" not in src:
            return
        name = src.rsplit("/", 1)[-1]
        doc["images"].append({"name": name, "section": section})
        cached = cache.get(name)
        if cached and cached.get("text"):
            label = cached.get("kind", "도식")
            add([section, label] if section else [label],
                cached["text"] + f" (도식 텍스트화: {name})")

    content = soup.find("div", id="content")
    if not content:
        return doc

    def walk_list(ol_el, base: list[str]):
        """중첩 목록 워커 — PM 템플릿의 3계층 li 규칙:
        li.c-N(대분류 제목) → ol > li.a-x(중분류 제목) → ol > li.h-N(본문 항목).
        lxml이 li를 조기 종료시켜 하위 ol·표·이미지가 '형제'로 오므로,
        순차 순회하며 직전 제목 li의 경로(cur)에 귀속시킨다."""
        cur = base
        for node in ol_el.children:
            nn = getattr(node, "name", None)
            if nn == "li":
                cls = (node.get("class") or [""])[0]
                sec_title, body = _li_title_and_body(node)
                if body:                                   # 제목+본문 복합 li
                    cur = base + [sec_title] if sec_title else base
                    for t in body:
                        add(cur or ["내용"], t)
                elif cls.startswith(("c-", "a-")) and len(sec_title) <= 24:
                    # 짧은 제목-only li = 하위 목록 예고
                    cur = base + [sec_title] if sec_title else base
                else:                                      # h-N 등 = 본문 항목(leaf)
                    add(base or ["내용"], sec_title)
                    cur = base
                for img in node.find_all("img"):
                    add_img(img, (cur or base or ["내용"])[-1])
                for tbl in node.find_all("table"):
                    for item, desc in _table_rows(tbl):
                        add((cur or ["내용"]) + [item], desc)
            elif nn == "table":
                for item, desc in _table_rows(node):
                    add((cur or ["내용"]) + [item], desc)
            elif nn == "img":
                add_img(node, (cur or ["내용"])[-1])
            elif nn in ("ol", "ul"):
                walk_list(node, cur if cur is not None else base)
            elif nn == "div":
                walk_body(node, cur if cur is not None else base)

    def walk_body(container, base: list[str]):
        """섹션 본문 컨테이너(div.h3 등) 내부: p·ol/li·table·img 순회."""
        for el in container.children:
            name = getattr(el, "name", None)
            if name == "p":
                t = norm(el.get_text(" "))
                if t:
                    add(base or ["개요"], t)
                    if not doc["summary"]:
                        doc["summary"] = t
            elif name in ("ol", "ul"):
                walk_list(el, base)
            elif name == "dl":
                # 정의 목록 변형(BSP05030 등): dt=항목, dd=설명
                item = ""
                for c in el.children:
                    cn = getattr(c, "name", None)
                    if cn == "dt":
                        item = norm(c.get_text(" "))
                    elif cn == "dd":
                        add(base + [item] if item else (base or ["내용"]),
                            norm(c.get_text(" ")))
            elif name == "table":
                for item, desc in _table_rows(el):
                    add((base or ["내용"]) + [item], desc)
            elif name == "img":
                add_img(el, base[-1] if base else "")
            elif name == "div":
                walk_body(el, base)

    # 문서 골격: h3.s-01(섹션 제목) → div.h3(본문 컨테이너) 쌍의 연속
    section = ""
    for el in content.children:
        name = getattr(el, "name", None)
        if name is None:
            continue
        cls = set(el.get("class") or [])
        if name in ("h2", "h3", "h4") or (name == "p" and cls & HEADING_CLASSES):
            section = norm(el.get_text(" "))
        elif name == "div":
            walk_body(el, [section] if section else [])
        elif name in ("p", "ol", "ul", "table", "img"):
            # 헤딩 없이 등장하는 본문 요소도 동일 규칙
            walk_body(_wrap(el), [section] if section else [])
    return doc


def _wrap(el):
    """단일 요소를 walk_body가 받는 컨테이너 형태로 감싼다."""
    return type("W", (), {"children": [el]})()


if __name__ == "__main__":
    import sys
    for p in sys.argv[1:]:
        d = parse_html(p)
        print(f"== {d['screen_id']} {d['title']}  breadcrumbs={len(d['breadcrumbs'])} images={len(d['images'])}")
        for b in d["breadcrumbs"][:12]:
            print("  ", " > ".join(b["path"])[:70], "||", b["text"][:40])
