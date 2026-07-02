import React from 'react';
import {AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import {Bg, Rise, SceneFade, Spark} from '../components/base';
import {Captions, Cue} from '../components/Caption';
import {T, GRAD} from '../theme';

const badges = ['356개 화면', '4,443개 검색 단위', '100% 로컬 · 오프라인'];

export const Intro: React.FC<{cues: Cue[]}> = ({cues}) => {
  const f = useCurrentFrame();
  const {fps} = useVideoConfig();
  const logo = spring({frame: f - 8, fps, config: {damping: 14, stiffness: 120, mass: 0.8}});
  const lineW = interpolate(f, [30, 55], [0, 320], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});

  return (
    <SceneFade>
      <Bg glow={0.9} />
      <AbsoluteFill style={{alignItems: 'center', justifyContent: 'center', paddingBottom: 120}}>
        <div style={{transform: `scale(${logo})`, marginBottom: 40}}>
          <Spark size={132} />
        </div>
        <Rise at={16}>
          <div style={{fontFamily: T.sans, fontWeight: 900, fontSize: 108, color: T.ink, letterSpacing: -2}}>
            PB 매뉴얼 데스크
          </div>
        </Rise>
        <div style={{width: lineW, height: 4, background: GRAD, borderRadius: 3, margin: '34px 0'}} />
        <Rise at={34}>
          <div style={{fontFamily: T.sans, fontWeight: 600, fontSize: 40, color: T.ink2}}>
            PowerBASE 계좌 매뉴얼 <span style={{color: T.brandSoft, fontWeight: 800}}>RAG 챗봇</span>
          </div>
        </Rise>
        <div style={{display: 'flex', gap: 22, marginTop: 62}}>
          {badges.map((b, i) => (
            <Rise key={b} at={56 + i * 9}>
              <div
                style={{
                  padding: '14px 32px',
                  borderRadius: 999,
                  border: `1px solid ${T.line2}`,
                  background: 'rgba(255,255,255,0.04)',
                  fontFamily: T.sans,
                  fontWeight: 700,
                  fontSize: 29,
                  color: T.ink2,
                }}
              >
                {b}
              </div>
            </Rise>
          ))}
        </div>
      </AbsoluteFill>
      <Captions cues={cues} />
    </SceneFade>
  );
};
