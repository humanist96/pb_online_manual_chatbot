import React from 'react';
import {interpolate, OffthreadVideo, Sequence, staticFile, useCurrentFrame, useVideoConfig} from 'remotion';
import {T} from '../theme';

export type Seg = {
  from: number;  // 원본 영상 내 시작(초)
  dur: number;   // 보여줄 길이(초)
  zoom?: number; // 1 = 전체
  x?: number;    // 줌 중심 (0~1, 기본 0.5)
  y?: number;
  label?: string; // 좌상단 스텝 라벨
};

/* 캡처 원본(webm)을 세그먼트로 잘라 이어붙이고, 세그먼트별 줌/팬. 대기 구간은 자연스럽게 스킵. */
export const DemoClip: React.FC<{src: string; segs: Seg[]; playbackRate?: number}> = ({src, segs}) => {
  const {fps} = useVideoConfig();
  let acc = 0;
  return (
    <>
      {segs.map((s, i) => {
        const start = Math.round(acc * fps);
        const dur = Math.round(s.dur * fps);
        acc += s.dur;
        return (
          <Sequence key={i} from={start} durationInFrames={dur} layout="none">
            <SegView src={src} seg={s} />
          </Sequence>
        );
      })}
    </>
  );
};

const SegView: React.FC<{src: string; seg: Seg}> = ({src, seg}) => {
  const f = useCurrentFrame();
  const {fps, durationInFrames} = useVideoConfig();
  const zoom = seg.zoom ?? 1;
  // 세그먼트 안에서 은은한 줌 드리프트 (정적인 화면도 살아있게)
  const drift = interpolate(f, [0, durationInFrames], [0, 0.018], {extrapolateRight: 'clamp'});
  const z = zoom + drift * zoom;
  const cx = (seg.x ?? 0.5) * 100;
  const cy = (seg.y ?? 0.5) * 100;
  const fadeIn = interpolate(f, [0, 6], [0, 1], {extrapolateRight: 'clamp'});
  return (
    <div
      style={{
        position: 'absolute',
        inset: 0,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        opacity: fadeIn,
      }}
    >
      <div
        style={{
          width: 1744,
          height: 984,
          borderRadius: 20,
          overflow: 'hidden',
          border: `1px solid ${T.line2}`,
          boxShadow: '0 50px 110px -35px rgba(0,0,0,0.9), 0 0 0 1px rgba(255,255,255,0.04)',
          position: 'relative',
          background: '#f6f7f9',
        }}
      >
        <OffthreadVideo
          src={staticFile(src)}
          startFrom={Math.round(seg.from * fps)}
          muted
          style={{
            width: '100%',
            height: '100%',
            objectFit: 'cover',
            transform: `scale(${z})`,
            transformOrigin: `${cx}% ${cy}%`,
          }}
        />
        {seg.label ? (
          <div
            style={{
              position: 'absolute',
              top: 22,
              left: 22,
              padding: '10px 22px',
              borderRadius: 12,
              background: 'rgba(11,14,19,0.85)',
              border: `1px solid rgba(245,130,31,0.45)`,
              fontFamily: T.sans,
              fontWeight: 800,
              fontSize: 26,
              color: T.brandSoft,
              backdropFilter: 'blur(4px)',
            }}
          >
            {seg.label}
          </div>
        ) : null}
      </div>
    </div>
  );
};
