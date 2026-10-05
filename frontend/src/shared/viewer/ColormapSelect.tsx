/**
 * 3D 뷰어의 **색 지도 고르기** — 뷰어 아래 막대와 「여러 개 보기」 막대에 둔다. 어디서 고르든 화면의
 * 모든 뷰어가 다시 칠한다(`colormaps.ts`). 옆의 띠가 고른 색이다(왼쪽 0 → 오른쪽 최대).
 *
 * 네이티브 `<select>` 다 — 고를 것이 몇 개뿐이고, 시험이 `selectOptions` 로 바로 고를 수 있다.
 * vtk.js 를 부르지 않는다.
 */

import { COLORMAPS, gradientOf, setColormap, useColormap } from '@/shared/viewer/colormaps'

export function ColormapSelect({ swatch = false }: { swatch?: boolean }) {
  const map = useColormap()
  return (
    <label className="text-muted-foreground flex items-center gap-2 text-xs">
      색
      <select
        aria-label="색 지도"
        className="border-input bg-background text-foreground h-8 rounded-md border px-2 text-xs"
        value={map.key}
        onChange={(event) => setColormap(event.target.value)}
      >
        {COLORMAPS.map((one) => (
          <option key={one.key} value={one.key}>
            {one.label}
          </option>
        ))}
      </select>
      {swatch && <span aria-hidden className="h-2 w-16 rounded" style={{ background: gradientOf(map) }} />}
    </label>
  )
}
