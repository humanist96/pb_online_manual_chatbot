import React from 'react';
import {interpolate, useCurrentFrame, useVideoConfig} from 'remotion';
import {T} from '../theme';

/* ── RoboHelp 트리 탐색의 답답함 목업 ── */
const ROWS = [
  {d: 0, t: '계좌', open: true},
  {d: 1, t: '계좌개설'},
  {d: 1, t: '계좌정보관리', open: true},
  {d: 2, t: '계좌정보변경'},
  {d: 2, t: '고객명의변경'},
  {d: 2, t: '지점계좌서비스…', hit: true},
  {d: 1, t: '약정관리', open: true},
  {d: 2, t: '선물연계약정'},
  {d: 2, t: 'SMS서비스신청'},
  {d: 1, t: '출력물관리'},
  {d: 0, t: '주문'},
  {d: 0, t: '출납'},
];

export const TreeMock: React.FC<{at?: number}> = ({at = 0}) => {
  const f = useCurrentFrame();
  const {fps} = useVideoConfig();
  const sec = f / fps - at;
  // 커서가 행 사이를 헤매는 궤적
  const seq = [1, 3, 7, 4, 9, 2, 8, 5];
  const step = Math.max(0, Math.min(seq.length - 1, Math.floor(sec / 1.1)));
  const cursorRow = seq[step];
  return (
    <div
      style={{
        width: 620,
        borderRadius: 18,
        background: '#f6f7f9',
        border: '1px solid #d7dbe2',
        boxShadow: '0 40px 80px -30px rgba(0,0,0,0.8)',
        overflow: 'hidden',
        fontFamily: T.sans,
      }}
    >
      <div style={{height: 52, background: '#eceef2', borderBottom: '1px solid #d7dbe2', display: 'flex', alignItems: 'center', padding: '0 22px', fontSize: 21, fontWeight: 700, color: '#4b5361'}}>
        PowerBASE 온라인 매뉴얼 — 목차
      </div>
      <div style={{padding: '16px 10px 20px'}}>
        {ROWS.map((r, i) => {
          const isCur = i === cursorRow;
          return (
            <div
              key={i}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 10,
                padding: '9px 14px',
                paddingLeft: 16 + r.d * 34,
                borderRadius: 9,
                background: isCur ? '#e2e6ec' : 'transparent',
                transition: 'background 0.2s',
              }}
            >
              <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
                {r.open !== undefined ? (
                  <path d={r.open ? 'M5 8l5 5 5-5' : 'M8 5l5 5-5 5'} stroke="#8a93a1" strokeWidth="2" strokeLinecap="round" />
                ) : (
                  <rect x="4" y="5" width="12" height="10" rx="2" stroke="#aeb5c0" strokeWidth="1.8" />
                )}
              </svg>
              <span style={{fontSize: 21.5, color: r.hit ? '#c9610a' : '#4b5361', fontWeight: r.hit ? 700 : 500}}>
                {r.t}
              </span>
              {isCur && (
                <svg width="22" height="22" viewBox="0 0 24 24" style={{marginLeft: 'auto'}}>
                  <path d="M5 3l14 8-6 1.5L9.5 19 5 3z" fill="#191c20" stroke="#fff" strokeWidth="1.2" />
                </svg>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
};

/* ── 가치 카드 3종 ── */
const Icons = {
  chat: (
    <svg width="52" height="52" viewBox="0 0 24 24" fill="none">
      <path d="M4 6a3 3 0 0 1 3-3h10a3 3 0 0 1 3 3v7a3 3 0 0 1-3 3H9l-4 4v-4a3 3 0 0 1-1-2.2V6z" stroke={T.brandSoft} strokeWidth="1.7" strokeLinejoin="round" />
      <path d="M8 8.5h8M8 11.5h5" stroke={T.brandSoft} strokeWidth="1.7" strokeLinecap="round" />
    </svg>
  ),
  cite: (
    <svg width="52" height="52" viewBox="0 0 24 24" fill="none">
      <rect x="3" y="4" width="18" height="16" rx="3" stroke={T.blue} strokeWidth="1.7" />
      <path d="M7 9h10M7 12.5h7" stroke={T.blue} strokeWidth="1.7" strokeLinecap="round" />
      <rect x="12.5" y="15" width="6" height="3.4" rx="1.6" fill={T.blue} opacity="0.9" />
    </svg>
  ),
  lock: (
    <svg width="52" height="52" viewBox="0 0 24 24" fill="none">
      <path d="M12 3l7 3v5c0 4.6-3 8-7 10-4-2-7-5.4-7-10V6l7-3z" stroke={T.ok} strokeWidth="1.7" strokeLinejoin="round" />
      <path d="M9.4 11.8l2 2 3.4-3.8" stroke={T.ok} strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  ),
};

export const ValueCards: React.FC<{at: number}> = ({at}) => {
  const f = useCurrentFrame();
  const {fps} = useVideoConfig();
  const sec = f / fps;
  const cards = [
    {icon: Icons.chat, t: '자연어로 질문', s: '화면 이름을 몰라도\n의미로 찾아줍니다', c: T.brandSoft},
    {icon: Icons.cite, t: '근거 있는 답변', s: '모든 문장에 매뉴얼\n출처가 붙습니다', c: T.blue},
    {icon: Icons.lock, t: '완전 로컬', s: '폐쇄망 안에서 동작\n데이터 유출 없음', c: T.ok},
  ];
  return (
    <div style={{display: 'flex', gap: 44, justifyContent: 'center'}}>
      {cards.map((c, i) => {
        const cAt = at + i * 1.1;
        const p = interpolate(sec, [cAt, cAt + 0.6], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
        return (
          <div
            key={i}
            style={{
              width: 400,
              padding: '44px 40px 40px',
              borderRadius: 22,
              background: T.panel,
              border: `1px solid ${T.line2}`,
              boxShadow: `0 30px 70px -30px rgba(0,0,0,0.8)`,
              textAlign: 'center',
              opacity: p,
              transform: `translateY(${(1 - p) * 40}px) scale(${0.96 + p * 0.04})`,
            }}
          >
            <div
              style={{
                width: 96,
                height: 96,
                margin: '0 auto 26px',
                borderRadius: 24,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                background: `${c.c}18`,
                border: `1px solid ${c.c}40`,
              }}
            >
              {c.icon}
            </div>
            <div style={{fontFamily: T.sans, fontWeight: 800, fontSize: 38, color: T.ink, marginBottom: 14}}>
              <span style={{color: c.c, marginRight: 10}}>{i + 1}</span>
              {c.t}
            </div>
            <div style={{fontFamily: T.sans, fontWeight: 500, fontSize: 26, color: T.ink2, lineHeight: 1.5, whiteSpace: 'pre-line'}}>
              {c.s}
            </div>
          </div>
        );
      })}
    </div>
  );
};

/* ── 챗 목업(문제 씬 우측): 질문 타이핑 → 답변 + 출처 칩 ── */
export const ChatMock: React.FC<{at?: number}> = ({at = 0}) => {
  const f = useCurrentFrame();
  const {fps} = useVideoConfig();
  const sec = f / fps - at;
  const q = 'SMS 일괄 발송은 어디서 하나요?';
  const typed = Math.max(0, Math.min(q.length, Math.floor(sec * 11)));
  const showA = sec > q.length / 11 + 0.8;
  const aP = interpolate(sec, [q.length / 11 + 0.8, q.length / 11 + 1.4], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  return (
    <div style={{width: 680, fontFamily: T.sans}}>
      <div style={{display: 'flex', justifyContent: 'flex-end', marginBottom: 22}}>
        <div
          style={{
            padding: '18px 28px',
            borderRadius: '20px 20px 6px 20px',
            background: '#20242b',
            border: `1px solid ${T.line2}`,
            fontSize: 27,
            fontWeight: 600,
            color: T.ink,
            minHeight: 34,
          }}
        >
          {q.slice(0, typed)}
          {typed < q.length && <span style={{color: T.brandSoft}}>▏</span>}
        </div>
      </div>
      {showA && (
        <div
          style={{
            padding: '26px 30px',
            borderRadius: '20px 20px 20px 6px',
            background: T.panel,
            border: `1px solid ${T.line2}`,
            opacity: aP,
            transform: `translateY(${(1 - aP) * 16}px)`,
          }}
        >
          <div style={{fontSize: 27, color: T.ink2, lineHeight: 1.6}}>
            <b style={{color: T.ink}}>SMS발송[2797]</b> 화면에서 최대 50건까지 발송할 수 있습니다{' '}
            <span
              style={{
                display: 'inline-block',
                padding: '2px 12px 4px',
                borderRadius: 8,
                background: T.brandTint,
                border: '1px solid rgba(245,130,31,0.45)',
                color: T.brandSoft,
                fontWeight: 800,
                fontSize: 22,
              }}
            >
              S1
            </span>
          </div>
          <div style={{marginTop: 18, paddingTop: 16, borderTop: `1px solid ${T.line}`, fontSize: 21, color: T.dim}}>
            근거 · SMS서비스 신청(해지)내역 조회 › 질문보기
          </div>
        </div>
      )}
    </div>
  );
};
