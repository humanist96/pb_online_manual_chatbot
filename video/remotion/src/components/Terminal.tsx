import React from 'react';
import {interpolate, useCurrentFrame, useVideoConfig} from 'remotion';
import {T} from '../theme';

export type TermStep = {
  cmd: string;       // 타이핑되는 명령
  out: string;       // 출력 (여러 줄)
  typeAt: number;    // 타이핑 시작(초, 씬 기준)
  outAt: number;     // 출력 표시(초)
  outLines?: number; // 출력을 몇 줄씩 순차 공개할지 (기본: 한 번에)
};

const CPS = 28; // 타이핑 속도 (chars/sec)

/* 출력 안 하이라이트: ✓, PASS, 숫자 강조 등 간단 톤업 */
const colorize = (line: string, i: number) => {
  let color = '#c7d0dc';
  let fontWeight: number | undefined;
  if (/^PASS|✓|✅/.test(line.trim())) color = T.ok;
  if (/passed|완료|wrote /.test(line)) {
    color = T.ok;
    fontWeight = 700;
  }
  if (/^\[S\d+\]/.test(line.trim())) color = T.brandSoft;
  if (/^\s*\(로컬 LLM/.test(line)) color = T.dim;
  return (
    <div key={i} style={{color, fontWeight, whiteSpace: 'pre-wrap', wordBreak: 'break-all'}}>
      {line || ' '}
    </div>
  );
};

export const Terminal: React.FC<{
  steps: TermStep[];
  title?: string;
  width?: number;
  height?: number;
  fontSize?: number;
}> = ({steps, title = 'kevin@pb-server: ~/pb-chatbot', width = 1560, height = 760, fontSize = 27}) => {
  const f = useCurrentFrame();
  const {fps} = useVideoConfig();
  const sec = f / fps;

  const blocks: React.ReactNode[] = [];
  steps.forEach((s, si) => {
    if (sec < s.typeAt) return;
    const typed = Math.min(s.cmd.length, Math.floor((sec - s.typeAt) * CPS));
    const done = typed >= s.cmd.length;
    blocks.push(
      <div key={`c${si}`} style={{display: 'flex', gap: 14, marginTop: si ? 26 : 0}}>
        <span style={{color: T.ok, fontWeight: 700}}>❯</span>
        <span style={{color: T.ink, whiteSpace: 'pre-wrap', wordBreak: 'break-all'}}>
          {s.cmd.slice(0, typed)}
          {!done && <span style={{opacity: Math.round(sec * 2.4) % 2 ? 1 : 0.1, color: T.brandSoft}}>▊</span>}
        </span>
      </div>,
    );
    if (sec >= s.outAt) {
      const lines = s.out.split('\n');
      const per = s.outLines ?? lines.length;
      const shown = Math.min(lines.length, Math.ceil((sec - s.outAt) * per * 3 + 1));
      blocks.push(
        <div key={`o${si}`} style={{marginTop: 10}}>
          {lines.slice(0, shown).map(colorize)}
        </div>,
      );
    }
  });

  // 커서가 항상 보이도록 내용이 넘치면 위로 스크롤
  const totalLines = steps.reduce((acc, s) => {
    if (sec < s.typeAt) return acc;
    let n = 1.6;
    if (sec >= s.outAt) {
      const lines = s.out.split('\n');
      n += Math.min(lines.length, Math.ceil((sec - s.outAt) * (s.outLines ?? lines.length) * 3 + 1));
    }
    return acc + n;
  }, 0);
  const lineH = fontSize * 1.52;
  const visible = Math.floor((height - 120) / lineH);
  const scroll = Math.max(0, (totalLines - visible) * lineH);

  const appear = interpolate(f, [0, 12], [0, 1], {extrapolateRight: 'clamp'});

  return (
    <div
      style={{
        width,
        height,
        borderRadius: 18,
        background: '#0d1117',
        border: `1px solid ${T.line2}`,
        boxShadow: '0 40px 90px -30px rgba(0,0,0,0.85), 0 0 0 1px rgba(255,255,255,0.03)',
        overflow: 'hidden',
        opacity: appear,
        transform: `scale(${0.985 + appear * 0.015})`,
      }}
    >
      <div
        style={{
          height: 54,
          display: 'flex',
          alignItems: 'center',
          gap: 10,
          padding: '0 22px',
          background: '#161c26',
          borderBottom: `1px solid ${T.line}`,
        }}
      >
        {['#ff5f57', '#febc2e', '#28c840'].map((c) => (
          <span key={c} style={{width: 15, height: 15, borderRadius: 8, background: c, opacity: 0.9}} />
        ))}
        <span
          style={{
            flex: 1,
            textAlign: 'center',
            fontFamily: T.mono,
            fontSize: 20,
            color: T.dim,
            marginRight: 60,
          }}
        >
          {title}
        </span>
      </div>
      <div style={{padding: '30px 34px', fontFamily: T.mono, fontSize, lineHeight: 1.52, overflow: 'hidden', height: height - 54}}>
        <div style={{transform: `translateY(-${scroll}px)`}}>{blocks}</div>
      </div>
    </div>
  );
};

/* 터미널 위 명령 콜아웃 배지 — "지금 실행 중인 명령" */
export const CmdBadge: React.FC<{cmd: string; label: string; at?: number}> = ({cmd, label, at = 0}) => {
  const f = useCurrentFrame();
  const o = interpolate(f, [at, at + 10], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  return (
    <div
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 16,
        padding: '12px 24px',
        borderRadius: 14,
        background: T.brandTint,
        border: `1px solid rgba(245,130,31,0.4)`,
        opacity: o,
        transform: `translateY(${(1 - o) * -8}px)`,
      }}
    >
      <span style={{fontFamily: T.sans, fontWeight: 800, fontSize: 24, color: T.brandSoft}}>{label}</span>
      <code style={{fontFamily: T.mono, fontSize: 24, color: T.ink}}>{cmd}</code>
    </div>
  );
};
