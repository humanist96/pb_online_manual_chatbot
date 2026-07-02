import React from 'react';
import {AbsoluteFill} from 'remotion';
import {Bg, Kicker, SceneFade} from '../components/base';
import {Captions, Cue} from '../components/Caption';
import {CmdBadge, Terminal, TermStep} from '../components/Terminal';
import {T} from '../theme';
import {CHUNKS_OUT, CLI_OUT, CLI_Q, INDEX_OUT, PARSE_OUT, TEST_OUT} from '../data/term';

const Layout: React.FC<{
  kicker: string;
  title: React.ReactNode;
  steps: TermStep[];
  cues: Cue[];
  badge?: {cmd: string; label: string; at: number};
  fontSize?: number;
  height?: number;
}> = ({kicker, title, steps, cues, badge, fontSize, height}) => (
  <SceneFade>
    <Bg />
    <AbsoluteFill style={{padding: '80px 120px 0'}}>
      <div style={{display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between', marginBottom: 40}}>
        <div>
          <Kicker at={4}>{kicker}</Kicker>
          <div style={{marginTop: 22, fontFamily: T.sans, fontWeight: 850, fontSize: 54, color: T.ink, letterSpacing: -1}}>
            {title}
          </div>
        </div>
        {badge ? <CmdBadge cmd={badge.cmd} label={badge.label} at={badge.at} /> : null}
      </div>
      <div style={{display: 'flex', justifyContent: 'center'}}>
        <Terminal steps={steps} fontSize={fontSize} height={height} />
      </div>
    </AbsoluteFill>
    <Captions cues={cues} />
  </SceneFade>
);

/* 파이프라인 빌드: parse → to_chunks → build_index */
export const PipelineTerm: React.FC<{cues: Cue[]}> = ({cues}) => (
  <Layout
    kicker="HANDS-ON ①"
    title={<>한 줄씩 — 원문이 <span style={{color: T.brandSoft}}>인덱스</span>가 되기까지</>}
    badge={{cmd: 'make build 하나로 전 단계 일괄 실행', label: 'TIP', at: 240}}
    fontSize={24.5}
    height={800}
    steps={[
      {cmd: 'python src/parse.py data/html/AC250400.html', typeAt: 0.8, outAt: 3.2, out: PARSE_OUT, outLines: 4},
      {cmd: 'python src/to_chunks.py data/html/*.html', typeAt: 13.5, outAt: 16.2, out: CHUNKS_OUT, outLines: 3},
      {cmd: 'python src/build_index.py', typeAt: 26.5, outAt: 28.4, out: INDEX_OUT, outLines: 2},
    ]}
    cues={cues}
  />
);

/* 회귀 테스트 */
export const TestTerm: React.FC<{cues: Cue[]}> = ({cues}) => (
  <Layout
    kicker="HANDS-ON ②"
    title={<>품질은 <span style={{color: T.brandSoft}}>골든값 테스트</span>가 지킵니다</>}
    fontSize={30}
    height={640}
    steps={[{cmd: 'make test', typeAt: 0.9, outAt: 2.4, out: TEST_OUT, outLines: 2}]}
    cues={cues}
  />
);

/* CLI 질의 */
export const CliTerm: React.FC<{cues: Cue[]}> = ({cues}) => (
  <Layout
    kicker="HANDS-ON ③"
    title={<>터미널에서도 <span style={{color: T.brandSoft}}>근거와 함께</span> 답합니다</>}
    fontSize={25}
    height={720}
    steps={[
      {
        cmd: `python src/chatbot.py "${CLI_Q}"`,
        typeAt: 0.9,
        outAt: 4.6,
        out: CLI_OUT,
        outLines: 2,
      },
    ]}
    cues={cues}
  />
);

/* 배포: systemd + Docker 카드 */
const CodeCard: React.FC<{title: string; code: string; at: number; accent: string}> = ({title, code, at, accent}) => (
  <div style={{width: 760}}>
    <div
      style={{
        borderRadius: 18,
        overflow: 'hidden',
        border: `1px solid ${T.line2}`,
        boxShadow: '0 40px 90px -30px rgba(0,0,0,0.85)',
      }}
    >
      <div
        style={{
          padding: '16px 26px',
          background: '#161c26',
          borderBottom: `1px solid ${T.line}`,
          fontFamily: T.sans,
          fontWeight: 800,
          fontSize: 26,
          color: accent,
        }}
      >
        {title}
      </div>
      <pre
        style={{
          margin: 0,
          padding: '26px 30px',
          background: '#0d1117',
          fontFamily: T.mono,
          fontSize: 23,
          lineHeight: 1.6,
          color: '#c7d0dc',
          whiteSpace: 'pre-wrap',
        }}
      >
        {code}
      </pre>
    </div>
  </div>
);

export const DeployScene: React.FC<{cues: Cue[]}> = ({cues}) => (
  <SceneFade>
    <Bg />
    <AbsoluteFill style={{padding: '80px 120px 0'}}>
      <Kicker at={4}>DEPLOY</Kicker>
      <div style={{marginTop: 22, marginBottom: 50, fontFamily: T.sans, fontWeight: 850, fontSize: 54, color: T.ink, letterSpacing: -1}}>
        서버 반입은 <span style={{color: T.brandSoft}}>두 가지 방식</span> 중 선택
      </div>
      <div style={{display: 'flex', gap: 48, justifyContent: 'center'}}>
        <CodeCard
          at={0.8}
          accent={T.brandSoft}
          title="방식 A — venv + systemd (상시 실행)"
          code={`$ bash deploy/install.sh   # 의존성 (root 불필요)
$ bash deploy/build.sh     # 수집 → 청크 → 색인
$ bash deploy/run.sh       # 서버 기동 :8000

# 부팅 자동시작
$ systemctl enable pb-chatbot.service`}
        />
        <CodeCard
          at={2.2}
          accent={T.blue}
          title="방식 B — Docker (이미지엔 코드만)"
          code={`$ docker compose up -d     # → :8000

volumes:
  - ./data:/app/data       # 사내 데이터는
  - hf-cache:/root/.cache  # 볼륨으로만 주입`}
        />
      </div>
    </AbsoluteFill>
    <Captions cues={cues} />
  </SceneFade>
);
