/* 웹 챗 UI 데모 캡처 — playwright-core + chrome-headless-shell
 * 산출: captures/out/07_webapp.webm + markers.json (편집점)
 * 사용: node 07_webapp.mjs <baseURL> <chromePath> <outDir>
 */
import {chromium} from 'playwright-core';
import {mkdirSync, writeFileSync, renameSync, readdirSync} from 'node:fs';
import {join} from 'node:path';

const BASE = process.argv[2] ?? 'http://127.0.0.1:8010';
const CHROME = process.argv[3];
const OUT = process.argv[4] ?? '../out';

const Q1 = process.env.Q1 ?? 'SMS 일괄 발송은 어디서 하나요?';
const Q2 = process.env.Q2 ?? '';               // 비우면 후속질문 칩 클릭
const Q3 = process.env.Q3 ?? '연차 휴가 신청은 어디서 하나요?';

const markers = [];
let t0 = 0;
const mark = (label) => {
  markers.push({label, t: (Date.now() - t0) / 1000});
  console.log(`  ▸ ${label} @ ${((Date.now() - t0) / 1000).toFixed(1)}s`);
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/* 가짜 커서 (헤드리스에는 포인터가 안 보임) — 이동 추적 + 클릭 리플 */
const CURSOR_JS = `
(() => {
  if (window.__cur) return;
  const el = document.createElement('div');
  el.id = '__cursor';
  el.innerHTML = '<svg width="26" height="26" viewBox="0 0 24 24"><path d="M5 3l14 8.2-6.4 1.3L9.8 19 5 3z" fill="#16181c" stroke="#fff" stroke-width="1.4"/></svg>';
  Object.assign(el.style, {position:'fixed',left:'0',top:'0',zIndex:999999,pointerEvents:'none',
    transition:'transform 0.06s linear',transform:'translate(-60px,-60px)'});
  const add = () => document.body ? document.body.appendChild(el) : setTimeout(add, 50);
  add();
  window.__cur = el;
  document.addEventListener('mousemove', (e) => {
    el.style.transform = 'translate(' + e.clientX + 'px,' + e.clientY + 'px)';
  }, true);
  document.addEventListener('mousedown', (e) => {
    const r = document.createElement('div');
    Object.assign(r.style, {position:'fixed',left:(e.clientX-18)+'px',top:(e.clientY-18)+'px',
      width:'36px',height:'36px',borderRadius:'50%',zIndex:999998,pointerEvents:'none',
      border:'2.5px solid rgba(245,130,31,0.9)',animation:'__rip 0.5s ease-out forwards'});
    document.body.appendChild(r);
    setTimeout(() => r.remove(), 600);
  }, true);
  const st = document.createElement('style');
  st.textContent = '@keyframes __rip{from{transform:scale(0.4);opacity:1}to{transform:scale(1.5);opacity:0}}';
  document.head.appendChild(st);
})();`;

/* 사람 손 느낌의 이동 + 클릭 */
async function humanClick(page, locator) {
  const box = await locator.boundingBox();
  if (!box) throw new Error('no box');
  const x = box.x + box.width / 2 + (Math.random() * 8 - 4);
  const y = box.y + box.height / 2 + (Math.random() * 4 - 2);
  await page.mouse.move(x, y, {steps: 22});
  await sleep(260);
  await page.mouse.down();
  await sleep(70);
  await page.mouse.up();
}

async function typeSlow(page, sel, text) {
  await humanClick(page, page.locator(sel));
  await sleep(200);
  for (const ch of text) {
    await page.keyboard.type(ch);
    await sleep(28 + Math.random() * 40);
  }
}

const run = async () => {
  mkdirSync(OUT, {recursive: true});
  const browser = await chromium.launch({
    executablePath: CHROME,
    headless: true,
    args: ['--no-sandbox', '--disable-dev-shm-usage', '--font-render-hinting=none', '--force-device-scale-factor=1'],
  });
  const ctx = await browser.newContext({
    viewport: {width: 1920, height: 1080},
    deviceScaleFactor: 1,
    recordVideo: {dir: OUT, size: {width: 1920, height: 1080}},
    locale: 'ko-KR',
    timezoneId: 'Asia/Seoul',
  });
  await ctx.addInitScript(CURSOR_JS);
  const ZOOM = process.env.ZOOM ?? '1.12'; // 영상 가독성용 페이지 확대
  await ctx.addInitScript(`document.addEventListener('DOMContentLoaded',()=>{document.documentElement.style.zoom='${ZOOM}';});`);
  const page = await ctx.newPage();
  page.setDefaultTimeout(240000);

  t0 = Date.now();
  await page.goto(BASE, {waitUntil: 'networkidle'});
  await page.waitForFunction(() => document.querySelector('#index-chip')?.textContent?.includes('청크'));
  await page.mouse.move(960, 700, {steps: 10});
  mark('hero');
  await sleep(2600);

  const lastTurn = () => page.locator('.turn').last();

  /* Q1 — 타이핑 → 근거 선노출 → 답변 → 출처 클릭 */
  mark('q1_type');
  await typeSlow(page, '#q', Q1);
  await sleep(350);
  mark('q1_sent');
  await page.keyboard.press('Enter');
  await lastTurn().locator('.src-strip').waitFor();
  mark('q1_evidence');
  await lastTurn().locator('.a-body').waitFor();
  mark('q1_answer');
  await sleep(2400);
  const cite = lastTurn().locator('.a-body .cite').first();
  if (await cite.count()) {
    await humanClick(page, cite);
    mark('q1_cite');
    await sleep(2600);
  }

  /* Q2 — 후속질문 칩 or 타이핑 */
  const chip = page.locator('.followups .ask-chip').first();
  if (!Q2 && (await chip.count())) {
    await humanClick(page, chip);
    mark('q2_sent');
  } else {
    mark('q2_type');
    await typeSlow(page, '#q', Q2 || 'SMS 통보 서비스 약정은 어디서 등록하나요?');
    mark('q2_sent');
    await page.keyboard.press('Enter');
  }
  await lastTurn().locator('.src-strip').waitFor();
  mark('q2_evidence');
  await lastTurn().locator('.a-body').waitFor();
  mark('q2_answer');
  await sleep(2200);
  // 근거 지도 hover — 인용↔카드 상호 점등
  const mapRow = page.locator('.mn-row').first();
  if (await mapRow.count()) {
    const box = await mapRow.boundingBox();
    if (box) {
      await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2, {steps: 18});
      mark('q2_map');
      await sleep(1800);
    }
  }

  /* Q3 — 매뉴얼 밖 질문 → 거절 */
  mark('q3_type');
  await typeSlow(page, '#q', Q3);
  mark('q3_sent');
  await page.keyboard.press('Enter');
  await lastTurn().locator('.a-gated, .a-body').waitFor();
  mark('q3_gated');
  await sleep(3000);

  /* QA 계측 모드 */
  await page.mouse.move(700, 300, {steps: 12});
  await page.mouse.down();
  await page.mouse.up();
  await sleep(400);
  await page.keyboard.press('q');
  mark('qa_on');
  await sleep(1600);

  const drag = async (sel, toRatio, label) => {
    const box = await page.locator(sel).boundingBox();
    if (!box) return;
    const y = box.y + box.height / 2;
    const cur = box.x + box.width * 0.5;
    await page.mouse.move(cur, y, {steps: 14});
    await sleep(250);
    await page.mouse.down();
    for (let i = 1; i <= 12; i++) {
      await page.mouse.move(box.x + box.width * (0.5 + (toRatio - 0.5) * (i / 12)), y);
      await sleep(55);
    }
    await page.mouse.up();
    mark(label);
  };
  await drag('#alpha', 0.92, 'alpha_hi');
  await sleep(1300);
  await drag('#alpha', 0.1, 'alpha_lo');
  await sleep(1300);
  await drag('#tau', 0.75, 'tau_hi');
  await sleep(2000);

  mark('end');
  await sleep(1200);

  await ctx.close();
  await browser.close();

  const f = readdirSync(OUT).find((x) => x.endsWith('.webm'));
  renameSync(join(OUT, f), join(OUT, '07_webapp.webm'));
  writeFileSync(join(OUT, 'markers.json'), JSON.stringify(markers, null, 2));
  console.log('saved:', join(OUT, '07_webapp.webm'));
};

run().catch((e) => {
  console.error(e);
  process.exit(1);
});
