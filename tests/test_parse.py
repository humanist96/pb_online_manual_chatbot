"""
파서 회귀 테스트 — AC250400 파일럿 골든값 고정.
실행: .venv/bin/python tests/test_parse.py
(외부 의존 없이 assert 기반, pytest 불필요)
"""
import sys
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from parse import parse_html, split_term  # noqa: E402

HTML = str(ROOT / "data/html/AC250400.html")


def test_metadata():
    d = parse_html(HTML)
    assert d["screen_id"] == "AC250400"
    assert d["screen_no"] == "0878"
    assert d["title"] == "지점계좌서비스약정등록내역"
    assert d["code"] == "0878-AC250400"


def test_split_term():
    assert split_term("등록 : 부가서비스 약정 등록한 계좌를 말함") == (
        "등록", "부가서비스 약정 등록한 계좌를 말함", True)
    t, dsc, ok = split_term("계좌번호를 입력함")
    assert ok is False and dsc == ""


def test_hierarchy():
    d = parse_html(HTML)
    paths = [" > ".join(b["path"]) for b in d["breadcrumbs"]]
    root = "지점계좌서비스약정등록내역"
    # 조건입력 계층
    assert f"{root} > 화면설명 > 조건입력 > 조회구분 > 지점별" in paths
    assert f"{root} > 화면설명 > 조건입력 > 등록구분 > 등록" in paths
    # icon02 콜론 자식 병합
    assert f"{root} > 화면설명 > 조건입력 > 상품유형 > 개별계좌 > 위탁계좌" in paths
    # 섹션들
    assert any(p.startswith(f"{root} > 용어찾기 > ELW") for p in paths)
    assert f"{root} > 관련화면 > 지점계좌서비스약정현황[2494]" in paths
    assert any(p.startswith(f"{root} > 질문보기") for p in paths)


def test_counts():
    d = parse_html(HTML)
    assert len(d["breadcrumbs"]) >= 60
    assert len(d["glossary"]) == 3
    assert len(d["related"]) == 4
    assert len(d["qa"]) == 1


def test_qa_content():
    d = parse_html(HTML)
    qa = d["qa"][0]
    assert "변경사용자" in qa["a"]


# ── 전 부문 확장 골든 (부문별 파일럿) — 계좌 골든과 동일한 회귀 방지선 ──

def test_sector_full_template():
    """선물주문 ON400100 — 정식 템플릿이 타 부문에서도 동일 규칙으로 파싱."""
    d = parse_html(str(ROOT / "data/html/ON400100.html"))
    assert len(d["breadcrumbs"]) >= 25
    assert len(d["glossary"]) == 3
    assert len(d["related"]) == 6
    assert len(d["qa"]) == 1
    paths = [" > ".join(b["path"]) for b in d["breadcrumbs"]]
    assert any("화면설명" in p for p in paths)


def test_sector_h2_template():
    """감사 AD008300 — 경량 h2 템플릿: <h2>라벨</h2><div class=h2>본문(목록)</div>."""
    d = parse_html(str(ROOT / "data/html/AD008300.html"))
    assert len(d["breadcrumbs"]) >= 10
    paths = [" > ".join(b["path"]) for b in d["breadcrumbs"]]
    # 라벨이 '내용N'이 아니라 실제 h2 텍스트로 살아나야 함
    assert any("화면설명/사용방법" in p for p in paths)
    assert any("단계1" in p for p in paths)


def test_sector_intro_fallback():
    """시스템소개 SQ010000 — 구조 클래스 전무: 본문 문단을 화면개요로 보존."""
    d = parse_html(str(ROOT / "data/html/SQ010000.html"))
    assert len(d["breadcrumbs"]) >= 3
    assert all(b["path"][1] == "화면개요" for b in d["breadcrumbs"])


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"FAIL {fn.__name__}: {e}")
    print(f"\n{passed}/{len(fns)} passed")
    sys.exit(0 if passed == len(fns) else 1)
