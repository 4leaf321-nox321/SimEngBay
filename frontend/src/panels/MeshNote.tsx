/**
 * 대화 안 결과 화면(패널)에서 3D 형상 뷰어(`shared/viewer/MeshViewer`) 자리에 서는 안내 — 패널 묶음은
 * 2 MiB 상한이라 vtk.js(1MB 남짓)를 싣지 않는다(`scripts/build-panels.mjs` 가 이것으로 바꿔 끼운다).
 */

export default function MeshNote({ heightClass }: { heightClass?: string }) {
  return (
    <div
      className={`text-muted-foreground bg-muted/30 flex items-center justify-center rounded-md border border-dashed p-4 text-center text-sm ${heightClass && heightClass.startsWith('aspect') ? heightClass : 'min-h-24'}`}
    >
      3D 형상은 SimEngBay 화면에서 봅니다 — 대화 안 화면에는 3D 뷰어를 싣지 않습니다.
    </div>
  )
}
