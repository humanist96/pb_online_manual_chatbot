/* captions/*.json + timeline.json → SRT (참고용 부산출물)
 * 사용: node scripts/make-srt.mjs Report|Full out.srt
 */
import {readFileSync, writeFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import {dirname, join} from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const comp = (process.argv[2] ?? 'Report').toLowerCase();
const out = process.argv[3] ?? `${comp}.srt`;

const timeline = JSON.parse(readFileSync(join(here, '../src/timeline.json'), 'utf8'));
const caps = JSON.parse(readFileSync(join(here, `../src/captions/${comp}.json`), 'utf8'));

const fmt = (sec) => {
  const ms = Math.round(sec * 1000);
  const h = String(Math.floor(ms / 3600000)).padStart(2, '0');
  const m = String(Math.floor((ms % 3600000) / 60000)).padStart(2, '0');
  const s = String(Math.floor((ms % 60000) / 1000)).padStart(2, '0');
  const t = String(ms % 1000).padStart(3, '0');
  return `${h}:${m}:${s},${t}`;
};

let offset = 0;
const entries = [];
for (const scene of timeline[comp]) {
  for (const c of caps[scene.id] ?? []) {
    entries.push({start: offset + c.t, end: offset + c.t + c.d, text: c.text.replaceAll('**', '')});
  }
  offset += scene.dur;
}
entries.sort((a, b) => a.start - b.start);
writeFileSync(out, entries.map((e, i) => `${i + 1}\n${fmt(e.start)} --> ${fmt(e.end)}\n${e.text}\n`).join('\n'));
console.log(`wrote ${out} (${entries.length} cues)`);
