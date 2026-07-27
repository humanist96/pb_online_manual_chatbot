"""AICC 청크 변환기(parse_aicc.py) 골든 테스트.

합성 대장+카드 fixture만 사용(실데이터 파일 비의존 — 진행 중인 refine_aicc 산출물과 무관).
결정적·LLM 불요 변환의 회귀 방지선. pytest 금지 — unittest 스타일.

  .venv/bin/python tests/test_parse_aicc.py
"""
from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "deploy" / "online"))

import parse_aicc as P  # noqa: E402


VALID_SECTORS = {"계좌", "출납", "자산운용"}

# ── 합성 fixture ─────────────────────────────────────────────────────────────
# 대장: indexed 2행(하나는 clear 2카드 중 1개만 색인)·excluded 1행
LEDGER = {
    "aaaa1111": {
        "recording_id": "aaaa1111", "status": "indexed", "reason": ["ok"],
        "metrics": {"chars": 900, "avg_logprob": -0.2, "segments": 12,
                    "role_resolved": True},
        "card_ids": ["cc:aaaa1111:0001"], "masked": True, "refined_at": "x",
    },
    "bbbb2222": {
        "recording_id": "bbbb2222", "status": "indexed", "reason": ["ok"],
        "metrics": {"chars": 700, "avg_logprob": -0.25, "segments": 9,
                    "role_resolved": True},
        "card_ids": ["cc:bbbb2222:0001"], "masked": True, "refined_at": "x",
    },
    "cccc3333": {
        "recording_id": "cccc3333", "status": "excluded", "reason": ["unresolved"],
        "metrics": {"chars": 400, "avg_logprob": -0.3, "segments": 6,
                    "role_resolved": True},
        "card_ids": [], "masked": True, "refined_at": "x",
    },
}

CARDS = {
    # 색인 대상: clear·resolved·유효 부문·화면번호 2개·구어 표현
    "aaaa1111": {
        "recording_id": "aaaa1111",
        "cards": [
            {"id": "cc:aaaa1111:0001",
             "issue": "5333 화면에서 반대매매 대상이 빨간색으로 표시될 때 실제 처리 여부는 어디서 확인하나요?",
             "issue_colloquial": "5333에서 미수라고 빨갛게 뜨는데 믿어도 되나요?",
             "answer": "5333의 빨간 표시는 후보라 정확하지 않고, 실제 처리 내역은 5339에서 계좌를 조회해 확인해야 한다.",
             "screen_nos": ["5333", "5339"], "sector_guess": "계좌",
             "resolved": True, "clarity": "clear", "evidence": "근거"},
            # 같은 통화의 두 번째 카드(ambiguous)는 card_ids에 없어 자연 제외
            {"id": "cc:aaaa1111:0002",
             "issue": "계좌 비밀번호는 어떻게 입력하나요?",
             "issue_colloquial": "", "answer": "확정 안내 아님",
             "screen_nos": ["5339"], "sector_guess": "계좌",
             "resolved": False, "clarity": "ambiguous", "evidence": "근거"},
        ],
        "verdict": {"indexable": True, "reason": "ok"},
    },
    # 부문 불일치(코퍼스에 없는 '주문')·화면번호 없음
    "bbbb2222": {
        "recording_id": "bbbb2222",
        "cards": [
            {"id": "cc:bbbb2222:0001",
             "issue": "체결내역과 결제일이 함께 나오는 화면은?",
             "issue_colloquial": "결제일도 같이 보이는 화면 있나요?",
             "answer": "계좌별 거래 현황 화면을 매매 구분으로 조회하면 결제일 기준으로 나온다.",
             "screen_nos": [], "sector_guess": "주문",
             "resolved": True, "clarity": "clear", "evidence": "근거"},
        ],
        "verdict": {"indexable": True, "reason": "ok"},
    },
    "cccc3333": {"recording_id": "cccc3333", "cards": [], "verdict": {}},
}


class BuildChunksTests(unittest.TestCase):
    def setUp(self):
        self.chunks, self.stats = P.build_chunks(LEDGER, CARDS, VALID_SECTORS, warn=False)
        self.by_id = {c["id"]: c for c in self.chunks}

    def test_only_indexed_clear_cards(self):
        # indexed 2행 × 각 card_ids 1개 = 청크 2개, excluded 행·ambiguous 카드 제외
        self.assertEqual(len(self.chunks), 2)
        self.assertEqual(set(self.by_id), {"cc:aaaa1111:0001", "cc:bbbb2222:0001"})
        self.assertNotIn("cc:aaaa1111:0002", self.by_id)   # ambiguous 미포함

    def test_stats(self):
        self.assertEqual(self.stats["indexed_rows"], 2)
        self.assertEqual(self.stats["cards_seen"], 2)
        self.assertEqual(self.stats["chunks"], 2)

    def test_fifteen_fields_present(self):
        expected = {"id", "screen_id", "code", "aup", "screen_no", "title",
                    "source_url", "manual", "sector", "sector_path", "chunk_type",
                    "section_path", "path_str", "term", "text", "embed_text"}
        for c in self.chunks:
            self.assertEqual(set(c), expected, f"필드셋 불일치: {c['id']}")

    def test_fixed_field_shapes(self):
        for c in self.chunks:
            self.assertEqual(c["manual"], "상담사례")
            self.assertEqual(c["chunk_type"], "qa")
            self.assertEqual(c["term"], "")
            self.assertEqual(c["screen_id"], "")
            self.assertEqual(c["code"], "")
            self.assertEqual(c["aup"], "")
            self.assertEqual(c["source_url"], "")
            self.assertEqual(c["sector_path"][0], "상담사례")
            self.assertEqual(c["section_path"][0], "상담사례")
            self.assertRegex(c["id"], r"^cc:[0-9a-f]{8}:\d{4}$")

    def test_sector_only_when_corpus_match(self):
        # 계좌: 코퍼스 존재 → 2-level, 부문 채움
        a = self.by_id["cc:aaaa1111:0001"]
        self.assertEqual(a["sector"], "계좌")
        self.assertEqual(a["sector_path"], ["상담사례", "계좌"])
        # 주문: 코퍼스에 없음 → 빈 부문, 1-level
        b = self.by_id["cc:bbbb2222:0001"]
        self.assertEqual(b["sector"], "")
        self.assertEqual(b["sector_path"], ["상담사례"])

    def test_screen_no_first_value(self):
        a = self.by_id["cc:aaaa1111:0001"]
        self.assertEqual(a["screen_no"], "5333")          # 첫 값 채택
        b = self.by_id["cc:bbbb2222:0001"]
        self.assertEqual(b["screen_no"], "")              # 없으면 빈 값

    def test_text_format(self):
        a = self.by_id["cc:aaaa1111:0001"]
        self.assertTrue(a["text"].startswith("Q. "))
        self.assertIn("\nA. ", a["text"])

    def test_title_format(self):
        a = self.by_id["cc:aaaa1111:0001"]
        self.assertTrue(a["title"].startswith("상담사례: "))

    def test_embed_prefix_and_screenno_injection(self):
        a = self.by_id["cc:aaaa1111:0001"]
        # 부문 있는 카드: "[상담사례/계좌] " 접두
        self.assertTrue(a["embed_text"].startswith("[상담사례/계좌] "))
        # 화면번호 주입(공백 구분, 전 화면번호)
        self.assertIn("화면번호 5333 5339", a["embed_text"])
        # 구어 표현 병기
        self.assertIn("(고객 표현: ", a["embed_text"])
        # 부문 없는 카드: 화면번호 없으면 접두만
        b = self.by_id["cc:bbbb2222:0001"]
        self.assertTrue(b["embed_text"].startswith("[상담사례] "))
        self.assertNotIn("화면번호", b["embed_text"])

    def test_embed_cap(self):
        for c in self.chunks:
            self.assertLessEqual(len(c["embed_text"]), P.EMBED_CAP)


class CardLevelDefenseTests(unittest.TestCase):
    def test_ambiguous_card_excluded_even_if_ledger_references_it(self):
        # 대장이 잘못 참조해도(이중 방어) clarity!=clear 카드는 제외
        led = {"zz": {"recording_id": "zz", "status": "indexed", "reason": ["ok"],
                      "metrics": {}, "card_ids": ["cc:zz:0001"], "masked": True}}
        cards = {"zz": {"recording_id": "zz", "cards": [
            {"id": "cc:zz:0001", "issue": "q", "answer": "a", "screen_nos": [],
             "sector_guess": "", "resolved": True, "clarity": "ambiguous"}]}}
        chunks, stats = P.build_chunks(led, cards, VALID_SECTORS, warn=False)
        self.assertEqual(chunks, [])
        self.assertEqual(stats["card_excluded"], 1)

    def test_unresolved_card_excluded(self):
        led = {"zz": {"recording_id": "zz", "status": "indexed", "reason": ["ok"],
                      "metrics": {}, "card_ids": ["cc:zz:0001"], "masked": True}}
        cards = {"zz": {"recording_id": "zz", "cards": [
            {"id": "cc:zz:0001", "issue": "q", "answer": "a", "screen_nos": [],
             "sector_guess": "", "resolved": False, "clarity": "clear"}]}}
        chunks, _ = P.build_chunks(led, cards, VALID_SECTORS, warn=False)
        self.assertEqual(chunks, [])

    def test_empty_answer_excluded(self):
        led = {"zz": {"recording_id": "zz", "status": "indexed", "reason": ["ok"],
                      "metrics": {}, "card_ids": ["cc:zz:0001"], "masked": True}}
        cards = {"zz": {"recording_id": "zz", "cards": [
            {"id": "cc:zz:0001", "issue": "q", "answer": "", "screen_nos": [],
             "sector_guess": "", "resolved": True, "clarity": "clear"}]}}
        chunks, _ = P.build_chunks(led, cards, VALID_SECTORS, warn=False)
        self.assertEqual(chunks, [])


class MaskReapplyTests(unittest.TestCase):
    def test_clean_card_no_change(self):
        # 이미 마스킹된(인명 없는) 카드 → 재마스킹 무변화, 경고 없이 청크 생성
        card = {"id": "cc:dddd4444:0001",
                "issue": "예탁금이용료는 어디서 조회하나요?",
                "issue_colloquial": "이용료 화면 어디예요?",
                "answer": "2876 화면에서 조회합니다.",
                "screen_nos": ["2876"], "sector_guess": "출납",
                "resolved": True, "clarity": "clear"}
        chunk = P.card_to_chunk(card, VALID_SECTORS, warn=False)
        self.assertIsNotNone(chunk)
        # 재마스킹 무변화 = 마스킹 함수가 다시 돌려도 동일
        self.assertEqual(P.remask(chunk["text"]), chunk["text"])
        self.assertEqual(P.remask(chunk["embed_text"]), chunk["embed_text"])


class DeterminismTests(unittest.TestCase):
    def _write_fixture(self, d: pathlib.Path):
        (d / "aicc_ledger.jsonl").write_text(
            "\n".join(json.dumps(LEDGER[k], ensure_ascii=False) for k in sorted(LEDGER)),
            encoding="utf-8")
        (d / "aicc_cards.json").write_text(
            json.dumps(CARDS, ensure_ascii=False), encoding="utf-8")
        # 부문명 대조용 최소 코퍼스
        (d / "chunks.jsonl").write_text(
            "\n".join(json.dumps({"sector": s}, ensure_ascii=False) for s in VALID_SECTORS),
            encoding="utf-8")

    def test_byte_identical_two_runs(self):
        with tempfile.TemporaryDirectory() as td:
            d = pathlib.Path(td)
            self._write_fixture(d)
            out1, out2 = d / "o1.jsonl", d / "o2.jsonl"
            common = ["--ledger", str(d / "aicc_ledger.jsonl"),
                      "--cards", str(d / "aicc_cards.json"),
                      "--chunks", str(d / "chunks.jsonl")]
            P.main(common + ["--out", str(out1)])
            P.main(common + ["--out", str(out2)])
            self.assertEqual(out1.read_bytes(), out2.read_bytes())
            # 산출 확인: 2청크·id 정렬
            lines = out1.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 2)
            ids = [json.loads(x)["id"] for x in lines]
            self.assertEqual(ids, sorted(ids))


if __name__ == "__main__":
    unittest.main(verbosity=2)
