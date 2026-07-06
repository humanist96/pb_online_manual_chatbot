"""
PowerBASE 온라인매뉴얼(Adobe RoboHelp 2022) '계좌' 토픽 HTML → 구조화 트리.

핵심 계층 규칙 (CSS class 기반, AC250400 파일럿에서 검증):
  - div.title_box   : 대분류 (화면알아보기 / 용어찾기 / 질문보기)
  - div.Step00_icon : 중분류 (화면개요 / 화면설명 / 용어찾기 / 관련화면)
  - div.Step1_Nxx   : 화면설명 단계 (선두 문단 + 항목 테이블)
  - table tr        : th=항목명, td=ul>li 목록
  - li.icon01       : 1레벨 항목
  - li.icon02       : 2레벨 — 콜론이 있으면 자식 항목, 없으면 부모의 ► 하위불릿
  - li (class 없음) : 직전 항목 설명의 줄바꿈 연속(병합)
  - table.T_QAbox   : th.Que=질문 / td.Ans=답변

출력: 화면당 dict (screen_id, code, title, summary, breadcrumbs, glossary, related, qa ...)
외부 의존: beautifulsoup4, lxml (모두 오픈소스/로컬)
"""
from __future__ import annotations
import re
import sys
import json
import html
import pathlib
import warnings
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

BASE_URL = "http://211.255.203.234:8080/000/ST"

# ─────────────────────────────── 텍스트 정규화 ───────────────────────────────

def norm(s: str) -> str:
    """공백/개행/NBSP 정규화. ► 불릿 등 의미기호는 보존."""
    s = html.unescape(s or "")
    s = s.replace("\r", " ").replace("\n", " ").replace(" ", " ")
    s = re.sub(r"[ \t]+", " ", s)
    return s.strip()


def split_term(text: str):
    """'용어 : 설명' → (term, desc, True). 콜론 없으면 (text, '', False).
    첫 콜론 기준. 문장 중간 콜론 오탐 방지를 위해 용어 길이를 40자로 제한."""
    m = re.match(r"^(.{1,40}?)\s*:\s*(\S.*)$", text)
    if m:
        return m.group(1).strip(), m.group(2).strip(), True
    return text.strip(), "", False


def clean_name(s: str) -> str:
    """항목/용어명 정리: 여는 괄호 앞 공백 제거 등."""
    s = norm(s)
    s = re.sub(r"\s+\(", "(", s)
    return s


# ─────────────────────────────── 항목 목록 파싱 ──────────────────────────────

def _join_desc(parts: list[str]) -> str:
    return " ".join(p for p in parts if p).strip()


def parse_item_list(ul) -> list[tuple[list[str], str]]:
    """td 안의 <ul> → [(경로세그먼트[...], 설명), ...].

    icon01 항목마다 그룹을 만들고, 뒤따르는 icon02/무클래스 li 를 규칙대로 병합.
    반환 세그먼트는 최대 2단계(부모라벨 > 자식)까지."""
    results: list[tuple[list[str], str]] = []

    cur = None            # 현재 icon01 그룹: {term, desc, colon}
    children: list[dict] = []
    last_target = None    # 연속(무클래스) li 가 붙을 대상 dict

    def flush():
        nonlocal cur, children
        if cur is None:
            return
        if children:
            # icon01 은 부모 라벨. 자체 설명(콜론)이 있으면 그 노드도 방출.
            if cur["desc"]:
                results.append(([cur["term"]], _join_desc(cur["desc"])))
            for ch in children:
                results.append(([cur["term"], ch["term"]], _join_desc(ch["desc"])))
        else:
            results.append(([cur["term"]], _join_desc(cur["desc"])))
        cur, children = None, []

    for li in ul.find_all("li"):
        cls = li.get("class") or []
        text = norm(li.get_text(" "))
        if not text:
            continue
        if "icon01" in cls:
            flush()
            term, desc, _ = split_term(text)
            cur = {"term": term, "desc": [desc] if desc else [], "colon": bool(desc)}
            last_target = cur
        elif "icon02" in cls:
            term, desc, has_colon = split_term(text)
            if has_colon:
                child = {"term": term, "desc": [desc] if desc else []}
                children.append(child)
                last_target = child
            elif cur is not None:
                cur["desc"].append("► " + text)   # 하위불릿 → 부모 설명에 병합
                last_target = cur
        else:  # 무클래스 li = 직전 항목의 줄바꿈 연속
            if last_target is not None:
                last_target["desc"].append(text)
    flush()
    return results


# ─────────────────────────────── 단계 라벨 추론 ──────────────────────────────

def step_label(lead_para: str, idx: int) -> str:
    p = lead_para
    if "조회결과" in p or "결과를 보여주는" in p:
        return "조회 결과"
    if "입력하는 창" in p or "조건을 입력" in p:
        return "조건입력"
    return f"단계{idx}"


def _lead_paragraph(step_div) -> str:
    """Step1 div 에서 테이블을 제외한 선두 문단 텍스트."""
    clone = BeautifulSoup(str(step_div), "lxml")
    for tbl in clone.find_all("table"):
        tbl.decompose()
    return norm(clone.get_text(" "))


# 단계/섹션 경계로 취급할 요소 (이 요소를 만나면 현재 단계의 테이블 탐색 중단)
def _is_barrier(el) -> bool:
    if not getattr(el, "get", None):
        return False
    cls = el.get("class") or []
    return any(c.startswith("Step1_N") or c in ("Step00_icon", "title_box") for c in cls)


def _step_table(step_div):
    """Step1 div 에 속한 테이블을 반환.
    HTML 구조에 따라 테이블이 div의 자식(AC250400) 또는 형제(ACA50300)로 파싱되므로 둘 다 처리.
    자식이 없으면, 다음 단계/섹션 경계 이전에 나오는 첫 테이블을 채택."""
    t = step_div.find("table")
    if t is not None:
        return t
    for el in step_div.find_all_next():
        if _is_barrier(el):
            return None
        if getattr(el, "name", None) == "table":
            return el
    return None


# ─────────────────────────────── 메인 파서 ───────────────────────────────────

def parse_html(path: str) -> dict:
    raw = pathlib.Path(path).read_text(encoding="utf-8")
    soup = BeautifulSoup(raw, "lxml")

    screen_id = pathlib.Path(path).stem            # AC250400
    # 제목/화면번호: h1 span → "지점계좌서비스약정등록내역[0878]"
    h1 = soup.find("h1")
    h1txt = clean_name(h1.get_text(" ")) if h1 else screen_id
    mno = re.search(r"\[(\d+)\]", h1txt)
    screen_no = mno.group(1) if mno else ""
    title = re.sub(r"\s*\[\d+\]\s*$", "", h1txt).strip()
    topic_id = ""
    meta_tid = soup.find("meta", attrs={"name": "gTopicId"})
    if meta_tid:
        topic_id = meta_tid.get("content", "")

    code = f"{screen_no}-{screen_id}" if screen_no else screen_id

    doc = {
        "screen_id": screen_id,
        "code": code,
        "aup": screen_id,
        "title": title,
        "screen_no": screen_no,
        "topic_id": topic_id,
        "source_url": f"{BASE_URL}/{screen_id}.html",
        "summary": "",
        "breadcrumbs": [],   # {path:[...], text}
        "glossary": [],      # {term, desc}
        "related": [],       # {screen, desc}
        "qa": [],            # {q, a}
    }

    def add_bc(path_segs: list[str], text: str):
        text = norm(text)
        if text:
            doc["breadcrumbs"].append({"path": path_segs, "text": text})

    # ── 화면설명: Step1_Nxx 단계들 (먼저 존재 여부 확인) ──
    steps = soup.find_all("div", class_=re.compile(r"^Step1_N"))

    # ── 화면개요 (요약) ──
    h2s = soup.find_all("div", class_="h2")
    if h2s:
        doc["summary"] = norm(h2s[0].get_text(" "))
        add_bc([title, "화면개요"], doc["summary"])
    # 테이블 단계가 없는 h2 전용 토픽(ACA40100, 감사/투자정보 등 경량 템플릿):
    # <h2>라벨</h2><div class="h2">본문</div> 쌍 구조 — 라벨을 살리고 목록은 단계별로 분할
    if not steps and len(h2s) > 1:
        for j, h in enumerate(h2s[1:], 1):
            head = h.find_previous_sibling("h2")
            label = norm(head.get_text(" ")) if head else f"내용{j}"
            lst = h.find(["ol", "ul"])
            lis = (lst.find_all("li", recursive=False) or lst.find_all("li")) if lst else []
            if lis:
                for k, li in enumerate(lis, 1):
                    add_bc([title, label, f"단계{k}"], norm(li.get_text(" ")))
            else:
                add_bc([title, label], norm(h.get_text(" ")))

    # 최후 폴백(SQ010000 등 소개 문서): 구조 클래스가 전혀 없으면 본문 문단을 개요로 보존
    if not doc["breadcrumbs"]:
        content = soup.find("div", id="content")
        if content:
            for p in content.find_all("p"):
                t = norm(p.get_text(" "))
                if len(t) >= 15:
                    add_bc([title, "화면개요"], t)

    for i, step in enumerate(steps, 1):
        lead = _lead_paragraph(step)
        label = step_label(lead, i)
        # 선두 문단은 첫 항목명 이후가 잘려 있을 수 있으므로 첫 문장만 사용
        lead_first = re.split(r"(?<=[.。])\s", lead, maxsplit=1)[0] if lead else lead
        add_bc([title, "화면설명", label], lead_first)
        table = _step_table(step)
        if not table:
            continue
        for tr in table.find_all("tr"):
            th = tr.find("th")
            td = tr.find("td")
            if not th or not td:
                continue
            item = clean_name(th.get_text(" "))
            ul = td.find("ul")
            if not ul:
                continue
            for segs, desc in parse_item_list(ul):
                # 리프 항목명이 항목(th)명과 같으면 중복 세그먼트 축약
                if segs and segs[0] == item:
                    segs = segs[1:]
                add_bc([title, "화면설명", label, item, *segs], desc)

    # ── 용어찾기 / 관련화면: Step00_icon 라벨로 섹션 식별 ──
    for icon in soup.find_all("div", class_="Step00_icon"):
        sect = norm(icon.get_text(" "))
        table = icon.find_next("table")
        if not table:
            continue
        if sect == "용어찾기":
            for tr in table.find_all("tr"):
                th = tr.find("th")
                td = tr.find("td")
                if not th or not td:
                    continue
                term = clean_name(th.get_text(" "))
                desc = norm(td.get_text(" "))
                if term and desc:
                    doc["glossary"].append({"term": term, "desc": desc})
                    add_bc([title, "용어찾기", term], desc)
        elif sect == "관련화면":
            for tr in table.find_all("tr"):
                th = tr.find("th")
                td = tr.find("td")
                if not th or not td:
                    continue
                screen = clean_name(th.get_text(" "))
                desc = norm(td.get_text(" "))
                if screen in ("화면명", "") or desc in ("화면설명", ""):
                    continue  # 헤더행 스킵
                doc["related"].append({"screen": screen, "desc": desc})
                add_bc([title, "관련화면", screen], desc)

    # ── 질문보기 (Q&A) ──
    for qbox in soup.find_all("table", class_="T_QAbox"):
        q = qbox.find(class_="Que")
        a = qbox.find(class_="Ans")
        if q and a:
            qa = {"q": norm(q.get_text(" ")), "a": norm(a.get_text(" "))}
            doc["qa"].append(qa)
            add_bc([title, "질문보기", qa["q"]], qa["a"])

    return doc


def main():
    if len(sys.argv) < 2:
        print("usage: python src/parse.py <html-file> [out.json]", file=sys.stderr)
        sys.exit(1)
    doc = parse_html(sys.argv[1])
    out = sys.argv[2] if len(sys.argv) > 2 else None
    js = json.dumps(doc, ensure_ascii=False, indent=2)
    if out:
        pathlib.Path(out).write_text(js, encoding="utf-8")
        print(f"wrote {out}")
    # 요약 통계
    print(f"screen={doc['screen_id']} title={doc['title']} no={doc['screen_no']}", file=sys.stderr)
    print(f"breadcrumbs={len(doc['breadcrumbs'])} glossary={len(doc['glossary'])} "
          f"related={len(doc['related'])} qa={len(doc['qa'])}", file=sys.stderr)
    if not out:
        print(js)


if __name__ == "__main__":
    main()
