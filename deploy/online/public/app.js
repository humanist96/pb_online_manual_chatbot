/* ═══════════════════════════════════════════════════════════════════
   PB 매뉴얼 데스크 — 프런트 (vanilla JS, 무의존)
   상담 모드(기본): 스레드 + 근거 패널.  QA 모드: 계측 레이어 온.
   ═══════════════════════════════════════════════════════════════════ */
"use strict";

const $ = s => document.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"']/g,
  c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const TYPES = {
  overview:    "화면개요",
  description: "화면설명",
  glossary:    "용어찾기",
  related:     "관련화면",
  qa:          "질문보기",
};
const LS_KEY = "pbdesk.v1";
let FEEDBACK_AVAILABLE = false;

/* ── 상태 ── */
const S = {
  qa: false,
  rerank: true,        // 정밀 게이트(리랭커) 사용 여부 — 컴포저 '정밀' 토글
  tauTouched: false,   // QA 슬라이더로 τ를 직접 만졌는지 (아니면 서버 기본값 추종)
  scope: [],           // 브레드크럼 스코프 (부문>중분류>화면) — 교차 오염 방지
  sectorTree: null,    // /api/sectors 캐시
  alpha: 0.5, topk: 5, tau: 0.5, gateMode: "cosine",
  types: new Set(Object.keys(TYPES)),
  samples: [],        // 예상 질문 후보 [{q,sid,t}] — /api/suggest 로 채움
  metaSamples: [],    // /api/meta 의 samples(문자열) — suggest 실패 시 폴백 원본
  suggestSeed: null,  // 다양성 시드 ("다른 질문 보기"로 교체)
  suggestBusy: false, // suggest 로딩 중복 방지
  sessions: [],       // [{id,title,ts,turns:[]}] — localStorage 영속
  cur: null,          // 현재 세션 id
  turns: [],          // 현재 세션 turns 참조
  sel: null,          // 근거 패널이 보여주는 turn id
  busy: false,
};

const uid = () => (crypto.randomUUID ? crypto.randomUUID()
  : "t" + Date.now().toString(36) + Math.random().toString(36).slice(2, 8));

/* ═══════════════ 영속화 ═══════════════ */
function loadStore() {
  try {
    const d = JSON.parse(localStorage.getItem(LS_KEY) || "{}");
    S.sessions = Array.isArray(d.sessions) ? d.sessions : [];
    S.qa = !!d.qa;
    S.rerank = d.rerank !== false;
    S.scope = Array.isArray(d.scope) ? d.scope : [];
    // 확장(화면/업무 루트) 이전에 저장된 구형 스코프 마이그레이션 — 당시엔 화면매뉴얼뿐이었다
    if (S.scope.length && S.scope[0] !== "화면" && S.scope[0] !== "업무")
      S.scope = ["화면", ...S.scope];
    if (d.navClosed) document.body.classList.add("nav-closed");
    // 중단된 턴은 오류로 정리
    for (const ss of S.sessions)
      for (const t of ss.turns)
        if (t.state !== "done" && t.state !== "gated") t.state = t.answer ? "done" : "error";
  } catch { S.sessions = []; }
}
function saveStore() {
  try {
    S.sessions.sort((a, b) => b.ts - a.ts);
    localStorage.setItem(LS_KEY, JSON.stringify({
      sessions: S.sessions.slice(0, 30),
      qa: S.qa,
      rerank: S.rerank,
      scope: S.scope,
      navClosed: document.body.classList.contains("nav-closed"),
    }));
  } catch { /* 저장소 초과 시 조용히 무시 */ }
}
const trimHits = hits => (hits || []).map(h => ({
  rank: h.rank, chunk_type: h.chunk_type, section_path: h.section_path,
  sector: h.sector, sector_path: h.sector_path, manual: h.manual,
  text: h.text, screen_id: h.screen_id, screen_no: h.screen_no, title: h.title,
  source_url: h.source_url, confidence: h.confidence, low_conf: h.low_conf,
  dense: h.dense, sparse: h.sparse, cos: h.cos,
}));

/* ═══════════════ 마크다운 경량 렌더 ═══════════════ */
function inline(s) {
  return s
    .replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>")
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/►/g, '<span class="bullet">►</span>')
    .replace(/\[S(\d+)\]/g, (_, n) =>
      `<button type="button" class="cite" data-r="${n}" aria-label="근거 ${n} 보기">S${n}</button>`);
}
function mdTable(rows) {
  const cells = r => {
    const a = r.split("|").map(c => c.trim());
    if (a[0] === "") a.shift();
    if (a.length && a[a.length - 1] === "") a.pop();
    return a;
  };
  const head = cells(rows[0]), body = rows.slice(2).map(cells);
  return `<table><thead><tr>${head.map(h => `<th>${inline(h)}</th>`).join("")}</tr></thead><tbody>${
    body.map(r => `<tr>${r.map(c => `<td>${inline(c)}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
}
const LIST_RE = /^\s*([-*•►]|\d+[.)])\s+/;
function mdlite(text) {
  const lines = esc(text).split(/\r?\n/), out = [];
  let i = 0;
  while (i < lines.length) {
    const L = lines[i];
    if (!L.trim()) { i++; continue; }
    if ((L.match(/\|/g) || []).length >= 2 && i + 1 < lines.length && /^[\s|:\-]+$/.test(lines[i + 1])) {
      const rows = [L]; let j = i + 1;
      while (j < lines.length && lines[j].includes("|")) rows.push(lines[j++]);
      out.push(mdTable(rows)); i = j; continue;
    }
    if (LIST_RE.test(L)) {
      const ordered = /^\s*\d+[.)]/.test(L), items = []; let j = i;
      while (j < lines.length && LIST_RE.test(lines[j]))
        items.push(lines[j++].replace(LIST_RE, ""));
      out.push(`<${ordered ? "ol" : "ul"}>${items.map(x => `<li>${inline(x)}</li>`).join("")}</${ordered ? "ol" : "ul"}>`);
      i = j; continue;
    }
    const par = [L]; let j = i + 1;
    while (j < lines.length && lines[j].trim() && !LIST_RE.test(lines[j]) && !lines[j].includes("|"))
      par.push(lines[j++]);
    out.push(`<p>${par.map(inline).join("<br/>")}</p>`); i = j;
  }
  return out.join("");
}

/* 근거 본문 질의어 하이라이트 */
function highlight(text, q) {
  let html = esc(text).replace(/►/g, '<span class="bullet">►</span>');
  const toks = [...new Set(((q || "").match(/[0-9A-Za-z]{2,}|[가-힣]{2,}/g) || []))]
    .sort((a, b) => b.length - a.length).slice(0, 12);
  for (const t of toks) {
    const re = new RegExp(t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "gi");
    html = html.replace(re, m => `<mark>${m}</mark>`);
  }
  return html;
}

/* ═══════════════ 스레드 렌더 ═══════════════ */
const thread = $("#thread"), threadWrap = $("#thread-wrap");

function modePill(turn) {
  if (turn.state === "gated")
    return `<span class="mode-pill out"><span class="dot"></span>매뉴얼 밖</span>`;
  if (turn.used_llm)
    return `<span class="mode-pill gen"><span class="dot"></span>AI 생성 · ${esc((turn.backend || "").split(":").pop())}</span>`;
  return `<span class="mode-pill"><span class="dot"></span>발췌 답변</span>`;
}
function srcStrip(turn) {
  if (!turn.hits?.length) return "";
  const chips = turn.hits.map((h, i) => {
    const leaf = (h.section_path || []).slice(-1)[0] || h.screen_no || h.title || "";
    return `<button type="button" class="src-chip" data-r="${h.rank}" style="--i:${i}" title="${esc(leaf)}">
      <span class="sn">S${h.rank}</span><span class="sl">${esc(leaf)}</span></button>`;
  }).join("");
  return `<div class="src-strip">${chips}</div>`;
}
function turnFoot(turn) {
  const secs = ((turn.search_ms || 0) + (turn.gen_ms || 0)) / 1000;
  const meta = S.qa
    ? `검색 ${turn.search_ms}ms · 생성 ${turn.gen_ms}ms`
    : (secs ? `${secs.toFixed(1)}초` : "");
  const rx = turn.reacted, done = !!rx;
  const feedbackActions = FEEDBACK_AVAILABLE ? `<span class="a-react">
      <button type="button" class="a-act rx rx-up${rx === "up" ? " on" : ""}"${done ? " disabled" : ""}
        title="도움이 됐어요" aria-label="도움이 됐어요">👍</button>
      <button type="button" class="a-act rx rx-down${rx === "down" ? " on" : ""}"${done ? " disabled" : ""}
        title="아쉬웠어요" aria-label="아쉬웠어요">👎</button>
      <button type="button" class="a-act fb-open-turn" title="이 답변에 대한 상세 피드백 남기기">피드백</button>
    </span>` : "";
  return `<footer class="a-foot">
    <button type="button" class="a-act act-copy">복사</button>
    <button type="button" class="a-act act-regen">재생성</button>
    <button type="button" class="a-act ev-open-btn">근거 ${turn.hits?.length ?? 0}건</button>
    ${feedbackActions}
    ${modePill(turn)}<span class="a-meta">${esc(meta)}</span>
  </footer>`;
}
/* 예상·관련 질문 말풍선 1개. item 은 {q,sid,t} 또는 문자열(폴백) 모두 허용.
   data-q 에 질문 원문(esc), title 에 출처 화면(t), --i 는 순차 등장 스태거. */
function bubbleChip(item, i, left) {
  const q = typeof item === "string" ? item : (item.q || "");
  const t = typeof item === "string" ? "" : (item.t || "");
  return `<button type="button" class="chip ask-chip q-bubble${left ? " left" : ""}"
    data-q="${esc(q)}" style="--i:${i}"${t ? ` title="${esc(t)}"` : ""}>${esc(q)}</button>`;
}
function followups(turn) {
  const isLast = S.turns.length && S.turns[S.turns.length - 1].id === turn.id;
  if (!isLast || turn.state !== "done") return "";   // 마지막 done 턴에만 (기존 정책 유지)
  const asked = new Set(S.turns.map(t => t.q));
  const items = [], seen = new Set();
  const push = (q, t) => {
    q = (q || "").trim();
    if (!q || asked.has(q) || seen.has(q)) return;
    seen.add(q); items.push({ q, t });
  };
  // ① 이번 답변 근거 기반 관련 질문 우선 (최대 3, 세션에서 이미 물은 질문 제외)
  for (const r of (turn.related || [])) { if (items.length >= 3) break; push(r.q, r.t); }
  // ② 부족하면 근거 hits 의 qa 청크 질문으로 보충
  for (const h of (turn.hits || [])) {
    if (items.length >= 3) break;
    if (h.chunk_type !== "qa") continue;
    const q = (h.section_path || []).slice(-1)[0];
    if (q && q.endsWith("?") && q.length <= 60) push(q, h.screen_no || h.title || "");
  }
  // ③ 그래도 최소 2개 못 채우면 예상 질문(samples)으로 보충
  for (const sm of S.samples) {
    if (items.length >= 2) break;
    push(typeof sm === "string" ? sm : sm.q, typeof sm === "string" ? "" : sm.t);
  }
  if (!items.length) return "";
  return `<div class="followups"><p class="fl">이어서 물어볼 만한 질문이에요</p>
    <div class="chips">${items.map((it, i) => bubbleChip(it, i, true)).join("")}</div></div>`;
}
function turnBody(turn) {
  switch (turn.state) {
    case "searching":
      return `<div class="a-status"><span class="spin"></span>매뉴얼 검색 중…</div>
        <div class="skel-box"><div class="skel"></div><div class="skel"></div><div class="skel"></div></div>`;
    case "writing":
      return `${srcStrip(turn)}
        <div class="a-status"><span class="spin"></span>근거 ${turn.hits.length}건 확보 · 답변 작성 중…</div>
        <div class="skel-box"><div class="skel"></div><div class="skel"></div><div class="skel"></div></div>`;
    case "gated": {
      // 근거 기반 우회 질문(related) 우선, 없으면 예상 질문(samples) 폴백
      const gq = (turn.related && turn.related.length)
        ? turn.related.slice(0, 3) : S.samples.slice(0, 3);
      return `<div class="a-gated">
          <h3>매뉴얼에서 확인되지 않았어요</h3>
          <p>계좌 매뉴얼 안에서 이 질문의 근거를 찾지 못했어요.
             화면 이름이나 용어를 넣어 질문을 바꿔보시겠어요? 오른쪽 근거는 참고용이에요.</p>
          <div class="chips">${gq.map((it, i) => bubbleChip(it, i, true)).join("")}</div>
          <button type="button" class="fb-gap-link">이 내용이 매뉴얼에 있어야 한다고 생각하시나요? — 보강 요청하기 →</button>
        </div>${turnFoot(turn)}`;
    }
    case "error":
      return `<div class="a-error"><b>일시적인 연결 문제가 있었어요</b> — 잠시 후 다시 시도해 주세요.
        <button type="button" class="retry act-regen">다시 시도</button></div>`;
    default: { // done
      // 범위가 걸린 채 근거 0건 — 구형/과협소 스코프 안내 배너로 막다른 골목 방지
      const unscope = (turn.scope?.length && !(turn.hits || []).length)
        ? `<div class="scope-banner" role="status">
            <span class="sb-t">선택한 범위(${esc(turn.scope.join(" › "))})에서 근거를 찾지 못했어요.</span>
            <button type="button" class="sb-chip sb-unscope" data-q="${esc(turn.q)}">전체 범위로 다시 검색</button></div>` : "";
      return `${unscope}${srcStrip(turn)}
        <div class="a-body">${mdlite(turn.answer || "")}</div>
        ${turnFoot(turn)}`;
    }
  }
}
function scopeBanner(turn) {
  const h = turn.scope_hint;
  if (!h || turn.hintDismissed) return "";
  // ① 매뉴얼 레벨(화면/업무) 우선 — 스코프가 매뉴얼조차 없을 때
  if (h.ambiguous_manual && !(turn.scope?.length)) {
    const chips = h.manuals.slice(0, 2).map(m =>
      `<button type="button" class="sb-chip sb-scope" data-scope="${esc((m.scope || [m.manual]).join(">"))}"
         data-q="${esc(turn.q)}">${esc(m.manual)} 매뉴얼에서만 (${m.count}건 · ${(+m.best).toFixed(2)})</button>`).join("");
    return `<div class="scope-banner" role="status">
      <span class="sb-t">화면·업무 매뉴얼에 걸쳐 있어요 — 어느 매뉴얼 기준으로 볼까요?</span>
      ${chips}<button type="button" class="sb-chip keep sb-keep">전체 유지</button></div>`;
  }
  // ② 부문 레벨 — 매뉴얼이 정해졌거나 단일 매뉴얼일 때
  if (h.ambiguous && (turn.scope?.length || 0) <= 1) {
    const chips = h.sectors.slice(0, 3).map(s =>
      `<button type="button" class="sb-chip sb-scope" data-scope="${esc((s.scope || [s.sector]).join(">"))}"
         data-q="${esc(turn.q)}">${esc(s.sector)}에서만 (${s.count}건 · ${(+s.best).toFixed(2)})</button>`).join("");
    return `<div class="scope-banner" role="status">
      <span class="sb-t">근거가 여러 부문에 걸쳐 있어요 — 어느 업무 기준으로 볼까요?</span>
      ${chips}<button type="button" class="sb-chip keep sb-keep">전체 유지</button></div>`;
  }
  return "";
}
function renderTurn(turn) {
  const el = document.createElement("article");
  el.className = "turn"; el.id = "turn-" + turn.id; el.dataset.turn = turn.id;
  const scopeTag = turn.scope?.length
    ? `<div class="u-scope">범위: <b>${esc(turn.scope.join(" › "))}</b></div>` : "";
  el.innerHTML = `<div class="u-row"><div class="u-bubble">${esc(turn.q)}</div></div>${scopeTag}
    <section class="a-card" aria-live="polite">${
      turn.state === "done" ? scopeBanner(turn) : ""}${turnBody(turn)}</section>${followups(turn)}`;
  return el;
}
function updateTurn(turn) {
  const el = document.getElementById("turn-" + turn.id);
  if (el) el.replaceWith(renderTurn(turn)); else thread.appendChild(renderTurn(turn));
}
function renderThread() {
  thread.innerHTML = "";
  for (const t of S.turns) thread.appendChild(renderTurn(t));
  document.body.classList.toggle("is-empty", !S.turns.length);
}
const scrollBottom = () => { threadWrap.scrollTop = threadWrap.scrollHeight; };

/* ═══════════════ 근거 패널 ═══════════════ */
const evMap = $("#ev-map"), evCards = $("#ev-cards"), evEmpty = $("#ev-empty"), evHead = $("#ev-head");

function buildTree(hits) {
  // 전 부문 확장: 부문(sector)을 최상위 레벨로 — 부문·화면 노드는 scope(좁히기 경로)를 가진다
  const roots = new Map();
  for (const h of hits) {
    const prefix = h.manual ? [h.manual, h.sector].filter(Boolean)
                            : (h.sector ? [h.sector] : []);
    const segs = [...prefix, ...(h.section_path || [])];
    if (!segs.length) continue;
    if (!roots.has(segs[0]))
      roots.set(segs[0], { label: segs[0], children: new Map(), ranks: [],
                           scope: prefix.length ? [prefix[0]] : null });
    let node = roots.get(segs[0]);
    segs.slice(1).forEach((seg, idx) => {
      if (!node.children.has(seg))
        node.children.set(seg, { label: seg, children: new Map(), ranks: [], scope: null });
      node = node.children.get(seg);
      if (!node.scope && prefix.length && idx < prefix.length - 1)
        node.scope = prefix.slice(0, idx + 2);          // 부문 레벨 스코프
      if (!node.scope && prefix.length && idx === prefix.length - 1)
        node.scope = [...(h.sector_path || prefix), h.screen_id];  // 문서 레벨
    });
    node.ranks.push(h.rank);
  }
  const collapse = (n, isRoot) => {
    while (!isRoot && n.children.size === 1 && !n.ranks.length) {
      const c = n.children.values().next().value;
      n.label += " › " + c.label; n.ranks = c.ranks; n.children = c.children;
      n.scope = c.scope || n.scope;
    }
    for (const c of n.children.values()) collapse(c, false);
  };
  for (const r of roots.values()) collapse(r, true);
  return roots;
}
const scopeBtn = n => n.scope
  ? `<button type="button" class="mn-scope" data-scope="${esc(n.scope.join(">"))}"
       title="이 경로로 범위를 좁혀 다시 검색">좁히기</button>` : "";
const subRanks = n => {
  const acc = [...n.ranks];
  for (const c of n.children.values()) acc.push(...subRanks(c));
  return acc;
};
function renderNode(n, counter) {
  const ranks = subRanks(n).sort((a, b) => a - b);
  const cites = n.ranks.sort((a, b) => a - b).map(r =>
    `<button type="button" class="cite" data-r="${r}" aria-label="근거 ${r} 보기">S${r}</button>`).join("");
  let html = `<div class="mn-row" data-ranks="${ranks.join(" ")}" style="--i:${counter.v++}">
    <span class="mn-t" title="${esc(n.label)}">${esc(n.label)}</span>${cites}${scopeBtn(n)}</div>`;
  if (n.children.size)
    html += `<div class="mn-kids">${[...n.children.values()].map(c => renderNode(c, counter)).join("")}</div>`;
  return html;
}
function renderMap(hits) {
  const roots = buildTree(hits);
  if (!roots.size) { evMap.hidden = true; return; }
  const counter = { v: 0 };
  evMap.innerHTML = `<div class="map-l">근거 지도 — 매뉴얼 내 위치</div>` +
    [...roots.values()].map(r => {
      const own = r.ranks.sort((a, b) => a - b).map(k =>
        `<button type="button" class="cite" data-r="${k}">S${k}</button>`).join("");
      return `<div class="mn-root" data-ranks="${subRanks(r).join(" ")}">
          <span class="mn-t" title="${esc(r.label)}">${esc(r.label)}</span>${own}${scopeBtn(r)}</div>` +
        (r.children.size
          ? `<div class="mn-kids">${[...r.children.values()].map(c => renderNode(c, counter)).join("")}</div>`
          : "");
    }).join("");
  evMap.hidden = false;
}
function evCard(h, q) {
  const path = h.section_path || [];
  const trail = path.map((seg, i) =>
    `<span class="${i === path.length - 1 ? "leaf" : ""}">${esc(seg)}</span>` +
    (i < path.length - 1 ? '<span class="sep">›</span>' : "")).join("");
  const low = h.confidence != null && h.confidence < S.tau;
  return `<article class="ev-card${low ? " low" : ""}" id="evc-${h.rank}" data-r="${h.rank}"
      data-conf="${h.confidence ?? ""}" tabindex="0">
    <div class="evc-top">
      <button type="button" class="cite" data-r="${h.rank}">S${h.rank}</button>
      <span class="t-dot t-${esc(h.chunk_type)}"></span>
      <span class="evc-type">${esc(TYPES[h.chunk_type] || h.chunk_type)}</span>
      ${h.manual === "업무" ? '<span class="m-badge">업무</span>'
        : h.manual === "상담" ? '<span class="m-badge cs">상담</span>' : ""}
      ${low ? '<span class="low-flag">참고용</span>' : ""}
      <span class="evc-conf mono">${h.confidence != null ? h.confidence.toFixed(2) : ""}</span>
    </div>
    <div class="evc-path">${trail}</div>
    <p class="evc-text">${highlight(h.text, q)}</p>
    <button type="button" class="more" hidden>더보기</button>
    <div class="evc-meter">
      <div class="mrow"><span class="ml">dense</span><span class="mtrack"><i class="mfill dense" style="width:${Math.round((h.dense || 0) * 100)}%"></i></span><span class="mv">${(h.dense ?? 0).toFixed(2)}</span></div>
      <div class="mrow"><span class="ml">sparse</span><span class="mtrack"><i class="mfill sparse" style="width:${Math.round((h.sparse || 0) * 100)}%"></i></span><span class="mv">${(h.sparse ?? 0).toFixed(2)}</span></div>
    </div>
    <div class="evc-foot">
      ${h.screen_no
        ? `<button type="button" class="ticker" data-copy="${esc(h.screen_no)}" title="화면번호 복사 — 단말 입력용">화면 ${esc(h.screen_no)}</button>` : ""}
      ${h.source_url ? `<a href="${esc(h.source_url)}" target="_blank" rel="noopener">원문 매뉴얼 ↗</a>` : ""}
    </div>
  </article>`;
}
function renderEvidence(turn) {
  if (!turn) return;
  S.sel = turn.id;
  const hits = turn.hits || [];
  evHead.hidden = !hits.length;
  $("#ev-count").textContent = hits.length + "건";
  $("#ev-sub").textContent = "· " + turn.q;
  evEmpty.hidden = !!hits.length;
  if (hits.length) renderMap(hits); else evMap.hidden = true;
  evCards.innerHTML = hits.map(h => evCard(h, turn.q)).join("");
  requestAnimationFrame(() => {
    evCards.querySelectorAll(".evc-text").forEach(el => {
      if (el.scrollHeight > el.clientHeight + 2) el.nextElementSibling.hidden = false;
    });
  });
  updateQaStat(turn);
}

/* ═══════════════ QA 패널 ═══════════════ */
function updateQaStat(turn) {
  if (!turn) return;
  $("#qa-stat").textContent = turn.gen_ms != null
    ? `검색 ${turn.search_ms}ms · 생성 ${turn.gen_ms}ms · ${turn.backend || ""}`
    : (turn.search_ms != null ? `검색 ${turn.search_ms}ms` : "");
  const g = turn.gate;
  $("#qa-gate").innerHTML = g
    ? `게이트 <b>${esc(g.mode)}</b> · best <b>${(+g.best).toFixed(2)}</b> · τ <b>${S.tau.toFixed(2)}</b>${
        g.all_low ? " · <b>전건 저신뢰</b>" : ""} — τ 변경은 화면에 즉시, 답변 게이트엔 다음 질문부터 적용돼요.${
        g.rewrite ? `<br/>재작성${g.rewrite.cached ? "(캐시)" : ""}: <b>${esc(g.rewrite.rewritten)}</b>` : ""}`
    : "";
  const cnt = {};
  (turn.hits || []).forEach(h => cnt[h.chunk_type] = (cnt[h.chunk_type] || 0) + 1);
  document.querySelectorAll(".qa-type .c").forEach(el =>
    el.textContent = cnt[el.dataset.t] || "·");
}
function reflagTau() {
  document.querySelectorAll(".ev-card[data-conf]").forEach(card => {
    const conf = parseFloat(card.dataset.conf);
    if (isNaN(conf)) return;
    const low = conf < S.tau;
    card.classList.toggle("low", low);
    let flag = card.querySelector(".low-flag");
    if (low && !flag) {
      flag = document.createElement("span");
      flag.className = "low-flag"; flag.textContent = "참고용";
      card.querySelector(".evc-conf").before(flag);
    } else if (!low && flag) flag.remove();
  });
}
function setQa(on) {
  S.qa = on;
  document.body.classList.toggle("qa", on);
  $("#qa-toggle").setAttribute("aria-pressed", on);
  $("#qa-panel").hidden = !on;
  saveStore();
}

/* ═══════════════ 세션 이력 ═══════════════ */
function dayLabel(ts) {
  const d = new Date(ts), now = new Date();
  const day = x => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const diff = (day(now) - day(d)) / 86400000;
  return diff < 1 ? "오늘" : diff < 2 ? "어제" : "이전";
}
function renderSessions() {
  const box = $("#sess");
  S.sessions.sort((a, b) => b.ts - a.ts);
  $("#rail-empty").hidden = !!S.sessions.length;
  let html = "", lastDay = null;
  for (const ss of S.sessions) {
    const d = dayLabel(ss.ts);
    if (d !== lastDay) { html += `<div class="sess-day">${d}</div>`; lastDay = d; }
    html += `<div class="sess-item${ss.id === S.cur ? " on" : ""}" data-s="${ss.id}" role="button" tabindex="0">
      <span class="t">${esc(ss.title)}</span>
      <button type="button" class="del" aria-label="이력 삭제" title="삭제">×</button></div>`;
  }
  box.innerHTML = html;
}
function openSession(id) {
  const ss = S.sessions.find(x => x.id === id);
  if (!ss || S.busy) return;
  S.cur = id; S.turns = ss.turns;
  renderThread(); renderSessions();
  const last = S.turns[S.turns.length - 1];
  if (last) renderEvidence(last);
  scrollBottom();
  document.body.classList.remove("nav-open");
  syncScrim();
}
function newSession() {
  if (S.busy) return;
  S.cur = null; S.turns = []; S.sel = null;
  renderThread(); renderSessions();
  evCards.innerHTML = ""; evMap.hidden = true; evHead.hidden = true; evEmpty.hidden = false;
  $("#q").focus();
}

/* ═══════════════ 질문 실행 (2단: search → answer) ═══════════════ */
const DEMO_KEY_STORAGE = "pbdemo.key";
try { localStorage.removeItem(DEMO_KEY_STORAGE); } catch { /* 기존 장기 보관 키 폐기 */ }
function demoKeyGet() {
  try { return sessionStorage.getItem(DEMO_KEY_STORAGE) || ""; } catch { return ""; }
}
function demoKeySet(value) {
  try { sessionStorage.setItem(DEMO_KEY_STORAGE, value); } catch { /* 현재 요청은 401로 종료 */ }
}
async function getJSON(url, retried) {
  const key = demoKeyGet();
  const r = await fetch(url, { headers: key ? { "x-demo-key": key } : {} });
  if (r.status === 401 && !retried) {
    const k = prompt("접근 키를 입력하세요 (사내 담당자에게 문의)");
    if (k) { demoKeySet(k.trim()); return getJSON(url, true); }
  }
  if (!r.ok) throw new Error("http " + r.status);
  return r.json();
}
/* 일시적 서버 오류(간헐 502 등) 1회 자동 재시도 — 사용자가 못 느끼게.
   401(접근키)은 재시도하지 않는다(키 프롬프트 중복 방지). */
async function getJSONRetry(url) {
  try { return await getJSON(url); }
  catch (e) {
    if (String(e).includes("401")) throw e;
    await new Promise(r => setTimeout(r, 700));
    return getJSON(url);
  }
}
function buildParams(q) {
  return new URLSearchParams({
    q, alpha: S.alpha, topk: S.topk,
    tau: S.tauTouched ? S.tau : "",          // 빈 값 → 서버가 게이트 모드별 보정값 사용
    rerank: S.rerank ? "1" : "0",
    scope: S.scope.join(">"),
    types: S.types.size === Object.keys(TYPES).length ? "" : [...S.types].join(","),
  });
}
/* 서버가 결정한 τ(게이트 모드별 보정값)를 화면에 반영 — 사용자가 직접 만지기 전까지 */
function syncTau(gate) {
  if (!gate || S.tauTouched) return;
  S.tau = +gate.tau; S.gateMode = gate.mode;
  $("#tau").value = S.tau; $("#tau-v").textContent = S.tau.toFixed(2);
  $("#qa-gatemode").textContent = "게이트: " + (gate.mode === "rerank" ? "리랭커" : "코사인");
}
async function ask(q, opts) {
  opts = opts || {};
  q = (q || "").trim();
  if (!q || S.busy) return;
  S.busy = true;
  const askBtn = $("#ask");
  askBtn.disabled = true; askBtn.textContent = "답변 작성 중…";
  $("#q").value = ""; autoresize();

  if (!S.cur) {
    const ss = { id: uid(), title: q.length > 42 ? q.slice(0, 42) + "…" : q, ts: Date.now(), turns: [] };
    S.sessions.unshift(ss); S.cur = ss.id; S.turns = ss.turns;
  }
  const sess = S.sessions.find(x => x.id === S.cur);
  sess.ts = Date.now();

  const turn = { id: uid(), q, state: "searching", ts: Date.now(), hits: [], gate: null };
  S.turns.push(turn);
  document.body.classList.remove("is-empty");
  updateTurn(turn); renderSessions(); scrollBottom();

  turn.scope = [...S.scope];                                    // 이 턴에 적용된 스코프
  const params = buildParams(q);
  try {
    const s = await getJSONRetry("/api/search?" + params);      // 1단: 근거 선노출
    turn.hits = trimHits(s.hits); turn.gate = s.gate; turn.search_ms = s.elapsed_ms;
    turn.scope_hint = s.scope_hint;
    syncTau(s.gate);
    turn.state = "writing";
    updateTurn(turn); renderEvidence(turn); scrollBottom();

    // 말풍선에서 시작된 질문만 &src=chip (계측용) — /api/search 에는 붙이지 않음
    const a = await getJSONRetry("/api/answer?" + params + (opts.src === "chip" ? "&src=chip" : ""));  // 2단: 답변
    Object.assign(turn, {
      hits: trimHits(a.hits), gate: a.gate, answer: a.answer,
      backend: a.backend, used_llm: a.used_llm, scope_hint: a.scope_hint,
      search_ms: a.search_ms, gen_ms: a.gen_ms,
      related: Array.isArray(a.related) ? a.related : [],   // 관련 질문 말풍선 재료
    });
    turn.state = (a.backend === "gated" || a.gate?.all_low) ? "gated" : "done";
  } catch {
    turn.state = "error";
  }
  updateTurn(turn);
  if (turn.state !== "error") renderEvidence(turn);
  saveStore(); renderSessions();
  S.busy = false;
  askBtn.disabled = false; askBtn.textContent = "질문하기";
  scrollBottom();
  if (window.matchMedia("(min-width: 960px)").matches) $("#q").focus();
}

/* ═══════════════ 인용 ↔ 카드 ↔ 지도 상호 하이라이트 ═══════════════ */
function lit(r, on) {
  document.querySelectorAll(
    `#evc-${r}, .mn-row[data-ranks~="${r}"], .mn-root[data-ranks~="${r}"]`)
    .forEach(el => el.classList.toggle("lit", on));
  document.querySelectorAll(`.cite[data-r="${r}"], .src-chip[data-r="${r}"]`)
    .forEach(el => el.classList.toggle("lit", on));
}
function focusCard(r, turnId) {
  if (turnId && turnId !== S.sel) {
    const t = S.turns.find(x => x.id === turnId);
    if (t) renderEvidence(t);
  }
  if (window.matchMedia("(max-width: 960px)").matches) {
    document.body.classList.add("ev-open"); syncScrim();
  }
  const card = document.getElementById("evc-" + r);
  if (card) {
    card.scrollIntoView({ behavior: "smooth", block: "center" });
    card.classList.remove("flash"); void card.offsetWidth; card.classList.add("flash");
  }
}

/* ═══════════════ 이벤트 배선 ═══════════════ */
const qEl = $("#q");
function autoresize() {
  qEl.style.height = "auto";
  qEl.style.height = Math.min(qEl.scrollHeight, 160) + "px";
}
function syncScrim() {
  const on = document.body.classList.contains("nav-open") || document.body.classList.contains("ev-open");
  const sc = $("#scrim");
  sc.hidden = !on; sc.classList.toggle("show", on);
}
function copyText(t, el) {
  const done = () => {
    if (!el) return;
    const old = el.textContent;
    el.textContent = "복사됨"; setTimeout(() => { el.textContent = old; }, 900);
  };
  if (navigator.clipboard?.writeText) navigator.clipboard.writeText(t).then(done, done);
  else done();
}

document.addEventListener("click", e => {
  const spItem = e.target.closest(".sp-item");
  if (spItem) {
    setScope(JSON.parse(spItem.dataset.path));
    renderScopePanel();
    return;
  }
  const sbScope = e.target.closest(".sb-scope");
  if (sbScope) {                        // 모호성 배너 → 매뉴얼/부문 확정 후 재검색
    const t = S.turns.find(x => x.id === sbScope.closest(".turn")?.dataset.turn);
    if (t) { t.hintDismissed = true; updateTurn(t); }
    setScope(sbScope.dataset.scope.split(">"));
    ask(sbScope.dataset.q);
    return;
  }
  const sbUn = e.target.closest(".sb-unscope");
  if (sbUn) { setScope([]); ask(sbUn.dataset.q); return; }
  const sbKeep = e.target.closest(".sb-keep");
  if (sbKeep) {
    const t = S.turns.find(x => x.id === sbKeep.closest(".turn")?.dataset.turn);
    if (t) { t.hintDismissed = true; updateTurn(t); }
    return;
  }
  const mnScope = e.target.closest(".mn-scope");
  if (mnScope) {                        // 근거 지도 → 이 경로로 좁혀 재검색
    setScope(mnScope.dataset.scope.split(">"));
    const t = S.turns.find(x => x.id === S.sel);
    if (t) ask(t.q); else qEl.focus();
    return;
  }
  if (!e.target.closest("#scope-panel, #scope-chip")) $("#scope-panel").hidden = true;
  const cite = e.target.closest("[data-r]");
  if (cite && (cite.classList.contains("cite") || cite.classList.contains("src-chip"))) {
    focusCard(+cite.dataset.r, cite.closest(".turn")?.dataset.turn);
    return;
  }
  const chip = e.target.closest(".ask-chip");
  if (chip) { ask(chip.dataset.q || chip.textContent, { src: "chip" }); return; }
  const more = e.target.closest(".more");
  if (more) {
    const txt = more.previousElementSibling;
    const open = txt.classList.toggle("open");
    more.textContent = open ? "접기" : "더보기";
    return;
  }
  const tick = e.target.closest(".ticker");
  if (tick) { copyText(tick.dataset.copy, tick); return; }
  const copyBtn = e.target.closest(".act-copy");
  if (copyBtn) {
    const t = S.turns.find(x => x.id === copyBtn.closest(".turn")?.dataset.turn);
    if (t) copyText(t.answer || "", copyBtn);
    return;
  }
  const regen = e.target.closest(".act-regen");
  if (regen) {
    const t = S.turns.find(x => x.id === regen.closest(".turn")?.dataset.turn);
    if (t) ask(t.q);
    return;
  }
  const rx = e.target.closest(".rx-up, .rx-down");
  if (rx) {
    const t = S.turns.find(x => x.id === rx.closest(".turn")?.dataset.turn);
    if (t) reactAnswer(t, rx.classList.contains("rx-up") ? "up" : "down");
    return;
  }
  const fbTurn = e.target.closest(".fb-open-turn");
  if (fbTurn) {
    const t = S.turns.find(x => x.id === fbTurn.closest(".turn")?.dataset.turn);
    fbOpen("write", { type: "quality", ctx: t ? turnCtx(t) : null });
    return;
  }
  const fbGap = e.target.closest(".fb-gap-link");
  if (fbGap) {
    const t = S.turns.find(x => x.id === fbGap.closest(".turn")?.dataset.turn);
    fbOpen("write", { type: "missing", ctx: t ? turnCtx(t) : null });
    return;
  }
  const evBtn = e.target.closest(".ev-open-btn");
  if (evBtn) {
    const t = S.turns.find(x => x.id === evBtn.closest(".turn")?.dataset.turn);
    if (t) renderEvidence(t);
    document.body.classList.add("ev-open"); syncScrim();
    return;
  }
  const card = e.target.closest(".a-card");
  if (card) {
    const t = S.turns.find(x => x.id === card.closest(".turn")?.dataset.turn);
    if (t && t.id !== S.sel && t.hits?.length) renderEvidence(t);
    return;
  }
  const del = e.target.closest(".sess-item .del");
  if (del) {
    const id = del.closest(".sess-item").dataset.s;
    if (confirm("이 질문 이력을 삭제할까요?")) {
      S.sessions = S.sessions.filter(x => x.id !== id);
      if (S.cur === id) newSession();
      saveStore(); renderSessions();
    }
    return;
  }
  const si = e.target.closest(".sess-item");
  if (si) openSession(si.dataset.s);
});

/* 인용 hover → 경로 점등 */
document.addEventListener("mouseover", e => {
  const el = e.target.closest("[data-r]");
  if (el) lit(+el.dataset.r, true);
});
document.addEventListener("mouseout", e => {
  const el = e.target.closest("[data-r]");
  if (el) lit(+el.dataset.r, false);
});
document.addEventListener("focusin", e => {
  const el = e.target.closest("[data-r]");
  if (el) lit(+el.dataset.r, true);
});
document.addEventListener("focusout", e => {
  const el = e.target.closest("[data-r]");
  if (el) lit(+el.dataset.r, false);
});

/* 컴포저 */
$("#composer").addEventListener("submit", e => { e.preventDefault(); ask(qEl.value); });
qEl.addEventListener("keydown", e => {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); ask(qEl.value); }
});
qEl.addEventListener("input", autoresize);

/* ═══════════════ 브레드크럼 스코프 (전 부문 확장) ═══════════════ */
function renderScopeChip() {
  const c = $("#scope-chip");
  c.textContent = S.scope.length ? "범위: " + S.scope.join(" › ") : "범위: 전체 ▾";
  c.classList.toggle("on", !!S.scope.length);
}
function setScope(segs) {
  S.scope = segs || [];
  renderScopeChip(); saveStore();
  loadSuggest(false);   // 스코프 연동 예상 질문 갱신 (같은 시드 유지)
}
async function ensureSectors() {
  if (S.sectorTree) return S.sectorTree;
  const d = await getJSON("/api/sectors");
  S.sectorTree = d.tree || [];
  return S.sectorTree;
}
function renderScopePanel() {
  const box = $("#sp-cols");
  $("#sp-cur").textContent = S.scope.length ? S.scope.join(" › ") : "전체";
  const cols = [];
  let parent = { children: S.sectorTree || [], screens: [] };
  for (let level = 0; parent && cols.length < 8; level++) {
    const sel = S.scope[level];
    const books = (parent.children || []).map(n => {
      const path = [...S.scope.slice(0, level), n.name];
      return `<button type="button" class="sp-item${n.name === sel ? " on" : ""}"
        data-path="${esc(JSON.stringify(path))}">
        <span class="n">${esc(n.name)}</span><span class="c">${n.count}</span>
        ${(n.children?.length || n.screens?.length) ? '<span class="arr">›</span>' : ""}</button>`;
    }).join("");
    const screens = (parent.screens || []).map(s => {
      const path = [...S.scope.slice(0, level), s.id];
      return `<button type="button" class="sp-item${s.id === sel ? " on" : ""}"
        data-path="${esc(JSON.stringify(path))}">
        <span class="n">${esc(s.title)}</span>${s.no ? `<span class="c">${esc(s.no)}</span>` : ""}</button>`;
    }).join("");
    if (!books && !screens) break;
    cols.push(`<div class="sp-col">${books}${screens}</div>`);
    parent = (parent.children || []).find(n => n.name === sel);
  }
  box.innerHTML = cols.join("");
}
$("#scope-chip").addEventListener("click", async () => {
  const panel = $("#scope-panel");
  if (!panel.hidden) { panel.hidden = true; return; }
  try { await ensureSectors(); } catch { return; }
  renderScopePanel(); panel.hidden = false;
});
$("#sp-close").addEventListener("click", () => { $("#scope-panel").hidden = true; });
$("#sp-all").addEventListener("click", () => { setScope([]); renderScopePanel(); });

/* 정밀 게이트(리랭커) 토글 — 라벨이 현재 모드를 말해준다 */
function renderPrecise() {
  const p = $("#precise");
  p.setAttribute("aria-pressed", S.rerank);
  p.textContent = S.rerank ? "정밀 검색" : "빠른 검색";
  p.title = S.rerank
    ? "정밀 검색 중 — 리랭커가 관련도를 정확히 판정해요(질문당 +수 초). 누르면 빠른 검색으로 전환"
    : "빠른 검색 중 — 코사인 판정으로 즉시 응답해요. 누르면 정밀 검색으로 전환";
}
$("#precise").addEventListener("click", () => {
  S.rerank = !S.rerank;
  renderPrecise();
  saveStore();
});

/* 헤더·레일 */
$("#new-q").addEventListener("click", newSession);
$("#qa-toggle").addEventListener("click", () => triggerQa(!S.qa));
$("#nav-toggle").addEventListener("click", () => {
  if (window.matchMedia("(max-width: 960px)").matches) {
    document.body.classList.toggle("nav-open"); syncScrim();
  } else {
    document.body.classList.toggle("nav-closed"); saveStore();
  }
});
$("#scrim").addEventListener("click", () => {
  document.body.classList.remove("nav-open", "ev-open"); syncScrim();
});

/* 단축키 */
document.addEventListener("keydown", e => {
  if (e.key === "Escape") {
    if (!$("#fb-lightbox").hidden) { closeLightbox(); return; }
    if (!$("#qa-coach").hidden) { closeCoach(); return; }
    if (!$("#ob-modal").hidden) { obDismiss(); return; }
    if (!$("#fb-modal").hidden) { fbClose(); return; }
    document.body.classList.remove("nav-open", "ev-open"); syncScrim();
    $("#scope-panel").hidden = true;
    return;
  }
  if (e.target.closest("input, textarea")) return;
  if (e.key === "/" || ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k")) {
    e.preventDefault(); qEl.focus();
  } else if (e.key.toLowerCase() === "q" && !e.ctrlKey && !e.metaKey && !e.altKey) {
    triggerQa(!S.qa);
  }
});

/* QA 컨트롤 */
$("#alpha").addEventListener("input", e => {
  S.alpha = +e.target.value; $("#alpha-v").textContent = S.alpha.toFixed(2);
});
$("#tau").addEventListener("input", e => {
  S.tauTouched = true;
  S.tau = +e.target.value; $("#tau-v").textContent = S.tau.toFixed(2);
  reflagTau();
  const t = S.turns.find(x => x.id === S.sel);
  if (t) updateQaStat(t);
});
$("#topk").addEventListener("change", e => {
  S.topk = Math.max(1, Math.min(30, +e.target.value || 5));
  e.target.value = S.topk;
});
(function initTypeChips() {
  const box = $("#qa-types");
  for (const [k, ko] of Object.entries(TYPES)) {
    const b = document.createElement("button");
    b.type = "button"; b.className = "qa-type"; b.setAttribute("aria-pressed", "true");
    b.innerHTML = `<span class="t-dot t-${k}"></span>${ko}<span class="c" data-t="${k}">·</span>`;
    b.addEventListener("click", () => {
      const on = b.getAttribute("aria-pressed") !== "true";
      b.setAttribute("aria-pressed", on);
      on ? S.types.add(k) : S.types.delete(k);
      if (!S.types.size) {          // 전부 끄면 전부 켠 것과 동일 — 명시적으로 복원
        Object.keys(TYPES).forEach(x => S.types.add(x));
        box.querySelectorAll(".qa-type").forEach(x => x.setAttribute("aria-pressed", "true"));
      }
    });
    box.appendChild(b);
  }
})();

/* ═══════════════ 예상 질문 (스코프 연동) ═══════════════ */
function renderSamples() {
  $("#samples").innerHTML = S.samples.slice(0, 4)
    .map((it, i) => bubbleChip(it, i, false)).join("");
  const more = $("#suggest-more");
  if (more) more.hidden = !S.samples.length;   // 후보가 있을 때만 셔플 버튼 노출
}
/* /api/suggest 로 스코프 연동 예상 질문 로드. reshuffle=true 면 시드를 바꿔 다른 조합.
   실패·빈 응답 시 META.samples(문자열)를 {q} 로 감싸 폴백. */
async function loadSuggest(reshuffle) {
  if (S.suggestBusy) return;                    // 로딩 중 중복 클릭 방지
  S.suggestBusy = true;
  if (reshuffle || S.suggestSeed == null) S.suggestSeed = Math.floor(Math.random() * 1e6);
  const more = $("#suggest-more");
  if (more && reshuffle) more.classList.add("spin-once");
  const p = new URLSearchParams({ scope: S.scope.join(">"), n: 8, seed: S.suggestSeed });
  try {
    const d = await getJSON("/api/suggest?" + p);
    const qs = Array.isArray(d.questions) ? d.questions : [];
    S.samples = qs.length ? qs : (S.metaSamples || []).map(q => ({ q }));
  } catch {
    S.samples = (S.metaSamples || []).map(q => ({ q }));
  } finally {
    S.suggestBusy = false;
    if (more) more.classList.remove("spin-once");
  }
  renderSamples();
}
$("#suggest-more").addEventListener("click", () => loadSuggest(true));

/* ═══════════════════════════════════════════════════════════════════
   사용자 피드백 — 등록·조회·통계 (버그/품질/최신화/보강/제안)
   저장은 /api/feedback (Upstash Redis). 답변 턴에서 열면 근거 컨텍스트 자동 첨부.
   ═══════════════════════════════════════════════════════════════════ */
const FB_TYPES = [
  { k: "bug", ko: "버그·오류",
    guide: "어떤 동작을 했을 때 · 무엇이 잘못됐는지 · (가능하면) 브라우저나 기기를 함께 적어주세요.",
    ph: "예) 범위를 '업무'로 좁히고 질문하면 로딩이 끝나지 않아요 (모바일 크롬)" },
  { k: "quality", ko: "답변 품질",
    guide: "어떤 질문에 · 어떤 답이 나왔고 · 왜 아쉬웠는지 적어주세요. 질문·근거는 자동으로 함께 전송돼요.",
    ph: "예) 근거에는 4단계인데 답변은 3단계까지만 요약했어요" },
  { k: "outdated", ko: "매뉴얼 최신화",
    guide: "매뉴얼의 어느 화면·절차가 · 현행 업무와 어떻게 다른지 적어주세요.",
    ph: "예) 비밀번호 해제는 올해부터 OTP 인증이 추가됐는데 매뉴얼에 없어요" },
  { k: "missing", ko: "매뉴얼 보강",
    guide: "무엇을 찾으려 했는지 · 어떤 업무 상황에서 필요한지 적어주세요.",
    ph: "예) 휴면계좌 부활 절차를 물었는데 매뉴얼에서 확인되지 않는대요" },
  { k: "idea", ko: "제안·기타",
    guide: "자유롭게 적어주세요. 어떤 상황에서 불편했는지·필요했는지 곁들이면 더 좋아요.",
    ph: "예) 근거 카드에서 해당 화면 매뉴얼 원문으로 바로 이동하고 싶어요" },
];
const FB_TYPE_KO = Object.fromEntries(FB_TYPES.map(t => [t.k, t.ko]));
const FB_TYPE_COLOR = {
  bug: "#b3462e", quality: "#c9610a", outdated: "#a9721f", missing: "#2f7d63", idea: "#6b5588",
};
const FB_STATUS = {
  open: { ko: "접수", cls: "open", color: "#8a93a1" },
  ack:  { ko: "확인중", cls: "ack", color: "#46708f" },
  done: { ko: "반영", cls: "done", color: "#1e8a62" },
  hold: { ko: "보류", cls: "hold", color: "#b7791f" },
};

const FB = {
  type: "bug", ctx: null, tab: "write",
  filter: "", offset: 0, items: [], total: 0,
  loading: false, admin: false, adminKey: "", flashId: null,
  voted: new Set(),
  enabled: false, contextEnabled: false, publicBoardEnabled: false,
  imagesEnabled: false, imageCapsLoaded: false, imageCapsPromise: null,
  images: [],      // 남기기 폼에 스테이징된 첨부(압축된 data URL)
  imgCache: {},    // 보드 카드별 로드한 이미지 캐시 {id:[dataUrl]}
};
try { FB.voted = new Set(JSON.parse(localStorage.getItem("fb.voted") || "[]")); } catch { /* */ }

/* 답변 턴 → 첨부 컨텍스트(재현용 최소 정보만) */
function turnCtx(turn) {
  if (!turn) return null;
  return {
    q: turn.q || "",
    backend: turn.backend || "",
    scope: (turn.scope || []).join(">"),
    gate: turn.gate ? { best: turn.gate.best, tau: turn.gate.tau, all_low: !!turn.gate.all_low } : null,
    hits: (turn.hits || []).slice(0, 3).map(h => ({
      sid: h.screen_id || "", no: h.screen_no || "",
      path: (h.section_path || []).join(" > "),
    })),
  };
}

/* ── POST 헬퍼(접근키·관리자키 헤더) ── */
async function fbPost(url, body, admin) {
  const key = demoKeyGet();
  const h = { "Content-Type": "application/json" };
  if (key) h["x-demo-key"] = key;
  if (admin && FB.adminKey) h["x-admin-key"] = FB.adminKey;
  const r = await fetch(url, { method: "POST", headers: h, body: JSON.stringify(body || {}) });
  if (r.status === 401 && !admin) {
    const k = prompt("접근 키를 입력하세요 (사내 담당자에게 문의)");
    if (k) { demoKeySet(k.trim()); return fbPost(url, body, admin); }
  }
  return r.json().catch(() => ({}));
}
const fbAction = (qs, admin) => fbPost("/api/feedback?" + qs, {}, admin);

async function fbGetJSON(url) {
  const key = demoKeyGet();
  const h = {};
  if (key) h["x-demo-key"] = key;
  if (FB.admin && FB.adminKey) h["x-admin-key"] = FB.adminKey;
  const r = await fetch(url, { headers: h });
  if (!r.ok) throw new Error("http " + r.status);
  return r.json();
}

function syncFbVisibility() {
  FEEDBACK_AVAILABLE = FB.enabled;
  $("#fb-open").hidden = !FB.enabled;
  const boardVisible = FB.enabled && (FB.publicBoardEnabled || FB.admin);
  document.querySelectorAll('.fb-tab[data-tab="board"], .fb-tab[data-tab="stats"]')
    .forEach(el => { el.hidden = !boardVisible; });
  if (!FB.contextEnabled) { FB.ctx = null; renderFbCtx(); }
  renderThread();
}

function setFbImagesEnabled(enabled) {
  FB.imagesEnabled = enabled === true;
  $("#fb-image-field").hidden = !FB.imagesEnabled;
  if (!FB.imagesEnabled) {
    FB.images = []; FB.imgCache = {};
    renderFbThumbs(); closeLightbox();
  }
  if (FB.items.length) renderBoard();
}
async function loadFbCapabilities() {
  if (FB.imageCapsLoaded) return;
  if (FB.imageCapsPromise) return FB.imageCapsPromise;
  FB.imageCapsPromise = getJSON("/api/feedback?action=capabilities")
    .then(d => {
      FB.enabled = d?.feedback_enabled === true;
      FB.contextEnabled = d?.context_enabled === true;
      FB.publicBoardEnabled = d?.public_board_enabled === true;
      setFbImagesEnabled(FB.enabled && d?.images_enabled === true);
      FB.imageCapsLoaded = true;
      syncFbVisibility();
    })
    .catch(() => { FB.enabled = false; setFbImagesEnabled(false); syncFbVisibility(); })
    .finally(() => { FB.imageCapsPromise = null; });
  return FB.imageCapsPromise;
}

/* ── 모달 열고 닫기 ── */
function fbOpen(tab, preset) {
  if (!FB.enabled) return;
  preset = preset || {};
  if (preset.ctx && FB.contextEnabled) FB.ctx = preset.ctx;
  if (preset.type) setFbType(preset.type);
  renderFbCtx();
  const m = $("#fb-modal"), sc = $("#fb-scrim");
  m.hidden = false; sc.hidden = false;
  requestAnimationFrame(() => { m.classList.add("show"); sc.classList.add("show"); });
  document.body.classList.add("fb-lock");
  void loadFbCapabilities();
  fbTab(tab || "write");
}
function fbClose() {
  const m = $("#fb-modal"), sc = $("#fb-scrim");
  m.classList.remove("show"); sc.classList.remove("show");
  document.body.classList.remove("fb-lock");
  FB.images = []; renderFbThumbs(); $("#fb-msg").hidden = true;
  setTimeout(() => { m.hidden = true; sc.hidden = true; }, 180);
}
function fbTab(t) {
  FB.tab = t;
  document.querySelectorAll(".fb-tab").forEach(b => b.classList.toggle("on", b.dataset.tab === t));
  $("#fb-write").hidden = t !== "write";
  $("#fb-board").hidden = t !== "board";
  $("#fb-stats").hidden = t !== "stats";
  if (t === "write") setTimeout(() => $("#fb-content").focus(), 60);
  if (t === "board" && !FB.items.length) loadBoard(true);
  if (t === "stats") loadStats();
}

/* ── 남기기 폼 ── */
function buildFbTypes() {
  $("#fb-types").innerHTML = FB_TYPES.map(t =>
    `<button type="button" class="fb-typechip" data-k="${t.k}" aria-pressed="${t.k === FB.type}">
      <span class="dot" style="background:${FB_TYPE_COLOR[t.k]}"></span>${t.ko}</button>`).join("");
}
function setFbType(k) {
  if (!FB_TYPE_KO[k]) k = "bug";
  FB.type = k;
  document.querySelectorAll("#fb-types .fb-typechip")
    .forEach(b => b.setAttribute("aria-pressed", b.dataset.k === k));
  const t = FB_TYPES.find(x => x.k === k);
  $("#fb-guide").textContent = t.guide;
  $("#fb-content").setAttribute("placeholder", t.ph);
}
function renderFbCtx() {
  const box = $("#fb-ctx");
  if (!FB.ctx || !FB.ctx.q) { box.hidden = true; box.innerHTML = ""; return; }
  const hits = (FB.ctx.hits || [])
    .map(h => esc((h.no ? "화면 " + h.no + " · " : "") + (h.path || h.sid || "")))
    .filter(Boolean).join(" / ");
  box.hidden = false;
  box.innerHTML = `<div class="fbx-h"><span>이 질문·근거가 함께 전송돼요</span>
      <button type="button" class="fbx-rm" id="fb-ctx-rm">첨부 제외</button></div>
    <div class="fbx-q">Q. ${esc(FB.ctx.q)}</div>
    ${hits ? `<div class="fbx-hits">${hits}</div>` : ""}`;
}
function updateFbLen() {
  const v = $("#fb-content").value, n = v.trim().length;
  $("#fb-len").textContent = v.length + "/1000";
  $("#fb-hint").textContent = (n > 0 && n < 15)
    ? "조금만 더 구체적으로 적어주시면 반영에 큰 도움이 돼요" : "";
}
function fbMsg(t, err) {
  const m = $("#fb-msg");
  m.hidden = false; m.textContent = t; m.classList.toggle("err", !!err);
}
async function submitFb() {
  if (FB.loading) return;
  const content = $("#fb-content").value.trim();
  if (content.length < 5) { fbMsg("내용을 5자 이상 적어주세요.", true); $("#fb-content").focus(); return; }
  FB.loading = true;
  const btn = $("#fb-submit"); btn.disabled = true; btn.textContent = "등록 중…";
  const body = { type: FB.type, content, nick: $("#fb-nick").value.trim(),
                 website: $("#fb-website").value };
  if (FB.contextEnabled && FB.ctx) body.ctx = FB.ctx;
  if (FB.imagesEnabled && FB.images.length) body.images = FB.images;
  try {
    const r = await fbPost("/api/feedback", body);
    if (r && r.error) { fbMsg(r.error, true); }
    else {
      fbMsg("등록됐어요. 소중한 의견 감사합니다!", false);
      $("#fb-content").value = ""; $("#fb-nick").value = ""; updateFbLen();
      FB.ctx = null; renderFbCtx();
      FB.images = []; renderFbThumbs();
      if (r && r.item && (FB.publicBoardEnabled || FB.admin)) FB.items.unshift(r.item);
      if (FB.publicBoardEnabled || FB.admin)
        setTimeout(() => { fbTab("board"); loadBoard(true); }, 650);
    }
  } catch {
    fbMsg("등록 중 문제가 발생했어요. 잠시 후 다시 시도해 주세요.", true);
  } finally {
    FB.loading = false; btn.disabled = false; btn.textContent = "등록하기";
  }
}

/* ── 둘러보기 ── */
function fbDate(ts) {
  if (!ts) return "";
  const d = new Date(ts);
  if (isNaN(d)) return "";
  return `${d.getMonth() + 1}.${d.getDate()}`;
}
function renderFilter() {
  $("#fb-filter").innerHTML =
    `<button type="button" class="fb-flt${FB.filter === "" ? " on" : ""}" data-t="">전체</button>` +
    FB_TYPES.map(t => `<button type="button" class="fb-flt${FB.filter === t.k ? " on" : ""}" data-t="${t.k}">
      <span class="dot" style="background:${FB_TYPE_COLOR[t.k]}"></span>${t.ko}</button>`).join("");
}
function fbCard(it) {
  const st = FB_STATUS[it.status] || FB_STATUS.open;
  const ctx = it.ctx && it.ctx.q
    ? `<div class="fbc-ctx"><span class="fbc-ctx-l">연결된 질문</span> ${esc(it.ctx.q)}</div>` : "";
  const voted = FB.voted.has(it.id);
  const adminSel = FB.admin
    ? `<select class="fbc-status" data-id="${it.id}" aria-label="상태 변경">${
        STATUS_ORDER_JS.map(k => `<option value="${k}"${k === it.status ? " selected" : ""}>${FB_STATUS[k].ko}</option>`).join("")}</select>`
    : "";
  return `<article class="fb-card" data-id="${it.id}">
    <div class="fbc-top">
      <span class="fbc-type" style="--c:${FB_TYPE_COLOR[it.type] || "#8a93a1"}">${esc(FB_TYPE_KO[it.type] || it.type)}</span>
      <span class="fbc-status-b s-${st.cls}">${st.ko}</span>
      <span class="fbc-date">${fbDate(it.ts)}</span>
      <span class="fbc-nick">${it.nick ? esc(it.nick) : "익명"}</span>
      ${adminSel}
    </div>
    <p class="fbc-body">${esc(it.content)}</p>
    ${ctx}
    ${FB.imagesEnabled && it.img ? `<button type="button" class="fbc-img" data-id="${it.id}">📷 화면 캡처 ${it.img}장 보기</button>
      <div class="fbc-imgwrap" id="fbimg-${it.id}" hidden></div>` : ""}
    <div class="fbc-foot">
      <button type="button" class="fbc-vote${voted ? " on" : ""}" data-id="${it.id}"
        title="같은 의견이에요 (공감)"><span class="hv">♥</span><span class="vn">${it.votes || 0}</span></button>
    </div>
  </article>`;
}
const STATUS_ORDER_JS = ["open", "ack", "done", "hold"];
function renderBoard() {
  const list = $("#fb-list");
  if (!FB.items.length) {
    list.innerHTML = ""; $("#fb-empty").hidden = false; $("#fb-more").hidden = true; return;
  }
  $("#fb-empty").hidden = true;
  list.innerHTML = FB.items.map(fbCard).join("");
  $("#fb-more").hidden = !(FB.items.length < (FB.total || 0));
  if (FB.flashId != null) {
    const el = list.querySelector(`.fb-card[data-id="${FB.flashId}"]`);
    if (el) { el.scrollIntoView({ block: "center" }); el.classList.add("flash"); }
    FB.flashId = null;
  }
}
async function loadBoard(reset) {
  if (FB.loading) return;
  if (reset) { FB.offset = 0; FB.items = []; }
  FB.loading = true;
  const p = new URLSearchParams({ offset: FB.offset, n: 20 });
  if (FB.filter) p.set("type", FB.filter);
  try {
    const d = await fbGetJSON("/api/feedback?" + p);
    const items = Array.isArray(d.items) ? d.items : [];
    FB.items = reset ? items : FB.items.concat(items);
    FB.offset += items.length;
    FB.total = d.total || FB.items.length;
  } catch { /* 유지 */ }
  FB.loading = false;
  renderBoard();
}
async function voteFb(id) {
  if (FB.voted.has(id)) return;
  FB.voted.add(id);
  try { localStorage.setItem("fb.voted", JSON.stringify([...FB.voted])); } catch { /* */ }
  const it = FB.items.find(x => x.id === id);
  if (it) it.votes = (it.votes || 0) + 1;
  renderBoard();
  try { await fbAction("action=vote&id=" + id); } catch { /* */ }
}
async function changeStatus(id, to) {
  const r = await fbAction("action=status&id=" + id + "&to=" + to, true);
  if (r && r.error) { alert("상태 변경 실패 — 관리자 키를 확인하세요."); return; }
  const it = FB.items.find(x => x.id === id);
  if (it) it.status = to;
  renderBoard();
}

/* ── 답변 반응(👍/👎) — 계측 카운터만, 목록 미오염 ── */
async function reactAnswer(turn, v) {
  if (turn.reacted) return;
  turn.reacted = v;
  saveStore(); updateTurn(turn);
  try { await fbAction("action=react&v=" + v); } catch { /* */ }
  if (v === "down") fbOpen("write", { type: "quality", ctx: turnCtx(turn) });  // 즉시 상세 유도
}

/* ── 통계 대시보드(인라인 SVG/CSS, 무의존) ── */
function fbSparkline(vals) {
  const W = 168, H = 38, n = vals.length;
  const pts = vals.map((v, i) => v == null ? null
    : [n <= 1 ? W / 2 : i / (n - 1) * W, H - 3 - v * (H - 6)]);
  const seg = pts.filter(Boolean);
  const path = seg.map((p, i) => (i ? "L" : "M") + p[0].toFixed(1) + " " + p[1].toFixed(1)).join(" ");
  const dots = seg.map(p => `<circle cx="${p[0].toFixed(1)}" cy="${p[1].toFixed(1)}" r="1.6"/>`).join("");
  return `<svg class="fb-spark" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" aria-hidden="true">
    <line x1="0" y1="${H / 2}" x2="${W}" y2="${H / 2}" class="fb-spark-mid"/>
    ${path ? `<path d="${path}"/>${dots}` : ""}</svg>`;
}
function renderStats(d) {
  const dash = $("#fb-dash");
  if (!d || !d.total) {
    dash.innerHTML = `<p class="fb-empty">아직 집계할 피드백이 없어요. 첫 피드백을 남겨보세요.</p>`;
    return;
  }
  const tiles = [
    ["총 피드백", d.total, ""], ["미처리", d.open || 0, "warn"],
    ["반영 완료", d.done || 0, "ok"], ["공감", d.votes || 0, "brand"],
  ].map(([l, v, c]) => `<div class="fb-tile ${c}"><b>${v}</b><span>${l}</span></div>`).join("");

  const maxT = Math.max(1, ...FB_TYPES.map(t => d.by_type[t.k] || 0));
  const typeBars = FB_TYPES.map(t => {
    const n = d.by_type[t.k] || 0;
    return `<div class="fb-brow"><span class="fb-bl">${t.ko}</span>
      <span class="fb-btrack"><i style="width:${Math.round(n / maxT * 100)}%;background:${FB_TYPE_COLOR[t.k]}"></i></span>
      <span class="fb-bv">${n}</span></div>`;
  }).join("");

  const stSum = STATUS_ORDER_JS.reduce((a, k) => a + (d.by_status[k] || 0), 0) || 1;
  const stack = STATUS_ORDER_JS.filter(k => (d.by_status[k] || 0) > 0).map(k =>
    `<i style="width:${(d.by_status[k] || 0) / stSum * 100}%;background:${FB_STATUS[k].color}"
        title="${FB_STATUS[k].ko} ${d.by_status[k]}"></i>`).join("");
  const stackLeg = STATUS_ORDER_JS.map(k =>
    `<span class="fb-leg"><i style="background:${FB_STATUS[k].color}"></i>${FB_STATUS[k].ko} ${d.by_status[k] || 0}</span>`).join("");
  const doneRate = Math.round((d.done || 0) / (d.total || 1) * 100);

  const daily = d.daily || [];
  const maxD = Math.max(1, ...daily.map(x => x.n));
  const dailyBars = daily.map(x =>
    `<span class="fb-day" title="${x.d} · ${x.n}건"><i style="height:${x.n ? Math.max(6, x.n / maxD * 100) : 2}%"></i></span>`).join("");

  const react = d.react || [];
  const upSum = react.reduce((a, x) => a + x.up, 0), dnSum = react.reduce((a, x) => a + x.down, 0);
  const rTot = upSum + dnSum, upPct = rTot ? Math.round(upSum / rTot * 100) : 0;
  const spark = fbSparkline(react.map(x => { const t = x.up + x.down; return t ? x.up / t : null; }));

  const top = (d.top || []).map(it =>
    `<button type="button" class="fb-topi" data-id="${it.id}">
      <span class="fb-topv">♥ ${it.votes || 0}</span>
      <span class="fb-topt" style="--c:${FB_TYPE_COLOR[it.type] || "#8a93a1"}">${esc(FB_TYPE_KO[it.type] || it.type)}</span>
      <span class="fb-topc">${esc((it.content || "").slice(0, 64))}</span></button>`).join("");

  dash.innerHTML = `
    <div class="fb-tiles">${tiles}</div>
    <div class="fb-grid2">
      <div class="fb-widget">
        <h3>유형 분포</h3>${typeBars}
      </div>
      <div class="fb-widget">
        <h3>처리 현황 <span class="fb-sub">반영 ${doneRate}%</span></h3>
        <div class="fb-stack">${stack}</div>
        <div class="fb-legs">${stackLeg}</div>
      </div>
    </div>
    <div class="fb-grid2">
      <div class="fb-widget">
        <h3>일별 등록 추이 <span class="fb-sub">최근 14일</span></h3>
        <div class="fb-daily">${dailyBars}</div>
      </div>
      <div class="fb-widget">
        <h3>답변 반응 <span class="fb-sub">${rTot ? `👍 ${upPct}% · ${rTot}건` : "아직 없음"}</span></h3>
        ${spark}
        <div class="fb-react-l"><span>👍 ${upSum}</span><span>👎 ${dnSum}</span></div>
      </div>
    </div>
    ${top ? `<div class="fb-widget"><h3>공감 많은 피드백 TOP 5</h3><div class="fb-top">${top}</div></div>` : ""}`;
}
async function loadStats() {
  $("#fb-dash").innerHTML = `<p class="fb-loading">집계 중…</p>`;
  try { renderStats(await fbGetJSON("/api/feedback?action=stats")); }
  catch { $("#fb-dash").innerHTML = `<p class="fb-empty">통계를 불러오지 못했어요.</p>`; }
}

/* ── 화면 캡처 첨부(클라 압축 → data URL) ── */
const FB_IMG_MAX = 400000;   // 압축 후 data URL 문자 상한(≈300KB, 서버 캡과 정합)
const FB_IMAGE_DATA_RE = /^data:image\/(?:png|jpeg|webp|gif);base64,[A-Za-z0-9+/]+={0,2}$/;
function isFeedbackImage(src) {
  return typeof src === "string" && src.length <= 420000 && FB_IMAGE_DATA_RE.test(src);
}
function feedbackImage(src, alt, lazy) {
  if (!isFeedbackImage(src)) return null;
  const img = document.createElement("img");
  img.src = src;
  img.alt = alt;
  img.dataset.big = "1";
  if (lazy) img.loading = "lazy";
  return img;
}
function fbCompress(file) {
  return new Promise((resolve, reject) => {
    if (!/^image\//.test(file.type)) return reject(new Error("이미지 파일만 첨부할 수 있어요."));
    const url = URL.createObjectURL(file), img = new Image();
    img.onload = () => {
      URL.revokeObjectURL(url);
      let w = img.naturalWidth, h = img.naturalHeight, MAX = 1400;
      const fit = () => {
        const s = Math.min(1, MAX / Math.max(w, h));
        const cw = Math.max(1, Math.round(w * s)), ch = Math.max(1, Math.round(h * s));
        const c = document.createElement("canvas");
        c.width = cw; c.height = ch;
        c.getContext("2d").drawImage(img, 0, 0, cw, ch);
        let out = c.toDataURL("image/webp", 0.72);
        if (!out.startsWith("data:image/webp")) out = c.toDataURL("image/jpeg", 0.72);
        let q = 0.72;
        const webp = out.startsWith("data:image/webp");
        while (out.length > FB_IMG_MAX && q > 0.4) {
          q -= 0.12; out = c.toDataURL(webp ? "image/webp" : "image/jpeg", q);
        }
        return out;
      };
      let out = fit();
      if (out.length > FB_IMG_MAX && MAX > 900) { MAX = 900; out = fit(); }  // 그래도 크면 축소 재시도
      if (out.length > FB_IMG_MAX) return reject(new Error("이미지가 너무 커요 — 일부만 잘라 첨부해 주세요."));
      resolve(out);
    };
    img.onerror = () => { URL.revokeObjectURL(url); reject(new Error("이미지를 읽지 못했어요.")); };
    img.src = url;
  });
}
async function fbAddImages(files) {
  if (!FB.imagesEnabled) return;
  for (const f of files) {
    if (FB.images.length >= 3) { fbMsg("이미지는 최대 3장까지 첨부할 수 있어요.", true); break; }
    try { FB.images.push(await fbCompress(f)); $("#fb-msg").hidden = true; }
    catch (e) { fbMsg(String(e.message || e), true); }
  }
  renderFbThumbs();
}
function renderFbThumbs() {
  const box = $("#fb-thumbs");
  box.replaceChildren();
  FB.images.forEach((src, i) => {
    const img = feedbackImage(src, `첨부 ${i + 1}`, false);
    if (!img) return;
    const wrap = document.createElement("span");
    wrap.className = "fb-thumb";
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "fb-thumb-x";
    remove.dataset.i = String(i);
    remove.setAttribute("aria-label", "첨부 제거");
    remove.textContent = "✕";
    wrap.append(img, remove);
    box.append(wrap);
  });
  $("#fb-drop").style.display = FB.images.length >= 3 ? "none" : "";
}
function openLightbox(src) {
  if (!isFeedbackImage(src)) return;
  $("#fb-lightbox-img").src = src;
  $("#fb-lightbox").hidden = false;
}
function closeLightbox() {
  $("#fb-lightbox").hidden = true; $("#fb-lightbox-img").src = "";
}
async function toggleImgs(id) {
  const box = document.getElementById("fbimg-" + id);
  if (!box || !FB.imagesEnabled) return;
  if (!box.hidden && box.dataset.loaded) { box.hidden = true; return; }
  box.hidden = false;
  if (!FB.imgCache[id]) {
    const loading = document.createElement("span");
    loading.className = "fb-loading"; loading.textContent = "불러오는 중…";
    box.replaceChildren(loading);
    try {
      const d = await fbGetJSON("/api/feedback?action=img&id=" + id);
      FB.imgCache[id] = Array.isArray(d.images) ? d.images : [];
    }
    catch { FB.imgCache[id] = []; }
  }
  const images = (FB.imgCache[id] || [])
    .map((src, i) => feedbackImage(src, `캡처 ${i + 1}`, true)).filter(Boolean);
  if (images.length) box.replaceChildren(...images);
  else {
    const empty = document.createElement("span");
    empty.className = "fb-loading"; empty.textContent = "이미지를 불러오지 못했어요.";
    box.replaceChildren(empty);
  }
  box.dataset.loaded = "1";
}

/* ── 관리자 로그인(?admin=1 일 때만 노출) ── */
function fbAdminLogin() {
  const k = prompt("관리자 키를 입력하세요");
  if (!k) return;
  FB.adminKey = k.trim(); FB.admin = true;
  try { sessionStorage.setItem("fb.admin", FB.adminKey); } catch { /* */ }
  $("#fb-admin-btn").textContent = "🔑 관리자 ✓";
  syncFbVisibility();
  renderBoard();
}

/* ── 배선 ── */
buildFbTypes(); setFbType("bug"); renderFilter();
$("#fb-open").addEventListener("click", () =>
  fbOpen(FB.publicBoardEnabled || FB.admin ? "board" : "write"));
$("#fb-close").addEventListener("click", fbClose);
$("#fb-cancel").addEventListener("click", fbClose);
$("#fb-scrim").addEventListener("click", fbClose);
$("#fb-form").addEventListener("submit", e => { e.preventDefault(); submitFb(); });
$("#fb-content").addEventListener("input", updateFbLen);
$("#fb-more").addEventListener("click", () => loadBoard(false));
$("#fb-admin-btn").addEventListener("click", fbAdminLogin);
$("#fb-modal").addEventListener("click", e => {
  const big = e.target.closest("img[data-big]");
  if (big) { openLightbox(big.src); return; }
  const tab = e.target.closest(".fb-tab");
  if (tab) { fbTab(tab.dataset.tab); return; }
  const tc = e.target.closest(".fb-typechip");
  if (tc) { setFbType(tc.dataset.k); return; }
  const thx = e.target.closest(".fb-thumb-x");
  if (thx) { FB.images.splice(+thx.dataset.i, 1); renderFbThumbs(); return; }
  if (FB.imagesEnabled && e.target.closest("#fb-drop")) { $("#fb-file").click(); return; }
  if (e.target.closest("#fb-ctx-rm")) { FB.ctx = null; renderFbCtx(); return; }
  const flt = e.target.closest(".fb-flt");
  if (flt) { FB.filter = flt.dataset.t || ""; renderFilter(); loadBoard(true); return; }
  const fim = e.target.closest(".fbc-img");
  if (fim && FB.imagesEnabled) { toggleImgs(+fim.dataset.id); return; }
  const vt = e.target.closest(".fbc-vote");
  if (vt) { voteFb(+vt.dataset.id); return; }
  const topi = e.target.closest(".fb-topi");
  if (topi) { FB.filter = ""; renderFilter(); FB.flashId = +topi.dataset.id; fbTab("board"); loadBoard(true); return; }
});
$("#fb-file").addEventListener("change", e => {
  if (FB.imagesEnabled) fbAddImages([...e.target.files]);
  e.target.value = "";
});
["dragenter", "dragover"].forEach(ev => $("#fb-drop").addEventListener(ev, e => {
  e.preventDefault(); $("#fb-drop").classList.add("over");
}));
["dragleave", "drop"].forEach(ev => $("#fb-drop").addEventListener(ev, e => {
  e.preventDefault(); $("#fb-drop").classList.remove("over");
}));
$("#fb-drop").addEventListener("drop", e => {
  if (!FB.imagesEnabled) return;
  const fs = [...(e.dataTransfer?.files || [])].filter(f => f.type.startsWith("image/"));
  if (fs.length) fbAddImages(fs);
});
$("#fb-lightbox").addEventListener("click", closeLightbox);
/* 캡처 붙여넣기(Ctrl+V) — 모달의 남기기 탭이 열려 있을 때만 */
document.addEventListener("paste", e => {
  if (!FB.imagesEnabled || $("#fb-modal").hidden || FB.tab !== "write") return;
  const fs = [];
  for (const it of (e.clipboardData?.items || []))
    if (it.type.startsWith("image/")) { const f = it.getAsFile(); if (f) fs.push(f); }
  if (fs.length) { e.preventDefault(); fbAddImages(fs); }
});
$("#fb-modal").addEventListener("change", e => {
  const sel = e.target.closest(".fbc-status");
  if (sel) changeStatus(+sel.dataset.id, sel.value);
});
(function initFbAdmin() {
  if (new URLSearchParams(location.search).get("admin") === "1") {
    $("#fb-admin-btn").hidden = false;
    let k = null;
    try { k = sessionStorage.getItem("fb.admin"); } catch { /* */ }
    if (k) { FB.adminKey = k; FB.admin = true; $("#fb-admin-btn").textContent = "🔑 관리자 ✓"; }
  }
})();

/* ═══════════════════════════════════════════════════════════════════
   온보딩·도움말 — 최초 방문 환영 캐러셀 + 상시 도움말(탭) + QA 첫 활성화 코치
   전부 프런트 자체완결(서버·API 무관). 콘텐츠는 아래 상수에 단일화.
   ═══════════════════════════════════════════════════════════════════ */
const OB_VER = "ob1";
const OB_STEPS = [
  { t: "매뉴얼 안에서만 답해요",
    b: "근거가 없으면 추측하지 않고 ‘매뉴얼에서 확인되지 않습니다’라고 답해요. 그래서 믿고 쓸 수 있어요.",
    svg: `<svg viewBox="0 0 260 130" class="ob-svg" aria-hidden="true">
      <rect x="96" y="16" width="68" height="96" rx="7" fill="#fff" stroke="#e6e9ee" stroke-width="1.5"/>
      <rect x="108" y="30" width="44" height="5" rx="2.5" fill="#e6e9ee"/>
      <rect x="108" y="44" width="44" height="5" rx="2.5" fill="#e6e9ee"/>
      <rect x="108" y="58" width="30" height="5" rx="2.5" fill="#e6e9ee"/>
      <circle cx="158" cy="96" r="17" fill="#1e8a62"/>
      <path d="M150 96l5 5 10-11" stroke="#fff" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" fill="none"/></svg>` },
  { t: "물어보고, 근거로 확인",
    b: "아래에 질문을 입력하면 매뉴얼 근거에서 답을 만들어요. 문장의 [S1] 표시를 누르면 어느 근거에서 나왔는지 바로 볼 수 있어요.",
    svg: `<svg viewBox="0 0 260 130" class="ob-svg" aria-hidden="true">
      <rect x="58" y="28" width="144" height="54" rx="12" fill="#fff" stroke="#e6e9ee" stroke-width="1.5"/>
      <path d="M82 82v16l16-16" fill="#fff" stroke="#e6e9ee" stroke-width="1.5" stroke-linejoin="round"/>
      <rect x="72" y="42" width="84" height="5" rx="2.5" fill="#e6e9ee"/>
      <rect x="72" y="56" width="54" height="5" rx="2.5" fill="#e6e9ee"/>
      <rect x="160" y="50" width="30" height="18" rx="5" fill="#fff4e9" stroke="#f3d5b3"/>
      <text x="175" y="63" text-anchor="middle" font-size="11" font-weight="700" fill="#c9610a" font-family="monospace">S1</text></svg>` },
  { t: "근거는 여기 있어요",
    b: "PC에서는 오른쪽 ‘근거’ 패널에, 모바일에서는 답변 아래 ‘근거 N건’ 버튼을 누르면 근거 지도와 카드가 열려요.",
    svg: `<svg viewBox="0 0 260 130" class="ob-svg" aria-hidden="true">
      <rect x="26" y="26" width="132" height="80" rx="7" fill="#fff" stroke="#e6e9ee" stroke-width="1.5"/>
      <rect x="26" y="26" width="30" height="80" rx="7" fill="#f6f7f9"/>
      <rect x="126" y="27" width="31" height="78" fill="#fff4e9"/>
      <line x1="126" y1="27" x2="126" y2="105" stroke="#f3d5b3"/>
      <rect x="134" y="40" width="16" height="5" rx="2.5" fill="#f5821f"/>
      <rect x="134" y="52" width="16" height="5" rx="2.5" fill="#f3d5b3"/>
      <rect x="186" y="32" width="46" height="74" rx="9" fill="#fff" stroke="#e6e9ee" stroke-width="1.5"/>
      <rect x="194" y="82" width="30" height="15" rx="4" fill="#fff4e9" stroke="#f3d5b3"/>
      <text x="209" y="92.5" text-anchor="middle" font-size="7.5" font-weight="700" fill="#c9610a">근거 3건</text></svg>` },
  { t: "좁혀 묻고, 알려주세요",
    b: "‘범위’를 고르면 특정 부문 안에서만 찾아 정확도가 올라가요. 답이 아쉬우면 👍/👎나 ‘피드백’으로 알려주시면 품질이 좋아져요.",
    svg: `<svg viewBox="0 0 260 130" class="ob-svg" aria-hidden="true">
      <rect x="48" y="52" width="92" height="26" rx="8" fill="#fff4e9" stroke="#f3d5b3"/>
      <text x="94" y="69" text-anchor="middle" font-size="11" font-weight="700" fill="#c9610a">범위: 계좌 ▾</text>
      <rect x="152" y="52" width="26" height="26" rx="7" fill="#fff" stroke="#e6e9ee"/>
      <text x="165" y="71" text-anchor="middle" font-size="13">👍</text>
      <rect x="184" y="52" width="26" height="26" rx="7" fill="#fff" stroke="#e6e9ee"/>
      <text x="197" y="71" text-anchor="middle" font-size="13">👎</text></svg>` },
];

const OB_QA_HTML = `
  <p class="ob-lead">검색이 왜 이렇게 나왔는지 <b>뜯어보는 계측 모드</b>예요. 답을 얻는 데는 필요 없고, 품질을 평가·튜닝할 때 켜요.</p>
  <p class="ob-note">켜는 법 — <kbd>Q</kbd> 키 · 헤더 <b>QA</b> 버튼 · 주소 <code>?qa=1</code></p>
  <table class="ob-table"><tbody>
    <tr><td>혼합 α</td><td>0 = 키워드(그 단어) · 1 = 의미(비슷한 뜻) · 0.5 = 반반</td></tr>
    <tr><td>임계 τ</td><td>관련도 통과선. 최고점이 τ보다 낮으면 ‘매뉴얼 밖’ 처리 <span class="ob-dim">(답변 게이트는 다음 질문부터)</span></td></tr>
    <tr><td>top-k</td><td>근거로 가져올 개수</td></tr>
    <tr><td>dense / sparse</td><td>근거 카드 하단 막대 — 의미검색·키워드검색에서 각각 얼마나 걸렸는지</td></tr>
    <tr><td>게이트</td><td>코사인(빠름) ↔ 리랭커(정밀 토글, 느리지만 정확)</td></tr>
    <tr><td>유형 칩</td><td>화면개요·화면설명·용어찾기·관련화면·질문보기 필터</td></tr>
  </tbody></table>`;

const OB_FB_HTML = `
  <p class="ob-lead">답변 품질과 매뉴얼은 <b>여러분의 피드백으로 좋아져요.</b> 남긴 의견이 반영되면 상태가 ‘반영’으로 바뀌어 보드에서 확인할 수 있어요.</p>
  <p class="ob-sub">어디서 남기나</p>
  <ul class="ob-list">
    <li>답변 하단 <b>👍 / 👎</b> — 원클릭 (👎는 상세 피드백으로 이어져요)</li>
    <li>답변 하단 <b>「피드백」</b> — 그 질문·근거가 <b>자동 첨부</b>돼 조치 가능한 지적이 돼요</li>
    <li>‘매뉴얼에서 확인되지 않습니다’ 답변의 <b>‘보강 요청하기’</b></li>
    <li>헤더 <b>「피드백」</b> — 전역 등록 + 둘러보기 + 통계</li>
  </ul>
  <p class="ob-sub">유형 5가지</p>
  <p class="ob-p">버그 · 답변 품질 · 매뉴얼 최신화 · 매뉴얼 보강 · 제안. 유형을 고르면 <b>작성 가이드·예시</b>가 그 자리에서 바뀌어요. 활성화된 환경에서는 화면 캡처도 붙일 수 있어요.</p>
  <p class="ob-note">개인정보·실계좌번호는 적지 마세요.</p>`;

const OB_HELP = [
  { k: "basic", ko: "기본 사용법", html: `
    <ul class="ob-list">
      <li><b>매뉴얼 안에서만</b> 답해요 — 근거 없으면 ‘확인되지 않습니다’.</li>
      <li><b>물어보고 근거로 확인</b> — 답변의 <b>[S1]</b>을 누르면 근거로 이동해요.</li>
      <li><b>근거 위치</b> — PC는 오른쪽 근거 패널, 모바일은 답변 아래 <b>‘근거 N건’</b> 버튼.</li>
      <li><b>범위</b>로 좁혀 물으면 다른 부문이 섞이지 않아 정확해져요.</li>
    </ul>` },
  { k: "evidence", ko: "근거·범위", html: `
    <p class="ob-sub">근거 지도</p>
    <p class="ob-p">답이 매뉴얼 어디서 왔는지 트리로 보여줘요. 항목의 <b>‘좁히기’</b>를 누르면 그 경로 안에서만 다시 검색해요.</p>
    <p class="ob-sub">범위(브레드크럼)</p>
    <p class="ob-p">컴포저의 <b>‘범위’</b> 칩으로 부문을 한정하면 다른 부문 결과가 섞이지 않아요.
    매뉴얼은 <b>화면</b>(조작법)·<b>업무</b>(절차)·<b>상담</b>(고객센터 Q&amp;A 사례) 세 갈래예요 — 범위 첫 단계에서 고를 수 있어요.</p>
    <p class="ob-sub">정밀 / 빠른 검색</p>
    <p class="ob-p"><b>정밀</b>은 리랭커로 관련도를 더 정확히(질문당 몇 초 더), <b>빠른</b>은 즉시 응답이에요.</p>` },
  { k: "qa", ko: "QA 모드", html: OB_QA_HTML },
  { k: "feedback", ko: "피드백·품질", html: OB_FB_HTML },
  { k: "shortcuts", ko: "단축키·모바일", html: `
    <p class="ob-sub">단축키</p>
    <ul class="ob-list">
      <li><kbd>/</kbd> 또는 <kbd>⌘</kbd><kbd>K</kbd> — 입력창 포커스</li>
      <li><kbd>Q</kbd> — QA 모드 켜기/끄기</li>
      <li><kbd>Esc</kbd> — 열린 창 닫기</li>
    </ul>
    <p class="ob-sub">모바일</p>
    <ul class="ob-list">
      <li>이력 — 좌상단 <b>☰</b></li>
      <li>근거 — 답변 아래 <b>‘근거 N건’</b> 버튼</li>
      <li>QA · 피드백 — 헤더 <b>QA</b> · <b>피드백</b> 버튼</li>
    </ul>` },
];

const OB = { step: 0, view: "welcome", tab: "basic" };
const obFlag = n => { try { return localStorage.getItem(n); } catch { return null; } };
const obSetFlag = (n, v) => { try { localStorage.setItem(n, v); } catch { /* */ } };

function obRenderStep() {
  const s = OB_STEPS[OB.step];
  $("#ob-track").innerHTML = `<div class="ob-step">
    <div class="ob-illus">${s.svg}</div><h3>${s.t}</h3><p>${s.b}</p></div>`;
  $("#ob-dots").innerHTML = OB_STEPS.map((_, i) =>
    `<span class="ob-dot${i === OB.step ? " on" : ""}"></span>`).join("");
  $("#ob-prev").style.visibility = OB.step === 0 ? "hidden" : "visible";
  const last = OB.step === OB_STEPS.length - 1;
  $("#ob-next").textContent = last ? "시작하기" : "다음";
  // 마지막 스텝 + 데스크톱에서만 '자세히 둘러보기' 투어 CTA 노출
  $("#ob-tour").hidden = !(last && window.matchMedia("(min-width: 960px)").matches);
}
function obGo(d) {
  const n = OB.step + d;
  if (n < 0) return;
  if (n >= OB_STEPS.length) { obDoneWelcome(); return; }
  OB.step = n; obRenderStep();
}
function obDoneWelcome() {
  obSetFlag("pbdesk.onboarded", OB_VER);
  obClose();
  if (S.qa) maybeQaCoach();   // 환영을 QA 켠 채 봤으면 이어서 코치
}
function renderHelp() {
  $("#ob-tabs").innerHTML = OB_HELP.map(t =>
    `<button type="button" class="ob-tab${t.k === OB.tab ? " on" : ""}" data-k="${t.k}" role="tab">${t.ko}</button>`).join("");
  const t = OB_HELP.find(x => x.k === OB.tab) || OB_HELP[0];
  const body = $("#ob-help-body");
  body.innerHTML = t.html; body.scrollTop = 0;
}
function obOpen(view, tab) {
  OB.view = view || "welcome";
  $("#ob-welcome").hidden = OB.view !== "welcome";
  $("#ob-help").hidden = OB.view !== "help";
  if (OB.view === "welcome") { OB.step = 0; obRenderStep(); }
  else { OB.tab = tab || "basic"; renderHelp(); }
  // 도움말 뷰: 데스크톱에서 '화면 둘러보기' 투어 CTA 노출
  $("#ob-help-tour").hidden = OB.view !== "help" || !window.matchMedia("(min-width: 960px)").matches;
  const m = $("#ob-modal"), sc = $("#ob-scrim");
  m.hidden = false; sc.hidden = false;
  requestAnimationFrame(() => { m.classList.add("show"); sc.classList.add("show"); });
  document.body.classList.add("fb-lock");
  $("#ob-close").focus();
}
function obClose() {
  const m = $("#ob-modal"), sc = $("#ob-scrim");
  m.classList.remove("show"); sc.classList.remove("show");
  document.body.classList.remove("fb-lock");
  setTimeout(() => { m.hidden = true; sc.hidden = true; }, 180);
}
function obDismiss() {   // 환영을 완료 없이 닫아도 다시 뜨지 않게(스킵/스크림/Esc)
  if (OB.view === "welcome") obSetFlag("pbdesk.onboarded", OB_VER);
  obClose();
}
function maybeOnboard() {
  if (obFlag("pbdesk.onboarded") === OB_VER) return;
  if (new URLSearchParams(location.search).get("q")) return;  // 딥링크 질문 땐 방해 안 함
  obOpen("welcome");
}

/* QA 첫 활성화 코치 — 계측 패널이 처음 켜질 때 1회 */
function maybeQaCoach() {
  if (obFlag("pbdesk.qacoached") === "qa1") return;
  if (!$("#ob-modal").hidden) return;   // 온보딩과 겹치면 다음 기회에
  const c = $("#qa-coach");
  c.innerHTML = `<div class="qa-coach-card">
    <div class="qa-coach-h"><b>QA 모드를 켰어요</b>
      <button type="button" class="qa-coach-x" id="qa-coach-x" aria-label="닫기">✕</button></div>
    ${OB_QA_HTML}
    <p class="ob-note">이 설명은 오른쪽 위 <b>?</b> 도움말에서 다시 볼 수 있어요.</p>
    <div class="qa-coach-foot"><button type="button" class="qa-coach-ok" id="qa-coach-ok">알겠어요</button></div>
  </div>`;
  c.hidden = false;
  requestAnimationFrame(() => c.classList.add("show"));
}
function closeCoach() {
  obSetFlag("pbdesk.qacoached", "qa1");
  const c = $("#qa-coach");
  c.classList.remove("show");
  setTimeout(() => { c.hidden = true; }, 180);
}
/* QA 토글 진입점 — 켜질 때 코치 훅(저장 상태 복원엔 쓰지 않음) */
function triggerQa(on) { setQa(on); if (on) maybeQaCoach(); }

/* 배선 */
$("#help-open").addEventListener("click", () => obOpen("help", "basic"));
$("#hero-guide").addEventListener("click", () => obOpen("welcome"));
$("#ob-close").addEventListener("click", obDismiss);
$("#ob-skip").addEventListener("click", obDismiss);
$("#ob-scrim").addEventListener("click", obDismiss);
$("#ob-prev").addEventListener("click", () => obGo(-1));
$("#ob-next").addEventListener("click", () => obGo(1));
$("#ob-tabs").addEventListener("click", e => {
  const t = e.target.closest(".ob-tab");
  if (t) { OB.tab = t.dataset.k; renderHelp(); }
});
$("#qa-coach").addEventListener("click", e => {
  if (e.target.closest("#qa-coach-ok, #qa-coach-x")) closeCoach();
});
let obTouchX = null;
$("#ob-track").addEventListener("touchstart", e => { obTouchX = e.touches[0].clientX; }, { passive: true });
$("#ob-track").addEventListener("touchend", e => {
  if (obTouchX == null) return;
  const dx = e.changedTouches[0].clientX - obTouchX; obTouchX = null;
  if (Math.abs(dx) > 40) obGo(dx < 0 ? 1 : -1);
});
document.addEventListener("keydown", e => {   // 환영 캐러셀 좌우 화살표
  if ($("#ob-modal").hidden || OB.view !== "welcome") return;
  if (e.key === "ArrowRight") obGo(1);
  else if (e.key === "ArrowLeft") obGo(-1);
});

/* ═══════════════════════════════════════════════════════════════════
   인앱 튜토리얼 — 바닐라 스포트라이트 코치마크 투어 (데스크톱 전용)
   대상 하나만 밝히는 구멍(box-shadow cutout)으로 실제 요소를 순차 안내.
   챕터 3은 예시 질문을 자동 실행해 '방금 일어난 일' 위에 하이라이트.
   부재/숨은 대상(예: 온라인 숨김 #precise)은 진행 방향대로 자동 스킵.
   ═══════════════════════════════════════════════════════════════════ */
const TOUR_VER = "tour1";
const TOUR_DEMO_Q = "계좌개설 절차 알려줘";   // 추천 칩이 비었을 때 시연 폴백 질문
const TOUR_STEPS = [
  /* ── 챕터 1 · 화면이 이렇게 생겼어요 ── */
  { chapter: "화면 둘러보기", target: ".shell", pad: 0, placement: "center",
    title: "세 칸으로 나뉘어 있어요",
    html: `화면은 <b>왼쪽 이력 · 가운데 대화 · 오른쪽 근거</b> 세 칸이에요.
      질문하고, 답을 받고, 그 답의 근거까지 <b>한 화면에서</b> 같이 볼 수 있게 짜였어요.
      <span class="tour-tip-hint">💡 지금부터 각 칸을 하나씩 짚어 드릴게요.</span>` },
  { chapter: "화면 둘러보기", target: "#rail",
    title: "왼쪽 · 질문 이력",
    html: `질문할 때마다 여기에 <b>이력이 쌓여요.</b> 지난 질문을 다시 눌러 답과 근거를 그대로 다시 열어볼 수 있어요.
      <span class="tour-tip-hint">💡 새로 시작하려면 위쪽 「＋ 새 질문」.</span>` },
  { chapter: "화면 둘러보기", target: "#evidence", placement: "left",
    title: "오른쪽 · 근거",
    html: `답의 출처가 <b>지도와 카드</b>로 여기 나타나요. 어느 화면·부문에서 나온 답인지 늘 함께 보여줘서,
      답을 <b>믿을 근거</b>를 바로 확인할 수 있어요.` },
  { chapter: "화면 둘러보기", target: "#composer", placement: "top",
    title: "가운데 아래 · 질문 입력",
    html: `질문은 <b>여기</b>서 입력해요. 지금부터 이 입력줄의 기능을 하나씩 알려드릴게요.` },
  /* ── 챕터 2 · 이렇게 물어보세요 ── */
  { chapter: "이렇게 물어보세요", target: "#q", placement: "top",
    title: "무엇이든, 편하게",
    html: `“<b>계좌개설 절차</b>”처럼 짧게도, 문장으로도 물어보면 돼요. 매뉴얼 근거에서 답을 만들어 드려요.
      <span class="tour-tip-hint">💡 <kbd>Enter</kbd> 전송 · <kbd>Shift</kbd>+<kbd>Enter</kbd> 줄바꿈 · <kbd>/</kbd> 또는 <kbd>⌘K</kbd>로 입력창 포커스.</span>` },
  { chapter: "이렇게 물어보세요", target: "#scope-chip", placement: "top",
    title: "범위로 좁혀 묻기",
    html: `부문을 좁히면 <b>다른 업무의 결과가 섞이지 않아</b> 정확도가 올라가요. 매뉴얼은 화면·업무·상담 세 갈래라 첫 단계에서 고를 수 있어요.
      <span class="tour-tip-hint">💡 답이 여러 부문에 걸치면 배너로 “화면 기준? 업무 기준?”을 먼저 되물어봐요.</span>` },
  { chapter: "이렇게 물어보세요", target: "#samples", placement: "bottom",
    title: "뭘 물을지 막막하면",
    html: `<b>검증된 추천 질문</b>으로 시작해 보세요. 클릭 한 번이면 바로 물어봐요.
      <span class="tour-tip-hint">💡 아래 「↻ 다른 질문 보기」로 다른 추천을 볼 수 있어요.</span>` },
  { chapter: "이렇게 물어보세요", target: "#precise", placement: "top",
    title: "정밀 · 빠른 검색",   // 온라인은 리랭커 미설치 → 숨김이라 자동 스킵
    html: `<b>정밀</b>은 리랭커로 관련도를 더 정확히(질문당 몇 초 더), <b>빠른</b>은 즉시 응답이에요. 필요할 때 켜세요.` },
  /* ── 챕터 3 · 실제로 해볼게요 (가이드 시연) ── */
  { chapter: "실제로 해볼게요", target: null, placement: "center",
    title: "예시로 한 번 보여드릴까요?",
    html: `실제 질문을 <b>대신 한 번 던져</b> 답과 근거가 어떻게 이어지는지 보여드릴게요. 부담 없으면 바로 시작해 보세요.
      <div class="tour-choice">
        <button type="button" class="tour-btn primary" data-tour-act="demo">예시 보여주기 →</button>
        <button type="button" class="tour-btn" data-tour-act="skip-demo">직접 할게요</button>
      </div>` },
  { chapter: "실제로 해볼게요", target: ".thread .cite", dep: "demo", allowClick: true, pad: 6,
    title: "문장 끝의 [S1]을 눌러보세요",
    html: `답변 문장 끝의 <b>[S1]</b> 같은 표시가 <b>인용 근거</b>예요. 누르면 그 답이 나온 <b>매뉴얼 위치로 이동</b>해요.
      <span class="tour-tip-hint">💡 지금 실제로 눌러봐도 돼요 — 오른쪽 근거 카드가 반짝이며 열려요.</span>` },
  { chapter: "실제로 해볼게요", target: ["#ev-map", ".ev-card"], dep: "demo", placement: "left",
    title: "근거 지도 · 카드",
    html: `여기서 답이 <b>어느 화면·부문</b>에서 나왔는지 확인해요. 카드의 <b>화면번호</b>로 단말에서 바로 그 화면을 찾을 수 있어요.
      <span class="tour-tip-hint">💡 지도 항목의 「좁히기」를 누르면 그 경로 안에서만 다시 검색해요.</span>` },
  /* ── 마무리 ── */
  { chapter: "마무리", target: "#help-open", placement: "bottom",
    title: "언제든 다시, 그리고 알려주세요",
    html: `사용법이 헷갈리면 <b>?</b> 도움말에서 다시 볼 수 있어요. 답이 아쉬우면 <b>피드백</b>으로,
      검색이 왜 이렇게 나왔는지 뜯어보려면 헤더의 <b>QA</b>를 켜 보세요. 이제 직접 물어볼 차례예요!` },
];

const TOUR = {
  steps: TOUR_STEPS, i: 0, dir: 1, active: false,
  demoRan: false, demoOk: false, loading: false,   // loading=시연 대기 중(입력 무시)
  scrim: null, hole: null, tip: null,
  curEl: null, ro: null, raf: 0,
};
const tourEligible = () => window.matchMedia("(min-width: 960px)").matches;
const tourReduced = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/* 대상 해석: null=중앙 안내(정상), 배열=첫 가시요소, undefined=대상 없음(스킵) */
function tourResolve(s) {
  if (!s.target) return null;
  const sels = Array.isArray(s.target) ? s.target : [s.target];
  for (const sel of sels) {
    const el = document.querySelector(sel);
    if (el && !el.hidden && el.offsetParent !== null) return el;
  }
  return undefined;
}

function tourEnsureDom() {
  if (TOUR.scrim) return;
  const scrim = document.createElement("div");
  scrim.className = "tour-scrim"; scrim.id = "tour-scrim";
  const hole = document.createElement("div");
  hole.className = "tour-hole"; hole.id = "tour-hole"; hole.setAttribute("aria-hidden", "true");
  const tip = document.createElement("div");
  tip.className = "tour-tip"; tip.id = "tour-tip";
  tip.setAttribute("role", "dialog");
  tip.setAttribute("aria-modal", "true");
  tip.setAttribute("aria-live", "polite");
  document.body.append(scrim, hole, tip);
  TOUR.scrim = scrim; TOUR.hole = hole; TOUR.tip = tip;
  scrim.addEventListener("click", () => { if (TOUR.active) tourGo(1); });   // 스크림 클릭 = 다음
  tip.addEventListener("click", e => {
    const b = e.target.closest("[data-tour-act]");
    if (!b) return;
    const act = b.dataset.tourAct;
    if (act === "prev") tourGo(-1);
    else if (act === "next" || act === "demo") tourGo(1);
    else if (act === "skip") endTour(false);
    else if (act === "done") endTour(true);
    else if (act === "skip-demo") { TOUR.demoRan = true; TOUR.demoOk = false; tourGo(1); }
  });
}

function startTour(from) {
  if (!tourEligible()) { obOpen("welcome"); return; }   // 모바일·좁은 화면 → 캐러셀 폴백
  tourEnsureDom();
  TOUR.active = true; TOUR.i = 0; TOUR.dir = 1;
  TOUR.demoRan = false; TOUR.demoOk = false;
  document.body.classList.add("tour-on");
  TOUR.scrim.hidden = false; TOUR.hole.hidden = false; TOUR.tip.hidden = false;
  requestAnimationFrame(() => {
    TOUR.scrim.classList.add("show"); TOUR.tip.classList.add("show");
  });
  addEventListener("scroll", tourReposition, true);
  addEventListener("resize", tourReposition);
  tourRender();
}

function endTour(completed) {
  if (!TOUR.active) return;
  TOUR.active = false;
  removeEventListener("scroll", tourReposition, true);
  removeEventListener("resize", tourReposition);
  if (TOUR.ro) { TOUR.ro.disconnect(); TOUR.ro = null; }
  if (TOUR.raf) { cancelAnimationFrame(TOUR.raf); TOUR.raf = 0; }
  document.body.classList.remove("tour-on");
  if (TOUR.scrim) { TOUR.scrim.classList.remove("show"); TOUR.tip.classList.remove("show"); }
  setTimeout(() => {
    if (TOUR.active) return;   // 재시작 방지
    if (TOUR.scrim) { TOUR.scrim.hidden = true; TOUR.hole.hidden = true; TOUR.tip.hidden = true; }
  }, 200);
  if (completed) obSetFlag("pbdesk.tour", TOUR_VER);
  const hg = $("#hero-guide"); if (hg) hg.classList.remove("pulse");
}

function tourGo(d) {
  if (!TOUR.active || TOUR.loading) return;   // 시연 대기 중 입력 무시
  TOUR.dir = d < 0 ? -1 : 1;
  TOUR.i += TOUR.dir;
  if (TOUR.i < 0) { TOUR.i = 0; TOUR.dir = 1; }
  if (TOUR.i >= TOUR.steps.length) { endTour(true); return; }
  tourRender();
}

/* 현재 스텝을 렌더 — 스킵/시연 대기 처리 포함(비동기) */
async function tourRender() {
  if (!TOUR.active) return;
  let guard = 0;
  while (guard++ < TOUR.steps.length + 3) {
    const s = TOUR.steps[TOUR.i];
    if (!s) { endTour(true); return; }
    // 시연 의존 스텝: 예시가 실패했으면 스킵
    if (s.dep === "demo" && TOUR.demoRan && !TOUR.demoOk) { TOUR.i += TOUR.dir; if (tourClamp()) return; continue; }
    // 시연 실행(첫 진입 시 1회) — before 없이 dep로 묶고, 첫 dep 스텝 진입 때 실행
    if (s.dep === "demo" && !TOUR.demoRan) {
      tourLoading("예시 질문을 실행하고 있어요…");
      TOUR.loading = true;
      const ok = await tourDemoRun();
      TOUR.loading = false;
      if (!TOUR.active) return;
      TOUR.demoRan = true; TOUR.demoOk = ok;
      if (!ok) { TOUR.i += TOUR.dir; if (tourClamp()) return; continue; }
    }
    const el = s.target ? tourResolve(s) : null;
    if (s.target && !el) { TOUR.i += TOUR.dir; if (tourClamp()) return; continue; }
    tourPaint(s, el);
    return;
  }
  endTour(true);
}
function tourClamp() {   // 방향대로 스킵하다 경계를 벗어나면 종료 처리
  if (TOUR.i < 0) { TOUR.i = 0; TOUR.dir = 1; return false; }
  if (TOUR.i >= TOUR.steps.length) { endTour(true); return true; }
  return false;
}

/* 예시 질문 자동 실행 → 인용이 달린 done 답변이 나올 때까지 (실패 시 1회 재시도) */
async function tourDemoRun() {
  const pool = [];
  for (const sm of (S.samples || [])) if (sm && sm.q) pool.push(sm.q);
  const cands = (pool.length ? pool.slice(0, 2) : []);
  cands.push(TOUR_DEMO_Q);
  for (const q of cands.slice(0, 2)) {
    if (!TOUR.active) return false;
    try { await ask(q, { src: "tour" }); } catch { continue; }
    if (!TOUR.active) return false;
    const t = S.turns[S.turns.length - 1];
    if (t && t.state === "done" && document.querySelector(".thread .cite")) return true;
  }
  return false;
}

/* 시연 대기 중 안내 카드(중앙, 구멍 없음) */
function tourLoading(msg) {
  const hole = TOUR.hole, tip = TOUR.tip;
  hole.classList.remove("show");
  tip.dataset.place = "center";
  tip.style.left = "50%"; tip.style.top = "50%"; tip.style.transform = "translate(-50%,-50%)";
  tip.innerHTML = `<div class="tour-loading"><span class="tour-spin" aria-hidden="true"></span>${esc(msg)}</div>`;
}

/* 툴팁 본문 HTML (스텝 콘텐츠는 저작 상수 — 사용자 입력 아님) */
function tourTipHTML(s) {
  const no = TOUR.i + 1, tot = TOUR.steps.length;
  const isLast = TOUR.i === tot - 1;
  const custom = /data-tour-act="(demo|skip-demo)"/.test(s.html);   // 선택형 스텝은 기본 [다음] 생략
  const nav = custom ? "" : `<button type="button" class="tour-btn primary" data-tour-act="${isLast ? "done" : "next"}">${isLast ? "둘러보기 완료" : "다음 →"}</button>`;
  const prev = TOUR.i === 0 ? "" : `<button type="button" class="tour-btn ghost" data-tour-act="prev">이전</button>`;
  return `<div class="tour-prog"><span class="tour-chap">${esc(s.chapter)}</span><span class="tour-count">${no} / ${tot}</span></div>
    <div class="tour-bar"><i style="width:${Math.round(no / tot * 100)}%"></i></div>
    <h4 class="tour-title">${s.title}</h4>
    <div class="tour-body">${s.html}</div>
    <div class="tour-foot">
      <button type="button" class="tour-btn link" data-tour-act="skip">건너뛰기</button>
      <div class="tour-foot-nav">${prev}${nav}</div>
    </div>`;
}

/* 대상 위 스포트라이트 + 툴팁 배치 */
function tourPaint(s, el) {
  const tip = TOUR.tip, hole = TOUR.hole;
  tip.innerHTML = tourTipHTML(s);
  // 시연 인용 스텝만 뒤 요소 실제 클릭 허용(그 외는 스크림이 오조작 차단)
  TOUR.scrim.style.pointerEvents = s.allowClick ? "none" : "auto";

  if (TOUR.ro) { TOUR.ro.disconnect(); TOUR.ro = null; }
  TOUR.curEl = el;

  if (!el) {   // 중앙 안내 스텝(구멍 없음)
    hole.classList.remove("show");
    tip.dataset.place = "center";
    tip.style.left = "50%"; tip.style.top = "50%"; tip.style.transform = "translate(-50%,-50%)";
  } else {
    const r0 = el.getBoundingClientRect();
    const off = r0.top < 72 || r0.bottom > innerHeight - 72;
    if (off) el.scrollIntoView({ behavior: tourReduced() ? "auto" : "smooth", block: "center" });
    hole.classList.add("show");
    tourSetHole(s, el);   // 즉시 1회 배치 (스크롤 이벤트가 이후 미세보정)
    // 대상 크기 변화 추종
    if (typeof ResizeObserver === "function") {
      TOUR.ro = new ResizeObserver(() => tourReposition());
      try { TOUR.ro.observe(el); } catch { /* */ }
    }
  }
  // 다음/완료 버튼에 포커스(접근성) — 선택형은 첫 버튼
  const fb = tip.querySelector('[data-tour-act="next"],[data-tour-act="done"],[data-tour-act="demo"]');
  if (fb) fb.focus();
}

/* 구멍·툴팁 위치 계산 (rAF 디바운스로 재사용) */
function tourSetHole(s, el) {
  const r = el.getBoundingClientRect();
  const pad = s.pad ?? 8;
  const hole = TOUR.hole;
  hole.style.left = (r.left - pad) + "px";
  hole.style.top = (r.top - pad) + "px";
  hole.style.width = (r.width + pad * 2) + "px";
  hole.style.height = (r.height + pad * 2) + "px";
  const br = parseFloat(getComputedStyle(el).borderRadius) || 0;
  hole.style.borderRadius = (br ? br + pad : 12) + "px";
  tourSetTip(s, r);
}
function tourSetTip(s, r) {
  const tip = TOUR.tip;
  const tw = tip.offsetWidth, th = tip.offsetHeight;
  const gap = 14, m = 12, vw = innerWidth, vh = innerHeight;
  const below = vh - r.bottom, above = r.top;
  let place = s.placement && s.placement !== "center" ? s.placement : ((below >= above) ? "bottom" : "top");
  // 세로 공간 부족 시 flip
  if ((place === "bottom") && below < th + gap && above > below) place = "top";
  else if ((place === "top") && above < th + gap && below > above) place = "bottom";
  let top, left;
  if (place === "top") { top = r.top - th - gap; left = r.left + r.width / 2 - tw / 2; }
  else if (place === "bottom") { top = r.bottom + gap; left = r.left + r.width / 2 - tw / 2; }
  else if (place === "left") { left = r.left - tw - gap; top = r.top + r.height / 2 - th / 2; }
  else { left = r.right + gap; top = r.top + r.height / 2 - th / 2; }   // right
  // 좌우 경계 감지 후 flip(가로 배치일 때)
  if (place === "left" && left < m) { place = "right"; left = r.right + gap; }
  else if (place === "right" && left + tw > vw - m) { place = "left"; left = r.left - tw - gap; }
  left = Math.max(m, Math.min(left, vw - tw - m));
  top = Math.max(m, Math.min(top, vh - th - m));
  tip.style.transform = "none";
  tip.style.left = left + "px";
  tip.style.top = top + "px";
  tip.dataset.place = place;
  const cx = r.left + r.width / 2, cy = r.top + r.height / 2;
  tip.style.setProperty("--arrow-x", Math.max(18, Math.min(cx - left, tw - 18)) + "px");
  tip.style.setProperty("--arrow-y", Math.max(18, Math.min(cy - top, th - 18)) + "px");
}
function tourReposition() {
  if (!TOUR.active || TOUR.raf) return;
  TOUR.raf = requestAnimationFrame(() => {
    TOUR.raf = 0;
    if (!TOUR.active || !TOUR.curEl) return;
    const s = TOUR.steps[TOUR.i];
    tourSetHole(s, TOUR.curEl);
  });
}

/* 키보드 — 캡처 단계에서 선점(투어 중 배경 단축키 차단) */
document.addEventListener("keydown", e => {
  if (!TOUR.active) return;
  const k = e.key;
  if (k === "Escape") { e.preventDefault(); e.stopPropagation(); endTour(false); return; }
  if (k === "ArrowRight") { e.preventDefault(); e.stopPropagation(); tourGo(1); return; }
  if (k === "ArrowLeft") { e.preventDefault(); e.stopPropagation(); tourGo(-1); return; }
  if (k === "Enter") {
    const inTip = TOUR.tip && document.activeElement && TOUR.tip.contains(document.activeElement);
    if (!inTip) { e.preventDefault(); e.stopPropagation(); tourGo(1); }   // 버튼 포커스면 네이티브 클릭에 위임
    return;
  }
  if (k.length === 1) e.stopPropagation();   // Q·/ 등 배경 단축키 차단
}, true);

/* 진입점 배선 */
$("#ob-tour").addEventListener("click", () => {   // 환영 캐러셀 마지막 스텝 CTA
  obSetFlag("pbdesk.onboarded", OB_VER);
  obClose();
  setTimeout(() => startTour("welcome"), 190);   // 캐러셀 닫힘 후 시작
});
$("#ob-help-tour").addEventListener("click", () => {   // 도움말 '기본' 탭 CTA
  obClose();
  setTimeout(() => startTour("help"), 190);
});

/* ═══════════════ 부트 ═══════════════ */
loadStore();
if (new URLSearchParams(location.search).get("qa") === "1") S.qa = true;
setQa(S.qa);
void loadFbCapabilities();
renderScopeChip();
renderSessions();
renderThread();
autoresize();
qEl.focus();

getJSON("/api/meta").then(m => {
  const model = (m.embed_model || "").split("/").pop();
  $("#index-chip").textContent = `${(m.count ?? 0).toLocaleString()} 청크 · ${model}`;
  $("#index-chip").title =
    `임베딩 ${m.embed_model} · ${m.dim}차원 · 리랭커 ${m.reranker || "없음"} · 게이트 ${m.gate?.mode} τ=${m.gate?.tau}`;
  if (m.gate) syncTau(m.gate);
  if (m.reranker) {
    $("#precise").hidden = false;
    renderPrecise();
  } else {
    S.rerank = false;   // 리랭커 미설치 — 토글 숨김, 항상 코사인
  }
  S.metaSamples = m.samples || [];   // suggest 실패 시 폴백 원본
  loadSuggest(false);                // 스코프 연동 예상 질문 비동기 로드
  // 딥링크: /?q=질문 → 자동 질의 (게이트 기본값 로딩 후 실행)
  const params = new URLSearchParams(location.search);
  const initQ = params.get("q");
  if (initQ && !S.busy) ask(initQ);
  // 온보딩: 최초 방문 환영(딥링크 질문 땐 생략) · ?onboarding=1 강제 · ?qa=1 코치
  if (params.get("tour") === "1") { startTour("query"); }   // 투어 강제 실행(디버깅)
  else if (params.get("onboarding") === "1") obOpen("welcome");
  else maybeOnboard();
  if (params.get("qa") === "1") maybeQaCoach();
  // 재방문 데스크톱(온보딩 완료·투어 미완료): 자동 시작 없이 hero-guide 1회 펄스로만 발견성 ↑
  if (obFlag("pbdesk.onboarded") === OB_VER && obFlag("pbdesk.tour") !== TOUR_VER
      && !params.get("q") && window.matchMedia("(min-width: 960px)").matches) {
    const hg = $("#hero-guide"); if (hg) hg.classList.add("pulse");
    document.addEventListener("click", () => { if (hg) hg.classList.remove("pulse"); }, { once: true });
  }
}).catch(() => {
  $("#index-chip").textContent = "서버 연결 안 됨";
});
