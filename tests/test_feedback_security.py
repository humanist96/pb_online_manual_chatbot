"""온라인 피드백 이미지·보안 헤더 회귀 테스트(외부 서비스 불필요)."""
from __future__ import annotations

import base64
import io
import json
import os
import pathlib
import subprocess
import sys
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
API = ROOT / "deploy" / "online" / "api"
sys.path.insert(0, str(API))

import feedback as fb  # noqa: E402


def _data_url(mime: str, raw: bytes) -> str:
    return f"data:{mime};base64," + base64.b64encode(raw).decode("ascii")


PNG = b"\x89PNG\r\n\x1a\n" + b"p0-test"
JPEG = b"\xff\xd8\xff\xe0p0-test\xff\xd9"
GIF = b"GIF89a" + b"p0-test"
WEBP = b"RIFF" + (11).to_bytes(4, "little") + b"WEBP" + b"p0-test"
VALID = {
    "image/png": PNG,
    "image/jpeg": JPEG,
    "image/gif": GIF,
    "image/webp": WEBP,
}


def _raises_value_error(fn):
    try:
        fn()
    except ValueError:
        return
    raise AssertionError("ValueError expected")


def test_images_disabled_without_explicit_env():
    env = os.environ.copy()
    for name in ("FEEDBACK_ENABLED", "FEEDBACK_CONTEXT_ENABLED",
                 "FEEDBACK_PUBLIC_BOARD_ENABLED", "FEEDBACK_IMAGES_ENABLED"):
        env.pop(name, None)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    code = (f"sys.path.insert(0, {str(API)!r}); import feedback; "
            "print(int(feedback.FEEDBACK_ENABLED), "
            "int(feedback.FEEDBACK_CONTEXT_ENABLED), "
            "int(feedback.FEEDBACK_PUBLIC_BOARD_ENABLED), "
            "int(feedback.FEEDBACK_IMAGES_ENABLED))")
    r = subprocess.run([sys.executable, "-B", "-c", "import sys; " + code],
                       cwd=ROOT, env=env, text=True, capture_output=True, check=True)
    assert r.stdout.strip() == "0 0 0 0", r.stdout
    env["FEEDBACK_ENABLED"] = "true"
    env["FEEDBACK_IMAGES_ENABLED"] = "true"
    r = subprocess.run([sys.executable, "-B", "-c", "import sys; " + code],
                       cwd=ROOT, env=env, text=True, capture_output=True, check=True)
    assert r.stdout.strip() == "1 0 0 1", r.stdout


def test_disabled_rejects_upload_and_blocks_legacy_reads():
    old_flag, old_redis, old_send = fb.FEEDBACK_IMAGES_ENABLED, fb._redis, fb.send_json
    captured = {}
    try:
        fb.FEEDBACK_IMAGES_ENABLED = False
        _raises_value_error(lambda: fb._clean_images({"images": [_data_url("image/png", PNG)]}))
        assert fb._clean_images({}) == []

        def no_redis(_cmds):
            raise AssertionError("disabled image read reached Redis")

        fb._redis = no_redis
        fb.send_json = lambda _h, obj, code=200: captured.update(obj=obj, code=code)
        fb.imgs(object(), {"id": "1"})
        assert captured == {"obj": {"images": [], "error": "image attachments disabled"},
                            "code": 404}
    finally:
        fb.FEEDBACK_IMAGES_ENABLED, fb._redis, fb.send_json = old_flag, old_redis, old_send


def test_strict_decode_magic_and_canonical_reencode():
    old_flag = fb.FEEDBACK_IMAGES_ENABLED
    try:
        fb.FEEDBACK_IMAGES_ENABLED = True
        for mime, raw in VALID.items():
            original = _data_url(mime, raw)
            assert fb._clean_images({"images": [original]}) == [original]

        # Python의 strict decoder도 사용하지 않는 pad bit는 허용한다. 저장값은 반드시
        # 재인코딩된 단일 표현이어야 하므로 같은 바이트의 비정규 표현을 정규화한다.
        raw = PNG + b"x"
        canonical = _data_url("image/png", raw)
        prefix, payload = canonical.split(",", 1)
        assert payload.endswith("==")
        alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
        pos = alphabet.index(payload[-3])
        noncanonical = payload[:-3] + alphabet[(pos & 0b110000) | 1] + "=="
        assert base64.b64decode(noncanonical, validate=True) == raw
        assert fb._clean_images({"images": [prefix + "," + noncanonical]}) == [canonical]

        png = _data_url("image/png", PNG)
        payload = png.split(",", 1)[1]
        attacks = [
            png + '\" onerror=\"globalThis.pwned=1',
            "data:image/png;base64," + payload[:4] + "\n" + payload[4:],
            _data_url("image/png", b"not-a-png"),
            _data_url("image/jpeg", PNG),
            "data:image/svg+xml;base64," + payload,
            "data:image/png;base64,",
            "data:image/png;base64," + "A" * fb.MAX_IMG_LEN,
        ]
        for value in attacks:
            _raises_value_error(lambda value=value: fb._clean_images({"images": [value]}))
        _raises_value_error(lambda: fb._clean_images({"images": "not-a-list"}))
        _raises_value_error(lambda: fb._clean_images({"images": [png] * (fb.MAX_IMAGES + 1)}))
    finally:
        fb.FEEDBACK_IMAGES_ENABLED = old_flag


def test_http_registration_rejects_xss_before_redis():
    valid = _data_url("image/png", PNG)
    body = json.dumps({
        "type": "bug", "content": "보안 회귀 테스트입니다",
        "images": [valid + '\" onerror=\"globalThis.pwned=1'],
    }).encode()

    class Request:
        headers = {"content-length": str(len(body)), "x-forwarded-for": "127.0.0.1"}
        rfile = io.BytesIO(body)

    old_enabled, old_flag, old_url, old_redis, old_send = (
        fb.FEEDBACK_ENABLED, fb.FEEDBACK_IMAGES_ENABLED,
        fb.REDIS_URL, fb._redis, fb.send_json)
    captured = {}
    try:
        fb.FEEDBACK_ENABLED = True
        fb.FEEDBACK_IMAGES_ENABLED = True
        fb.REDIS_URL = "https://redis.invalid"
        fb._redis = lambda _cmds: (_ for _ in ()).throw(
            AssertionError("invalid image reached Redis"))
        fb.send_json = lambda _h, obj, code=200: captured.update(obj=obj, code=code)
        fb.register(Request())
        assert captured["code"] == 400
        assert "이미지" in captured["obj"]["error"]
    finally:
        (fb.FEEDBACK_ENABLED, fb.FEEDBACK_IMAGES_ENABLED,
         fb.REDIS_URL, fb._redis, fb.send_json) = (
            old_enabled, old_flag, old_url, old_redis, old_send)


def test_enabled_legacy_read_filters_malicious_values():
    old_flag, old_public, old_redis, old_send = (
        fb.FEEDBACK_IMAGES_ENABLED, fb.FEEDBACK_PUBLIC_BOARD_ENABLED,
        fb._redis, fb.send_json)
    valid = _data_url("image/png", PNG)
    malicious = valid + '\" onerror=\"globalThis.pwned=1'
    captured = {}
    try:
        fb.FEEDBACK_IMAGES_ENABLED = True
        fb.FEEDBACK_PUBLIC_BOARD_ENABLED = True

        def fake_redis(cmds):
            command = cmds[0][0]
            if command == "GET":
                return [json.dumps({"img": 2, "status": "done"})]
            if command == "MGET":
                return [[valid, malicious]]
            raise AssertionError(command)

        fb._redis = fake_redis
        fb.send_json = lambda _h, obj, code=200: captured.update(obj=obj, code=code)
        fb.imgs(type("Request", (), {"headers": {}})(), {"id": "7"})
        assert captured == {"obj": {"images": [valid]}, "code": 200}
    finally:
        (fb.FEEDBACK_IMAGES_ENABLED, fb.FEEDBACK_PUBLIC_BOARD_ENABLED,
         fb._redis, fb.send_json) = (old_flag, old_public, old_redis, old_send)


def test_private_or_unmoderated_images_are_not_disclosed():
    old = (fb.FEEDBACK_IMAGES_ENABLED, fb.FEEDBACK_PUBLIC_BOARD_ENABLED,
           fb.ADMIN_KEY, fb._redis, fb.send_json)
    captured = {}

    class Request:
        headers = {}

    try:
        fb.FEEDBACK_IMAGES_ENABLED = True
        fb.FEEDBACK_PUBLIC_BOARD_ENABLED = False
        fb.ADMIN_KEY = "admin-secret"
        fb._redis = lambda _cmds: [json.dumps({"img": 1, "status": "open"})]
        fb.send_json = lambda _h, obj, code=200: captured.update(obj=obj, code=code)
        fb.imgs(Request(), {"id": "9"})
        assert captured == {"obj": {"images": []}, "code": 404}
    finally:
        (fb.FEEDBACK_IMAGES_ENABLED, fb.FEEDBACK_PUBLIC_BOARD_ENABLED,
         fb.ADMIN_KEY, fb._redis, fb.send_json) = old


def test_nonfinite_and_sensitive_input_rejected_before_redis():
    old = (fb.FEEDBACK_ENABLED, fb.FEEDBACK_CONTEXT_ENABLED, fb.REDIS_URL,
           fb._redis, fb.send_json)
    captured = {}

    def request(raw: bytes):
        return type("Request", (), {
            "headers": {"content-length": str(len(raw)),
                        "x-forwarded-for": "127.0.0.1"},
            "rfile": io.BytesIO(raw),
        })()

    try:
        fb.FEEDBACK_ENABLED = True
        fb.FEEDBACK_CONTEXT_ENABLED = True
        fb.REDIS_URL = "https://feedback-redis.invalid"
        fb._redis = lambda _cmds: (_ for _ in ()).throw(
            AssertionError("invalid input reached Redis"))
        fb.send_json = lambda _h, obj, code=200: captured.update(obj=obj, code=code)

        raw = (b'{"type":"bug","content":"security regression test",'
               b'"ctx":{"gate":{"best":NaN,"tau":Infinity}}}')
        fb.register(request(raw))
        assert captured["code"] == 400

        for body in (
            {"type": "bug", "content": "contact test@example.com please"},
            {"type": "bug", "content": "security regression test",
             "ctx": {"q": "account 123456789012 lookup"}},
        ):
            captured.clear()
            fb.register(request(json.dumps(body).encode()))
            assert captured["code"] == 400
            assert "민감정보" in captured["obj"]["error"]
    finally:
        (fb.FEEDBACK_ENABLED, fb.FEEDBACK_CONTEXT_ENABLED, fb.REDIS_URL,
         fb._redis, fb.send_json) = old


def test_disabled_listing_hides_existing_image_count():
    old_flag, old_redis = fb.FEEDBACK_IMAGES_ENABLED, fb._redis
    replies = iter([[[json.dumps({"id": 1, "img": 3})]], [["0"]]])
    try:
        fb.FEEDBACK_IMAGES_ENABLED = False
        fb._redis = lambda _cmds: next(replies)
        items = fb._load_items([1])
        assert len(items) == 1 and "img" not in items[0]
    finally:
        fb.FEEDBACK_IMAGES_ENABLED, fb._redis = old_flag, old_redis


def test_frontend_uses_dom_properties_for_images():
    js = (ROOT / "deploy/online/public/app.js").read_text(encoding="utf-8")
    html = (ROOT / "deploy/online/public/index.html").read_text(encoding="utf-8")
    assert '<img src="${s}"' not in js
    assert '<img src="${d}"' not in js
    assert "img.src = src;" in js
    assert "box.replaceChildren(...images)" in js
    assert 'id="fb-image-field" hidden' in html
    open_tag = html.split('id="fb-open"', 1)[1].split(">", 1)[0]
    assert "hidden" in open_tag
    assert "d?.feedback_enabled === true" in js
    assert "d?.context_enabled === true" in js
    assert "d?.public_board_enabled === true" in js
    assert "fbGetJSON" in js and 'h["x-admin-key"] = FB.adminKey' in js


def test_feedback_uses_purpose_specific_redis_env():
    source = (API / "feedback.py").read_text(encoding="utf-8")
    assert "FEEDBACK_REDIS_REST_URL" in source
    assert "FEEDBACK_REDIS_REST_TOKEN" in source
    assert "from _common import authorized, parse_qs, send_json, _post\n" in source


def test_vercel_security_headers():
    config = json.loads((ROOT / "deploy/online/vercel.json").read_text(encoding="utf-8"))
    headers = {h["key"]: h["value"] for h in config["headers"][0]["headers"]}
    required = {
        "Content-Security-Policy", "X-Content-Type-Options", "X-Frame-Options",
        "Referrer-Policy", "Permissions-Policy", "Strict-Transport-Security",
    }
    assert required <= headers.keys()
    csp = {p.strip().split()[0]: p.strip().split()[1:]
           for p in headers["Content-Security-Policy"].split(";") if p.strip()}
    assert csp["script-src"] == ["'self'"]
    assert csp["object-src"] == ["'none'"]
    assert csp["frame-ancestors"] == ["'none'"]
    assert "data:" in csp["img-src"] and "blob:" in csp["img-src"]
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["X-Frame-Options"] == "DENY"
    assert headers["Referrer-Policy"] == "no-referrer"


def load_tests(_loader, _tests, _pattern):
    suite = unittest.TestSuite()
    for name, value in sorted(globals().items()):
        if name.startswith("test_") and callable(value):
            suite.addTest(unittest.FunctionTestCase(value, description=name))
    return suite


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for test in tests:
        try:
            test()
            print(f"PASS {test.__name__}")
            passed += 1
        except Exception as exc:
            print(f"FAIL {test.__name__}: {type(exc).__name__}: {exc}")
    print(f"\n{passed}/{len(tests)} passed")
    raise SystemExit(0 if passed == len(tests) else 1)
