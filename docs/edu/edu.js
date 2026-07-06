/* KOSCOM RAG 실습 과정 — 슬라이드 내비/복사 (무의존) */
"use strict";
const slides = [...document.querySelectorAll(".slide")];

/* 쪽번호·딥링크 id 주입 (#p12 형태로 특정 슬라이드 공유 가능) */
slides.forEach((s, i) => {
  s.id = "p" + (i + 1);
  const pg = s.querySelector(".foot .pg");
  if (pg && !pg.textContent.trim()) pg.textContent = String(i + 1).padStart(2, "0");
});
if (location.hash) document.querySelector(location.hash)?.scrollIntoView({ behavior: "instant" });

/* 진행바 + 현재 쪽 표시 */
const bar = document.getElementById("progress");
const num = document.getElementById("pagenum");
let cur = 0;
function onScroll() {
  const y = window.scrollY, h = window.innerHeight;
  cur = Math.min(slides.length - 1, Math.round(y / h));
  bar.style.width = ((cur + 1) / slides.length * 100) + "%";
  num.textContent = `${cur + 1} / ${slides.length}`;
}
document.addEventListener("scroll", onScroll, { passive: true });
onScroll();

/* 키보드 내비 */
const go = i => slides[Math.max(0, Math.min(slides.length - 1, i))]
  .scrollIntoView({ behavior: "smooth" });
document.addEventListener("keydown", e => {
  if (e.target.closest("input,textarea")) return;
  const toc = document.getElementById("toc");
  if (e.key === "Escape") { toc.classList.remove("open"); return; }
  if (e.key.toLowerCase() === "t") { toc.classList.toggle("open"); return; }
  if (toc.classList.contains("open")) return;
  if (["ArrowRight", "ArrowDown", "PageDown", " "].includes(e.key)) { e.preventDefault(); go(cur + 1); }
  else if (["ArrowLeft", "ArrowUp", "PageUp"].includes(e.key)) { e.preventDefault(); go(cur - 1); }
  else if (e.key === "Home") { e.preventDefault(); go(0); }
  else if (e.key === "End") { e.preventDefault(); go(slides.length - 1); }
});

/* 목차 오버레이 (data-title 기반, data-part로 구분 라벨) */
(function buildToc() {
  const ol = document.querySelector("#toc ol");
  slides.forEach((s, i) => {
    if (s.dataset.part) {
      const d = document.createElement("div");
      d.className = "t-part"; d.textContent = s.dataset.part;
      ol.appendChild(d);
    }
    const li = document.createElement("li");
    const b = document.createElement("button");
    b.textContent = s.dataset.title || `슬라이드 ${i + 1}`;
    b.addEventListener("click", () => {
      document.getElementById("toc").classList.remove("open");
      go(i);
    });
    li.appendChild(b); ol.appendChild(li);
  });
})();
document.getElementById("toc").addEventListener("click", e => {
  if (e.target.id === "toc") e.target.classList.remove("open");
});

/* 복사 버튼 — 모든 .code / .prompt 블록에 주입 */
document.querySelectorAll(".code, .prompt").forEach(block => {
  const pre = block.querySelector("pre");
  if (!pre) return;
  const btn = document.createElement("button");
  btn.type = "button"; btn.className = "copy-btn"; btn.textContent = "복사";
  btn.setAttribute("aria-label", "블록 내용 복사");
  btn.addEventListener("click", () => {
    // 주석(.c)·출력 강조는 그대로 두되, 프롬프트/셸 원문 텍스트를 복사
    const text = pre.innerText.replace(/\n{3,}/g, "\n\n").trim();
    const done = () => {
      btn.textContent = "복사됨 ✓"; btn.classList.add("done");
      setTimeout(() => { btn.textContent = "복사"; btn.classList.remove("done"); }, 1200);
    };
    if (navigator.clipboard?.writeText) navigator.clipboard.writeText(text).then(done, done);
    else {  // file:// 등 클립보드 API 불가 환경 폴백
      const ta = document.createElement("textarea");
      ta.value = text; document.body.appendChild(ta); ta.select();
      try { document.execCommand("copy"); } catch {}
      ta.remove(); done();
    }
  });
  block.appendChild(btn);
});
