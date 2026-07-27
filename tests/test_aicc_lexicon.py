"""AICC 용어사전 생성기(build_aicc_lexicon.py) 회귀 테스트.

합성 chunks.jsonl(tempfile)로 추출·정렬·결정성을 검증한다. 실데이터에 의존하지
않는다. 실행: .venv/bin/python tests/test_aicc_lexicon.py
"""
from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "deploy" / "online"))

from build_aicc_lexicon import SEED_TERMS, build_lexicon  # noqa: E402


SAMPLE_CHUNKS = [
    {
        "id": "AC110100#0000", "screen_id": "AC110100", "screen_no": "2150",
        "title": "고객정보조회", "manual": "화면", "chunk_type": "description",
        "term": "조건입력", "text": "설명 텍스트",
    },
    {
        # 같은 screen_no 재등장 — 첫 title(고객정보조회)이 대표값으로 유지되어야 함
        "id": "AC110100#0001", "screen_id": "AC110100", "screen_no": "2150",
        "title": "고객정보조회-상세", "manual": "화면", "chunk_type": "description",
        "term": "종합계좌번호", "text": "설명 텍스트2",
    },
    {
        "id": "AC110200#0000", "screen_id": "AC110200", "screen_no": "2474",
        "title": "고객신분이상등록내역", "manual": "화면", "chunk_type": "glossary",
        "term": "채무불이행", "text": "용어 설명",
    },
    {
        "id": "AC110200#0001", "screen_id": "AC110200", "screen_no": "2474",
        "title": "고객신분이상등록내역", "manual": "화면", "chunk_type": "glossary",
        "term": "채무불이행", "text": "중복 용어 — dedup 확인",
    },
    {
        # 용어 길이 하한 미만(1자) — 제외되어야 함
        "id": "AC110200#0002", "screen_id": "AC110200", "screen_no": "2474",
        "title": "고객신분이상등록내역", "manual": "화면", "chunk_type": "glossary",
        "term": "가", "text": "너무 짧은 용어",
    },
    {
        # 용어 길이 상한 초과(41자) — 제외되어야 함
        "id": "AC110200#0003", "screen_id": "AC110200", "screen_no": "2474",
        "title": "고객신분이상등록내역", "manual": "화면", "chunk_type": "glossary",
        "term": "가" * 41, "text": "너무 긴 용어",
    },
    {
        # 공백뿐인 term — 제외
        "id": "AC110200#0004", "screen_id": "AC110200", "screen_no": "2474",
        "title": "고객신분이상등록내역", "manual": "화면", "chunk_type": "glossary",
        "term": "   ", "text": "공백 용어",
    },
    {
        # 업무매뉴얼 — screen_no 빈 값, glossary 아님
        "id": "pm:ACP01010#0000", "screen_id": "ACP01010", "screen_no": "",
        "title": "고객정보및계좌관리체계", "manual": "업무", "chunk_type": "description",
        "term": "계좌관리 체계", "text": "업무 설명",
    },
]


def _write_chunks(dirpath: pathlib.Path, rows) -> pathlib.Path:
    p = dirpath / "chunks.jsonl"
    with p.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return p


class BuildLexiconTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmpdir = pathlib.Path(self._tmp.name)
        self.chunks_path = _write_chunks(self.tmpdir, SAMPLE_CHUNKS)

    def test_screen_nos_dedup_first_value_wins(self):
        lex = build_lexicon(self.chunks_path)
        self.assertEqual(lex["screen_nos"]["2150"], "고객정보조회")
        self.assertEqual(lex["screen_nos"]["2474"], "고객신분이상등록내역")
        self.assertEqual(len(lex["screen_nos"]), 2)
        # numeric-key ordering (문자열 정렬이 아니라 정수 정렬)
        self.assertEqual(list(lex["screen_nos"].keys()), ["2150", "2474"])

    def test_glossary_terms_filtered_and_deduped(self):
        lex = build_lexicon(self.chunks_path)
        self.assertIn("채무불이행", lex["terms"])
        self.assertEqual(lex["terms"].count("채무불이행"), 1)
        # description/업무 chunk_type의 term은 terms에 섞이면 안 됨
        self.assertNotIn("조건입력", lex["terms"])
        self.assertNotIn("계좌관리 체계", lex["terms"])
        # 길이 하한/상한/공백 위반 제외
        self.assertNotIn("가", lex["terms"])
        self.assertNotIn("가" * 41, lex["terms"])
        for t in lex["terms"]:
            self.assertTrue(2 <= len(t) <= 40)

    def test_terms_sorted(self):
        lex = build_lexicon(self.chunks_path)
        self.assertEqual(lex["terms"], sorted(lex["terms"]))

    def test_titles_unique_and_sorted(self):
        lex = build_lexicon(self.chunks_path)
        self.assertEqual(lex["titles"], sorted(set(lex["titles"])))
        self.assertIn("고객정보조회", lex["titles"])
        self.assertIn("고객정보조회-상세", lex["titles"])
        self.assertIn("고객정보및계좌관리체계", lex["titles"])

    def test_seed_present_and_sorted(self):
        lex = build_lexicon(self.chunks_path)
        self.assertEqual(lex["seed"], sorted(set(SEED_TERMS)))
        self.assertIn("PowerBASE", lex["seed"])
        self.assertIn("코스콤", lex["seed"])

    def test_deterministic_output_bytes(self):
        lex1 = build_lexicon(self.chunks_path)
        lex2 = build_lexicon(self.chunks_path)
        bytes1 = json.dumps(lex1, ensure_ascii=False, indent=1).encode("utf-8")
        bytes2 = json.dumps(lex2, ensure_ascii=False, indent=1).encode("utf-8")
        self.assertEqual(bytes1, bytes2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
