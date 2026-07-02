import React from 'react';
import {AbsoluteFill} from 'remotion';
import {Bg, Spark} from '../components/base';
import {ensureFonts} from '../fonts';
import {T, GRAD} from '../theme';

/* 썸네일 (Still) */
export const Thumb: React.FC = () => {
  ensureFonts();
  return (
    <AbsoluteFill>
      <Bg glow={1} />
      <AbsoluteFill style={{alignItems: 'center', justifyContent: 'center'}}>
        <div style={{display: 'flex', alignItems: 'center', gap: 34, marginBottom: 44}}>
          <Spark size={110} />
          <div style={{fontFamily: T.sans, fontWeight: 900, fontSize: 120, color: T.ink, letterSpacing: -2.5}}>
            PB 매뉴얼 데스크
          </div>
        </div>
        <div style={{fontFamily: T.sans, fontWeight: 700, fontSize: 46, color: T.ink2, marginBottom: 60}}>
          원장 매뉴얼에게 <span style={{color: T.brandSoft, fontWeight: 900}}>직접 물어보세요</span>
        </div>
        <div style={{display: 'flex', gap: 24}}>
          {['356개 화면', '근거 있는 답변', '100% 사내 서버'].map((b) => (
            <span
              key={b}
              style={{
                padding: '16px 38px',
                borderRadius: 999,
                background: T.panel,
                border: `1.5px solid ${T.line2}`,
                fontFamily: T.sans,
                fontWeight: 800,
                fontSize: 34,
                color: T.ink,
              }}
            >
              {b}
            </span>
          ))}
        </div>
      </AbsoluteFill>
      <div style={{position: 'absolute', left: 0, right: 0, bottom: 0, height: 14, background: GRAD}} />
    </AbsoluteFill>
  );
};
