import React from 'react';
import {interpolate, useCurrentFrame, useVideoConfig} from 'remotion';
import {T, GRAD} from '../theme';

type Node = {label: string; sub?: string; color?: string};

const NODES: Node[] = [
  {label: '매뉴얼 HTML', sub: 'RoboHelp 원문 356화면'},
  {label: '구조 보존 파싱', sub: '계층 경로(브레드크럼) 유지', color: T.brandSoft},
  {label: '청크 4,443', sub: '경로 1개 = 근거 1개'},
  {label: '하이브리드 검색', sub: '의미(FAISS) + 키워드(BM25)', color: T.blue},
  {label: '답변 생성', sub: '검색된 근거 안에서만', color: T.ok},
];

/* 파이프라인 다이어그램 — 노드 순차 점등 + 커넥터 펄스 + 사내망 테두리 */
export const Pipeline: React.FC<{
  stagger?: number;   // 노드 간 등장 간격(초)
  boundaryAt?: number; // '사내 서버' 경계 강조 시점(초)
  crumbAt?: number;   // 브레드크럼 예시 표시 시점(초, 0이면 숨김)
}> = ({stagger = 1.6, boundaryAt = 99, crumbAt = 0}) => {
  const f = useCurrentFrame();
  const {fps} = useVideoConfig();
  const sec = f / fps;

  const W = 1640;
  const nodeW = 288;
  const gap = (W - nodeW * NODES.length - 80) / (NODES.length - 1);

  const bAppear = interpolate(sec, [boundaryAt, boundaryAt + 0.8], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  return (
    <div style={{position: 'relative', width: W, margin: '0 auto'}}>
      {/* 사내 서버 경계 */}
      <div
        style={{
          position: 'absolute',
          inset: '-70px -30px',
          borderRadius: 30,
          border: `2px dashed rgba(62,207,142,${0.65 * bAppear})`,
          background: `rgba(62,207,142,${0.05 * bAppear})`,
          opacity: bAppear,
        }}
      >
        <div
          style={{
            position: 'absolute',
            top: -22,
            left: 40,
            padding: '6px 20px 8px',
            borderRadius: 12,
            background: '#0f1721',
            border: '1px solid rgba(62,207,142,0.5)',
            fontFamily: T.sans,
            fontWeight: 800,
            fontSize: 26,
            color: T.ok,
            display: 'flex',
            gap: 10,
            alignItems: 'center',
          }}
        >
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none">
            <rect x="4" y="10" width="16" height="10" rx="2.5" stroke={T.ok} strokeWidth="2" />
            <path d="M8 10V7a4 4 0 0 1 8 0v3" stroke={T.ok} strokeWidth="2" />
          </svg>
          사내 서버 안에서 완결 — 데이터 외부 반출 없음
        </div>
      </div>

      <div style={{display: 'flex', alignItems: 'stretch', padding: '0 40px'}}>
        {NODES.map((n, i) => {
          const at = i * stagger;
          const p = interpolate(sec, [at, at + 0.55], [0, 1], {
            extrapolateLeft: 'clamp',
            extrapolateRight: 'clamp',
          });
          const accent = n.color ?? T.ink2;
          return (
            <React.Fragment key={i}>
              {i > 0 && (
                <div style={{width: gap, display: 'flex', alignItems: 'center', position: 'relative'}}>
                  <Connector show={sec >= at - stagger * 0.25} pulse={(sec * 0.8 + i * 0.37) % 1} />
                </div>
              )}
              <div
                style={{
                  width: nodeW,
                  padding: '26px 22px 24px',
                  borderRadius: 18,
                  background: T.panel,
                  border: `1px solid ${p > 0.9 ? `${accent}55` : T.line}`,
                  boxShadow: p > 0.9 ? `0 20px 44px -22px ${accent}40` : 'none',
                  opacity: p,
                  transform: `translateY(${(1 - p) * 26}px)`,
                  textAlign: 'center',
                }}
              >
                <div style={{fontFamily: T.sans, fontWeight: 800, fontSize: 30, color: T.ink, marginBottom: 8}}>
                  {n.label}
                </div>
                <div style={{fontFamily: T.sans, fontWeight: 500, fontSize: 20.5, color: T.dim, lineHeight: 1.4, wordBreak: 'keep-all'}}>
                  {n.sub}
                </div>
              </div>
            </React.Fragment>
          );
        })}
      </div>

      {/* 브레드크럼 예시 */}
      {crumbAt > 0 && (
        <Crumb
          at={crumbAt}
          path={['지점계좌서비스약정등록내역', '화면설명', '단계2', '서비스종류', 'SMS통보 : 문자 통보 서비스']}
        />
      )}
    </div>
  );
};

const Connector: React.FC<{show: boolean; pulse: number}> = ({show, pulse}) => (
  <div style={{width: '100%', height: 3, background: show ? T.line2 : 'transparent', position: 'relative', borderRadius: 2}}>
    {show && (
      <div
        style={{
          position: 'absolute',
          left: `${pulse * 86}%`,
          top: -3.5,
          width: 26,
          height: 10,
          borderRadius: 6,
          background: GRAD,
          filter: 'blur(0.5px)',
          opacity: 0.95,
        }}
      />
    )}
  </div>
);

const Crumb: React.FC<{at: number; path: string[]}> = ({at, path}) => {
  const f = useCurrentFrame();
  const {fps} = useVideoConfig();
  const sec = f / fps;
  const o = interpolate(sec, [at, at + 0.6], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  return (
    <div
      style={{
        marginTop: 120,
        display: 'flex',
        justifyContent: 'center',
        alignItems: 'center',
        gap: 12,
        opacity: o,
        transform: `translateY(${(1 - o) * 18}px)`,
        flexWrap: 'wrap',
      }}
    >
      <span
        style={{
          fontFamily: T.sans,
          fontSize: 23,
          fontWeight: 700,
          color: T.dim,
          marginRight: 8,
        }}
      >
        청크 예시
      </span>
      {path.map((seg, i) => {
        const segAt = at + 0.3 + i * 0.5;
        const p = interpolate(sec, [segAt, segAt + 0.4], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
        const last = i === path.length - 1;
        return (
          <React.Fragment key={i}>
            {i > 0 && <span style={{color: T.faint, fontSize: 26, opacity: p}}>›</span>}
            <span
              style={{
                padding: '9px 18px',
                borderRadius: 11,
                fontFamily: T.sans,
                fontWeight: last ? 800 : 600,
                fontSize: 24,
                color: last ? T.brandSoft : T.ink2,
                background: last ? T.brandTint : T.panel,
                border: `1px solid ${last ? 'rgba(245,130,31,0.45)' : T.line}`,
                opacity: p,
                transform: `translateY(${(1 - p) * 10}px)`,
              }}
            >
              {seg}
            </span>
          </React.Fragment>
        );
      })}
    </div>
  );
};
