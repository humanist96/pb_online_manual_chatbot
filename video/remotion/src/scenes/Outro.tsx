import React from 'react';
import {AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig} from 'remotion';
import {Bg, Rise, SceneFade, Spark} from '../components/base';
import {Captions, Cue} from '../components/Caption';
import {T, GRAD} from '../theme';

const steps = ['계좌 (완료)', '주문 · 출납', '원장 전 부문'];

export const Outro: React.FC<{cues: Cue[]}> = ({cues}) => {
  const f = useCurrentFrame();
  const {fps} = useVideoConfig();
  const sec = f / fps;

  return (
    <SceneFade out={false}>
      <Bg glow={0.85} />
      <AbsoluteFill style={{alignItems: 'center', justifyContent: 'center', paddingBottom: 140}}>
        {/* 로드맵 */}
        <div style={{display: 'flex', alignItems: 'center', gap: 26, marginBottom: 90}}>
          {steps.map((s, i) => {
            const at = 0.6 + i * 0.9;
            const p = interpolate(sec, [at, at + 0.5], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
            const active = i === 0;
            return (
              <React.Fragment key={s}>
                {i > 0 && (
                  <svg width="46" height="20" viewBox="0 0 46 20" style={{opacity: p}}>
                    <path d="M2 10h36m0 0l-7-6m7 6l-7 6" stroke={T.dim} strokeWidth="2.4" strokeLinecap="round" />
                  </svg>
                )}
                <span
                  style={{
                    padding: '16px 36px',
                    borderRadius: 999,
                    fontFamily: T.sans,
                    fontWeight: 800,
                    fontSize: 31,
                    color: active ? '#1a1006' : T.ink2,
                    background: active ? GRAD : T.panel,
                    border: `1px solid ${active ? 'transparent' : T.line2}`,
                    opacity: p,
                    transform: `translateY(${(1 - p) * 16}px)`,
                  }}
                >
                  {s}
                </span>
              </React.Fragment>
            );
          })}
        </div>

        <Rise at={110}>
          <div style={{display: 'flex', alignItems: 'center', gap: 30}}>
            <Spark size={88} />
            <div style={{fontFamily: T.sans, fontWeight: 900, fontSize: 84, color: T.ink, letterSpacing: -1.5}}>
              PB 매뉴얼 데스크
            </div>
          </div>
        </Rise>
        <Rise at={126}>
          <div style={{marginTop: 30, fontFamily: T.sans, fontWeight: 600, fontSize: 36, color: T.ink2}}>
            찾는 시간은 <span style={{color: T.brandSoft, fontWeight: 800}}>줄이고</span>, 답의 확신은{' '}
            <span style={{color: T.brandSoft, fontWeight: 800}}>높이고</span>
          </div>
        </Rise>
      </AbsoluteFill>
      <Captions cues={cues} />
    </SceneFade>
  );
};
