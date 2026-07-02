import React from 'react';
import {interpolate, useCurrentFrame, useVideoConfig} from 'remotion';
import {T} from '../theme';

export type Cue = {t: number; d: number; text: string};

/* **강조** → 브랜드 컬러 볼드 */
const rich = (s: string) =>
  s.split(/(\*\*[^*]+\*\*)/g).map((part, i) =>
    part.startsWith('**') ? (
      <span key={i} style={{color: T.brandSoft, fontWeight: 800}}>
        {part.slice(2, -2)}
      </span>
    ) : (
      <React.Fragment key={i}>{part}</React.Fragment>
    ),
  );

/* 씬 로컬 자막 트랙 — 하단 고정, 페이드+살짝 상승. 유튜브 가독 기준(44px, 스크림). */
export const Captions: React.FC<{cues: Cue[]}> = ({cues}) => {
  const f = useCurrentFrame();
  const {fps} = useVideoConfig();
  const sec = f / fps;
  const cue = cues.find((c) => sec >= c.t && sec < c.t + c.d);
  if (!cue) return null;
  const local = sec - cue.t;
  const inO = interpolate(local, [0, 0.22], [0, 1], {extrapolateRight: 'clamp'});
  const outO = interpolate(local, [cue.d - 0.25, cue.d], [1, 0], {extrapolateLeft: 'clamp'});
  const o = Math.min(inO, outO);
  return (
    <div
      style={{
        position: 'absolute',
        left: 0,
        right: 0,
        bottom: 64,
        display: 'flex',
        justifyContent: 'center',
        pointerEvents: 'none',
      }}
    >
      <div
        style={{
          maxWidth: 1520,
          padding: '18px 44px',
          borderRadius: 18,
          background: 'rgba(8,10,14,0.78)',
          border: `1px solid ${T.line}`,
          boxShadow: '0 18px 50px -20px rgba(0,0,0,0.8)',
          fontFamily: T.sans,
          fontWeight: 650,
          fontSize: 44,
          lineHeight: 1.4,
          color: T.ink,
          textAlign: 'center',
          opacity: o,
          transform: `translateY(${(1 - o) * 10}px)`,
          backdropFilter: 'blur(6px)',
          WebkitBackdropFilter: 'blur(6px)',
        }}
      >
        {rich(cue.text)}
      </div>
    </div>
  );
};
