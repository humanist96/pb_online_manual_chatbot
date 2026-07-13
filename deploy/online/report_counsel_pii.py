"""상담매뉴얼 PII 분석·마스킹 근거 웹보고서 생성 — 로컬 실행 도구(배포 제외).

원본 .xls 19개를 mask_pii 적용 전 상태로 재파싱해 규칙별 마스킹 이벤트를 계측하고,
보존 결정 항목(고객사·연락처·OTP 등) 현황을 스캔한 뒤, 배포 청크(chunks_counsel.jsonl)와
정합성을 대조해 자립형 단일 HTML 보고서를 만든다. 원본·파서·청크는 일절 수정하지 않는다.

  .venv/bin/python deploy/online/report_counsel_pii.py
  → presentations/counsel-pii-report.html  (실 PII 포함 — git 커밋 금지, .gitignore 등재)
"""
from __future__ import annotations
import sys
import json
import html
import pathlib
import re
import datetime

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from parse_counsel_xls import (  # noqa: E402 — 파서 로직 재사용(수정 금지)
    SRC_DIR, OUT, RE_CARD, RE_ACCT, RE_WEAK, _acct_is_example,
    mask_pii, sector_name, parse_file, dedup_merge, to_chunk,
)

REPORT = HERE.parents[1] / "presentations" / "counsel-pii-report.html"
CTX = 46  # 근거 스니펫 앞뒤 문맥 길이

# 보존 결정 항목 스캔 패턴 (마스킹 범위 밖 — 현황 계측용)
RE_PHONE = re.compile(r"\b0\d{1,2}[-. )]\s?\d{3,4}[-. ]\d{4}\b")
RE_MASKED_ALREADY = re.compile(r"\d\*{2,}")            # 원본 자체 끝자리 *** 문화
RE_LOOSE_WEAK = re.compile(r"(\d{7,})(\*+)")           # 가드 없는 식별번호+* (산식 포함)
RE_OTP_SERIAL = re.compile(r"\d[\d-]{6,}\d")


def snippet(t: str, s: int, e: int) -> dict:
    """매치 스팬 앞뒤 문맥 — 개행은 공백으로."""
    one = lambda x: re.sub(r"\s+", " ", x)
    return {"pre": ("…" if s > CTX else "") + one(t[max(0, s - CTX):s]),
            "hit": one(t[s:e]),
            "post": one(t[e:e + CTX]) + ("…" if e + CTX < len(t) else "")}


def analyze_field(t: str) -> tuple[str, list[dict], list[dict]]:
    """mask_pii와 동일한 순서(card→acct→weak)로 치환하며 이벤트를 계측.
    반환: (마스킹 결과, 마스킹 이벤트, 제외 이벤트). 결과는 mask_pii(t)와 반드시 일치."""
    events, excluded = [], []

    def sub_card(m):
        after = f"{m.group(1)}-****-****-****"
        events.append({"rule": "card", "before": m.group(), "after": after,
                       **{"ctx_" + k: v for k, v in snippet(t0, m.start(), m.end()).items()}})
        return after

    t0 = t
    t = RE_CARD.sub(sub_card, t)

    def sub_acct(m):
        p1, s1, p2, s2, p3, star = m.groups()
        if _acct_is_example(p1, p3):
            reason = ("999 예시지점" if p1 == "999" else
                      "전자리 동일" if len(set(p3)) == 1 else "0000xx 연번")
            excluded.append({"rule": "acct", "before": m.group(), "reason": reason,
                             **{"ctx_" + k: v for k, v in snippet(t1, m.start(), m.end()).items()}})
            return m.group()
        keep = p3[:2] if len(p3) <= 5 else p3[:3]
        after = f"{p1}{s1}{p2}{s2}{keep}{'*' * (len(p3) - len(keep) + len(star))}"
        events.append({"rule": "acct", "before": m.group(), "after": after,
                       **{"ctx_" + k: v for k, v in snippet(t1, m.start(), m.end()).items()}})
        return after

    t1 = t
    t = RE_ACCT.sub(sub_acct, t)

    def sub_weak(m):
        after = m.group(1)[:4] + "*" * (len(m.group(1)) - 4 + len(m.group(2)))
        events.append({"rule": "weak", "before": m.group(), "after": after,
                       **{"ctx_" + k: v for k, v in snippet(t2, m.start(), m.end()).items()}})
        return after

    t2 = t
    strict_spans = [(m.start(1), m.end(2)) for m in RE_WEAK.finditer(t2)]
    for m in RE_LOOSE_WEAK.finditer(t2):  # 가드(산식·소수점 보호)로 제외된 매치 계측
        if (m.start(1), m.end(2)) not in strict_spans:
            excluded.append({"rule": "weak", "before": m.group(), "reason": "산식·소수점 가드",
                             **{"ctx_" + k: v for k, v in snippet(t2, m.start(), m.end()).items()}})
    t = RE_WEAK.sub(sub_weak, t)
    return t, events, excluded


def main():
    files = sorted(SRC_DIR.glob("*.xls"))
    assert files, f"{SRC_DIR} 에 .xls 없음"

    sectors, all_events, all_excluded = [], [], []
    preserved_phone, preserved_otp, preserved_already = [], [], []
    client_pairs, client_names = 0, {}
    rebuilt, affected = [], []
    tot_rows = tot_qrows = tot_pairs = tot_merged = 0

    for i, f in enumerate(files, 1):
        sector = sector_name(f.name)
        pairs, st = parse_file(f)
        merged, n_dup = dedup_merge(pairs)
        tot_rows += st["rows"]; tot_qrows += st["q_rows"]
        tot_pairs += st["pairs"]; tot_merged += n_dup
        sid, title = f"CS{i:02d}", f"{sector} 상담 Q&A"
        sec_events = 0
        sec_affected = 0
        for k, p in enumerate(merged):
            cid = f"cs:{sector}:{k + 1:04d}"
            chunk = to_chunk(p, sector, sid, title, k + 1)  # 파서와 동일 경로(마스킹 포함)
            rebuilt.append(chunk)
            changed = False
            for field in ("q", "a", "note"):
                raw = p[field]
                masked, events, excluded = analyze_field(raw)
                assert masked == mask_pii(raw), f"계측 로직 불일치: {cid}/{field}"
                for ev in events:
                    ev.update({"id": cid, "sector": sector, "field": field})
                for ex in excluded:
                    ex.update({"id": cid, "sector": sector, "field": field})
                all_events.extend(events)
                all_excluded.extend(excluded)
                sec_events += len(events)
                if masked != raw:
                    changed = True
                # 보존 항목 스캔은 마스킹 전 원문 기준
                for m in RE_PHONE.finditer(raw):
                    preserved_phone.append({"id": cid, "sector": sector,
                                            **{"ctx_" + k2: v for k2, v in snippet(raw, m.start(), m.end()).items()}})
                for m in RE_MASKED_ALREADY.finditer(raw):
                    # 확장 스팬(별 포함 토큰 전체)으로 문맥 표기
                    s = m.start()
                    while s > 0 and (raw[s - 1].isdigit() or raw[s - 1] in "-*"):
                        s -= 1
                    e = m.end()
                    while e < len(raw) and raw[e] == "*":
                        e += 1
                    preserved_already.append({"id": cid, "sector": sector,
                                              **{"ctx_" + k2: v for k2, v in snippet(raw, s, e).items()}})
                for ln in raw.split("\n"):
                    if "OTP" in ln.upper():
                        for m in RE_OTP_SERIAL.finditer(ln):
                            if sum(c.isdigit() for c in m.group()) >= 7:
                                preserved_otp.append({"id": cid, "sector": sector,
                                                      **{"ctx_" + k2: v for k2, v in snippet(ln, m.start(), m.end()).items()}})
            if changed:
                affected.append(cid)
                sec_affected += 1
            if p["clients"]:
                client_pairs += 1
                for c in p["clients"]:
                    client_names[c] = client_names.get(c, 0) + 1
        sectors.append({"name": sector, "chunks": len(merged),
                        "affected": sec_affected, "events": sec_events})

    # ── 배포 청크(chunks_counsel.jsonl)와 전수 정합 대조 ──
    deployed = {}
    with OUT.open(encoding="utf-8") as fp:
        for ln in fp:
            c = json.loads(ln)
            deployed[c["id"]] = c
    match = sum(1 for c in rebuilt if deployed.get(c["id"]) == c)
    mismatch_ids = [c["id"] for c in rebuilt if deployed.get(c["id"]) != c]

    # ── 건별 자동검증 — 치환 이벤트마다 고유번호 부여 + 3중 체크 ──
    corpus = "\n".join(c["text"] + "\n" + c["embed_text"] for c in deployed.values())
    for n, ev in enumerate(all_events, 1):
        ev["eid"] = f"M-{n:03d}"
        dep = deployed.get(ev["id"])
        dep_text = (dep["text"] + "\n" + dep["embed_text"]) if dep else ""
        after, before = ev["after"], ev["before"]
        # ① 잔존 패턴: 마스킹 결과가 다시 PII 패턴으로 탐지되면 실패
        ev["chk_residual"] = not (RE_CARD.search(after) or RE_WEAK.search(after)
                                  or any(not _acct_is_example(m.group(1), m.group(5))
                                         for m in RE_ACCT.finditer(after))) and "*" in after
        # ② 원본 잔존: 마스킹 전 값이 배포 데이터 전체 어디에도 남아 있으면 실패
        ev["chk_leak"] = before not in corpus
        # ③ 배포 반영: 마스킹 후 값이 해당 배포 청크에 실제로 존재해야 통과
        ev["chk_applied"] = after in dep_text
        ev["auto"] = ev["chk_residual"] and ev["chk_leak"] and ev["chk_applied"]
    for n, ex in enumerate(all_excluded, 1):
        ex["eid"] = f"X-{n:03d}"
    auto_pass = sum(1 for e in all_events if e["auto"])

    rule_meta = {
        "card": {"name": "카드번호 풀노출", "regex": RE_CARD.pattern,
                 "policy": "16자리 카드번호 전체 노출 → 앞 4자리(BIN)만 남기고 전부 마스킹",
                 "shape": "5531-****-****-****"},
        "acct": {"name": "무마스킹 실계좌번호", "regex": RE_ACCT.pattern,
                 "policy": "원본 상담 문화와 동일한 끝자리 * 방식으로 누락분 보완 — 지점-과목-일련번호 중 일련번호 앞 2~3자리만 보존",
                 "shape": "001-01-12****"},
        "weak": {"name": "마스킹 미흡 식별번호", "regex": RE_WEAK.pattern,
                 "policy": "마스킹 의도(*)는 있으나 7자리+ 노출이 과한 번호(실명번호·접수번호 등) → 앞 4자리만 보존",
                 "shape": "1281*****"},
    }
    rules = []
    for key, meta in rule_meta.items():
        evs = [e for e in all_events if e["rule"] == key]
        exs = [e for e in all_excluded if e["rule"] == key]
        rules.append({"key": key, **meta, "count": len(evs), "excluded_count": len(exs),
                      "events": evs, "excluded": exs})

    top_clients = sorted(client_names.items(), key=lambda kv: -kv[1])[:12]
    data = {
        "generated": datetime.date.today().isoformat(),
        "totals": {
            "files": len(files), "rows": tot_rows, "q_rows": tot_qrows,
            "pairs": tot_pairs, "dup_merged": tot_merged, "chunks": len(rebuilt),
            "affected": len(affected), "events": len(all_events),
            "excluded": len(all_excluded), "auto_pass": auto_pass,
            "deployed": len(deployed), "match": match, "mismatch": mismatch_ids,
        },
        "rules": rules,
        "sectors": sectors,
        "affected_ids": affected,
        "preserved": [
            {"key": "clients", "name": "고객사명",
             "count": client_pairs, "unique": len(client_names),
             "note": f"Q&A쌍 {client_pairs:,}건에 고객사 표기, 고유 {len(client_names)}개사. 답변 본문에도 사명 등장.",
             "rationale": "출처·맥락 식별에 필요한 업무 정보 — 접근키 게이트 뒤 공개 범위 전제로 보존(사용자 결정 2026-07-09)",
             "examples": [{"ctx_pre": "", "ctx_hit": n, "ctx_post": f"  — {c:,}건", "id": "", "sector": ""}
                          for n, c in top_clients]},
            {"key": "phone", "name": "담당자 연락처(전화번호)",
             "count": len(preserved_phone),
             "note": "코스콤 상담 담당자·부서 연락처가 대부분 — 고객 개인 전화번호 아님.",
             "rationale": "사내 담당자 실명·연락처는 후속 문의 경로로서 업무상 필요 — 보존(사용자 결정 2026-07-09)",
             "examples": preserved_phone[:10]},
            {"key": "otp", "name": "OTP 일련번호",
             "count": len(preserved_otp),
             "note": "OTP 기기 일련번호 언급 — 단독으로는 계정 접근 불가한 기기 식별자.",
             "rationale": "장애 상담 재현에 필요한 값 — 보존(사용자 결정 2026-07-09)",
             "examples": preserved_otp[:10]},
            {"key": "already", "name": "원본 자체 끝자리 *** 마스킹(기존 문화)",
             "count": len(preserved_already),
             "note": "상담 원문이 이미 계좌·실명번호 끝자리를 *로 가려 기록하는 문화 — 추가 조치 불필요, mask_pii도 같은 방식을 따름.",
             "rationale": "이미 마스킹된 상태로 판단 — 이중 마스킹 없이 원형 유지",
             "examples": preserved_already[:10]},
        ],
    }

    # ── 콘솔 수지표 ──
    print(f"파일 {len(files)} · 행 {tot_rows:,} · Q행 {tot_qrows:,} · 쌍 {tot_pairs:,} · 중복병합 {tot_merged} · 청크 {len(rebuilt):,}")
    for r in rules:
        print(f"  [{r['key']}] {r['name']}: 마스킹 {r['count']}건 / 제외 {r['excluded_count']}건")
    print(f"영향 청크 {len(affected)}건: {affected}")
    print(f"건별 자동검증: {auto_pass}/{len(all_events)} 통과"
          + ("" if auto_pass == len(all_events) else
             f" · 실패 {[e['eid'] for e in all_events if not e['auto']]}"))
    print(f"보존 스캔 — 고객사쌍 {client_pairs:,}(고유 {len(client_names)}) · 전화 {len(preserved_phone)} · OTP {len(preserved_otp)} · 기존*** {len(preserved_already)}")
    print(f"배포 정합: {match:,}/{len(rebuilt):,} 일치" + (f" · 불일치 {mismatch_ids[:5]}" if mismatch_ids else " (전수 일치)"))

    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(TEMPLATE.replace("/*__DATA__*/null", payload), encoding="utf-8")
    print(f"\n[report] → {REPORT}")


TEMPLATE = r"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>상담매뉴얼 PII 분석·마스킹 보고서</title>
<style>
:root{
  --page:#f9f9f7; --surface:#fcfcfb; --ink:#0b0b0b; --ink2:#52514e; --muted:#898781;
  --grid:#e1e0d9; --axis:#c3c2b7; --ring:rgba(11,11,11,.10);
  --s1:#2a78d6; --seq:#2a78d6; --good:#0ca30c; --crit:#d03b3b; --warn:#fab219;
  --mask-del:#fdecec; --mask-del-ink:#a32626; --mask-add:#eaf6ea; --mask-add-ink:#0a5c0a;
  --keep:#fff7e6; --keep-ink:#8a5a00; --code:#f0efec;
}
@media (prefers-color-scheme: dark){:root{
  --page:#0d0d0d; --surface:#1a1a19; --ink:#fff; --ink2:#c3c2b7; --muted:#898781;
  --grid:#2c2c2a; --axis:#383835; --ring:rgba(255,255,255,.10);
  --s1:#3987e5; --seq:#3987e5; --good:#0ca30c; --crit:#d03b3b;
  --mask-del:#3a1d1d; --mask-del-ink:#f0a3a3; --mask-add:#1c3320; --mask-add-ink:#9fdba4;
  --keep:#33290f; --keep-ink:#e8c169; --code:#262624;
}}
*{box-sizing:border-box}
body{margin:0;background:var(--page);color:var(--ink);
  font:15px/1.65 system-ui,-apple-system,"Segoe UI","Malgun Gothic",sans-serif;}
.wrap{max-width:1060px;margin:0 auto;padding:0 24px 80px}
.banner{background:var(--crit);color:#fff;padding:10px 24px;font-weight:600;font-size:14px;
  display:flex;gap:10px;align-items:center;justify-content:center;text-align:center}
header.hero{padding:44px 0 8px}
h1{font-size:30px;line-height:1.25;margin:0 0 8px;letter-spacing:-.01em}
.sub{color:var(--ink2);max-width:70ch}
.meta{display:flex;flex-wrap:wrap;gap:8px 22px;color:var(--muted);font-size:13px;margin-top:14px}
.meta b{color:var(--ink2);font-weight:600}
h2{font-size:21px;margin:56px 0 6px;letter-spacing:-.01em}
h2 .no{color:var(--muted);font-weight:600;margin-right:8px}
h3{font-size:16px;margin:26px 0 6px}
.lede{color:var(--ink2);margin:0 0 18px;max-width:78ch}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:26px 0 6px}
.kpi{background:var(--surface);border:1px solid var(--ring);border-radius:12px;padding:14px 16px}
.kpi .v{font-size:26px;font-weight:700;letter-spacing:-.01em}
.kpi .l{font-size:12.5px;color:var(--muted);margin-top:2px}
.kpi.ok .v{color:var(--good)}
.card{background:var(--surface);border:1px solid var(--ring);border-radius:14px;padding:20px 22px;margin:16px 0}
code,.rx{font-family:ui-monospace,Consolas,monospace;font-size:12.5px;background:var(--code);
  border-radius:6px;padding:2px 6px}
.rx{display:block;padding:9px 12px;overflow-x:auto;white-space:pre;margin:8px 0;color:var(--ink2)}
.flow{display:flex;flex-wrap:wrap;align-items:stretch;gap:0;margin:18px 0 4px}
.flow .step{background:var(--surface);border:1px solid var(--ring);border-radius:10px;
  padding:10px 14px;min-width:118px;flex:1}
.flow .step b{display:block;font-size:13.5px;overflow-wrap:anywhere}
.flow .step span{font-size:12px;color:var(--muted)}
.flow .arr{align-self:center;color:var(--muted);padding:0 8px;font-size:16px}
.flow .step.hl{border-color:var(--s1);box-shadow:inset 0 0 0 1px var(--s1)}
table{width:100%;border-collapse:collapse;font-size:13.5px}
th{color:var(--muted);font-weight:600;text-align:left;padding:7px 10px;border-bottom:1px solid var(--axis);
  font-size:12px;white-space:nowrap}
td{padding:8px 10px;border-bottom:1px solid var(--grid);vertical-align:top}
tr:last-child td{border-bottom:none}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
.tbl-scroll{overflow-x:auto}
.pill{display:inline-block;font-size:11.5px;font-weight:600;border-radius:99px;padding:1px 9px;white-space:nowrap}
.pill.card{background:var(--mask-del);color:var(--mask-del-ink)}
.pill.acct{background:#e7f0fb;color:#1c5cab}
.pill.weak{background:var(--keep);color:var(--keep-ink)}
@media (prefers-color-scheme: dark){.pill.acct{background:#1d2a3d;color:#86b6ef}}
.b4{background:var(--mask-del);color:var(--mask-del-ink);text-decoration:line-through;
  padding:1px 5px;border-radius:5px;font-family:ui-monospace,Consolas,monospace;font-size:12.5px}
.af{background:var(--mask-add);color:var(--mask-add-ink);padding:1px 5px;border-radius:5px;
  font-family:ui-monospace,Consolas,monospace;font-size:12.5px}
.kp{background:var(--keep);color:var(--keep-ink);padding:1px 5px;border-radius:5px;
  font-family:ui-monospace,Consolas,monospace;font-size:12.5px}
.ctx{color:var(--ink2)}
.cid{font-family:ui-monospace,Consolas,monospace;font-size:11.5px;color:var(--muted);white-space:nowrap}
.legend{display:flex;flex-wrap:wrap;gap:16px;font-size:12.5px;color:var(--ink2);margin:6px 0 14px}
.chart{margin:10px 0 4px}
.bar-row{display:grid;grid-template-columns:130px 1fr 52px;align-items:center;gap:10px;padding:3px 0}
.bar-row .lbl{font-size:13px;text-align:right;color:var(--ink2);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.bar-track{height:18px;position:relative}
.bar{height:18px;background:var(--seq);border-radius:0 4px 4px 0;min-width:2px;position:relative}
.bar-row .val{font-size:12.5px;color:var(--ink2);font-variant-numeric:tabular-nums}
.bar-row:hover .bar{filter:brightness(1.12)}
.axis-line{border-left:1px solid var(--axis)}
.note{font-size:12.5px;color:var(--muted);margin-top:10px}
.keep-card{border-left:4px solid var(--warn)}
.keep-card h3{margin-top:0}
.keep-card .cnt{font-size:22px;font-weight:700;float:right;margin-left:16px}
.keep-card .why{font-size:13px;color:var(--ink2);background:var(--code);border-radius:8px;padding:8px 12px;margin:10px 0}
details{margin-top:10px}
summary{cursor:pointer;color:var(--s1);font-size:13.5px;font-weight:600}
.verify{display:flex;gap:10px;align-items:flex-start;background:var(--surface);
  border:1px solid var(--ring);border-left:4px solid var(--good);border-radius:12px;padding:14px 18px;margin:14px 0}
.verify .ic{color:var(--good);font-size:18px;line-height:1.4}
footer{margin-top:70px;padding-top:18px;border-top:1px solid var(--grid);color:var(--muted);font-size:12.5px}
.toc{display:flex;flex-wrap:wrap;gap:8px;margin-top:18px}
.toc a{font-size:12.5px;color:var(--s1);text-decoration:none;border:1px solid var(--ring);
  border-radius:99px;padding:3px 12px;background:var(--surface)}
.toc a:hover{border-color:var(--s1)}
#tip{position:fixed;pointer-events:none;background:var(--ink);color:var(--page);font-size:12px;
  padding:5px 9px;border-radius:7px;opacity:0;transition:opacity .12s;z-index:9;max-width:280px}
.badge{display:inline-flex;align-items:center;gap:4px;font-size:11.5px;font-weight:600;
  border-radius:99px;padding:1px 8px;white-space:nowrap}
.badge.ok{background:var(--mask-add);color:var(--mask-add-ink)}
.badge.fail{background:var(--mask-del);color:var(--mask-del-ink)}
.eid{font-family:ui-monospace,Consolas,monospace;font-size:11.5px;font-weight:700;white-space:nowrap}
.eval{display:flex;gap:4px}
.eval button{font:600 12px/1 system-ui,sans-serif;border:1px solid var(--ring);background:var(--surface);
  color:var(--ink2);border-radius:7px;padding:5px 9px;cursor:pointer;white-space:nowrap}
.eval button:hover{border-color:var(--s1)}
.eval button.on-ok{background:var(--mask-add);color:var(--mask-add-ink);border-color:var(--good)}
.eval button.on-ng{background:var(--mask-del);color:var(--mask-del-ink);border-color:var(--crit)}
.toolbar{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin:12px 0}
.toolbar .prog{font-size:13px;color:var(--ink2)}
.toolbar .prog b{color:var(--ink)}
.toolbar button{font:600 12.5px/1 system-ui,sans-serif;border:1px solid var(--ring);
  background:var(--surface);color:var(--s1);border-radius:8px;padding:7px 13px;cursor:pointer}
.toolbar button:hover{border-color:var(--s1)}
tr.row-ng td{background:var(--mask-del)}
</style>
</head>
<body>
<div class="banner">⚠️ 실제 개인·민감정보(마스킹 전 원본) 포함 — 로컬 열람 전용 · 외부 공유 및 git 커밋 금지</div>
<div class="wrap">

<header class="hero">
  <h1>상담(콜센터) 데이터 개인·민감정보 분석 및 마스킹 처리 보고서</h1>
  <p class="sub">PB고객지원센터 상담매뉴얼 원본(.xls 19개)을 전수 스캔해 마스킹 3종 규칙을 적용한 내역과,
  분석 후 <b>보존하기로 결정한 항목</b>의 현황을 실데이터 근거와 함께 정리했다.
  모든 수치는 이 보고서 생성 시점에 원본에서 재계측한 값이며, 온라인 배포 청크와 전수 대조로 검증했다.</p>
  <div class="meta">
    <span>생성일 <b id="m-date"></b></span>
    <span>원본 <b>코스콤(주)PB고객지원센터_ 상담매뉴얼/*.xls</b></span>
    <span>마스킹 로직 <b>deploy/online/parse_counsel_xls.py · mask_pii()</b></span>
    <span>재현 <b><code>.venv/bin/python deploy/online/report_counsel_pii.py</code></b></span>
  </div>
  <nav class="toc">
    <a href="#s1">① 요약</a><a href="#s2">② 처리 파이프라인</a><a href="#s3">③ 마스킹 규칙·근거</a>
    <a href="#s4">④ 업무별 분포</a><a href="#s5">⑤ 분석 후 보존 결정 항목</a><a href="#s6">⑥ 정합성 검증</a><a href="#s7">⑦ 부록: 전체 목록</a>
  </nav>
</header>

<h2 id="s1"><span class="no">①</span>요약</h2>
<p class="lede">2026-07-09 원본 전수 PII 스캔에서 원본 상담 문화가 이미 식별번호 끝자리를 <code>***</code>로 가리고
있음을 확인했고, 이 문화에서 <b>누락된 3가지 유형만</b> 같은 방식으로 보완 마스킹했다.
고객사명·담당자 연락처 등은 업무 필요성과 접근키 게이트(비공개 전제)를 근거로 보존을 결정했다.</p>
<div class="kpis" id="kpis"></div>

<h2 id="s2"><span class="no">②</span>처리 파이프라인</h2>
<p class="lede">마스킹은 중복병합 <b>뒤</b>, 청크 생성 시점에 적용된다 — 쌍 수·청크 id 순번이 마스킹과 무관하게
안정되도록 설계했다. 온라인 업로드는 접근키 게이트(<code>DEMO_ACCESS_KEY</code>) 뒤에서만 조회 가능하다.</p>
<div class="flow" id="flow"></div>

<h2 id="s3"><span class="no">③</span>마스킹 규칙과 실데이터 근거</h2>
<p class="lede">규칙 3종의 정규식·정책·제외(오탐 방지) 조건과, 원본에서 실제로 치환된 전 건을
<span class="b4">마스킹 전</span> → <span class="af">마스킹 후</span> 대조로 보인다.</p>
<div id="rules"></div>

<h2 id="s4"><span class="no">④</span>업무별 분포</h2>
<p class="lede">19개 업무(파일) 중 마스킹이 발생한 업무의 치환 건수. 막대에 마우스를 올리면 상세가 표시된다.</p>
<div class="card"><div class="chart" id="chart"></div>
<div class="note">치환 이벤트 기준(한 청크에 여러 건 가능) · 마스킹 0건 업무는 표에서 확인</div></div>
<details><summary>19개 업무 전체 표 보기</summary>
<div class="card tbl-scroll"><table id="sector-tbl">
<thead><tr><th>업무</th><th class="num">청크</th><th class="num">영향 청크</th><th class="num">치환 건수</th></tr></thead>
<tbody></tbody></table></div></details>

<h2 id="s5"><span class="no">⑤</span>분석 후 보존 결정 항목 (마스킹 미적용)</h2>
<p class="lede">스캔에서 식별되었으나 <b>마스킹하지 않기로 결정</b>한 항목들이다. 각 항목의 실측 규모와
대표 사례, 보존 사유(2026-07-09 사용자 결정, <code>상담매뉴얼_온라인추가_계획.md</code> §1·§7)를 기록한다.
전제 조건은 <b>접근키 게이트 뒤 비공개 운영</b>이며, 필요 시 마스킹 패스를 파서 옵션으로 재도입할 수 있다.</p>
<div id="preserved"></div>

<h2 id="s6"><span class="no">⑥</span>정합성 검증</h2>
<div id="verify"></div>
<p class="lede" style="margin-top:14px">검증 방법: 이 보고서 생성 시 원본 .xls를 파서와 동일한 경로로 재파싱·재마스킹해
청크를 재구성하고, 실제 배포 산출물 <code>data/chunks_counsel.jsonl</code>과 <b>필드 전체를 전수 비교</b>했다.
또한 계측용 치환 로직이 운영 <code>mask_pii()</code>와 청크·필드 단위로 완전 일치함을 assert로 강제했다.</p>

<h2 id="s7"><span class="no">⑦</span>부록 — 건별 추적·평가 대장</h2>
<p class="lede">마스킹 치환 <b>전 건</b>에 고유번호(M-###)를 부여한 추적 대장이다. 건마다
<b>3중 자동검증</b>(잔존 패턴 재탐지 · 원본 값의 배포 데이터 잔존 · 마스킹 결과의 배포 반영)을 수행했고,
우측 <b>평가</b> 버튼으로 사람이 건별 적합/부적합을 판정할 수 있다(브라우저에 저장, 내보내기 가능).</p>
<div class="toolbar">
  <span class="prog" id="eval-prog"></span>
  <button id="btn-export">평가 결과 내보내기 (JSON)</button>
  <button id="btn-csv">CSV</button>
  <button id="btn-reset">평가 초기화</button>
</div>
<div class="card tbl-scroll"><table id="appendix">
<thead><tr><th>No</th><th>청크 id</th><th>업무</th><th>규칙</th><th>필드</th>
<th>근거(문맥 · <span class="b4">전</span>→<span class="af">후</span>)</th><th>자동검증</th><th>평가</th></tr></thead>
<tbody></tbody></table></div>
<div class="note">자동검증 3항목 — <b>잔존</b>: 마스킹 결과가 다시 PII 패턴으로 탐지되지 않음 ·
<b>원본</b>: 마스킹 전 값이 배포 데이터(9천여 청크 전체) 어디에도 남아 있지 않음 ·
<b>반영</b>: 마스킹 후 값이 해당 배포 청크에 실제 존재함</div>

<footer>
  본 보고서는 읽기 전용 분석 도구가 생성했으며 원본·파서·배포 청크를 변경하지 않는다.
  마스킹 전 원본 값이 포함되므로 <b>presentations/counsel-pii-report.html은 .gitignore로 커밋이 차단</b>되어 있다.
</footer>
</div>
<div id="tip"></div>
<script>
const D = /*__DATA__*/null;
const esc = s => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt = n => n.toLocaleString('ko-KR');
document.getElementById('m-date').textContent = D.generated;

// ── KPI ──
const T = D.totals;
const kpis = [
  [fmt(T.files)+'개', '원본 .xls 파일', ''],
  [fmt(T.chunks), '상담 Q&A 청크', ''],
  [fmt(T.events)+'건', '마스킹 치환', ''],
  [fmt(T.affected)+'청크', '마스킹 영향', ''],
  [fmt(T.auto_pass)+'/'+fmt(T.events), '건별 자동검증 통과', T.auto_pass===T.events?'ok':''],
  [D.preserved.length+'항목', '분석 후 보존 결정', ''],
];
document.getElementById('kpis').innerHTML = kpis.map(([v,l,cls])=>
  `<div class="kpi ${cls}"><div class="v">${v}</div><div class="l">${l}</div></div>`).join('');

// ── 파이프라인 ──
const steps = [
  ['원본 .xls ×'+T.files, '고객지원센터 상담 Q&A'],
  ['파싱', fmt(T.q_rows)+' Q행 → '+fmt(T.pairs)+' 쌍'],
  ['중복병합', T.dup_merged+'건 병합'],
  ['mask_pii()', '3종 규칙 · '+T.events+'건 치환', true],
  ['chunks_counsel.jsonl', fmt(T.chunks)+' 청크'],
  ['Upstash 업서트', '접근키 게이트 뒤 공개'],
];
document.getElementById('flow').innerHTML = steps.map(([b,s,hl],i)=>
  (i? '<div class="arr">→</div>':'') +
  `<div class="step${hl?' hl':''}"><b>${esc(b)}</b><span>${esc(s)}</span></div>`).join('');

// ── 근거 행 렌더 ──
const evRow = e =>
  `<span class="ctx">${esc(e.ctx_pre)}</span><span class="b4">${esc(e.before)}</span>` +
  `<span class="af">→ ${esc(e.after)}</span><span class="ctx">${esc(e.ctx_post)}</span>`;
const exRow = e =>
  `<span class="ctx">${esc(e.ctx_pre)}</span><span class="kp">${esc(e.before)}</span>` +
  `<span class="ctx">${esc(e.ctx_post)}</span> <span class="cid">— ${esc(e.reason)}</span>`;
const fieldKo = {q:'질문', a:'답변', note:'비고'};
const chkKo = {chk_residual:'잔존', chk_leak:'원본', chk_applied:'반영'};
const autoBadge = e => e.auto
  ? '<span class="badge ok">✔ 3/3</span>'
  : '<span class="badge fail">✖ ' + Object.keys(chkKo).filter(k=>!e[k]).map(k=>chkKo[k]).join('·') + ' 실패</span>';

// ── 규칙 섹션 ──
const ruleNo = {card:'규칙 1', acct:'규칙 2', weak:'규칙 3'};
document.getElementById('rules').innerHTML = D.rules.map(r => `
<div class="card">
  <h3><span class="pill ${r.key}">${ruleNo[r.key]}</span> ${esc(r.name)} — 치환 ${r.count}건${r.excluded_count?` · 오탐 방지 제외 ${r.excluded_count}건`:''}</h3>
  <p style="margin:6px 0;color:var(--ink2)">${esc(r.policy)} → 결과 형태 <code>${esc(r.shape)}</code></p>
  <code class="rx">${esc(r.regex)}</code>
  <div class="tbl-scroll"><table>
    <thead><tr><th>No</th><th>청크 id</th><th>업무</th><th>필드</th><th>근거</th><th>자동검증</th></tr></thead>
    <tbody>${r.events.map(e=>`<tr><td class="eid">${e.eid}</td><td class="cid">${esc(e.id)}</td><td>${esc(e.sector)}</td>
      <td>${fieldKo[e.field]}</td><td>${evRow(e)}</td><td>${autoBadge(e)}</td></tr>`).join('')}</tbody>
  </table></div>
  ${r.excluded.length? `<details><summary>오탐 방지로 마스킹하지 않은 매치 ${r.excluded.length}건 (예시계좌·산식 보호)</summary>
  <div class="tbl-scroll" style="margin-top:8px"><table>
    <thead><tr><th>No</th><th>청크 id</th><th>업무</th><th>근거</th></tr></thead>
    <tbody>${r.excluded.slice(0,40).map(e=>`<tr><td class="eid">${e.eid}</td><td class="cid">${esc(e.id)}</td><td>${esc(e.sector)}</td><td>${exRow(e)}</td></tr>`).join('')}
    ${r.excluded.length>40?`<tr><td colspan="4" class="cid">… 외 ${r.excluded.length-40}건</td></tr>`:''}</tbody>
  </table></div></details>`:''}
</div>`).join('');

// ── 업무별 차트 (마스킹 발생 업무, 치환 건수 내림차순) ──
const withEv = D.sectors.filter(s=>s.events>0).sort((a,b)=>b.events-a.events);
const maxEv = Math.max(...withEv.map(s=>s.events), 1);
document.getElementById('chart').innerHTML = withEv.map(s=>`
  <div class="bar-row" data-tip="${esc(s.name)} — 치환 ${s.events}건 · 영향 ${s.affected}청크 / 전체 ${fmt(s.chunks)}청크">
    <div class="lbl">${esc(s.name)}</div>
    <div class="bar-track axis-line"><div class="bar" style="width:${(s.events/maxEv*100).toFixed(1)}%"></div></div>
    <div class="val">${s.events}건</div>
  </div>`).join('');
document.querySelector('#sector-tbl tbody').innerHTML = D.sectors.map(s=>
  `<tr><td>${esc(s.name)}</td><td class="num">${fmt(s.chunks)}</td>
   <td class="num">${s.affected||'—'}</td><td class="num">${s.events||'—'}</td></tr>`).join('');

// 툴팁
const tip = document.getElementById('tip');
document.querySelectorAll('[data-tip]').forEach(el=>{
  el.addEventListener('mousemove', ev=>{
    tip.textContent = el.dataset.tip; tip.style.opacity = 1;
    tip.style.left = Math.min(ev.clientX+14, innerWidth-300)+'px';
    tip.style.top = (ev.clientY+14)+'px';
  });
  el.addEventListener('mouseleave', ()=> tip.style.opacity = 0);
});

// ── 보존 결정 항목 ──
document.getElementById('preserved').innerHTML = D.preserved.map(p=>`
<div class="card keep-card">
  <div class="cnt">${fmt(p.count)}건${p.unique?`<span style="font-size:12.5px;color:var(--muted)"> · 고유 ${p.unique}</span>`:''}</div>
  <h3>${esc(p.name)}</h3>
  <p style="margin:4px 0;color:var(--ink2)">${esc(p.note)}</p>
  <div class="why"><b>보존 사유</b> — ${esc(p.rationale)}</div>
  ${p.examples.length? `<details><summary>실데이터 사례 ${Math.min(p.examples.length, p.key==='clients'?12:10)}건 보기</summary>
  <div class="tbl-scroll" style="margin-top:8px"><table>
    <thead><tr>${p.key==='clients'?'<th>고객사 (표기 상위)</th>':'<th>청크 id</th><th>업무</th><th>문맥</th>'}</tr></thead>
    <tbody>${p.examples.map(e=> p.key==='clients'
      ? `<tr><td><span class="kp">${esc(e.ctx_hit)}</span><span class="ctx">${esc(e.ctx_post)}</span></td></tr>`
      : `<tr><td class="cid">${esc(e.id)}</td><td>${esc(e.sector)}</td>
         <td><span class="ctx">${esc(e.ctx_pre)}</span><span class="kp">${esc(e.ctx_hit)}</span><span class="ctx">${esc(e.ctx_post)}</span></td></tr>`).join('')}</tbody>
  </table></div></details>`:''}
</div>`).join('');

// ── 검증 ──
const okAll = T.mismatch.length === 0;
document.getElementById('verify').innerHTML = `
<div class="kpis">
  <div class="kpi ok"><div class="v">${fmt(T.match)} / ${fmt(T.chunks)}</div><div class="l">재구성 청크 ↔ 배포 청크 전수 일치</div></div>
  <div class="kpi ok"><div class="v">${fmt(T.deployed)}</div><div class="l">배포 chunks_counsel.jsonl 청크 수</div></div>
  <div class="kpi ${okAll?'ok':''}"><div class="v">${okAll?'통과':'불일치 '+T.mismatch.length}</div><div class="l">정합성 판정</div></div>
</div>
<div class="verify"><div class="ic">${okAll?'✔':'⚠'}</div><div>
  ${okAll
    ? `원본에서 재구성한 <b>${fmt(T.chunks)}개 청크 전부</b>가 배포 산출물과 필드 단위까지 일치했다.
       즉 온라인에 올라간 상담 데이터는 이 보고서에 기록된 마스킹이 <b>빠짐없이 적용된 상태</b>다.
       마스킹 영향 청크는 ${T.affected}건이며 부록에서 전 건 확인 가능하다.`
    : `<b>${T.mismatch.length}건 불일치</b>: <code>${T.mismatch.slice(0,8).join(', ')}</code> — 원본 또는 배포 청크가
       보고서 생성 이후 변경되었을 수 있다. 재업서트·재생성으로 동기화 필요.`}
</div></div>`;

// ── 부록: 건별 추적·평가 대장 ──
const allEv = D.rules.flatMap(r=>r.events.map(e=>({...e, rname: r.key})));
allEv.sort((a,b)=> a.eid<b.eid?-1:1);
const EVAL_KEY = 'counsel-pii-eval-v1';
const loadEval = ()=> { try { return JSON.parse(localStorage.getItem(EVAL_KEY)||'{}'); } catch { return {}; } };
const saveEval = ev => localStorage.setItem(EVAL_KEY, JSON.stringify(ev));

document.querySelector('#appendix tbody').innerHTML = allEv.map(e=>
  `<tr id="row-${e.eid}"><td class="eid">${e.eid}</td><td class="cid">${esc(e.id)}</td><td>${esc(e.sector)}</td>
   <td><span class="pill ${e.rname}">${ruleNo[e.rname]}</span></td><td>${fieldKo[e.field]}</td>
   <td>${evRow(e)}</td><td>${autoBadge(e)}</td>
   <td><div class="eval" data-eid="${e.eid}">
     <button data-v="ok" title="마스킹 적합">✓ 적합</button>
     <button data-v="ng" title="마스킹 부적합/재검토">✗ 부적합</button>
   </div></td></tr>`).join('');

function refreshEval(){
  const st = loadEval();
  let done = 0, ng = 0;
  document.querySelectorAll('.eval').forEach(g=>{
    const v = st[g.dataset.eid];
    if (v) done++;
    if (v === 'ng') ng++;
    g.querySelector('[data-v="ok"]').className = v==='ok' ? 'on-ok' : '';
    g.querySelector('[data-v="ng"]').className = v==='ng' ? 'on-ng' : '';
    document.getElementById('row-'+g.dataset.eid).classList.toggle('row-ng', v==='ng');
  });
  document.getElementById('eval-prog').innerHTML =
    `사람 평가 <b>${done} / ${allEv.length}</b> 건 완료` + (ng? ` · <b style="color:var(--crit)">부적합 ${ng}건</b>`:'');
}
document.querySelectorAll('.eval button').forEach(b=>{
  b.addEventListener('click', ()=>{
    const st = loadEval(), eid = b.parentElement.dataset.eid, v = b.dataset.v;
    st[eid] = (st[eid] === v) ? undefined : v;   // 재클릭 시 해제
    if (!st[eid]) delete st[eid];
    saveEval(st); refreshEval();
  });
});
refreshEval();

const evalRecords = ()=> {
  const st = loadEval();
  return allEv.map(e=>({no:e.eid, chunk_id:e.id, sector:e.sector, rule:e.rname, field:e.field,
    before:e.before, after:e.after,
    auto: e.auto?'pass':'fail',
    auto_detail: Object.keys(chkKo).map(k=>chkKo[k]+':'+(e[k]?'통과':'실패')).join(' '),
    human: st[e.eid]==='ok'?'적합': st[e.eid]==='ng'?'부적합':'미평가'}));
};
const dl = (name, mime, body)=>{
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([body], {type:mime}));
  a.download = name; a.click(); URL.revokeObjectURL(a.href);
};
document.getElementById('btn-export').onclick = ()=>
  dl('counsel-pii-eval.json','application/json', JSON.stringify({generated:D.generated,
     evaluated_at:new Date().toISOString(), records:evalRecords()}, null, 2));
document.getElementById('btn-csv').onclick = ()=>{
  const rows = evalRecords();
  const hdr = Object.keys(rows[0]);
  const csv = '\uFEFF' + [hdr.join(','), ...rows.map(r=>hdr.map(h=>
    '"'+String(r[h]).replace(/"/g,'""')+'"').join(','))].join('\n');
  dl('counsel-pii-eval.csv','text/csv', csv);
};
document.getElementById('btn-reset').onclick = ()=>{
  if (confirm('건별 사람 평가 기록을 모두 초기화할까요?')) { localStorage.removeItem(EVAL_KEY); refreshEval(); }
};
</script>
</body>
</html>
"""

if __name__ == "__main__":
    main()
