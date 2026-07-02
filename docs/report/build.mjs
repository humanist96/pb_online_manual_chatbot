/* 임원 보고 PDF 빌드 — content/*.html 조립 → Playwright page.pdf()
 * 사용: node build.mjs [chrome-headless-shell 경로]
 * 산출: out/report.html (중간물), out/PB매뉴얼데스크_개발보고_2026-07.pdf
 * 완전 자립형: 폰트·이미지 전부 로컬 임베드, 외부 리소스 참조 없음(폐쇄망 열람 가능)
 */
import {chromium} from 'playwright-core';
import {readFileSync, readdirSync, writeFileSync, mkdirSync} from 'node:fs';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {dirname, join} from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const CHROME = process.argv[2] ?? process.env.CHROME;
if (!CHROME) {
  console.error('usage: node build.mjs <chrome-headless-shell path>');
  process.exit(1);
}

const css = readFileSync(join(here, 'template/print.css'), 'utf8');
const pages = readdirSync(join(here, 'content'))
  .filter((f) => f.endsWith('.html'))
  .sort()
  .map((f) => readFileSync(join(here, 'content', f), 'utf8'))
  .join('\n');

const html = `<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8"/>
<title>PB 매뉴얼 데스크 — 개발 보고</title>
<style>${css}</style>
</head><body>${pages}</body></html>`;

mkdirSync(join(here, 'out'), {recursive: true});
const htmlPath = join(here, 'out/report.html');
// 이미지 상대경로(images/...)가 리포트 루트 기준이므로 base 태그로 고정
writeFileSync(htmlPath, html.replace('<head>', `<head><base href="${pathToFileURL(here + '/').href}"/>`));

const browser = await chromium.launch({executablePath: CHROME, args: ['--no-sandbox']});
const page = await browser.newPage();
await page.goto(pathToFileURL(htmlPath).href, {waitUntil: 'networkidle'});
await page.evaluate(() => document.fonts.ready);
const out = join(here, 'out/PB매뉴얼데스크_개발보고_2026-07.pdf');
await page.pdf({path: out, format: 'A4', printBackground: true, margin: {top: 0, bottom: 0, left: 0, right: 0}});
await browser.close();
console.log('wrote', out);
