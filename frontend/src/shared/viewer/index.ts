/**
 * 3D 뷰어 — **`lazy()` 로만 받는다.**
 *
 * vtk.js 한 덩어리가 수백 KB 다. 결과를 안 보는 화면(목록 · 공지 · 계정)까지 매번 그것을 받을
 * 이유가 없다. 그래서 이 폴더의 것은 **컴포넌트 안에서 동적으로** 불러온다 — `MeshViewer` 는
 * 껍데기고, 실제 vtk.js 는 그것이 화면에 붙은 뒤에 온다.
 *
 * 쓰는 쪽:
 *
 *     const MeshViewer = lazy(() => import('@/shared/viewer/MeshViewer'))
 */

export type { MeshViewerProps } from '@/shared/viewer/MeshViewer'
