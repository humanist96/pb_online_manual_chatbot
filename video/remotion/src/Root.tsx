import React from 'react';
import {Composition, Series, Still} from 'remotion';
import {ensureFonts} from './fonts';
import {T} from './theme';
import timeline from './timeline.json';
import reportCaps from './captions/report.json';
import fullCaps from './captions/full.json';
import demoData from './data/demo.json';
import {Cue} from './components/Caption';
import {Seg} from './components/DemoClip';
import {Intro} from './scenes/Intro';
import {Problem} from './scenes/Problem';
import {Demo} from './scenes/Demo';
import {Arch} from './scenes/Arch';
import {Status} from './scenes/Status';
import {Outro} from './scenes/Outro';
import {CliTerm, DeployScene, PipelineTerm, TestTerm} from './scenes/TermScenes';
import {Thumb} from './scenes/Thumb';

type SceneDef = {id: string; dur: number};
type CapMap = Record<string, Cue[]>;

const sceneEl = (id: string, cues: Cue[], variant: 'report' | 'full') => {
  switch (id) {
    case 'intro':
      return <Intro cues={cues} />;
    case 'problem':
      return <Problem cues={cues} cardsAt={variant === 'report' ? 19 : 10} />;
    case 'demo':
      return <Demo cues={cues} segs={demoData[variant] as Seg[]} src={demoData.src} />;
    case 'arch':
      return <Arch cues={cues} boundaryAt={variant === 'report' ? 23.6 : 35.4} crumbAt={variant === 'full' ? 12.2 : 0} />;
    case 'pipeline':
      return <PipelineTerm cues={cues} />;
    case 'test':
      return <TestTerm cues={cues} />;
    case 'cli':
      return <CliTerm cues={cues} />;
    case 'deploy':
      return <DeployScene cues={cues} />;
    case 'status':
      return <Status cues={cues} />;
    case 'outro':
      return <Outro cues={cues} />;
    default:
      return null;
  }
};

const Movie: React.FC<{scenes: SceneDef[]; caps: CapMap; variant: 'report' | 'full'}> = ({scenes, caps, variant}) => {
  ensureFonts();
  return (
    <Series>
      {scenes.map((s) => (
        <Series.Sequence key={s.id} durationInFrames={Math.round(s.dur * T.fps)} name={s.id}>
          {sceneEl(s.id, (caps[s.id] ?? []) as Cue[], variant)}
        </Series.Sequence>
      ))}
    </Series>
  );
};

const total = (scenes: SceneDef[]) => scenes.reduce((a, s) => a + Math.round(s.dur * T.fps), 0);

export const Root: React.FC = () => (
  <>
    <Composition
      id="Report"
      component={Movie}
      durationInFrames={total(timeline.report)}
      fps={T.fps}
      width={T.w}
      height={T.h}
      defaultProps={{scenes: timeline.report, caps: reportCaps as CapMap, variant: 'report' as const}}
    />
    <Composition
      id="Full"
      component={Movie}
      durationInFrames={total(timeline.full)}
      fps={T.fps}
      width={T.w}
      height={T.h}
      defaultProps={{scenes: timeline.full, caps: fullCaps as CapMap, variant: 'full' as const}}
    />
    <Still id="Thumb" component={Thumb} width={T.w} height={T.h} />
  </>
);
