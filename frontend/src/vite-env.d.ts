/// <reference types="vite/client" />

/** vite.config.ts 가 굽는 값. 사이드바가 서버 버전과 견준다. */
declare const __APP_VERSION__: string

/**
 * plotly 묶음 — 웹은 전체(`full`, 4MB), 대화 안 결과 화면(패널)은 2D 묶음(`cartesian`)이다. 패널 한 장의
 * 상한(HWAX 2 MiB)에 전체가 안 들어가서다 — 2D 묶음은 3D · 산점도 행렬 · 평행 좌표를 못 그린다.
 */
declare const __PLOT_KIT__: 'full' | 'cartesian'

/**
 * vtk.js 의 **프로파일**에는 타입이 없다 — 내보내는 것이 없고 부작용만 있는 모듈이라서다.
 * (Actor · Mapper 의 OpenGL 짝을 등록한다. 안 받으면 렌더 트리를 걷다가 `traverse` 에서 죽는다.)
 */
declare module '@kitware/vtk.js/Rendering/Profiles/Geometry'
