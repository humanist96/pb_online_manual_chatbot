import React from 'react';
import {AbsoluteFill} from 'remotion';
import {Bg, SceneFade} from '../components/base';
import {Captions, Cue} from '../components/Caption';
import {DemoClip, Seg} from '../components/DemoClip';

export const Demo: React.FC<{cues: Cue[]; segs: Seg[]; src: string}> = ({cues, segs, src}) => (
  <SceneFade>
    <Bg glow={0.3} />
    <AbsoluteFill>
      <DemoClip src={src} segs={segs} />
    </AbsoluteFill>
    <Captions cues={cues} />
  </SceneFade>
);
