import React from 'react';
import {AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import {T, GRAD} from '../theme';

/* ── 배경: 다크 + 도트 그리드 + 오렌지 글로우 + 비네트 ── */
export const Bg: React.FC<{glow?: number}> = ({glow = 0.55}) => {
  const f = useCurrentFrame();
  const drift = Math.sin(f / 240) * 60;
  return (
    <AbsoluteFill style={{background: `linear-gradient(180deg, ${T.bg} 0%, ${T.bg2} 100%)`}}>
      <AbsoluteFill
        style={{
          backgroundImage: `radial-gradient(rgba(255,255,255,0.05) 1px, transparent 1px)`,
          backgroundSize: '34px 34px',
          maskImage: 'radial-gradient(ellipse 75% 65% at 50% 42%, black 30%, transparent 100%)',
          WebkitMaskImage: 'radial-gradient(ellipse 75% 65% at 50% 42%, black 30%, transparent 100%)',
        }}
      />
      <div
        style={{
          position: 'absolute',
          width: 1400,
          height: 900,
          left: 260 + drift,
          top: -430,
          background: `radial-gradient(ellipse at center, rgba(245,130,31,${0.13 * glow}) 0%, transparent 62%)`,
          filter: 'blur(10px)',
        }}
      />
      <AbsoluteFill
        style={{background: 'radial-gradient(ellipse 120% 100% at 50% 45%, transparent 55%, rgba(0,0,0,0.5) 100%)'}}
      />
    </AbsoluteFill>
  );
};

/* ── koscom 스파클 심볼 (web/index.html SVG 재사용) ── */
export const Spark: React.FC<{size?: number}> = ({size = 56}) => (
  <svg width={size} height={size} viewBox="0 0 28 28" fill="none">
    <defs>
      <linearGradient id="kAI" x1="0" y1="0" x2="28" y2="28" gradientUnits="userSpaceOnUse">
        <stop offset="0" stopColor="#ff9a3d" />
        <stop offset="1" stopColor="#e4670a" />
      </linearGradient>
    </defs>
    <rect x=".5" y=".5" width="27" height="27" rx="8.5" fill="url(#kAI)" />
    <rect x="1.6" y="1.6" width="24.8" height="12" rx="7.4" fill="#fff" opacity=".12" />
    <path
      d="M14 5.6C14.7 10.5 15.9 11.7 21.4 13C15.9 14.3 14.7 15.5 14 20.4 C13.3 15.5 12.1 14.3 6.6 13C12.1 11.7 13.3 10.5 14 5.6Z"
      fill="#fff"
    />
    <path
      d="M21.4 18.2C21.6 20 22 20.4 23.6 20.7C22 21 21.6 21.4 21.4 23.2 C21.2 21.4 20.8 21 19.2 20.7C20.8 20.4 21.2 20 21.4 18.2Z"
      fill="#fff"
      opacity=".85"
    />
  </svg>
);

/* ── 스프링 등장 래퍼 ── */
export const Rise: React.FC<{
  at?: number;
  children: React.ReactNode;
  dist?: number;
  style?: React.CSSProperties;
}> = ({at = 0, children, dist = 34, style}) => {
  const f = useCurrentFrame();
  const {fps} = useVideoConfig();
  const p = spring({frame: f - at, fps, config: {damping: 200, stiffness: 90}});
  return (
    <div style={{opacity: p, transform: `translateY(${(1 - p) * dist}px)`, ...style}}>
      {children}
    </div>
  );
};

/* ── 씬 페이드(인/아웃) ── */
export const SceneFade: React.FC<{children: React.ReactNode; out?: boolean}> = ({children, out = true}) => {
  const f = useCurrentFrame();
  const {durationInFrames} = useVideoConfig();
  const a = interpolate(f, [0, 10], [0, 1], {extrapolateRight: 'clamp'});
  const b = out ? interpolate(f, [durationInFrames - 10, durationInFrames - 1], [1, 0], {extrapolateLeft: 'clamp'}) : 1;
  return <AbsoluteFill style={{opacity: Math.min(a, b)}}>{children}</AbsoluteFill>;
};

/* ── 킥커(오렌지 라벨) + 타이틀 ── */
export const Kicker: React.FC<{children: React.ReactNode; at?: number}> = ({children, at = 0}) => (
  <Rise at={at}>
    <div
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 12,
        fontFamily: T.sans,
        fontWeight: 800,
        fontSize: 26,
        letterSpacing: 6,
        color: T.brandSoft,
        textTransform: 'uppercase',
      }}
    >
      <span style={{width: 44, height: 3, background: GRAD, borderRadius: 2}} />
      {children}
    </div>
  </Rise>
);

/* ── 숫자 카운트업 ── */
export const CountUp: React.FC<{to: number; at?: number; dur?: number; suffix?: string}> = ({
  to,
  at = 0,
  dur = 40,
  suffix = '',
}) => {
  const f = useCurrentFrame();
  const p = interpolate(f, [at, at + dur], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const eased = 1 - (1 - p) ** 3;
  return <>{Math.round(to * eased).toLocaleString()}{suffix}</>;
};
