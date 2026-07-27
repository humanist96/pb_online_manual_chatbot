"""update_static_aicc.py 회귀 테스트 — 합성 _static + 청크 fixture.

실제 deploy/online/api/_static.py를 수정하지 않는다(tempdir에 합성 모듈·청크를 만들어
검증). 확인 항목: 상담사례 루트 추가 / 멱등 / 기존 서브트리 바이트 보존 / META count 갱신.
실행: .venv/bin/python -m unittest tests.test_update_static_aicc
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

import update_static_aicc as u  # noqa: E402


# ── 합성 fixture ──────────────────────────────────────────────────────────
SYNTH_META = {
    "embed_model": "synthetic", "dim": 8, "count": 100, "demo": False,
    "reranker": None, "sectors": {"화면": 60, "업무": 25, "상담": 15},
    "samples": ["예시1", "예시2"],
    "gate": {"mode": "cosine", "tau": 0.7, "tau_rerank": 0.7, "tau_cos": 0.7},
}
SYNTH_SECTORS = {"tree": [
    {"name": "화면", "count": 60, "children": [
        {"name": "계좌", "count": 60, "children": [], "screens": [
            {"id": "AC000100", "title": "테스트화면", "no": "1234", "count": 60}]}],
     "screens": []},
    {"name": "업무", "count": 25, "children": [], "screens": []},
    {"name": "상담", "count": 15, "children": [], "screens": []},
]}
DOCSTRING = '"""합성 _static (테스트 전용)."""'


def write_static(path: pathlib.Path, meta, sectors, questions=None):
    path.write_text(u.render_static(DOCSTRING, meta, sectors, questions),
                    encoding="utf-8")


def write_chunks(path: pathlib.Path, rows):
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


AICC_CHUNKS = [
    {"id": "cc:aaaa1111:0001", "sector_path": ["상담사례", "계좌"]},
    {"id": "cc:aaaa1111:0002", "sector_path": ["상담사례", "계좌"]},
    {"id": "cc:bbbb2222:0001", "sector_path": ["상담사례", "주문"]},
    {"id": "cc:cccc3333:0001", "sector_path": ["상담사례"]},  # 부문 없음
]


def load_module_values(path: pathlib.Path):
    spec = importlib.util.spec_from_file_location("_verify_static", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class UpdateStaticAiccTests(unittest.TestCase):
    def _run(self, tmp, chunks=AICC_CHUNKS, meta=None, sectors=None):
        static = tmp / "_static.py"
        write_static(static, json.loads(json.dumps(meta or SYNTH_META)),
                     json.loads(json.dumps(sectors or SYNTH_SECTORS)))
        chunk_path = tmp / "chunks_aicc.jsonl"
        write_chunks(chunk_path, chunks)
        rc = u.main(["--chunks", str(chunk_path), "--static", str(static)])
        self.assertEqual(rc, 0)
        return static

    def test_adds_aicc_root_with_observed_sectors(self):
        with tempfile.TemporaryDirectory() as d:
            static = self._run(pathlib.Path(d))
            mod = load_module_values(static)
            root = next(r for r in mod.SECTORS["tree"] if r["name"] == "상담사례")
            self.assertEqual(root["count"], 4)
            self.assertEqual([c["name"] for c in root["children"]], ["계좌", "주문"])
            for c in root["children"]:
                self.assertEqual(set(c.keys()), {"name", "screens"})
                self.assertEqual(c["screens"], [])
            # META 갱신
            self.assertEqual(mod.META["sectors"]["상담사례"], 4)
            self.assertEqual(mod.META["count"], 104)  # 100 + 4

    def test_sectorless_chunks_yield_empty_children(self):
        with tempfile.TemporaryDirectory() as d:
            chunks = [{"id": "cc:x:0001", "sector_path": ["상담사례"]},
                      {"id": "cc:x:0002", "sector_path": ["상담사례"]}]
            static = self._run(pathlib.Path(d), chunks=chunks)
            mod = load_module_values(static)
            root = next(r for r in mod.SECTORS["tree"] if r["name"] == "상담사례")
            self.assertEqual(root["children"], [])
            self.assertEqual(root["count"], 2)
            self.assertEqual(mod.META["count"], 102)

    def test_preserves_existing_subtrees_byte_for_byte(self):
        with tempfile.TemporaryDirectory() as d:
            static = self._run(pathlib.Path(d))
            new_text = static.read_text(encoding="utf-8")
            # 원본 SECTORS 직렬화의 화면/업무/상담 루트가 그대로 들어있어야 한다.
            for root in SYNTH_SECTORS["tree"]:
                self.assertIn(repr(root), new_text)
            # docstring 보존
            self.assertTrue(new_text.startswith(DOCSTRING + "\n"))
            # 신규 노드는 SECTORS 트리에서 기존 세 루트 뒤(append)
            aicc_node = repr({"name": "상담사례", "count": 4, "children": [
                {"name": "계좌", "screens": []},
                {"name": "주문", "screens": []}], "screens": []})
            self.assertIn(aicc_node, new_text)
            self.assertLess(new_text.index(repr(SYNTH_SECTORS["tree"][2])),
                            new_text.index(aicc_node))

    def test_idempotent_on_rerun(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = pathlib.Path(d)
            static = self._run(tmp)
            first = static.read_text(encoding="utf-8")
            chunk_path = tmp / "chunks_aicc.jsonl"  # 이미 생성됨
            rc = u.main(["--chunks", str(chunk_path), "--static", str(static)])
            self.assertEqual(rc, 0)
            self.assertEqual(static.read_text(encoding="utf-8"), first)
            mod = load_module_values(static)
            roots = [r for r in mod.SECTORS["tree"] if r["name"] == "상담사례"]
            self.assertEqual(len(roots), 1)
            self.assertEqual(mod.META["count"], 104)  # 재실행해도 100+4 유지

    def test_rerun_with_new_counts_updates_in_place(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = pathlib.Path(d)
            static = self._run(tmp)
            # 청크가 늘어난 상황으로 재실행 → count·부문 갱신, 중복 루트 없음
            more = AICC_CHUNKS + [{"id": "cc:dddd:0001",
                                   "sector_path": ["상담사례", "펀드"]}]
            chunk_path = tmp / "chunks_aicc.jsonl"
            write_chunks(chunk_path, more)
            u.main(["--chunks", str(chunk_path), "--static", str(static)])
            mod = load_module_values(static)
            roots = [r for r in mod.SECTORS["tree"] if r["name"] == "상담사례"]
            self.assertEqual(len(roots), 1)
            self.assertEqual(roots[0]["count"], 5)
            self.assertEqual([c["name"] for c in roots[0]["children"]],
                             ["계좌", "주문", "펀드"])
            self.assertEqual(mod.META["count"], 105)   # 100 + 5(기존 4 대체)
            self.assertEqual(mod.META["sectors"]["상담사례"], 5)

    def test_preserves_questions_block_when_present(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = pathlib.Path(d)
            static = tmp / "_static.py"
            write_static(static, json.loads(json.dumps(SYNTH_META)),
                         json.loads(json.dumps(SYNTH_SECTORS)),
                         questions=[{"q": "합성 질문", "sid": "AC000100"}])
            chunk_path = tmp / "chunks_aicc.jsonl"
            write_chunks(chunk_path, AICC_CHUNKS)
            u.main(["--chunks", str(chunk_path), "--static", str(static)])
            mod = load_module_values(static)
            self.assertEqual(mod.QUESTIONS, [{"q": "합성 질문", "sid": "AC000100"}])

    def test_missing_chunks_file_errors_clearly(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = pathlib.Path(d)
            static = tmp / "_static.py"
            write_static(static, json.loads(json.dumps(SYNTH_META)),
                         json.loads(json.dumps(SYNTH_SECTORS)))
            with self.assertRaises(SystemExit) as cm:
                u.main(["--chunks", str(tmp / "nope.jsonl"),
                        "--static", str(static)])
            self.assertIn("청크 파일이 없습니다", str(cm.exception))

    def test_dry_run_does_not_write(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = pathlib.Path(d)
            static = tmp / "_static.py"
            write_static(static, json.loads(json.dumps(SYNTH_META)),
                         json.loads(json.dumps(SYNTH_SECTORS)))
            before = static.read_text(encoding="utf-8")
            chunk_path = tmp / "chunks_aicc.jsonl"
            write_chunks(chunk_path, AICC_CHUNKS)
            rc = u.main(["--chunks", str(chunk_path), "--static", str(static),
                         "--dry-run"])
            self.assertEqual(rc, 0)
            self.assertEqual(static.read_text(encoding="utf-8"), before)


if __name__ == "__main__":
    unittest.main()
