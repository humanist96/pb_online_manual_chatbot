"""AICC 정제 도구(refine_aicc.py) 회귀 테스트.

LLM 호출 없이 검증 가능한 부분만: 자동 게이트 판정, L1 패턴 적용, 화면번호 문맥
추출+lexicon 대조, 인사말 실명 마스킹, 대장 스키마, 카드 id 형식, LLM 주입/모킹.
합성 fixture를 tempdir에 생성해 사용한다. pytest 금지 — unittest 스타일.

  .venv/bin/python tests/test_refine_aicc.py
"""
from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "deploy" / "online"))

import refine_aicc as R  # noqa: E402


LEXICON = {
    "screen_nos": {"2876": "예탁금이용료지급내역", "3354": "예탁금이용료현황",
                   "5333": "계좌별종목조회", "2150": "고객정보조회"},
    "terms": ["예탁금이용료", "반대매매", "미수", "투자신탁"],
    "titles": ["예탁금이용료지급내역", "고객정보조회"],
    "seed": ["PowerBASE", "파워베이스", "코스콤"],
}


class GateTests(unittest.TestCase):
    def test_short_transcript(self):
        r = R.gate({"chars": 150, "avg_logprob": -0.2})
        self.assertIn("stt_short", r)
        self.assertNotIn("stt_lowconf", r)

    def test_lowconf(self):
        r = R.gate({"chars": 500, "avg_logprob": -0.40})
        self.assertIn("stt_lowconf", r)
        self.assertNotIn("stt_short", r)

    def test_pass(self):
        self.assertEqual(R.gate({"chars": 500, "avg_logprob": -0.2}), [])

    def test_both(self):
        r = R.gate({"chars": 100, "avg_logprob": -0.5})
        self.assertEqual(set(r), {"stt_short", "stt_lowconf"})

    def test_tau_arg(self):
        self.assertEqual(R.gate({"chars": 500, "avg_logprob": -0.30}, tau_logprob=-0.35), [])
        self.assertIn("stt_lowconf",
                      R.gate({"chars": 500, "avg_logprob": -0.30}, tau_logprob=-0.25))


class L1FixTests(unittest.TestCase):
    def test_apply_fixes(self):
        txt = "네, 항상 친절하겠습니다. 코스콤입니다."
        out, corr = R.apply_fixes(txt, {"친절하겠습니다": "친절하게 모시겠습니다"})
        self.assertIn("친절하게 모시겠습니다", out)
        self.assertEqual(len(corr), 1)
        self.assertEqual(corr[0]["from"], "친절하겠습니다")
        self.assertEqual(corr[0]["to"], "친절하게 모시겠습니다")

    def test_no_match_no_correction(self):
        out, corr = R.apply_fixes("변경 없음 문장", {"없는패턴": "대체"})
        self.assertEqual(out, "변경 없음 문장")
        self.assertEqual(corr, [])

    def test_ensure_fixes_file_created(self):
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d) / "aicc_fixes.json"
            fixes = R.ensure_fixes_file(p)
            self.assertTrue(p.exists())
            self.assertEqual(fixes, R.DEFAULT_FIXES)
            self.assertIn("친절하겠습니다", fixes)

    def test_ensure_fixes_file_existing(self):
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d) / "aicc_fixes.json"
            p.write_text(json.dumps({"a": "b"}, ensure_ascii=False), encoding="utf-8")
            self.assertEqual(R.ensure_fixes_file(p), {"a": "b"})


class ScreenNoTests(unittest.TestCase):
    def test_context_and_lexicon(self):
        txt = "지금 2876 화면 보고 계신가요? 화면번호 3354도 확인해주세요."
        out = R.extract_screen_nos(txt, LEXICON)
        self.assertIn("2876", out)
        self.assertIn("3354", out)

    def test_reject_non_lexicon(self):
        # 9999는 문맥은 맞지만 lexicon에 없음 → 제외
        txt = "9999 화면 보세요."
        self.assertEqual(R.extract_screen_nos(txt, LEXICON), [])

    def test_reject_no_context(self):
        # 문맥 패턴 없는 4자리(에러코드·펀드번호 등) → 제외
        txt = "에러코드 2876 발생, 펀드번호 3354 조회."
        self.assertEqual(R.extract_screen_nos(txt, LEXICON), [])

    def test_number_followed_by_beon(self):
        txt = "5333번을 보시면 됩니다."
        self.assertIn("5333", R.extract_screen_nos(txt, LEXICON))

    def test_dedup(self):
        txt = "2876 화면, 2876번 다시 2876 화면."
        self.assertEqual(R.extract_screen_nos(txt, LEXICON), ["2876"])


class MaskTests(unittest.TestCase):
    def test_greeting_name(self):
        out, n = R.mask_speech_names("코스콤 고객지원센터 홍길순입니다.")
        self.assertIn("홍**입니다", out)
        self.assertNotIn("홍길순", out)
        self.assertGreaterEqual(n, 1)

    def test_greeting_two_char_name(self):
        out, _ = R.mask_speech_names("고객지원센터 김철입니다.")
        self.assertIn("김*입니다", out)
        self.assertNotIn("김철입니다", out)

    def test_honorific_name(self):
        out, _ = R.mask_speech_names("홍길동 대리님 찾으세요?")
        self.assertNotIn("홍길동", out)
        self.assertIn("대리님", out)

    def test_self_intro_name(self):
        out, _ = R.mask_speech_names("성함은 홍길동입니다.")
        self.assertNotIn("홍길동입니다", out)

    def test_phone(self):
        out, _ = R.mask_speech_names("전화번호는 010-9876-5432입니다.")
        self.assertNotIn("9876", out)
        self.assertIn("010-****-****", out)

    def test_mask_all_reuses_mask_pii(self):
        out, _ = R.mask_all("계좌 123-45-678901 입니다")
        self.assertNotIn("678901", out)

    def test_residual_scan_clean_after_mask(self):
        out, _ = R.mask_speech_names("고객지원센터 홍길순입니다.")
        # 실명은 사라져야 함(홍길순 → 홍**)
        self.assertNotIn("홍길순", out)

    def test_greeting_variant_gaeksenteo(self):
        # "고객센터"(지원 없는 변형)도 마스킹
        out, _ = R.mask_speech_names("코스콤 고객센터 이몽입니다.")
        self.assertNotIn("이몽입니다", out)

    def test_greeting_indeyo_suffix(self):
        out, _ = R.mask_speech_names("고객센터 김나래인데요.")
        self.assertNotIn("김나래", out)

    def test_company_intro_name(self):
        out, _ = R.mask_speech_names("삼성자산운용 홍길동입니다.")
        self.assertNotIn("홍길동", out)
        self.assertIn("삼성자산운용", out)

    def test_dept_intro_name(self):
        out, _ = R.mask_speech_names("IBK 투자증권 감사부의 두리입니다.")
        self.assertNotIn("두리입니다", out)

    def test_sangdamwon_name(self):
        out, _ = R.mask_speech_names("상담원 김나래였습니다.")
        self.assertNotIn("김나래", out)

    def test_bare_name_iyo(self):
        out, _ = R.mask_speech_names("홍길동이요.")
        self.assertNotIn("홍길동", out)

    def test_honorific_with_particle(self):
        # -님 뒤 조사가 붙어도 마스킹(전량 실행에서 발견된 누락 회귀)
        out, _ = R.mask_speech_names("해외채권 관련해서 김미소 차장님과 통화하고 싶어서요.")
        self.assertNotIn("김미소", out)
        out, _ = R.mask_speech_names("성춘향 사원님 자리에 계신가요.")
        self.assertNotIn("성춘향", out)

    def test_honorific_stop_no_overmask(self):
        # 직함 앞 일반명사는 마스킹하지 않음
        for s in ("담당 대리님께 전달해 주세요", "저희 과장님이 요청하셨어요", "대리점에서 처리하시면 됩니다"):
            out, _ = R.mask_speech_names(s)
            self.assertEqual(out, s, f"과마스킹: {s} -> {out}")

    def test_bare_stop_no_overmask(self):
        # 서술형 명사는 문장 첫머리라도 마스킹하지 않음
        for s in ("확인입니다", "예정입니다", "과제입니다", "사원입니다", "예전입니다"):
            out, _ = R.mask_speech_names(s)
            self.assertEqual(out, s, f"과마스킹: {s} -> {out}")


class LedgerSchemaTests(unittest.TestCase):
    def test_row_keys_and_status(self):
        row = R.ledger_row("abc12345", "indexed", ["ok"],
                           {"chars": 500, "avg_logprob": -0.2, "segments": 8,
                            "role_resolved": True}, ["cc:abc12345:0001"])
        for k in ("recording_id", "status", "reason", "metrics", "card_ids",
                  "masked", "refined_at"):
            self.assertIn(k, row)
        self.assertEqual(row["status"], "indexed")
        self.assertTrue(row["masked"])
        for mk in ("chars", "avg_logprob", "segments", "role_resolved"):
            self.assertIn(mk, row["metrics"])

    def test_reason_codes_valid(self):
        for code in ("stt_short", "stt_lowconf", "role_unresolved",
                     "unresolved", "no_value", "ambiguous", "llm_error"):
            self.assertIn(code, R.VALID_REASONS)

    def test_ledger_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d) / "aicc_ledger.jsonl"
            rows = {"b": R.ledger_row("b", "excluded", ["stt_short"], {}, []),
                    "a": R.ledger_row("a", "indexed", ["ok"], {}, ["cc:a:0001"])}
            R.write_ledger(rows, p)
            back = R.load_ledger(p)
            self.assertEqual(set(back), {"a", "b"})
            self.assertEqual(back["a"]["status"], "indexed")
            # 정렬 기록 확인(a가 b보다 먼저)
            lines = p.read_text(encoding="utf-8").splitlines()
            self.assertTrue(lines[0].index('"a"') >= 0)


class CardNormalizeTests(unittest.TestCase):
    def test_card_id_format(self):
        raw = [{"issue": "질문", "answer": "정답", "screen_nos": ["2876"],
                "resolved": True, "clarity": "clear"}]
        cards = R.normalize_cards(raw, "abc12345", ["2876"], {})
        self.assertEqual(cards[0]["id"], "cc:abc12345:0001")
        import re
        self.assertRegex(cards[0]["id"], r"^cc:[0-9a-f]{8}:\d{4}$")

    def test_screen_nos_defense(self):
        # LLM이 verified 밖 번호를 넣어도 코드가 제거
        raw = [{"issue": "q", "answer": "a", "screen_nos": ["2876", "9999"],
                "resolved": True, "clarity": "clear"}]
        cards = R.normalize_cards(raw, "abc12345", ["2876"], {})
        self.assertEqual(cards[0]["screen_nos"], ["2876"])

    def test_multiple_cards_indexed(self):
        raw = [{"issue": "q1", "answer": "a1", "resolved": True, "clarity": "clear"},
               {"issue": "q2", "answer": "a2", "resolved": True, "clarity": "clear"}]
        cards = R.normalize_cards(raw, "deadbeef", [], {})
        self.assertEqual([c["id"] for c in cards],
                         ["cc:deadbeef:0001", "cc:deadbeef:0002"])


class ExtractJsonTests(unittest.TestCase):
    def test_plain(self):
        self.assertEqual(R._extract_json('{"a": 1}'), {"a": 1})

    def test_codefence(self):
        self.assertEqual(R._extract_json('```json\n{"a": 1}\n```'), {"a": 1})

    def test_surrounding_text(self):
        self.assertEqual(R._extract_json('설명\n{"a": {"b": 2}}\n끝'), {"a": {"b": 2}})


class ProcessCallTests(unittest.TestCase):
    """LLM을 모킹해 통화 처리 흐름(게이트/카드/대장)을 검증."""

    def _make_call(self, d: pathlib.Path, id8: str, text: str, avg=-0.2,
                   role_resolved=True):
        lines = text.strip().splitlines()
        segs = [{"start_ms": i * 1000, "end_ms": i * 1000 + 900,
                 "text": ln, "role": "상담사" if i % 2 == 0 else "고객",
                 "avg_logprob": avg} for i, ln in enumerate(lines)]
        (d / f"{id8}.v3.txt").write_text(text, encoding="utf-8")
        (d / f"{id8}.v3det.json").write_text(
            json.dumps({"recording_id": id8 + "0" * 56, "role_resolved": role_resolved,
                        "segments": segs}, ensure_ascii=False), encoding="utf-8")

    def test_gate_excluded_no_llm(self):
        with tempfile.TemporaryDirectory() as td:
            d = pathlib.Path(td)
            orig = R.AICC_DIR
            R.AICC_DIR = d
            try:
                self._make_call(d, "11111111", "[상담사] 짧은 통화입니다.\n[고객] 네.")
                called = {"n": 0}

                def fake_llm(prompt, **kw):
                    called["n"] += 1
                    return {}
                row, card, arch = R.process_call(
                    "11111111", LEXICON, {}, {}, R.DEFAULT_TAU_LOGPROB, llm_fn=fake_llm)
                self.assertEqual(row["status"], "excluded")
                self.assertIn("stt_short", row["reason"])
                self.assertEqual(called["n"], 0)  # 게이트 탈락 → LLM 미호출
                self.assertIsNone(card)
            finally:
                R.AICC_DIR = orig

    def test_indexed_with_mock_llm(self):
        with tempfile.TemporaryDirectory() as td:
            d = pathlib.Path(td)
            orig = R.AICC_DIR
            R.AICC_DIR = d
            try:
                long_text = ("[상담사] 코스콤 고객지원센터입니다.\n"
                             "[고객] 2876 화면 예탁금이용료 조회 방법 알려주세요. " * 20)
                self._make_call(d, "22222222", long_text)

                def fake_llm(prompt, **kw):
                    self.assertIn("2876", prompt)  # verified 화면번호 주입 확인
                    return {
                        "role_fixed_lines": ["[상담사] ...", "[고객] ..."],
                        "corrections": [{"from": "x", "to": "y", "reason": "test"}],
                        "cards": [{"issue": "예탁금이용료 조회 화면",
                                   "issue_colloquial": "이용료 어디서 봐요",
                                   "answer": "2876 화면에서 조회합니다.",
                                   "screen_nos": ["2876"], "sector_guess": "계좌",
                                   "resolved": True, "clarity": "clear",
                                   "evidence": "상담사: 2876에서 조회"}],
                        "verdict": {"indexable": True, "reason": "ok"},
                    }
                row, card, arch = R.process_call(
                    "22222222", LEXICON, {}, {}, R.DEFAULT_TAU_LOGPROB, llm_fn=fake_llm)
                self.assertEqual(row["status"], "indexed")
                self.assertEqual(row["card_ids"], ["cc:22222222:0001"])
                self.assertEqual(len(card["cards"]), 1)
                self.assertTrue(arch["original_masked"])
            finally:
                R.AICC_DIR = orig

    def test_llm_error_excluded(self):
        with tempfile.TemporaryDirectory() as td:
            d = pathlib.Path(td)
            orig = R.AICC_DIR
            R.AICC_DIR = d
            try:
                long_text = "[상담사] 코스콤 고객지원센터입니다. 예탁금이용료 조회 안내드립니다. " * 10
                self._make_call(d, "33333333", long_text)

                def boom(prompt, **kw):
                    raise RuntimeError("cli down")
                row, card, arch = R.process_call(
                    "33333333", LEXICON, {}, {}, R.DEFAULT_TAU_LOGPROB, llm_fn=boom)
                self.assertEqual(row["status"], "excluded")
                self.assertIn("llm_error", row["reason"])
            finally:
                R.AICC_DIR = orig


if __name__ == "__main__":
    unittest.main(verbosity=2)
