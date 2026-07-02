import {Config} from '@remotion/cli/config';

Config.setVideoImageFormat('jpeg');
Config.setOverwriteOutput(true);
// 윈도우 기본 플레이어 호환: H.264 + yuv420p 는 렌더 CLI 기본값(codec h264)
Config.setChromiumDisableWebSecurity(false);
