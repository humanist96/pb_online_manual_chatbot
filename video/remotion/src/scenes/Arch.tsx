import React from 'react';
import {AbsoluteFill} from 'remotion';
import {Bg, Kicker, SceneFade} from '../components/base';
import {Captions, Cue} from '../components/Caption';
import {Pipeline} from '../components/Diagram';
import {T} from '../theme';

export const Arch: React.FC<{cues: Cue[]; boundaryAt: number; crumbAt?: number}> = ({
  cues,
  boundaryAt,
  crumbAt = 0,
}) => (
  <SceneFade>
    <Bg />
    <AbsoluteFill style={{padding: '90px 120px 0', display: 'flex', flexDirection: 'column'}}>
      <Kicker at={4}>HOW IT WORKS</Kicker>
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
        매뉴얼 원문이 <span style={{color: T.brandSoft}}>그대로</span> 검색 인덱스가 됩니다
      </div>
      <div style={{flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'center', paddingBottom: 210}}>
        <Pipeline stagger={1.5} boundaryAt={boundaryAt} crumbAt={crumbAt} />
      </div>
    </AbsoluteFill>
    <Captions cues={cues} />
  </SceneFade>
);
