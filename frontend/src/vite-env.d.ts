/// <reference types="vite/client" />

/** vite.config.ts 가 굽는 값. 사이드바가 서버 버전과 견준다. */
declare const __APP_VERSION__: string

/**
 * vtk.js 의 **프로파일**에는 타입이 없다 — 내보내는 것이 없고 부작용만 있는 모듈이라서다.
 * (Actor · Mapper 의 OpenGL 짝을 등록한다. 안 받으면 렌더 트리를 걷다가 `traverse` 에서 죽는다.)
 */
declare module '@kitware/vtk.js/Rendering/Profiles/Geometry'
