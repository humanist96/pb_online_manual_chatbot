import React from 'react';
import {AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig} from 'remotion';
import {Bg, CountUp, Kicker, Rise, SceneFade} from '../components/base';
import {Captions, Cue} from '../components/Caption';
import {T, GRAD} from '../theme';

const stats = [
  {n: 356, suffix: '', label: '인덱싱된 화면', sub: '계좌 부문 전체', c: T.brandSoft},
  {n: 4443, suffix: '', label: '검색 단위(청크)', sub: '경로 1개 = 근거 1개', c: T.blue},
  {n: 5, suffix: '/5', label: '회귀 테스트 통과', sub: '파서 골든값 검증', c: T.ok},
];

const deploy = ['Docker 이미지', 'systemd 유닛', '설치 스크립트 3종'];

export const Status: React.FC<{cues: Cue[]}> = ({cues}) => {
  const f = useCurrentFrame();
  const {fps} = useVideoConfig();
  const sec = f / fps;
  const row2 = interpolate(sec, [15.5, 16.3], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});

  return (
    <SceneFade>
      <Bg />
      <AbsoluteFill style={{padding: '90px 120px 0'}}>
        <Kicker at={4}>STATUS</Kicker>
        <div style={{marginTop: 26, marginBottom: 76, fontFamily: T.sans, fontWeight: 850, fontSize: 62, color: T.ink, letterSpacing: -1}}>
          지금 <span style={{color: T.brandSoft}}>바로 쓸 수 있는</span> 상태입니다
        </div>

        <div style={{display: 'flex', gap: 40, justifyContent: 'center'}}>
          {stats.map((s, i) => (
            <Rise key={s.label} at={40 + i * 12}>
              <div
                style={{
                  width: 440,
                  padding: '46px 30px 40px',
                  borderRadius: 24,
                  background: T.panel,
                  border: `1px solid ${T.line2}`,
                  textAlign: 'center',
                  boxShadow: '0 30px 70px -30px rgba(0,0,0,0.8)',
                }}
              >
                <div style={{fontFamily: T.sans, fontWeight: 900, fontSize: 104, color: s.c, letterSpacing: -2, lineHeight: 1}}>
                  <CountUp to={s.n} at={46 + i * 12} dur={45} suffix={s.suffix} />
                </div>
                <div style={{marginTop: 20, fontFamily: T.sans, fontWeight: 800, fontSize: 34, color: T.ink}}>{s.label}</div>
                <div style={{marginTop: 10, fontFamily: T.sans, fontWeight: 500, fontSize: 24, color: T.dim}}>{s.sub}</div>
              </div>
            </Rise>
          ))}
        </div>

        <div
          style={{
            marginTop: 64,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: 22,
            opacity: row2,
            transform: `translateY(${(1 - row2) * 24}px)`,
          }}
        >
          <span style={{fontFamily: T.sans, fontWeight: 800, fontSize: 27, color: T.ink2, marginRight: 8}}>배포 준비 완료</span>
          {deploy.map((d) => (
            <span
              key={d}
              style={{
                padding: '12px 26px',
                borderRadius: 999,
                background: T.brandTint,
                border: '1px solid rgba(245,130,31,0.4)',
                fontFamily: T.sans,
                fontWeight: 700,
                fontSize: 25,
                color: T.brandSoft,
              }}
            >
              {d}
            </span>
          ))}
          <span
            style={{
              padding: '12px 26px',
              borderRadius: 999,
              background: 'rgba(62,207,142,0.1)',
              border: '1px solid rgba(62,207,142,0.4)',
              fontFamily: T.sans,
              fontWeight: 700,
              fontSize: 25,
              color: T.ok,
            }}
          >
            오픈소스 스택 — 라이선스 비용 0원
          </span>
        </div>
      </AbsoluteFill>
      <Captions cues={cues} />
      <div style={{position: 'absolute', left: 0, right: 0, top: 0, height: 6, background: GRAD, opacity: 0.6}} />
    </SceneFade>
  );
};
