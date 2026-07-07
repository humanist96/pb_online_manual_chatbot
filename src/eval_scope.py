"""
교차 오염 평가 — 전 부문 확장의 "겹치지 않음"을 수치로 증명 (전부문확장_계획 P6).

평가 1) 부문별 qa 청크에서 (질문, 정답 화면, 정답 부문) 쌍을 균형 샘플
        → Recall@5(정답 화면 포함률) · 부문 정확도(1위 근거 부문 = 정답 부문)
        → 같은 질의를 정답 부문 스코프로 재검색했을 때의 개선 폭
평가 2) 동음이의 질의(부문 중복 용어) → 부문 분포·모호성(ambiguous) 감지율

사용:
  HF_HUB_OFFLINE=1 python src/eval_scope.py            # 코사인 게이트(빠름, 기본)
  RERANK_ENABLE=off python src/eval_scope.py --per-sector 3

webapp.search()를 그대로 사용(서버와 동일 코드 경로). 전부 로컬.
"""
from __future__ import annotations
import sys
import json
import random

import webapp  # noqa: E402 — 인덱스·임베더 로딩 포함

PER_SECTOR = 5
if "--per-sector" in sys.argv:
    PER_SECTOR = int(sys.argv[sys.argv.index("--per-sector") + 1])

# 부문 중복이 의심되는 동음이의 질의 (교차 오염 스트레스 세트)
HOMONYM_QUERIES = [
    "약정 해지는 어디서 하나요", "수수료 조회", "비밀번호 변경 방법",
    "계좌번호 조회", "미수금 처리", "승인 처리 화면", "일별 현황 조회",
    "등록 내역 정정", "출금 한도", "담보 관리", "만기 처리", "이자 계산",
    "고객 정보 변경", "취소 처리 방법", "마감 처리", "잔고 조회",
    "신청 내역 조회", "권한 등록", "보고서 출력", "오류 정정",
]


def eval_recall():
    by_sector: dict[str, list[dict]] = {}
    for c in webapp._chunks:
        if c.get("chunk_type") != "qa" or not c.get("sector"):
            continue
        q = (c.get("section_path") or [""])[-1].strip()
        if q.endswith("?") and 8 <= len(q) <= 70:
            by_sector.setdefault(c["sector"], []).append(c)
    rng = random.Random(42)
    cases = []
    for s, arr in sorted(by_sector.items()):
        rng.shuffle(arr)
        seen = set()
        for c in arr:
            if c["screen_id"] in seen:
                continue
            seen.add(c["screen_id"])
            cases.append(c)
            if len(seen) >= PER_SECTOR:
                break

    n = len(cases)
    r5_open = r5_scoped = sec_acc = amb = 0
    for c in cases:
        q = c["section_path"][-1]
        hits, _ = webapp.search(q, 0.5, 5, None, use_rerank=False)
        screens = [h["screen_id"] for h in hits]
        r5_open += c["screen_id"] in screens
        if hits:
            sec_acc += (hits[0].get("sector") == c["sector"])
        amb += webapp._scope_hint(hits)["ambiguous"]
        hits_s, _ = webapp.search(q, 0.5, 5, None, use_rerank=False,
                                  scope=[c.get("manual") or "화면", c["sector"]])
        r5_scoped += c["screen_id"] in [h["screen_id"] for h in hits_s]

    print(f"\n── 평가 1: 부문별 qa {n}건 (부문당 ≤{PER_SECTOR}) · 코사인 게이트 ──")
    print(f"  Recall@5  스코프 없음  {r5_open}/{n} = {r5_open/n:.1%}")
    print(f"  Recall@5  부문 스코프  {r5_scoped}/{n} = {r5_scoped/n:.1%}   (개선 {r5_scoped-r5_open:+d})")
    print(f"  부문 정확도(top1)      {sec_acc}/{n} = {sec_acc/n:.1%}")
    print(f"  모호성 감지율           {amb}/{n} = {amb/n:.1%}  (qa 원질문은 낮아야 정상)")


def eval_homonym():
    n = len(HOMONYM_QUERIES)
    amb = 0
    multi = 0
    print(f"\n── 평가 2: 동음이의 질의 {n}건 — 부문 분포 ──")
    for q in HOMONYM_QUERIES:
        hits, _ = webapp.search(q, 0.5, 5, None, use_rerank=False)
        hint = webapp._scope_hint(hits)
        secs = hint["sectors"]
        multi += len(secs) >= 2
        amb += hint["ambiguous"]
        top = " · ".join(f"{s['sector']}({s['count']},{s['best']:.2f})" for s in secs[:3])
        mark = "⚠" if hint["ambiguous"] else " "
        print(f"  {mark} {q:<16} → {top}")
    print(f"\n  다부문 분산 {multi}/{n} = {multi/n:.0%} · 모호성 감지 {amb}/{n} = {amb/n:.0%}"
          f"  (동음이의 세트는 높아야 정상 — 배너가 뜰 상황)")


# 화면(조작법)·업무(절차) 양쪽에 존재하는 교차 질의 — 매뉴얼 모호성 스트레스 세트
MANUAL_CROSS_QUERIES = [
    "계좌 개설", "계좌 해지", "출금 처리", "입금 처리", "고객 정보 등록",
    "카드 발급", "비밀번호 등록", "계좌 이관", "명의 변경", "상속 처리",
    "대리인 등록", "휴면 계좌", "증거금 관리", "수표 지급", "어음 관리",
    "펀드 매수", "신용 거래", "대체 출고", "배당 처리", "권리 행사",
]


def eval_manual_cross():
    """평가 3: 매뉴얼 교차 — ①스코프 없음: 매뉴얼 모호성 감지 ②scope 지정: 완전 분리."""
    if not any(c.get("manual") == "업무" for c in webapp._chunks):
        print("\n── 평가 3: 건너뜀 — 인덱스에 업무매뉴얼 청크 없음 (재색인 전) ──")
        return
    n = len(MANUAL_CROSS_QUERIES)
    amb = both = leak_s = leak_p = 0
    print(f"\n── 평가 3: 매뉴얼 교차 질의 {n}건 — 화면/업무 분리 ──")
    for q in MANUAL_CROSS_QUERIES:
        hits, _ = webapp.search(q, 0.5, 5, None, use_rerank=False)
        hint = webapp._scope_hint(hits)
        mans = {m["manual"] for m in hint.get("manuals", [])}
        both += len(mans) >= 2
        amb += bool(hint.get("ambiguous_manual"))
        h_s, _ = webapp.search(q, 0.5, 5, None, use_rerank=False, scope=["화면"])
        h_p, _ = webapp.search(q, 0.5, 5, None, use_rerank=False, scope=["업무"])
        leak_s += any(h.get("manual") == "업무" for h in h_s)
        leak_p += any(h.get("manual") == "화면" for h in h_p)
        dist = " · ".join(f"{m['manual']}({m['count']},{m['best']:.2f})"
                          for m in hint.get("manuals", []))
        mark = "⚠" if hint.get("ambiguous_manual") else " "
        print(f"  {mark} {q:<10} → {dist}")
    print(f"\n  양매뉴얼 분산 {both}/{n} = {both/n:.0%} · 매뉴얼 모호성 감지 {amb}/{n} = {amb/n:.0%}")
    print(f"  scope=화면 누수 {leak_s}/{n} · scope=업무 누수 {leak_p}/{n}  (둘 다 0이어야 함)")


if __name__ == "__main__":
    eval_recall()
    eval_homonym()
    eval_manual_cross()
