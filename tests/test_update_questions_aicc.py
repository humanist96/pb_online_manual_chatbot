"""update_questions_aicc.py 회귀 테스트 — 합성 _questions + 청크 + 검증 리포트 fixture.

실제 deploy/online/api/_questions.py를 수정하지 않는다(tempdir에 합성 모듈·청크·리포트를
만들어 검증). 확인 항목: 정상 편입 / 멱등(2회 실행 후 동일 바이트) / self_hit misses 제외 /
리포트 부재 시 중단 / 기존 화면·업무 엔트리 바이트 보존.
실행: .venv/bin/python -m unittest tests.test_update_questions_aicc
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
ONLINE = ROOT / "deploy" / "online"
sys.path.insert(0, str(ONLINE))

import update_questions_aicc as u  # noqa: E402


# ── 합성 fixture ──────────────────────────────────────────────────────────
DOCSTRING = '"""합성 질문뱅크(테스트 전용).\n둘째 줄 — 여러 줄 docstring 보존 확인."""'

EXISTING = [
    {"q": "고객신분 이상 등록 해지는 어느 화면인가요?", "sid": "AC110200",
     "t": "고객신분이상등록내역", "sp": ["화면", "계좌", "고객관리"], "m": "화면"},
    {"q": "투자성향 정정 내역을 조회하려면?", "sid": "AC119600",
     "t": "투자정보확인서 등록/변경내역 조회", "sp": ["화면", "계좌"], "m": "화면"},
    {"q": "신용담보부족반대매매 업무 처리 절차를 알려줘", "sid": "STP06040",
     "t": "신용담보부족반대매매", "sp": ["업무", "현물결제"], "m": "업무"},
]


def aicc_chunk(cid: str, q: str, a: str, sector: str = "계좌") -> dict:
    return {
        "id": cid,
        "screen_id": "",
        "title": f"상담사례: {q[:20]}",
        "manual": "상담사례",
        "sector": sector,
        "sector_path": ["상담사례", sector],
        "chunk_type": "qa",
        "text": f"Q. {q}\nA. {a}",
        "embed_text": f"[상담사례/{sector}] {q} : {a}",
    }


AICC_CHUNKS = [
    aicc_chunk("cc:aaaa1111:0001", "신주인수권 권리금액은 언제 제외되나요?",
               "기준일 익일 배치 후 제외됩니다."),
    aicc_chunk("cc:bbbb2222:0001", "담보비율은 어느 시장 가격 기준인가요?",
               "정규장 기준가로 계산합니다.", sector="주문"),
    aicc_chunk("cc:cccc3333:0001", "폐쇄 계좌 입금분은 어떻게 출금하나요?",
               "별도 적요로 처리합니다."),
]


def write_questions(path: pathlib.Path, entries):
    path.write_text(u.render_questions(DOCSTRING, entries), encoding="utf-8")


def write_chunks(path: pathlib.Path, rows):
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def write_report(path: pathlib.Path, misses, total=len(AICC_CHUNKS)):
    report = {"aicc_chunks": total, "all_pass": not misses, "checks": [
        {"name": "vector_count", "pass": True},
        {"name": "self_hit", "pass": not misses, "hits": total - len(misses),
         "total": total, "misses": list(misses), "best_scores": []},
    ]}
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                    encoding="utf-8")


def load_module_values(path: pathlib.Path):
    spec = importlib.util.spec_from_file_location("_verify_questions", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class UpdateQuestionsAiccTests(unittest.TestCase):
    def _setup(self, tmp, chunks=AICC_CHUNKS, misses=(), entries=None,
               report=True):
        qpath = tmp / "_questions.py"
        write_questions(qpath, json.loads(json.dumps(
            EXISTING if entries is None else entries)))
        cpath = tmp / "chunks_aicc.jsonl"
        write_chunks(cpath, chunks)
        rpath = tmp / "aicc_verify_report.json"
        if report:
            write_report(rpath, misses, total=len(chunks))
        return qpath, cpath, rpath

    def _run(self, qpath, cpath, rpath, extra=()):
        rc = u.main(["--chunks", str(cpath), "--report", str(rpath),
                     "--questions", str(qpath), *extra])
        self.assertEqual(rc, 0)

    # ① 정상 편입
    def test_appends_verified_aicc_entries(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = pathlib.Path(d)
            qpath, cpath, rpath = self._setup(tmp)
            self._run(qpath, cpath, rpath)
            mod = load_module_values(qpath)
            self.assertEqual(len(mod.QUESTIONS), len(EXISTING) + 3)
            aicc = [e for e in mod.QUESTIONS if e["m"] == "상담사례"]
            self.assertEqual(len(aicc), 3)
            # 맨 뒤 append
            self.assertEqual(mod.QUESTIONS[-3:], aicc)
            first = aicc[0]
            self.assertEqual(list(first.keys()), ["q", "sid", "t", "sp", "m"])
            self.assertEqual(first["q"], "신주인수권 권리금액은 언제 제외되나요?")
            self.assertEqual(first["sid"], "")            # 빈 screen_id 그대로
            self.assertEqual(first["t"], "신주인수권 권리금액은 언제 제외되나요")  # 접두 제거
            self.assertFalse(first["t"].startswith("상담사례: "))
            self.assertEqual(first["sp"], ["상담사례", "계좌"])
            self.assertEqual(aicc[1]["sp"], ["상담사례", "주문"])

    # ② 멱등 재실행
    def test_idempotent_on_rerun(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = pathlib.Path(d)
            qpath, cpath, rpath = self._setup(tmp)
            self._run(qpath, cpath, rpath)
            first = qpath.read_bytes()
            self._run(qpath, cpath, rpath)
            self.assertEqual(qpath.read_bytes(), first)
            mod = load_module_values(qpath)
            self.assertEqual(
                len([e for e in mod.QUESTIONS if e["m"] == "상담사례"]), 3)

    def test_rerun_replaces_stale_aicc_entries(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = pathlib.Path(d)
            stale = EXISTING + [
                {"q": "옛 질문", "sid": "", "t": "옛 제목",
                 "sp": ["상담사례", "계좌"], "m": "상담사례"}]
            qpath, cpath, rpath = self._setup(tmp, entries=stale)
            self._run(qpath, cpath, rpath)
            mod = load_module_values(qpath)
            self.assertEqual(len(mod.QUESTIONS), len(EXISTING) + 3)
            self.assertNotIn("옛 질문", [e["q"] for e in mod.QUESTIONS])

    # ③ misses 제외
    def test_excludes_self_hit_misses(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = pathlib.Path(d)
            qpath, cpath, rpath = self._setup(tmp, misses=["cc:bbbb2222:0001"])
            self._run(qpath, cpath, rpath)
            mod = load_module_values(qpath)
            aicc = [e for e in mod.QUESTIONS if e["m"] == "상담사례"]
            self.assertEqual(len(aicc), 2)
            self.assertNotIn("담보비율은 어느 시장 가격 기준인가요?",
                             [e["q"] for e in aicc])

    def test_truncated_misses_list_aborts(self):
        """verify는 misses를 20건까지만 기록 — hits/total과 어긋나면 편입 금지."""
        with tempfile.TemporaryDirectory() as d:
            tmp = pathlib.Path(d)
            qpath, cpath, rpath = self._setup(tmp)
            report = json.loads(rpath.read_text(encoding="utf-8"))
            chk = next(c for c in report["checks"] if c["name"] == "self_hit")
            chk["hits"], chk["misses"] = 1, ["cc:bbbb2222:0001"]  # 2 miss 중 1건만
            rpath.write_text(json.dumps(report, ensure_ascii=False),
                             encoding="utf-8")
            with self.assertRaises(SystemExit) as cm:
                self._run(qpath, cpath, rpath)
            self.assertIn("불완전", str(cm.exception))

    # ④ 리포트 부재 시 중단
    def test_missing_report_aborts(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = pathlib.Path(d)
            qpath, cpath, rpath = self._setup(tmp, report=False)
            before = qpath.read_bytes()
            with self.assertRaises(SystemExit) as cm:
                self._run(qpath, cpath, rpath)
            self.assertIn("검증 리포트가 없습니다", str(cm.exception))
            self.assertEqual(qpath.read_bytes(), before)

    def test_report_without_self_hit_check_aborts(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = pathlib.Path(d)
            qpath, cpath, rpath = self._setup(tmp)
            rpath.write_text(json.dumps(
                {"checks": [{"name": "vector_count", "pass": True}]}),
                encoding="utf-8")
            with self.assertRaises(SystemExit) as cm:
                self._run(qpath, cpath, rpath)
            self.assertIn("self_hit", str(cm.exception))

    def test_missing_chunks_file_errors_clearly(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = pathlib.Path(d)
            qpath, _cpath, rpath = self._setup(tmp)
            with self.assertRaises(SystemExit) as cm:
                self._run(qpath, tmp / "nope.jsonl", rpath)
            self.assertIn("청크 파일이 없습니다", str(cm.exception))

    # ⑤ 기존 화면/업무 엔트리 바이트 보존
    def test_preserves_existing_entries_byte_for_byte(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = pathlib.Path(d)
            qpath, cpath, rpath = self._setup(tmp)
            before = qpath.read_text(encoding="utf-8")
            self._run(qpath, cpath, rpath)
            after = qpath.read_text(encoding="utf-8")
            # 기존 엔트리 줄이 순서·바이트 그대로 유지되고, 상담사례는 그 뒤에만 추가
            self.assertTrue(after.startswith(before[:before.index("]\n")]))
            pos = -1
            for e in EXISTING:
                line = "    " + repr(e) + ","
                idx = after.index(line)
                self.assertLess(pos, idx)
                pos = idx
            self.assertLess(pos, after.index("'m': '상담사례'"))
            # 여러 줄 docstring 보존
            self.assertTrue(after.startswith(DOCSTRING + "\n\nQUESTIONS = ["))
            # import 가능(모듈 문법 유효)
            mod = load_module_values(qpath)
            self.assertEqual(mod.QUESTIONS[:len(EXISTING)], EXISTING)

    def test_dry_run_does_not_write(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = pathlib.Path(d)
            qpath, cpath, rpath = self._setup(tmp)
            before = qpath.read_bytes()
            self._run(qpath, cpath, rpath, extra=["--dry-run"])
            self.assertEqual(qpath.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
