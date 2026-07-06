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

/* ── 상태 ── */
const S = {
  qa: false,
  rerank: true,        // 정밀 게이트(리랭커) 사용 여부 — 컴포저 '정밀' 토글
  tauTouched: false,   // QA 슬라이더로 τ를 직접 만졌는지 (아니면 서버 기본값 추종)
  scope: [],           // 브레드크럼 스코프 (부문>중분류>화면) — 교차 오염 방지
  sectorTree: null,    // /api/sectors 캐시
  alpha: 0.5, topk: 5, tau: 0.5, gateMode: "cosine",
  types: new Set(Object.keys(TYPES)),
  samples: [],
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
  sector: h.sector, sector_path: h.sector_path,
  text: h.text, screen_id: h.screen_id, screen_no: h.screen_no,
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
    const leaf = (h.section_path || []).slice(-1)[0] || h.screen_id;
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
  return `<footer class="a-foot">
    <button type="button" class="a-act act-copy">복사</button>
    <button type="button" class="a-act act-regen">재생성</button>
    <button type="button" class="a-act ev-open-btn">근거 ${turn.hits?.length ?? 0}건</button>
    ${modePill(turn)}<span class="a-meta">${esc(meta)}</span>
  </footer>`;
}
function followups(turn) {
  const isLast = S.turns.length && S.turns[S.turns.length - 1].id === turn.id;
  if (!isLast || turn.state !== "done") return "";
  const asked = new Set(S.turns.map(t => t.q));
  let qs = (turn.hits || []).filter(h => h.chunk_type === "qa")
    .map(h => (h.section_path || []).slice(-1)[0])
    .filter(q => q && q.endsWith("?") && q.length <= 60 && !asked.has(q));
  qs = [...new Set(qs)].slice(0, 2);
  for (const sm of S.samples) {
    if (qs.length >= 2) break;
    if (!asked.has(sm) && !qs.includes(sm)) qs.push(sm);
  }
  if (!qs.length) return "";
  return `<div class="followups"><p class="fl">이런 질문은 어떠세요?</p>
    <div class="chips">${qs.map(q =>
      `<button type="button" class="chip ask-chip">${esc(q)}</button>`).join("")}</div></div>`;
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
    case "gated":
      return `<div class="a-gated">
          <h3>매뉴얼에서 확인되지 않았어요</h3>
          <p>계좌 매뉴얼 안에서 이 질문의 근거를 찾지 못했어요.
             화면 이름이나 용어를 넣어 질문을 바꿔보시겠어요? 오른쪽 근거는 참고용이에요.</p>
          <div class="chips">${S.samples.slice(0, 3).map(q =>
            `<button type="button" class="chip ask-chip">${esc(q)}</button>`).join("")}</div>
        </div>${turnFoot(turn)}`;
    case "error":
      return `<div class="a-error"><b>서버에 연결할 수 없어요</b> — webapp.py 실행을 확인해 주세요.
        <button type="button" class="retry act-regen">다시 시도</button></div>`;
    default: // done
      return `${srcStrip(turn)}
        <div class="a-body">${mdlite(turn.answer || "")}</div>
        ${turnFoot(turn)}`;
  }
}
function scopeBanner(turn) {
  const h = turn.scope_hint;
  if (!h?.ambiguous || turn.scope?.length || turn.hintDismissed) return "";
  const chips = h.sectors.slice(0, 3).map(s =>
    `<button type="button" class="sb-chip sb-scope" data-sector="${esc(s.sector)}"
       data-q="${esc(turn.q)}">${esc(s.sector)}에서만 (${s.count}건 · ${(+s.best).toFixed(2)})</button>`).join("");
  return `<div class="scope-banner" role="status">
    <span class="sb-t">근거가 여러 부문에 걸쳐 있어요 — 어느 업무 기준으로 볼까요?</span>
    ${chips}<button type="button" class="sb-chip keep sb-keep">전체 유지</button></div>`;
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
    const segs = [...(h.sector ? [h.sector] : []), ...(h.section_path || [])];
    if (!segs.length) continue;
    if (!roots.has(segs[0]))
      roots.set(segs[0], { label: segs[0], children: new Map(), ranks: [],
                           scope: h.sector ? [h.sector] : null });
    let node = roots.get(segs[0]);
    segs.slice(1).forEach((seg, idx) => {
      if (!node.children.has(seg))
        node.children.set(seg, { label: seg, children: new Map(), ranks: [], scope: null });
      node = node.children.get(seg);
      if (h.sector && idx === 0 && !node.scope)   // 화면 제목 레벨 → 화면 단위 스코프
        node.scope = [...(h.sector_path || [h.sector]), h.screen_id];
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
      <button type="button" class="ticker" data-copy="${esc(h.screen_id)}" title="화면 코드 복사">${esc(h.screen_id)}</button>
      <span class="no mono">[${esc(h.screen_no)}]</span>
      <a href="${esc(h.source_url)}" target="_blank" rel="noopener">원문 매뉴얼 ↗</a>
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
        g.all_low ? " · <b>전건 저신뢰</b>" : ""} — τ 변경은 화면에 즉시, 답변 게이트엔 다음 질문부터 적용돼요.`
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
async function getJSON(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error("http " + r.status);
  return r.json();
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
async function ask(q) {
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
    const s = await getJSON("/api/search?" + params);           // 1단: 근거 선노출
    turn.hits = trimHits(s.hits); turn.gate = s.gate; turn.search_ms = s.elapsed_ms;
    turn.scope_hint = s.scope_hint;
    syncTau(s.gate);
    turn.state = "writing";
    updateTurn(turn); renderEvidence(turn); scrollBottom();

    const a = await getJSON("/api/answer?" + params);           // 2단: 답변
    Object.assign(turn, {
      hits: trimHits(a.hits), gate: a.gate, answer: a.answer,
      backend: a.backend, used_llm: a.used_llm, scope_hint: a.scope_hint,
      search_ms: a.search_ms, gen_ms: a.gen_ms,
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
  if (sbScope) {                        // 모호성 배너 → 부문 확정 후 같은 질문 재검색
    const t = S.turns.find(x => x.id === sbScope.closest(".turn")?.dataset.turn);
    if (t) { t.hintDismissed = true; updateTurn(t); }
    setScope([sbScope.dataset.sector]);
    ask(sbScope.dataset.q);
    return;
  }
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
  if (chip) { ask(chip.textContent); return; }
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
  for (let level = 0; parent && cols.length < 4; level++) {
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
        <span class="n">${esc(s.title)}</span><span class="c">${esc(s.id)}</span></button>`;
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
$("#qa-toggle").addEventListener("click", () => setQa(!S.qa));
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
    document.body.classList.remove("nav-open", "ev-open"); syncScrim();
    $("#scope-panel").hidden = true;
    return;
  }
  if (e.target.closest("input, textarea")) return;
  if (e.key === "/" || ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k")) {
    e.preventDefault(); qEl.focus();
  } else if (e.key.toLowerCase() === "q" && !e.ctrlKey && !e.metaKey && !e.altKey) {
    setQa(!S.qa);
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

/* ═══════════════ 부트 ═══════════════ */
function renderSamples() {
  $("#samples").innerHTML = S.samples.slice(0, 4).map(q =>
    `<button type="button" class="chip ask-chip">${esc(q)}</button>`).join("");
}
loadStore();
if (new URLSearchParams(location.search).get("qa") === "1") S.qa = true;
setQa(S.qa);
renderScopeChip();
renderSessions();
renderThread();
autoresize();
qEl.focus();

fetch("/api/meta").then(r => r.json()).then(m => {
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
  S.samples = m.samples || [];
  renderSamples();
  // 딥링크: /?q=질문 → 자동 질의 (게이트 기본값 로딩 후 실행)
  const initQ = new URLSearchParams(location.search).get("q");
  if (initQ && !S.busy) ask(initQ);
}).catch(() => {
  $("#index-chip").textContent = "서버 연결 안 됨";
});
