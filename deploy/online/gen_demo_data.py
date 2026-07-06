"""
PowerBASE 데모 매뉴얼 생성기 — 온라인 공개 데모용 비민감 합성 데이터.

PowerBASE 매뉴얼과 동일한 구조의 **합성** 매뉴얼을 절차적으로 생성한다.
실제 사내 매뉴얼과 무관한 완전 합성 데이터이며, 브레드크럼·부문 구조와
청크 스키마는 본 파이프라인(to_chunks.py 산출)과 동일하다.

부문 간 동음이의 용어(약정·수수료·한도·승인·마감·잔고)를 의도적으로 배치해
스코프 필터·모호성 배너 시연이 가능하게 한다. 결정적 시드(42) — 재실행 동일 출력.

  python deploy/online/gen_demo_data.py
  → deploy/online/demo_data/chunks.jsonl · sectors.json · meta.json
"""
from __future__ import annotations
import json
import random
import pathlib

OUT = pathlib.Path(__file__).resolve().parent / "demo_data"
rng = random.Random(42)

# 부문 → (코드 접두, 중분류 목록)
SECTORS = {
    "계좌": ("DA", ["고객관리", "계좌개설", "계좌정보관리", "사고관리"]),
    "주문": ("DO", ["현물주문", "주문정정취소", "주문현황"]),
    "출납": ("DC", ["입출금", "이체관리", "출납마감"]),
    "공통": ("DM", ["코드관리", "사용자권한", "공통조회"]),
}

# 부문 간 공유되는 동음이의 용어 (교차 오염 시연용)
HOMONYMS = ["약정", "수수료", "한도", "승인", "마감", "잔고"]

SCREEN_NOUNS = {
    "계좌": ["종합계좌", "고객정보", "실명확인", "비밀번호", "약정등록", "휴면계좌",
             "계좌이관", "사고신고", "출금한도", "수수료면제", "증거금", "고객등급",
             "계좌폐쇄", "위임장", "통보내역", "승인요청"],
    "주문": ["주문입력", "정정취소", "체결조회", "미체결", "호가한도", "약정현황",
             "주문승인", "대량주문", "예약주문", "주문수수료", "권한주문", "시장가",
             "지정가", "주문마감", "체결통보", "주문이력"],
    "출납": ["입금처리", "출금처리", "계좌이체", "타행이체", "이체한도", "수수료출납",
             "가상계좌", "출납승인", "일마감", "시재관리", "미수금", "출납잔고",
             "지급정지", "환불처리", "출납약정", "전표조회"],
    "공통": ["공통코드", "사용자등록", "권한승인", "메뉴관리", "부점코드", "영업일관리",
             "한도설정", "승인이력", "잔고대사", "마감스케줄", "수수료율", "약정코드",
             "알림설정", "로그조회", "환경설정", "단축키"],
}

ACTIONS = ["조회", "등록", "변경", "해지"]
FIELDS = ["계좌번호", "고객번호", "처리일자", "부점번호", "처리구분", "금액", "사유코드", "담당자"]
FIELD_DESC = {
    "계좌번호": "종합계좌번호를 직접 입력하거나 돋보기 아이콘을 클릭하여 선택합니다",
    "고객번호": "고객번호 또는 고객명으로 검색하여 선택합니다",
    "처리일자": "처리 기준일자를 입력합니다. 기본값은 당일입니다",
    "부점번호": "처리 부점을 선택합니다. 본인 소속 부점이 기본값입니다",
    "처리구분": "등록/변경/해지 중 처리 유형을 선택합니다",
    "금액": "처리 금액을 원 단위로 입력합니다",
    "사유코드": "처리 사유 코드를 선택합니다. 코드는 공통코드관리에서 관리됩니다",
    "담당자": "처리 담당자 ID가 자동 표시됩니다",
}


def make_screen(sector: str, mid: str, prefix: str, idx: int) -> dict:
    noun = SCREEN_NOUNS[sector][idx % len(SCREEN_NOUNS[sector])]
    action = ACTIONS[idx % len(ACTIONS)]
    title = f"{noun}{action}"
    screen_id = f"{prefix}{100 + idx}00"
    screen_no = f"{rng.randint(1000, 9899)}"
    homonym = HOMONYMS[idx % len(HOMONYMS)]

    bcs = []  # (path, text)
    bcs.append(([title, "화면개요"],
                f"{sector} 업무에서 {noun}을(를) {action}하는 화면입니다. "
                f"{mid} 메뉴에서 진입하며, {homonym} 정보와 함께 처리 내역을 관리합니다."))

    fields = rng.sample(FIELDS, 4)
    for f in fields:
        bcs.append(([title, "화면설명", "조건입력", f], FIELD_DESC[f]))
    bcs.append(([title, "화면설명", "조건입력", homonym,
                 f"{sector} {homonym}"],
                f"{sector} 부문의 {homonym} 기준을 적용합니다. 타 부문 {homonym}과(와) 별도로 관리됩니다."))

    for step, desc in [("조회", f"조건 입력 후 조회 버튼을 클릭하면 {noun} 내역이 목록에 표시됩니다"),
                       ("처리", f"목록에서 대상 건을 선택하고 {action} 버튼을 클릭합니다. "
                                f"{homonym} 한도를 초과하면 승인 절차가 필요합니다"),
                       ("확인", "처리 결과는 하단 메시지 영역과 처리이력 탭에서 확인합니다")]:
        bcs.append(([title, "화면설명", "처리절차", step], desc))

    bcs.append(([title, "용어찾기", homonym],
                f"{sector} 업무에서 {homonym}(이)란 {noun} 처리 시 적용되는 기준 정보를 말합니다."))
    bcs.append(([title, "용어찾기", f"{noun}코드"],
                f"{noun}을(를) 식별하는 코드로, 공통 부문의 코드관리 화면에서 등록합니다."))

    rel_idx = (idx + 3) % len(SCREEN_NOUNS[sector])
    rel = f"{SCREEN_NOUNS[sector][rel_idx]}{ACTIONS[rel_idx % 4]}"
    bcs.append(([title, "관련화면", f"{rel}[{prefix}{100 + rel_idx}00]"],
                f"{rel} 화면에서 연계 처리 내역을 확인할 수 있습니다."))

    q = f"{noun} {action} 시 {homonym} 오류가 발생하면 어떻게 하나요?"
    bcs.append(([title, "질문보기", q],
                f"{homonym} 기준 정보가 미등록된 경우입니다. {sector} 부문의 {homonym} 관리 화면에서 "
                f"기준을 먼저 등록한 뒤 재처리하면 됩니다."))

    return {"screen_id": screen_id, "screen_no": screen_no, "title": title,
            "sector": sector, "mid": mid, "bcs": bcs}


def main():
    chunks = []
    tree: dict = {}
    for sector, (prefix, mids) in SECTORS.items():
        for idx in range(16):
            mid = mids[idx % len(mids)]
            scr = make_screen(sector, mid, prefix, idx)
            sector_path = [sector, mid]
            for i, (path, text) in enumerate(scr["bcs"]):
                section = path[1]
                ctype = {"화면개요": "overview", "화면설명": "description",
                         "용어찾기": "glossary", "관련화면": "related",
                         "질문보기": "qa"}.get(section, "description")
                path_str = " > ".join(path)
                chunks.append({
                    "id": f"{scr['screen_id']}#{i:04d}",
                    "screen_id": scr["screen_id"],
                    "code": f"{scr['screen_no']}-{scr['screen_id']}",
                    "aup": scr["screen_id"],
                    "screen_no": scr["screen_no"],
                    "title": scr["title"],
                    "source_url": "#demo",
                    "sector": sector,
                    "sector_path": sector_path,
                    "scope_key": ">".join(sector_path + [scr["screen_id"]]),
                    "chunk_type": ctype,
                    "section_path": path,
                    "path_str": path_str,
                    "term": path[-1] if len(path) > 2 else section,
                    "text": text,
                    "embed_text": f"[{sector}] {path_str} : {text}",
                })
            node = tree.setdefault(sector, {"name": sector, "count": 0, "children": {}, "screens": {}})
            node["count"] += len(scr["bcs"])
            m = node["children"].setdefault(mid, {"name": mid, "count": 0, "children": {}, "screens": {}})
            m["count"] += len(scr["bcs"])
            m["screens"][scr["screen_id"]] = {"id": scr["screen_id"], "title": scr["title"],
                                              "count": len(scr["bcs"])}

    def ser(d):
        return [{"name": n["name"], "count": n["count"], "children": ser(n["children"]),
                 "screens": sorted(n["screens"].values(), key=lambda x: x["id"])}
                for n in d.values()]

    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "chunks.jsonl", "w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    samples = [c["section_path"][-1] for c in chunks if c["chunk_type"] == "qa"][:8]
    json.dump({"tree": ser(tree)}, open(OUT / "sectors.json", "w", encoding="utf-8"), ensure_ascii=False)
    json.dump({"embed_model": "upstash-hybrid/text-embedding-3-small", "dim": 1536,
               "count": len(chunks), "demo": True, "reranker": None,
               "sectors": {s: t["count"] for s, t in tree.items()},
               "samples": samples,
               "gate": {"mode": "cosine", "tau": 0.70, "tau_rerank": 0.70, "tau_cos": 0.70}},
              open(OUT / "meta.json", "w", encoding="utf-8"), ensure_ascii=False)
    print(f"[demo] {len(chunks)} chunks, {sum(1 for _ in SECTORS)} sectors → {OUT}/")


if __name__ == "__main__":
    main()
