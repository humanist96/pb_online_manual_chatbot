"""온라인 공개 데모의 이중 모드 데이터 경계 회귀 테스트.

deploy/online/api/_common.py 는 두 운영 모드를 갖는다.
  · PUBLIC_DEMO 꺼짐(기본) = 접근키 게이트 + 실데이터 운영(현 프로덕션).
    - 익명 서빙 금지(키 없으면 fail-closed), 필터는 scope/type만, META는 그대로 서빙,
      질문 추천은 _questions.py 뱅크에서 로드.
  · PUBLIC_DEMO 켜짐 = 합성 데이터셋(sha256 고정) 전용 fail-closed 강제.
    - 산출물이 승인된 합성 v2가 아니면 검색·메타·인증이 전면 차단,
      Vector 필터·반환 metadata에 합성 정체성(dataset_id 등)을 강제.

외부 Vector/LLM/Redis와 실제 네트워크를 사용하지 않는다(전부 mock).
실행: .venv/bin/python -m unittest tests.test_online_data_boundary
"""
from __future__ import annotations

import json
import pathlib
import tempfile
import sys
import unittest
from unittest import mock


ROOT = pathlib.Path(__file__).resolve().parents[1]
API = ROOT / "deploy" / "online" / "api"
ONLINE = ROOT / "deploy" / "online"
sys.path.insert(0, str(API))
sys.path.insert(0, str(ONLINE))

import _common as common  # noqa: E402
import _static as public_static  # noqa: E402
import gen_demo_data  # noqa: E402
import ingest  # noqa: E402
import ingest_real  # noqa: E402


class HandlerStub:
    def __init__(self, key: str = "", path: str = "/api/meta"):
        self.headers = {"x-demo-key": key} if key else {}
        self.path = path


class RealKeyedModeTests(unittest.TestCase):
    """기본(실데이터) 운영 모드 — PUBLIC_DEMO 꺼짐. 접근키 게이트가 유일한 관문."""

    def test_authorized_accepts_only_matching_header_key(self):
        # 실데이터 모드: 헤더 키가 정확히 일치할 때만 통과(쿼리스트링·오답·무키 전부 거부).
        with mock.patch.object(common, "ACCESS_KEY", "shared-key"):
            self.assertTrue(common.authorized(HandlerStub("shared-key")))
            # 쿼리스트링 ?key= 는 인증 수단이 아니다(헤더 미포함 → 거부).
            self.assertFalse(common.authorized(
                HandlerStub(path="/api/meta?key=shared-key")))
            self.assertFalse(common.authorized(HandlerStub("wrong-key")))
            self.assertFalse(common.authorized(HandlerStub()))

    def test_anonymous_denied_unless_public_demo_opt_in(self):
        # 불변식: 키 미설정 + PUBLIC_DEMO 꺼짐 = 익명 전면 거부(실데이터 무보호 노출 차단).
        with mock.patch.object(common, "ACCESS_KEY", ""), \
                mock.patch.object(common, "PUBLIC_DEMO", False):
            self.assertFalse(common.authorized(HandlerStub()))
        # PUBLIC_DEMO 켜져도 산출물이 합성 검증을 통과하지 못하면 여전히 거부(fail-closed).
        with mock.patch.object(common, "ACCESS_KEY", ""), \
                mock.patch.object(common, "PUBLIC_DEMO", True):
            self.assertFalse(common.public_dataset_ready())  # 현재 _static은 실데이터
            self.assertFalse(common.authorized(HandlerStub()))
        # 익명 허용은 오직 합성 공개 모드 + 합성 데이터셋 검증 통과 시에만.
        with mock.patch.object(common, "ACCESS_KEY", ""), \
                mock.patch.object(common, "PUBLIC_DEMO", True), \
                mock.patch.object(common, "public_dataset_ready", return_value=True):
            self.assertTrue(common.authorized(HandlerStub()))

    def test_filter_expr_has_scope_and_type_without_synthetic_identity(self):
        # 실데이터 모드 필터는 scope GLOB·chunk_type만 — 합성 정체성 스탬프는 붙지 않는다.
        with mock.patch.object(common, "PUBLIC_DEMO", False):
            expr = common._filter_expr(["계좌"], {"qa"})
        self.assertIn("scope_key GLOB '계좌*'", expr)
        self.assertIn("chunk_type = 'qa'", expr)
        self.assertNotIn("dataset_id", expr)
        self.assertNotIn("classification", expr)
        self.assertNotIn("source_url = '#demo'", expr)
        self.assertNotIn("manual = '화면'", expr)

    def test_search_runs_on_real_dataset_without_fail_closed(self):
        # 실데이터 META(demo:False)에서도 fail-closed가 아니라 정상 검색되어야 한다.
        bodies = []

        def fake_post(_url, _token, body, timeout=20):
            bodies.append(body)
            return {"result": []}

        with mock.patch.object(common, "PUBLIC_DEMO", False), \
                mock.patch.object(common, "OPENAI_KEY", ""), \
                mock.patch.object(common, "_post", side_effect=fake_post):
            hits, gate = common.search("계좌 해지 방법", 5, None, None)
        self.assertEqual(hits, [])
        self.assertFalse(gate["all_low"])
        # 본검색 + dense 게이트 2개 쿼리 전송, 본검색 body는 metadata 동봉.
        self.assertEqual(len(bodies), 2)
        self.assertIs(bodies[0].get("includeMetadata"), True)

    def test_questions_loaded_from_question_bank_module(self):
        # 실데이터 모드는 _static에 QUESTIONS가 없어 _questions.py 뱅크로 폴백된다.
        self.assertIn("_questions", sys.modules)
        self.assertTrue(common.QUESTIONS)
        entry = common.QUESTIONS[0]
        for key in ("q", "sid", "t"):
            self.assertIn(key, entry)

    def test_public_meta_returns_real_meta_verbatim(self):
        # 실데이터 운영은 ingest가 만든 META를 그대로 서빙(합성 allowlist 재구성 없음).
        with mock.patch.object(common, "PUBLIC_DEMO", False):
            self.assertIs(common.public_meta(), common.META)

    def test_online_params_reject_nonfinite_unbounded_and_unknown_values(self):
        # 파라미터 검증은 모드 무관 방어선 — 비정상·과대·미확인 값 거부(민감정보 포함).
        bad = [
            {"q": "x", "topk": "1000000000"},
            {"q": "x", "topk": "bad"},
            {"q": "x", "tau": "NaN"},
            {"q": "x", "tau": "-1"},
            {"q": "x", "types": "qa,secret"},
            {"q": "x", "scope": "상담>실데이터"},
            {"q": "x" * 501},
            {"q": "account 123456789012 lookup"},
            {"q": "test@example.com contact"},
        ]
        for params in bad:
            with self.subTest(params=params), self.assertRaises(ValueError):
                common.common_params(params)

    def test_openai_falls_back_when_cost_guard_is_unavailable(self):
        # 일일 카운터(Redis) 장애 시 외부 LLM 호출 금지 — 추출형으로 폴백(모드 무관).
        hits = [{"rank": 1, "text": "근거"}]
        with mock.patch.object(common, "OPENAI_KEY", "configured"), \
                mock.patch.object(common, "REDIS_URL", ""), \
                mock.patch.object(common, "_post") as post:
            result = common.answer("질문", hits)
        self.assertEqual(result["backend"], "guard-unavailable-extractive")
        self.assertFalse(result["used_llm"])
        post.assert_not_called()

    def test_access_key_is_header_only_and_tab_scoped(self):
        # 접근키는 sessionStorage(탭 한정)에만 저장 — localStorage 영속 저장 금지.
        js = (ONLINE / "public" / "app.js").read_text(encoding="utf-8")
        self.assertNotIn('localStorage.getItem("pbdemo.key")', js)
        self.assertNotIn('localStorage.setItem("pbdemo.key"', js)
        self.assertIn("sessionStorage.getItem(DEMO_KEY_STORAGE)", js)
        self.assertIn("sessionStorage.setItem(DEMO_KEY_STORAGE", js)


class PublicSyntheticModeTests(unittest.TestCase):
    """합성 공개 모드 — PUBLIC_DEMO 켜짐. 승인된 합성 v2 산출물만 서빙(fail-closed)."""

    def setUp(self):
        # 클래스 전 테스트에 PUBLIC_DEMO=True 강제(mock.patch로 원복 보장).
        p = mock.patch.object(common, "PUBLIC_DEMO", True)
        p.start()
        self.addCleanup(p.stop)

    def test_fail_closed_when_static_is_not_synthetic(self):
        # 핵심 불변식: 산출물이 실데이터(_static)면 합성 모드에서 전면 차단.
        self.assertFalse(common.public_dataset_ready())
        # 검색은 전송(_post) 이전에 경계 오류로 중단.
        with mock.patch.object(common, "_post") as post:
            with self.assertRaises(common.PublicDatasetBoundaryError):
                common.search("질문", 5, None, None)
            post.assert_not_called()
        # 메타 서빙도 거부.
        with self.assertRaises(common.PublicDatasetBoundaryError):
            common.public_meta()
        # 올바른 키가 있어도 데이터셋 미검증이면 인증 거부.
        with mock.patch.object(common, "ACCESS_KEY", "shared-key"):
            self.assertFalse(common.authorized(HandlerStub("shared-key")))

    def test_filter_expr_includes_public_identity(self):
        # 합성 모드 필터는 공개 namespace 정체성을 항상 강제(scope/type과 함께).
        expr = common._filter_expr(["계좌"], {"qa"})
        self.assertIn(f"dataset_id = '{common.PUBLIC_DATASET_ID}'", expr)
        self.assertIn(f"classification = '{common.PUBLIC_CLASSIFICATION}'", expr)
        self.assertIn(f"schema_version = {common.PUBLIC_SCHEMA_VERSION}", expr)
        self.assertIn(f"corpus_sha256 = '{common.PUBLIC_CORPUS_SHA256}'", expr)
        self.assertIn("source_url = '#demo'", expr)
        self.assertIn("manual = '화면'", expr)
        self.assertIn("scope_key GLOB '계좌*'", expr)
        self.assertIn("chunk_type = 'qa'", expr)

    def test_search_sends_boundary_filter_to_both_vector_queries(self):
        # 데이터셋 검증 통과 상황을 mock으로 만들고, 본검색·게이트 두 body 모두에
        # 합성 경계 필터가 실려 나가는지 확인.
        bodies = []

        def fake_post(_url, _token, body, timeout=20):
            bodies.append(body)
            return {"result": []}

        with mock.patch.object(common, "public_dataset_ready", return_value=True), \
                mock.patch.object(common, "OPENAI_KEY", ""), \
                mock.patch.object(common, "_post", side_effect=fake_post):
            hits, gate = common.search("합성 질문", 5, None, None)
        self.assertEqual(hits, [])
        self.assertFalse(gate["all_low"])
        self.assertEqual(len(bodies), 2)
        for body in bodies:
            self.assertIn(f"dataset_id = '{common.PUBLIC_DATASET_ID}'", body["filter"])
            self.assertIn(
                f"classification = '{common.PUBLIC_CLASSIFICATION}'", body["filter"])
            self.assertIn("source_url = '#demo'", body["filter"])
            self.assertIn("manual = '화면'", body["filter"])
            self.assertIs(body.get("includeMetadata"), True)

    def test_vector_result_is_rejected_on_any_boundary_mismatch(self):
        # Vector 필터 오작동까지 가정: 반환 metadata의 어느 정체성 필드라도 어긋나면 거부.
        sid = next(iter(common._PUBLIC_SCREEN_IDS))
        valid = {"metadata": {
            "dataset_id": common.PUBLIC_DATASET_ID,
            "classification": common.PUBLIC_CLASSIFICATION,
            "schema_version": common.PUBLIC_SCHEMA_VERSION,
            "corpus_sha256": common.PUBLIC_CORPUS_SHA256,
            "source_url": "#demo",
            "manual": "화면",
            "sector_path": ["화면", "계좌"],
            "screen_id": sid,
        }}
        self.assertEqual(common._validate_public_results([valid], "test"), [valid])

        for changed in (
            {"dataset_id": "private-real"},
            {"classification": "RESTRICTED_REAL"},
            {"schema_version": 1},
            {"corpus_sha256": "0" * 64},
            {"source_url": "https://internal.example/manual"},
            {"manual": "상담"},
            {"sector_path": ["상담", "계좌"]},
            {"screen_id": "UNKNOWN"},
        ):
            row = {"metadata": {**valid["metadata"], **changed}}
            with self.subTest(changed=changed), \
                    self.assertRaises(common.PublicDatasetBoundaryError):
                common._validate_public_results([row], "test")

    def test_synthetic_artifact_injection_makes_dataset_ready(self):
        # 양성 경로: 결정적 합성 산출물을 주입하면 public_dataset_ready 가 True 로 성립.
        # (파생 상수 _PUBLIC_SCREEN_IDS 재계산 포함 — 주입만으로 sha256 검증까지 통과.)
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp)
            gen_demo_data.main(out)
            meta = json.loads((out / "meta.json").read_text(encoding="utf-8"))
            sectors = json.loads((out / "sectors.json").read_text(encoding="utf-8"))
            questions = json.loads((out / "questions.json").read_text(encoding="utf-8"))
            screen_ids = frozenset(common._collect_screen_ids(sectors.get("tree") or []))
            with mock.patch.object(common, "META", meta), \
                    mock.patch.object(common, "SECTORS", sectors), \
                    mock.patch.object(common, "QUESTIONS", questions), \
                    mock.patch.object(common, "_PUBLIC_SCREEN_IDS", screen_ids):
                self.assertTrue(common.public_dataset_ready())
                self.assertTrue(common._public_questions_ready())


class RealIngestBreakGlassTests(unittest.TestCase):
    def test_break_glass_requires_flag_and_exact_confirmation(self):
        cases = [
            ([], {}),
            ([ingest_real.BREAK_GLASS_FLAG], {}),
            ([], {ingest_real.BREAK_GLASS_ENV:
                  ingest_real.BREAK_GLASS_CONFIRMATION}),
            ([ingest_real.BREAK_GLASS_FLAG],
             {ingest_real.BREAK_GLASS_ENV: "yes"}),
        ]
        for argv, env in cases:
            with self.subTest(argv=argv, env=env), self.assertRaises(SystemExit):
                ingest_real.require_break_glass(argv, env)

        ingest_real.require_break_glass(
            [ingest_real.BREAK_GLASS_FLAG],
            {ingest_real.BREAK_GLASS_ENV: ingest_real.BREAK_GLASS_CONFIRMATION})

    def test_main_blocks_before_read_write_or_network(self):
        with mock.patch.object(ingest_real, "load_chunks") as load, \
                mock.patch.object(ingest_real, "post") as post:
            with self.assertRaises(SystemExit):
                ingest_real.main([], {})
            load.assert_not_called()
            post.assert_not_called()

    def test_real_ingest_uses_restricted_identity(self):
        self.assertNotEqual(ingest_real.REAL_DATASET_ID, common.PUBLIC_DATASET_ID)
        self.assertEqual(ingest_real.REAL_CLASSIFICATION, "RESTRICTED_REAL")
        source = (ONLINE / "ingest_real.py").read_text(encoding="utf-8")
        self.assertNotIn('HERE / "api" / "_static.py"', source)
        self.assertNotIn('os.environ.get("UPSTASH_VECTOR_REST_URL"', source)
        self.assertIn("UPSTASH_PRIVATE_VECTOR_REST_URL", source)


class SyntheticArtifactTests(unittest.TestCase):
    FILES = ("chunks.jsonl", "sectors.json", "questions.json", "meta.json")

    def test_generator_is_byte_deterministic_and_ingestable(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            pa, pb = pathlib.Path(a), pathlib.Path(b)
            gen_demo_data.main(pa)
            gen_demo_data.main(pb)
            for name in self.FILES:
                self.assertEqual((pa / name).read_bytes(), (pb / name).read_bytes(), name)
            meta, _sectors, _questions, chunks = ingest.load_public_data(pa)
            self.assertEqual(len(chunks), ingest.PUBLIC_CHUNK_COUNT)
            batch = ingest.build_batch(chunks[:1], meta)
            metadata = batch[0]["metadata"]
            self.assertEqual(metadata["dataset_id"], ingest.PUBLIC_DATASET_ID)
            self.assertEqual(metadata["classification"], ingest.PUBLIC_CLASSIFICATION)
            self.assertEqual(metadata["schema_version"], ingest.PUBLIC_SCHEMA_VERSION)
            self.assertEqual(metadata["corpus_sha256"], ingest.PUBLIC_CORPUS_SHA256)

    def test_each_artifact_tamper_is_rejected_before_transport(self):
        for name in self.FILES:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                path = pathlib.Path(tmp)
                gen_demo_data.main(path)
                target = path / name
                if name == "meta.json":
                    target.write_bytes(target.read_bytes().replace(b'"count":832', b'"count":831', 1))
                else:
                    target.write_bytes(target.read_bytes() + b" ")
                with mock.patch.object(ingest, "post") as post, \
                        self.assertRaises((SystemExit, json.JSONDecodeError)):
                    ingest.load_public_data(path)
                post.assert_not_called()

    def test_public_upload_requires_explicit_two_factor_approval(self):
        with self.assertRaises(SystemExit):
            ingest.require_public_deploy([], {})
        ingest.require_public_deploy(
            [ingest.PUBLIC_DEPLOY_FLAG],
            {ingest.PUBLIC_DEPLOY_ENV: ingest.PUBLIC_DEPLOY_CONFIRMATION})


class PackagingBoundaryTests(unittest.TestCase):
    def test_sensitive_artifacts_are_excluded_from_all_contexts(self):
        gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")
        vercelignore = (ONLINE / ".vercelignore").read_text(encoding="utf-8")

        # GitHub 원격·Docker 이미지에는 실데이터 파생물(_questions.py 포함) 커밋/포함 금지.
        for content in (gitignore, dockerignore):
            self.assertIn(".env*", content)
            self.assertIn("*.xls", content)
            self.assertIn("deploy/online/api/_questions*.py", content)
        self.assertIn("data/questions*.json", dockerignore)
        self.assertIn("**/.env*", dockerignore)
        self.assertIn("**/*.xls", dockerignore)

        # Vercel 번들은 자격증명·원본만 제외한다. api/_questions*.py 는 여기서 제외하지
        # 않는다 — 실데이터 운영 모드가 런타임에 질문뱅크(_questions.py)를 임포트해
        # /api/suggest 추천을 제공하므로, Vercel 배포에는 반드시 포함되어야 한다
        # (데이터 자체는 승인된 egress). .gitignore/.dockerignore 제외로 원격·이미지
        # 유출은 별도로 차단됨.
        for pattern in (".env*", "**/*.xls", "gen_questions.py"):
            self.assertIn(pattern, vercelignore)


if __name__ == "__main__":
    unittest.main()
