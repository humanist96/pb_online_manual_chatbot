"""
업무매뉴얼 이미지 텍스트화 — 2패스(OCR + VLM).

  패스1 OCR  : EasyOCR(ko/en) — 노드 라벨·TR코드 고정밀 추출 (전량, 로컬)
  패스2 VLM  : 흐름도·표의 구조(순서·분기)를 단계 서술로.
               OCR 텍스트를 프롬프트에 주입해 코드·명칭 환각 억제.
               VLM 서빙은 승인된 Terra 모델에 한해서만 허용한다. 현재는 모델 ID·서빙·라이선스·해시 미확정으로 비활성 상태다.



캐시: data/pm_image_text.json {이름: {sha1, ocr, text, kind, vlm}} — 증분 안전.
우선순위: 본문 빈약 문서(파서 브레드크럼 0 또는 <5)의 이미지부터 VLM.

  python src/extract_pm_images.py --ocr                     # 패스1 전량 (수 초/장)
  python src/extract_pm_images.py --vlm --backend terra    # 승인 전에는 fail-closed
  python src/extract_pm_images.py --vlm --all --limit 20    # 전량 모드 + 상한
  python src/extract_pm_images.py --vlm --shard 0/3         # 병렬 샤딩(이름 정렬 기준)
"""
from __future__ import annotations
import io
import os
import sys
import json
import base64
import hashlib
import pathlib
import urllib.request

IMG_DIR = pathlib.Path("data/img_pm")
HTML_DIR = pathlib.Path("data/html_pm")
CACHE = pathlib.Path("data/pm_image_text.json")
VLM_APPROVAL_ENV = "PB_VLM_APPROVAL"
VLM_APPROVAL = "I_ACKNOWLEDGE_APPROVED_TERRA_VLM"

VLM_PROMPT = """이 이미지는 증권 원장시스템 업무매뉴얼의 도식(흐름도/표/구성도)입니다.
이미지에서 OCR로 추출된 텍스트는 다음과 같습니다:
{ocr}

위 텍스트만 사용하여(없는 코드·명칭을 만들지 마세요) 이미지의 내용을 한국어로 재구성하세요.
- 흐름도라면: 시작부터 끝까지 순서를 "1. → 2. →" 단계로, 분기는 "~인 경우/아닌 경우"로 서술
- 표라면: 각 행을 "항목: 내용" 형식으로
- TR-숫자 코드는 반드시 원문 그대로 유지
설명 없이 재구성 결과만 출력하세요."""


def load_cache() -> dict:
    """병렬 샤드 안전 읽기 — 원자적 저장과 짝. 순간 경합 시 짧게 재시도."""
    import time
    if not CACHE.exists():
        return {}
    for _ in range(5):
        try:
            return json.load(open(CACHE, encoding="utf-8"))
        except json.JSONDecodeError:
            time.sleep(0.2)
    return json.load(open(CACHE, encoding="utf-8"))


def save_cache(c: dict):
    """원자적 저장(temp + replace) — 동시 읽기가 부분 파일을 보지 않게."""
    tmp = CACHE.with_suffix(".json.tmp." + str(os.getpid()))
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(c, f, ensure_ascii=False, indent=1)
    os.replace(tmp, CACHE)


def img_png_bytes(path: pathlib.Path) -> bytes:
    from PIL import Image
    im = Image.open(path).convert("RGB")
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def priority_images() -> set[str]:
    """본문 빈약 문서의 이미지 이름 집합 — VLM 우선 대상."""
    sys.path.insert(0, "src")
    from parse_pm import parse_html
    names: set[str] = set()
    for f in sorted(HTML_DIR.glob("*.html")):
        d = parse_html(str(f))
        if len(d["breadcrumbs"]) < 5 and d["images"]:
            names.update(i["name"] for i in d["images"])
    return names


def run_ocr():
    import easyocr
    reader = easyocr.Reader(["ko", "en"], gpu=False, verbose=False)
    cache = load_cache()
    imgs = sorted(IMG_DIR.iterdir())
    done = 0
    for p in imgs:
        sha = hashlib.sha1(p.read_bytes()).hexdigest()[:12]
        ent = cache.get(p.name)
        if ent and ent.get("sha1") == sha and ent.get("ocr") is not None:
            continue
        try:
            import numpy as np
            from PIL import Image
            arr = np.array(Image.open(p).convert("RGB"))
            lines = [t for (_, t, conf) in reader.readtext(arr) if conf > 0.3]
        except Exception as e:
            print(f"[ocr] {p.name}: {e}", file=sys.stderr)
            lines = []
        cache[p.name] = {**(ent or {}), "sha1": sha, "ocr": lines,
                         "text": (ent or {}).get("text") or " · ".join(lines),
                         "kind": (ent or {}).get("kind") or "이미지 텍스트",
                         "vlm": (ent or {}).get("vlm", False)}
        done += 1
        if done % 20 == 0:
            save_cache(cache)
            print(f"[ocr] {done}/{len(imgs)}", flush=True)
    save_cache(cache)
    print(f"[ocr] 완료 — 신규 {done}장, 캐시 {len(cache)}건")


def require_vlm_approval(backend: str) -> None:
    if os.environ.get(VLM_APPROVAL_ENV) != VLM_APPROVAL:
        raise SystemExit(
            f"VLM 비활성: {VLM_APPROVAL_ENV}={VLM_APPROVAL} 승인 후에만 실행할 수 있습니다.")
    if backend != "terra":
        raise SystemExit("VLM backend는 승인된 terra만 허용합니다.")
    raise SystemExit("승인된 Terra VLM adapter가 아직 설치되지 않아 실행하지 않습니다.")


def run_vlm(limit: int | None, all_imgs: bool, backend: str, shard: str | None):
    require_vlm_approval(backend)
    return  # Terra adapter가 승인·설치되기 전에는 어떤 VLM도 호출하지 않음
    cache = load_cache()
    targets = sorted(IMG_DIR.iterdir())
    if not all_imgs:
        pri = priority_images()
        targets = [p for p in targets if p.name in pri]
    if shard:
        k, n = (int(x) for x in shard.split("/"))
        targets = [p for i, p in enumerate(targets) if i % n == k]
    todo = [p for p in targets if not cache.get(p.name, {}).get("vlm")]
    if limit:
        todo = todo[:limit]
    print(f"[vlm:{backend}] 대상 {len(todo)}장 (우선순위 모드={not all_imgs}, shard={shard})")
    for i, p in enumerate(todo, 1):
        ocr = " · ".join(cache.get(p.name, {}).get("ocr") or [])[:1500]
        try:
            out = call(p, ocr)
        except Exception as e:
            print(f"[vlm] {p.name}: {e}", file=sys.stderr, flush=True)
            continue
        if out:
            # 호출 동안의 타 샤드 갱신 유실 방지 — 저장 직전 재로드 후 병합
            cache = load_cache()
            ent = cache.get(p.name, {})
            ent.update({"text": out, "kind": "도식", "vlm": True})
            cache[p.name] = ent
            save_cache(cache)
        print(f"[vlm] {i}/{len(todo)} {p.name} ({len(out)}자)", flush=True)
    print(f"[vlm:{backend}] 완료")


if __name__ == "__main__":
    if "--ocr" in sys.argv:
        run_ocr()
    if "--vlm" in sys.argv:
        lim = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else None
        be = (sys.argv[sys.argv.index("--backend") + 1]
              if "--backend" in sys.argv else "ollama")
        sh = sys.argv[sys.argv.index("--shard") + 1] if "--shard" in sys.argv else None
        run_vlm(lim, "--all" in sys.argv, be, sh)
