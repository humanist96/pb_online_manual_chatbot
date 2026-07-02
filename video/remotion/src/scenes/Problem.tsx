import React from 'react';
import {AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig} from 'remotion';
import {Bg, Kicker, SceneFade} from '../components/base';
import {Captions, Cue} from '../components/Caption';
import {ChatMock, TreeMock, ValueCards} from '../components/mocks';
import {T} from '../theme';

/* 전반: 기존 탐색(트리) vs 챗봇(우측) 대비 → 후반: 가치 카드 3장 */
export const Problem: React.FC<{cues: Cue[]; cardsAt: number}> = ({cues, cardsAt}) => {
  const f = useCurrentFrame();
  const {fps} = useVideoConfig();
  const sec = f / fps;
  const phaseB = interpolate(sec, [cardsAt - 0.7, cardsAt], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  return (
    <SceneFade>
      <Bg />
      {/* Phase A: 대비 */}
      <AbsoluteFill style={{opacity: 1 - phaseB, padding: '90px 120px 0'}}>
        <Kicker at={4}>WHY</Kicker>
        <div
          style={{
            marginTop: 26,
            fontFamily: T.sans,
            fontWeight: 850,
            fontSize: 62,
            color: T.ink,
            letterSpacing: -1,
          }}
        >
          매뉴얼은 있는데, <span style={{color: T.brandSoft}}>찾기</span>가 일이었습니다
        </div>
        <div style={{display: 'flex', gap: 90, marginTop: 70, alignItems: 'flex-start', justifyContent: 'center'}}>
          <div>
            <TreeMock at={1.2} />
            <div style={{textAlign: 'center', marginTop: 22, fontFamily: T.sans, fontSize: 25, fontWeight: 700, color: T.dim}}>
              기존 — 트리 탐색의 반복
            </div>
          </div>
          <div style={{paddingTop: 60, fontFamily: T.sans, fontSize: 54, color: T.faint, fontWeight: 300}}>vs</div>
          <div>
            <ChatMock at={2.4} />
            <div style={{textAlign: 'center', marginTop: 22, fontFamily: T.sans, fontSize: 25, fontWeight: 700, color: T.brandSoft}}>
              이제 — 질문 한 줄
            </div>
          </div>
        </div>
      </AbsoluteFill>

      {/* Phase B: 가치 3 */}
      <AbsoluteFill style={{opacity: phaseB, padding: '110px 120px 0'}}>
        <div style={{textAlign: 'center', marginBottom: 84}}>
          <div style={{fontFamily: T.sans, fontWeight: 850, fontSize: 64, color: T.ink, letterSpacing: -1}}>
            세 가지 약속
          </div>
        </div>
        <ValueCards at={cardsAt + 0.5} />
      </AbsoluteFill>

      <Captions cues={cues} />
    </SceneFade>
  );
};
