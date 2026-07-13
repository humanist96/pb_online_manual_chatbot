"""상담매뉴얼(PB고객지원센터) .xls → 상담 청크(JSONL) — 온라인 데모 전용 로컬 실행 도구(배포 제외).

Q&A 쌍 기반 별도 청킹(HTML 파서와 무관). 상세 설계는 상담매뉴얼_온라인추가_계획.md.

  .venv/bin/python deploy/online/parse_counsel_xls.py           # → data/chunks_counsel.jsonl + 수지 표
  .venv/bin/python deploy/online/parse_counsel_xls.py --stats   # 파싱 수지만(파일 미기록)

규칙(실사 2026-07-09 기반):
  · 헤더 행(질문내용=="질문내용") 스킵 — 시트 중간 반복 헤더 포함. 고객사 열 기준 판정 금지.
  · 질문내용이 있는 행 = 새 쌍. 빈 행의 답변/비고/고객사는 직전 쌍의 해당 필드에 개행 병합.
  · 고객사·비고 보존(사용자 결정 2026-07-09, 마스킹 없음) — text 말미·embed_text에 포함.
  · 완전 중복(질문+답변)은 1청크로 병합하되 고객사 목록·비고를 합침.
  · 업무명 = 파일명 기준(첫 괄호 앞까지, 잡괄호·꼬리 쉼표 정제) — 1-level 스코프 ["상담", 업무명].
"""
from __future__ import annotations
import sys
import json
import hashlib
import pathlib
import re

import xlrd  # 순수 파이썬, 구형 BIFF .xls 전용 (로컬 도구 의존성)

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SRC_DIR = ROOT / "코스콤(주)PB고객지원센터_ 상담매뉴얼"
OUT = ROOT / "data" / "chunks_counsel.jsonl"
EMBED_CAP = 2000          # Upstash 임베딩 입력 절단 대비(본문 text는 전문 유지)
MIN_LEN = 5               # 질문·답변 최소 길이

NBSP = " "


def norm(s) -> str:
    """셀 텍스트 정규화 — 개행 유지, 행 내 다중 공백·NBSP 정리 (parse.norm 규칙 이식)."""
    if s is None:
        return ""
    if isinstance(s, float):  # xlrd 숫자 셀
        s = str(int(s)) if s == int(s) else str(s)
    lines = [re.sub(r"[ \t]+", " ", ln.replace(NBSP, " ")).strip()
             for ln in str(s).replace("\r", "\n").split("\n")]
    out = "\n".join(lines)
    return re.sub(r"\n{3,}", "\n\n", out).strip()


def one_line(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


# ── PII 마스킹 (2026-07-09 스캔 결과 반영 — 카드·계좌·마스킹 미흡 식별번호만) ──
# 원본 상담 문화가 이미 끝자리 '***' 마스킹을 쓰므로 같은 방식으로 누락분을 보완한다.
# 담당자 실명·연락처, OTP 일련번호 등은 사용자 결정으로 보존(마스킹 범위 밖).
RE_CARD = re.compile(r"\b(\d{4})[- ]\d{4}[- ]\d{4}[- ]\d{4}\b")
RE_ACCT = re.compile(r"\b(\d{3})([- ])(\d{2})([- ])(\d{5,8})(\*{0,3})")
# 7자리+ 숫자 뒤 마스킹(*) → 노출 과다. 단 소수점 일부(0.982…)와 곱셈(N*M)은 산식이므로 제외.
RE_WEAK = re.compile(r"(?<![\d*.])(\d{7,})(\*+)(?!\d)")


def _acct_is_example(p1: str, p3: str) -> bool:
    """테스트/예시 계좌 판정 — 999 지점, 전자리 동일, 0000xx 연번."""
    return (p1 == "999" or len(set(p3)) == 1
            or re.fullmatch(r"0{3,}\d{1,2}", p3) is not None)


def mask_pii(t: str) -> str:
    t = RE_CARD.sub(lambda m: f"{m.group(1)}-****-****-****", t)

    def acct(m):
        p1, s1, p2, s2, p3, star = m.groups()
        if _acct_is_example(p1, p3):
            return m.group()
        keep = p3[:2] if len(p3) <= 5 else p3[:3]
        return f"{p1}{s1}{p2}{s2}{keep}{'*' * (len(p3) - len(keep) + len(star))}"
    t = RE_ACCT.sub(acct, t)

    # 마스킹 의도가 있으나 노출이 과한 번호(실명·접수번호 등): 앞 4자리만 남김
    t = RE_WEAK.sub(lambda m: m.group(1)[:4] + "*" * (len(m.group(1)) - 4 + len(m.group(2))), t)
    return t


def sector_name(fname: str) -> str:
    """파일명 → 업무명. 첫 여는 괄호 앞까지 취하고 꼬리 쉼표·공백 정제.
    예) '출납((PB고객센터).xls'→'출납', '금융상품(RP,…)(PB고객센터).xls'→'금융상품'."""
    stem = pathlib.Path(fname).stem
    name = stem.split("(")[0]
    return name.rstrip(", ").strip()


def parse_file(path: pathlib.Path) -> tuple[list[dict], dict]:
    """한 파일 → [{q, a, clients:[..], note}] + 수지 카운터."""
    wb = xlrd.open_workbook(str(path))
    sheets = [sh for sh in wb.sheets() if sh.nrows > 0]
    stat = {"rows": 0, "q_rows": 0, "pairs": 0, "dropped": 0}
    pairs: list[dict] = []
    for sh in sheets:
        # 헤더에서 열 위치 탐색(공백 제거 비교 — '비  고' 변형 흡수)
        hdr = [re.sub(r"\s+", "", str(sh.cell_value(0, c))) for c in range(sh.ncols)]
        col = {name: (hdr.index(name) if name in hdr else None)
               for name in ("고객사", "질문내용", "답변", "비고")}
        if col["질문내용"] is None or col["답변"] is None:
            print(f"  ! 헤더 미인식 스킵: {path.name}/{sh.name} {hdr}", file=sys.stderr)
            continue
        cell = lambda r, name: (norm(sh.cell_value(r, col[name]))
                                if col[name] is not None and col[name] < sh.ncols else "")
        cur = None
        for r in range(1, sh.nrows):
            stat["rows"] += 1
            q = cell(r, "질문내용")
            if re.sub(r"\s+", "", q) == "질문내용":   # 시트 중간 반복 헤더
                continue
            a, note = cell(r, "답변"), cell(r, "비고")
            client = one_line(cell(r, "고객사"))       # 셀 내 개행 정리("리딩투자⏎증권")
            if client in ("고객사", "-"):               # 헤더 아티팩트 정제
                client = ""
            if q:                                       # 새 쌍 시작
                stat["q_rows"] += 1
                cur = {"q": q, "a": a, "clients": [client] if client else [], "note": note}
                pairs.append(cur)
            elif cur is not None:                       # 연속 행 — 각 필드에 병합
                if a:
                    cur["a"] = (cur["a"] + "\n" + a).strip()
                if note:
                    cur["note"] = (cur["note"] + "\n" + note).strip()
                if client and client not in cur["clients"]:
                    cur["clients"].append(client)
    kept = []
    for p in pairs:
        if len(one_line(p["q"])) < MIN_LEN or len(one_line(p["a"])) < MIN_LEN:
            stat["dropped"] += 1
            continue
        kept.append(p)
    stat["pairs"] = len(kept)
    return kept, stat


def dedup_merge(pairs: list[dict]) -> tuple[list[dict], int]:
    """완전 중복(질문+답변) → 1건으로 병합(고객사 목록 합침, 비고 상이 시 이어붙임)."""
    by_key: dict[str, dict] = {}
    order: list[str] = []
    for p in pairs:
        key = hashlib.sha1((one_line(p["q"]) + "\x00" + one_line(p["a"])).encode()).hexdigest()
        if key in by_key:
            tgt = by_key[key]
            for c in p["clients"]:
                if c not in tgt["clients"]:
                    tgt["clients"].append(c)
            if p["note"] and p["note"] not in tgt["note"]:
                tgt["note"] = (tgt["note"] + "\n" + p["note"]).strip()
        else:
            by_key[key] = p
            order.append(key)
    merged = [by_key[k] for k in order]
    return merged, len(pairs) - len(merged)


def to_chunk(p: dict, sector: str, screen_id: str, title: str, n: int) -> dict:
    # 마스킹은 중복병합 뒤(여기서) 적용 — 쌍 수·id 순번이 마스킹과 무관하게 안정
    p = {**p, "q": mask_pii(p["q"]), "a": mask_pii(p["a"]), "note": mask_pii(p["note"])}
    q1 = one_line(p["q"])
    tail = []
    if p["clients"]:
        tail.append("고객사: " + ", ".join(p["clients"]))
    if p["note"]:
        tail.append("비고: " + one_line(p["note"]))
    text = f"Q. {p['q']}\nA. {p['a']}"
    if tail:
        text += "\n― " + " · ".join(tail)
    embed = f"[상담/{sector}] {q1} : {one_line(p['a'])}"
    if tail:
        embed += " (" + ", ".join(tail) + ")"
    return {
        "id": f"cs:{sector}:{n:04d}",
        "manual": "상담",
        "sector": sector,
        "sector_path": ["상담", sector],
        "screen_id": screen_id,
        "screen_no": "",
        "title": title,
        "source_url": "",
        "chunk_type": "qa",
        "section_path": ["상담사례", q1[:120]],
        "path_str": f"상담 > {sector} > {q1[:60]}",
        "term": "",
        "text": text,
        "embed_text": embed[:EMBED_CAP],
    }


def main():
    files = sorted(SRC_DIR.glob("*.xls"))
    if not files:
        sys.exit(f"[counsel] {SRC_DIR} 에 .xls 없음")
    all_chunks: list[dict] = []
    print(f"{'업무':16} {'행':>6} {'Q행':>6} {'쌍':>6} {'중복병합':>6} {'최종':>6}")
    tot = dict(rows=0, q_rows=0, pairs=0, merged=0, final=0)
    for i, f in enumerate(files, 1):
        sector = sector_name(f.name)
        pairs, st = parse_file(f)
        merged, n_dup = dedup_merge(pairs)
        sid, title = f"CS{i:02d}", f"{sector} 상담 Q&A"
        chunks = [to_chunk(p, sector, sid, title, k + 1) for k, p in enumerate(merged)]
        all_chunks.extend(chunks)
        print(f"{sector:16} {st['rows']:>6} {st['q_rows']:>6} {st['pairs']:>6} {n_dup:>6} {len(chunks):>6}")
        tot["rows"] += st["rows"]; tot["q_rows"] += st["q_rows"]
        tot["pairs"] += st["pairs"]; tot["merged"] += n_dup; tot["final"] += len(chunks)
    print(f"{'합계':16} {tot['rows']:>6} {tot['q_rows']:>6} {tot['pairs']:>6} {tot['merged']:>6} {tot['final']:>6}")

    # ── 골든 스모크(실사 근거) — 회귀 방지선 ──
    acct = [c for c in all_chunks if c["sector"] == "계좌"]
    assert acct and acct[0]["text"].startswith("Q. SMS발송 내역이"), "계좌 첫 쌍 골든 불일치"
    assert "IBK투자증권" in acct[0]["text"], "고객사 보존 실패"
    assert {c["sector"] for c in all_chunks} == {sector_name(f.name) for f in files}, "업무 19종 불일치"
    assert all(c["sector_path"][0] == "상담" and len(c["sector_path"]) == 2 for c in all_chunks), "1-level 스코프 위반"

    multi = sorted((c for c in all_chunks if c["text"].count(",") and "고객사: " in c["text"]
                    and ", " in c["text"].split("고객사: ")[-1]),
                   key=lambda c: -len(c["text"].split("고객사: ")[-1]))[:5]
    print("\n[고객사 병합 샘플(복수 고객사 상위 5)]")
    for c in multi:
        print(" ·", c["id"], "→", c["text"].split("― ")[-1][:90])
    noted = [c for c in all_chunks if "비고: " in c["text"]][:3]
    print("[비고 보존 샘플]")
    for c in noted:
        print(" ·", c["id"], "→", c["text"].split("― ")[-1][:90])

    if "--stats" in sys.argv:
        print("\n(--stats: 파일 미기록)")
        return
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as fp:
        for c in all_chunks:
            fp.write(json.dumps(c, ensure_ascii=False) + "\n")
    print(f"\n[counsel] {len(all_chunks)}청크 → {OUT}")


if __name__ == "__main__":
    main()
