export const T = {
  w: 1920,
  h: 1080,
  fps: 30,

  // 다크 시네마틱 + koscom 오렌지 (web/styles.css 브랜드 팔레트에서 유도)
  bg: '#0b0e13',
  bg2: '#10141b',
  panel: '#151a22',
  panel2: '#1a2029',
  line: 'rgba(255,255,255,0.08)',
  line2: 'rgba(255,255,255,0.14)',

  ink: '#f3f5f9',
  ink2: '#b7c0cd',
  dim: '#77818f',
  faint: '#4c5560',

  brand: '#f5821f',
  brandDeep: '#e4670a',
  brandSoft: '#ffa14e',
  brandTint: 'rgba(245,130,31,0.12)',

  ok: '#3ecf8e',
  blue: '#6db3e8',
  purple: '#a98fd6',
  warn: '#e8b45a',

  sans: `'Pretendard', -apple-system, sans-serif`,
  mono: `'D2Coding', 'Cascadia Code', Consolas, monospace`,
} as const;

export const GRAD = `linear-gradient(135deg, ${T.brandSoft} 0%, ${T.brandDeep} 100%)`;
