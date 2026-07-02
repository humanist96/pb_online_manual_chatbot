# 임원 보고 PDF — PB 매뉴얼 데스크 개발 보고

`content/*.html`(쪽별 원고) + `template/print.css`(브랜드 스타일) → Playwright `page.pdf()` → A4 8쪽.
**완전 자립형 PDF**(폰트·이미지 임베드, 외부 참조 0) — 폐쇄망 PC에서 그대로 열린다.

## 빌드

```bash
cp ../../web/fonts/PretendardVariable.woff2 template/   # 최초 1회
node build.mjs <chrome-headless-shell 경로>              # → out/PB매뉴얼데스크_개발보고_2026-07.pdf
node shots.mjs <chrome 경로>                             # 쪽별 PNG 검수용
```

chrome-headless-shell은 `video/remotion`에서 `npx remotion browser ensure`로 받은 것을 재사용.
이미지(`images/`)는 소개 영상·데모 캡처에서 추출한 실제 화면 — 내용 수정 시 원고(content)만 고치고 재빌드.
산출 PDF는 사내 데이터가 포함되므로 커밋 금지(사내 공유만).
