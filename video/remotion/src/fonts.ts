import {continueRender, delayRender, staticFile} from 'remotion';

const loaded: Record<string, boolean> = {};

const load = (family: string, file: string, weight: string) => {
  const key = family + file;
  if (loaded[key]) return;
  loaded[key] = true;
  const handle = delayRender(`font ${family}`);
  const face = new FontFace(family, `url(${staticFile(file)})`, {weight});
  face
    .load()
    .then(() => {
      document.fonts.add(face);
      continueRender(handle);
    })
    .catch(() => continueRender(handle));
};

export const ensureFonts = () => {
  load('Pretendard', 'fonts/PretendardVariable.woff2', '45 920');
  load('D2Coding', 'fonts/D2Coding.woff', '400');
};
