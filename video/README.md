# video/ — 소개 영상 제작 도구 체인

PowerBASE 매뉴얼 챗봇 소개 영상 제작용. Remotion(React 기반 프로그래매틱 영상)으로
**보고용 `report.mp4`**(요약본)와 **상세본 `full.mp4`** 를 렌더링한다.

```
video/
├── remotion/            # Remotion 프로젝트 (씬·타임라인·자막)
│   ├── src/             #   Root.tsx, scenes/, components/, captions/, timeline.json
│   └── scripts/         #   make-srt.mjs (자막 SRT 생성)
├── captures/
│   ├── browser/         # 웹 UI 데모 캡처 스크립트 (playwright-core)
│   └── out/             # 캡처 산출물 (webm/png — git 제외, markers.json만 추적)
└── out/                 # 최종 mp4/srt (git 제외)
```

## 요구 도구

- Node 22+ (npm 포함)
- 리눅스: chrome-headless-shell 구동에 `libnss3`, `libnspr4` 필요 (`apt install libnss3 libnspr4`)

## 준비

```bash
cd video/remotion
npm install
```

### 폰트 (`video/remotion/public/fonts/` — git 제외, 직접 배치)

```bash
mkdir -p public/fonts
# Pretendard — 레포의 web/fonts 재사용
cp ../../web/fonts/PretendardVariable.woff2 public/fonts/
# D2Coding — https://github.com/naver/d2codingfont 릴리스에서 받아 D2Coding.woff 배치
# 또는 CDN: https://cdn.jsdelivr.net/gh/projectnoonnu/noonfonts_three@1.0/D2Coding.woff
curl -Lo public/fonts/D2Coding.woff \
  https://cdn.jsdelivr.net/gh/projectnoonnu/noonfonts_three@1.0/D2Coding.woff
```

## 데모 캡처 (웹 UI 화면 녹화)

1. webapp을 `:8010`에 띄운다 (예: `PORT=8010 python src/webapp.py`).
2. chrome-headless-shell 다운로드: `cd video/remotion && npx remotion browser ensure`
3. **시스템에 D2Coding TTF 설치** — 안 하면 UI의 모노스페이스 요소가 □로 렌더된다.
4. repo 루트에서:

```bash
node video/captures/browser/07_webapp.mjs \
  http://127.0.0.1:8010 <chrome-headless-shell 경로> video/captures/out
```

산출: `video/captures/out/07_webapp.webm` + `markers.json`(편집점).
캡처 결과를 Remotion 에셋으로 복사:

```bash
mkdir -p video/remotion/public/demo
cp video/captures/out/07_webapp.webm video/remotion/public/demo/07_webapp.webm
```

## 렌더

```bash
cd video/remotion
npx remotion render src/index.ts Report out/report.mp4 \
  --codec h264 --audio-codec aac --enforce-audio-track
npx remotion render src/index.ts Full out/full.mp4 \
  --codec h264 --audio-codec aac --enforce-audio-track
npx remotion still src/index.ts Thumb out/thumb.png      # 썸네일
node scripts/make-srt.mjs report out/report.srt          # 자막 (full 동일)
```

repo 루트에서 `make video-render`로도 실행 가능 (`make video-capture` 참고).

## 주의

- **렌더된 mp4는 사내 데이터(매뉴얼 화면·데모 답변)를 포함한다. 커밋 금지, 사내 공유만.**
- Remotion은 무료가 아닐 수 있음 — 회사 규모에 따른 상용 라이선스 조건을 확인할 것
  (https://remotion.dev/license).
