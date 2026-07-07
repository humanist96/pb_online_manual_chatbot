"""
업무매뉴얼(PM) 파서 회귀 테스트 — 파일럿 골든값 고정.
실행: .venv/bin/python tests/test_parse_pm.py   (data/html_pm 필요 — 사내망 수집분)
"""
import sys
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from parse_pm import parse_html  # noqa: E402

PM = ROOT / "data/html_pm"


def test_pm_structure_acp01010():
    """섹션(li) + 형제 표 귀속 + 표 항목 분해 — PM 템플릿의 핵심 규칙."""
    d = parse_html(str(PM / "ACP01010.html"))
    assert d["title"] == "고객정보및계좌관리체계"
    paths = [" > ".join(b["path"]) for b in d["breadcrumbs"]]
    assert len(d["breadcrumbs"]) >= 10
    # li 섹션
    assert any("고객정보관리" in p for p in paths)
    # li 형제로 놓인 표의 행이 해당 섹션에 귀속
    assert any(p.endswith("고객정보관리 > 고객 고유번호 부여") for p in paths)
    assert any("계좌번호 부여 체계 > 상품구분(2)" in p for p in paths)
    assert len(d["images"]) == 1


def test_pm_image_only_doc():
    """ACP02010(계좌개설절차) — 본문이 이미지뿐: 이미지 슬롯 2개 기록."""
    d = parse_html(str(PM / "ACP02010.html"))
    assert len(d["images"]) == 2
    # 텍스트화 캐시 존재 시 도식 청크가 생김 — 없으면 0 (둘 다 허용)
    if d["breadcrumbs"]:
        assert any("도식 텍스트화" in b["text"] for b in d["breadcrumbs"])


def test_pm_full_sweep():
    """전수 390문서 — 총량·빈 문서 상한 게이트."""
    docs = sorted(PM.glob("*.html"))
    assert len(docs) >= 380
    total = empty = 0
    for f in docs:
        d = parse_html(str(f))
        total += len(d["breadcrumbs"])
        if not d["breadcrumbs"] and not d["images"]:
            empty += 1
    assert total >= 3000, total
    assert empty <= 5, f"이미지도 텍스트도 없는 문서 {empty}"


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
