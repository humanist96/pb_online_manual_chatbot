"""webapp 보안 계약 회귀 테스트.

무거운 FAISS 인덱스나 임베딩 모델을 import하지 않고 소스 AST만 검사한다.
"""
from __future__ import annotations

import ast
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
WEBAPP_PATH = ROOT / "src" / "webapp.py"
SOURCE = WEBAPP_PATH.read_text(encoding="utf-8")
TREE = ast.parse(SOURCE, filename=str(WEBAPP_PATH))


def _assignment(name: str) -> ast.AST:
    for node in TREE.body:
        if isinstance(node, ast.Assign):
            if any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
                return node.value
    raise AssertionError(f"assignment not found: {name}")


def _function(name: str) -> ast.FunctionDef:
    for node in ast.walk(TREE):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"function not found: {name}")


def _called_attrs(node: ast.AST) -> set[str]:
    return {
        call.func.attr
        for call in ast.walk(node)
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
    }


def test_backend_allowlist_and_safe_default():
    allowed = ast.literal_eval(_assignment("LLM_BACKENDS"))
    assert allowed == ("none", "ollama")

    backend = _assignment("LLM_BACKEND")
    env_get = next(
        call for call in ast.walk(backend)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and call.func.attr == "get"
        and len(call.args) >= 2
    )
    assert ast.literal_eval(env_get.args[0]) == "LLM_BACKEND"
    assert ast.literal_eval(env_get.args[1]) == "none"

    rejects_invalid = any(
        isinstance(node, ast.If)
        and any(isinstance(child, ast.Raise) for child in ast.walk(node))
        and {name.id for name in ast.walk(node) if isinstance(name, ast.Name)}
        >= {"LLM_BACKEND", "LLM_BACKENDS"}
        for node in TREE.body
    )
    assert rejects_invalid


def test_agentic_backend_code_is_absent():
    lowered = SOURCE.lower()
    for forbidden in ("claude", "subprocess", "shutil", "call_claude", "_resolve_backend"):
        assert forbidden not in lowered, forbidden

    answer_names = {node.id for node in ast.walk(_function("answer")) if isinstance(node, ast.Name)}
    assert "call_ollama" in answer_names
    assert not ({"call_claude", "CLAUDE_BIN", "CLAUDE_MODEL"} & answer_names)

    image_extractor = (ROOT / "src" / "extract_pm_images.py").read_text(encoding="utf-8")
    assert "PB_VLM_APPROVAL" in image_extractor
    assert "I_ACKNOWLEDGE_APPROVED_TERRA_VLM" in image_extractor
    assert "_vlm_ollama" not in image_extractor
    assert "_vlm_claude" not in image_extractor



def test_security_headers_and_single_response_path():
    headers = ast.literal_eval(_assignment("SECURITY_HEADERS"))
    required = {
        "Content-Security-Policy",
        "X-Content-Type-Options",
        "X-Frame-Options",
        "Referrer-Policy",
        "Permissions-Policy",
        "Cross-Origin-Opener-Policy",
        "Cross-Origin-Resource-Policy",
    }
    assert required <= headers.keys()
    assert "script-src 'self'" in headers["Content-Security-Policy"]
    assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]

    handler = next(
        node for node in TREE.body
        if isinstance(node, ast.ClassDef) and node.name == "Handler"
    )
    end_headers = next(
        node for node in handler.body
        if isinstance(node, ast.FunctionDef) and node.name == "end_headers"
    )
    assert {"send_header", "end_headers"} <= _called_attrs(end_headers)

    do_get = next(node for node in handler.body if isinstance(node, ast.FunctionDef) and node.name == "do_GET")
    assert not ({"send_response", "send_header", "end_headers"} & _called_attrs(do_get))


def test_runtime_configs_default_to_none():
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")
    run_sh = (ROOT / "deploy" / "run.sh").read_text(encoding="utf-8")
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "LLM_BACKEND=none" in env_example
    assert 'LLM_BACKEND="${LLM_BACKEND:-none}"' in run_sh
    assert "LLM_BACKEND=none" in dockerfile
    assert 'LLM_BACKEND: "none"' in compose


def test_bind_and_query_limits_are_fail_safe():
    assert 'os.environ.get("HOST", "127.0.0.1")' in SOURCE
    assert "PB_ALLOW_NON_LOOPBACK_BIND" in SOURCE
    assert "PB_MAX_CONCURRENT_QUERIES" in SOURCE
    assert "parse_query_params(parsed.query)" in SOURCE
    assert "_query_slots.acquire(blocking=False)" in SOURCE

    run_sh = (ROOT / "deploy" / "run.sh").read_text(encoding="utf-8")
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    service = (ROOT / "deploy" / "pb-chatbot.service").read_text(encoding="utf-8")
    assert 'HOST="${HOST:-127.0.0.1}"' in run_sh
    assert "HOST=127.0.0.1" in dockerfile
    assert '127.0.0.1:8000:8000' in compose
    assert "Environment=HOST=127.0.0.1" in service


def load_tests(_loader, _tests, _pattern):
    suite = unittest.TestSuite()
    for name, value in sorted(globals().items()):
        if name.startswith("test_") and callable(value):
            suite.addTest(unittest.FunctionTestCase(value, description=name))
    return suite


if __name__ == "__main__":
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    passed = 0
    for test in tests:
        try:
            test()
            print(f"PASS {test.__name__}")
            passed += 1
        except AssertionError as exc:
            print(f"FAIL {test.__name__}: {exc}")
    print(f"\n{passed}/{len(tests)} passed")
    raise SystemExit(0 if passed == len(tests) else 1)
