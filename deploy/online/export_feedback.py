#!/usr/bin/env python3
"""사용자 피드백 내려받기 — Upstash Redis → data/feedback.jsonl + 유형별 마크다운 요약.

로컬 실행 도구(배포 제외). 주간 리뷰·백업·개선 환류용.

  export FEEDBACK_REDIS_REST_URL=... FEEDBACK_REDIS_REST_TOKEN=...
  python deploy/online/export_feedback.py                 # → data/feedback.jsonl (+ 요약 stdout)
  python deploy/online/export_feedback.py --md out.md      # 보강/최신화 요청 목록을 마크다운 파일로

산출:
  data/feedback.jsonl   피드백 전량(공감수 포함, 1줄=1건)
  마크다운 요약          missing/outdated → 매뉴얼 보강 요청 표, quality → 회귀 평가 시드 후보
"""
from __future__ import annotations
import os
import sys
import json
import urllib.request
import pathlib

URL = os.environ.get("FEEDBACK_REDIS_REST_URL", "").rstrip("/")
TOKEN = os.environ.get("FEEDBACK_REDIS_REST_TOKEN", "")
OUT = pathlib.Path("data/feedback.jsonl")
TYPE_KO = {"bug": "버그", "quality": "답변품질", "outdated": "최신화", "missing": "보강", "idea": "제안"}
STATUS_KO = {"open": "접수", "ack": "확인중", "done": "반영", "hold": "보류"}


def redis(cmds):
    req = urllib.request.Request(
        f"{URL}/pipeline", data=json.dumps(cmds).encode(),
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return [x.get("result") for x in json.loads(r.read())]


def main():
    if not URL:
        sys.exit("FEEDBACK_REDIS_REST_URL / _TOKEN 환경변수를 설정하세요.")
    ids = redis([["ZRANGE", "fb:index", "0", "-1", "REV"]])[0] or []
    if not ids:
        print("등록된 피드백이 없습니다."); return
    ids = [str(i) for i in ids]
    raws = redis([["MGET", *[f"fb:item:{i}" for i in ids]]])[0] or []
    votes = redis([["MGET", *[f"fb:votes:{i}" for i in ids]]])[0] or []

    items = []
    for i, raw in enumerate(raws):
        if not raw:
            continue
        try:
            it = json.loads(
                raw, parse_constant=lambda value: (_ for _ in ()).throw(
                    ValueError(f"non-finite JSON number: {value}")))
        except (TypeError, ValueError, json.JSONDecodeError):
            print(f"경고: 손상된 피드백 id={ids[i]} 건너뜀", file=sys.stderr)
            continue
        it["votes"] = int(votes[i]) if i < len(votes) and votes[i] else 0
        items.append(it)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as f:
        for it in items:
            f.write(json.dumps(it, ensure_ascii=False, allow_nan=False) + "\n")

    by_type: dict[str, int] = {}
    for it in items:
        by_type[it.get("type", "")] = by_type.get(it.get("type", ""), 0) + 1
    print(f"내려받기 완료: {len(items)}건 → {OUT}")
    print("유형별: " + ", ".join(f"{TYPE_KO.get(k, k)} {v}" for k, v in sorted(by_type.items(), key=lambda x: -x[1])))

    # 매뉴얼 보강/최신화 요청 목록(마크다운)
    gaps = [it for it in items if it.get("type") in ("missing", "outdated")]
    if gaps:
        lines = ["# 매뉴얼 보강·최신화 요청 목록\n",
                 "| # | 유형 | 상태 | 공감 | 내용 | 연결 질문 | 근거 화면 |",
                 "|---|---|---|---|---|---|---|"]
        for it in gaps:
            ctx = it.get("ctx") or {}
            q = (ctx.get("q") or "").replace("|", "·")
            hits = " / ".join(h.get("no") or h.get("sid") or "" for h in (ctx.get("hits") or []) if (h.get("no") or h.get("sid")))
            content = (it.get("content") or "").replace("\n", " ").replace("|", "·")[:120]
            lines.append(f"| {it['id']} | {TYPE_KO.get(it['type'], it['type'])} | "
                         f"{STATUS_KO.get(it.get('status', 'open'), '?')} | {it['votes']} | "
                         f"{content} | {q} | {hits} |")
        md = "\n".join(lines) + "\n"
        if "--md" in sys.argv:
            dst = pathlib.Path(sys.argv[sys.argv.index("--md") + 1])
            dst.write_text(md, encoding="utf-8")
            print(f"보강 요청 목록 {len(gaps)}건 → {dst}")
        else:
            print("\n" + md)

    # 회귀 평가 시드 후보(답변 품질 지적 중 질문 컨텍스트가 있는 건)
    seeds = [it for it in items if it.get("type") == "quality" and (it.get("ctx") or {}).get("q")]
    if seeds:
        print(f"\n회귀 평가 시드 후보: {len(seeds)}건 (ctx.q 보유 quality 피드백 — eval_scope.py 시드로 활용)")


if __name__ == "__main__":
    main()
