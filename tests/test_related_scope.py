"""related_questions 스코프 연동 회귀 테스트.

배경: 질문뱅크의 부문 버킷은 sp[1]만 키로 묶여 매뉴얼을 가로지른다
(예: '계좌' 버킷 = 화면>계좌 질문 + 상담사례>계좌 질문). 스코프가 걸린
답변의 related가 범위 밖 질문을 추천하면, 클릭 시 같은 스코프로 검색되어
근거 0건 막다른 골목이 된다(2026-07-28 실사용 보고). related_questions는
scope 인자를 받아 /api/suggest와 동일한 접두 매칭으로 후보를 걸러야 한다.

합성 뱅크를 주입해 검증한다 — 실데이터 _questions.py 내용에 비의존.
실행: .venv/bin/python -m unittest tests.test_related_scope
"""
from __future__ import annotations

import pathlib
import sys
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "deploy" / "online" / "api"))

import _common as common  # noqa: E402

# 합성 뱅크: 화면>계좌 2건 + 상담사례>계좌 1건 + 상담사례 루트 1건 + 업무 1건
SYN_BANK = [
    {"q": "화면 계좌 질문 A?", "sid": "AC000100", "t": "화면A",
     "sp": ["화면", "계좌", "고객관리"], "m": "화면"},
    {"q": "화면 계좌 질문 B?", "sid": "AC000200", "t": "화면B",
     "sp": ["화면", "계좌"], "m": "화면"},
    {"q": "사례 계좌 질문 C?", "sid": "", "t": "사례C",
     "sp": ["상담사례", "계좌"], "m": "상담사례"},
    {"q": "사례 루트 질문 D?", "sid": "", "t": "사례D",
     "sp": ["상담사례"], "m": "상담사례"},
    {"q": "업무 질문 E?", "sid": "STP00000", "t": "업무E",
     "sp": ["업무", "출납관리"], "m": "업무"},
]


def _buckets(entries):
    by_sid, by_sector = {}, {}
    for e in entries:
        by_sid.setdefault(e.get("sid", ""), []).append(e)
        sp = e.get("sp") or []
        sector = sp[1] if len(sp) >= 2 else (sp[0] if sp else "")
        by_sector.setdefault(sector, []).append(e)
    return by_sid, by_sector


def _patched():
    by_sid, by_sector = _buckets(SYN_BANK)
    return mock.patch.multiple(common, QUESTIONS=SYN_BANK,
                               _BANK_BY_SID=by_sid, _BANK_BY_SECTOR=by_sector)


AICC_HIT = {"screen_id": "", "manual": "상담사례", "sector": "계좌",
            "sector_path": ["상담사례", "계좌"]}
AICC_ROOT_HIT = {"screen_id": "", "manual": "상담사례", "sector": "",
                 "sector_path": ["상담사례"]}
SCREEN_HIT = {"screen_id": "AC000100", "manual": "화면", "sector": "계좌",
              "sector_path": ["화면", "계좌", "고객관리"]}


class RelatedScopeTests(unittest.TestCase):
    def test_unscoped_cross_manual_allowed(self):
        """스코프 없음 = 전체 검색이므로 교차 매뉴얼 추천은 기존대로 허용(크로스링크 기능)."""
        with _patched():
            out = common.related_questions("질의", [AICC_HIT], scope=None)
        self.assertTrue(out)  # '계좌' 버킷에서 화면 질문이 나와도 무해

    def test_scope_aicc_excludes_screen_questions(self):
        """상담사례 스코프에서는 화면매뉴얼 질문이 추천되면 안 된다(핵심 회귀)."""
        with _patched():
            out = common.related_questions("질의", [AICC_HIT], scope=["상담사례"])
        self.assertTrue(out)
        for e in out:
            self.assertIn(e["q"], {"사례 계좌 질문 C?", "사례 루트 질문 D?"},
                          f"범위 밖 질문 추천됨: {e['q']}")

    def test_scope_aicc_sector_excludes_root_level(self):
        """상담사례>계좌 스코프에서는 부문 미배정(루트 직속) 질문도 제외."""
        with _patched():
            out = common.related_questions("질의", [AICC_HIT],
                                           scope=["상담사례", "계좌"])
        self.assertEqual([e["q"] for e in out], ["사례 계좌 질문 C?"])

    def test_scope_screen_excludes_aicc(self):
        """화면>계좌 스코프에서는 상담사례 질문이 추천되면 안 된다(역방향)."""
        with _patched():
            out = common.related_questions("질의", [SCREEN_HIT],
                                           scope=["화면", "계좌"])
        self.assertTrue(out)
        for e in out:
            self.assertTrue(e["q"].startswith("화면"),
                            f"범위 밖 질문 추천됨: {e['q']}")

    def test_scope_deeper_than_entry_path(self):
        """스코프가 질문 경로보다 깊으면 매칭 실패로 제외(suggest와 동일 규칙)."""
        with _patched():
            out = common.related_questions(
                "질의", [SCREEN_HIT],
                scope=["화면", "계좌", "고객관리", "AC000100"])
        # 경로가 정확히 닿는 화면A만 허용 가능(자기 질문 제외 규칙과 무관한 질의어 사용)
        for e in out:
            self.assertEqual(e["q"], "화면 계좌 질문 A?")

    def test_scoped_no_candidates_returns_empty(self):
        """범위 안에 후보가 없으면 빈 목록 — 범위 밖을 채워 넣지 않는다."""
        with _patched():
            out = common.related_questions("질의", [AICC_ROOT_HIT],
                                           scope=["상담", "계좌"])
        self.assertEqual(out, [])


if __name__ == "__main__":
    unittest.main()
