/**
 * **겉면 그림을 다루는 셈** — 파트로 나누기 · 외곽선(모서리) 찾기. 3D 뷰어가 쓴다.
 *
 * 입력은 vtk 셀 배열 그대로(`[n, p0, …, pn-1, n, …]`)다. **vtk.js 를 부르지 않는다** — 셈만이라
 * 시험이 WebGL 없이 돈다.
 *
 * - **파트** — 서버가 그림에 셀 배열 `part` 를 적어 보낸다(`backend/app/core/surface_parts.py`).
 *   그 기능 전에 만든 그림에는 없어서, 그때는 **이어진 덩어리**로 나눈다(`components`) — 바디는
 *   접합해도 절점을 나누지 않으므로 대개 덩어리 하나가 바디 하나다. 이름은 모르니 「파트 N」.
 * - **외곽선** — 모서리를 나누는 두 면의 각이 30° 를 넘거나(꺾인 모서리), 면 하나에만 붙은
 *   모서리(쉘의 테두리)다. 요소 경계를 다 그리는 「요소」 선과 달리 **형상의 윤곽**만 남는다.
 */

/** 셀 배열을 훑는다 — 셀마다 (셀 번호, 시작 자리, 점 수). */
function forEachCell(flat: ArrayLike<number>, visit: (cell: number, start: number, size: number) => void) {
  let at = 0
  let cell = 0
  while (at < flat.length) {
    const size = flat[at]
    visit(cell, at + 1, size)
    at += size + 1
    cell += 1
  }
}

/** 셀 수. */
export function cellCount(flat: ArrayLike<number>): number {
  let count = 0
  forEachCell(flat, () => {
    count += 1
  })
  return count
}

/** 셀마다 이어진 덩어리 번호 — **큰 덩어리(셀 수)부터 0, 1, …**. 같으면 먼저 나온 것부터. */
export function components(flat: ArrayLike<number>, pointCount: number): Int32Array {
  const parent = new Int32Array(pointCount)
  for (let index = 0; index < pointCount; index += 1) parent[index] = index
  const root = (start: number) => {
    let one = start
    while (parent[one] !== one) {
      parent[one] = parent[parent[one]]
      one = parent[one]
    }
    return one
  }
  forEachCell(flat, (_, start, size) => {
    if (size === 0) return
    const first = root(flat[start])
    for (let offset = 1; offset < size; offset += 1) {
      const top = root(flat[start + offset])
      if (top !== first) parent[top] = first
    }
  })
  const raw: number[] = []
  forEachCell(flat, (_, start, size) => {
    raw.push(size === 0 ? -1 : root(flat[start]))
  })
  const sizes = new Map<number, number>()
  const seen = new Map<number, number>()
  raw.forEach((label, index) => {
    sizes.set(label, (sizes.get(label) ?? 0) + 1)
    if (!seen.has(label)) seen.set(label, index)
  })
  const order = [...sizes.keys()].sort(
    (a, b) => (sizes.get(b) ?? 0) - (sizes.get(a) ?? 0) || (seen.get(a) ?? 0) - (seen.get(b) ?? 0),
  )
  const renumber = new Map(order.map((label, index) => [label, index]))
  return Int32Array.from(raw, (label) => renumber.get(label) ?? 0)
}

/** 파트 번호마다 그 셀들만 담은 셀 배열. */
export function groupCells(flat: ArrayLike<number>, labels: ArrayLike<number>): Map<number, Uint32Array> {
  const lengths = new Map<number, number>()
  forEachCell(flat, (cell, _, size) => {
    const label = labels[cell]
    lengths.set(label, (lengths.get(label) ?? 0) + size + 1)
  })
  const out = new Map<number, Uint32Array>()
  const filled = new Map<number, number>()
  for (const [label, length] of lengths) {
    out.set(label, new Uint32Array(length))
    filled.set(label, 0)
  }
  forEachCell(flat, (cell, start, size) => {
    const label = labels[cell]
    const target = out.get(label) as Uint32Array
    let at = filled.get(label) ?? 0
    target[at] = size
    at += 1
    for (let offset = 0; offset < size; offset += 1) target[at + offset] = flat[start + offset]
    filled.set(label, at + size)
  })
  return out
}

/** 꺾인 모서리로 보는 각 — 두 면의 법선이 이보다 벌어지면 윤곽이다. */
export const FEATURE_ANGLE_DEG = 30

/**
 * 외곽선 — 꺾인 모서리 · 테두리(면 하나에만 붙은 모서리) · 셋 이상이 만나는 모서리를 vtk 선
 * 셀 배열(`[2, a, b, …]`)로. 법선은 다각형의 뉴웰 법선이다(사각형 요소면도 그대로 된다).
 */
export function featureEdges(
  flat: ArrayLike<number>,
  points: ArrayLike<number>,
  angleDeg = FEATURE_ANGLE_DEG,
): Uint32Array {
  const limit = Math.cos((angleDeg * Math.PI) / 180)
  const normals: number[] = []
  forEachCell(flat, (_, start, size) => {
    let nx = 0
    let ny = 0
    let nz = 0
    for (let offset = 0; offset < size; offset += 1) {
      const a = flat[start + offset] * 3
      const b = flat[start + ((offset + 1) % size)] * 3
      nx += (points[a + 1] - points[b + 1]) * (points[a + 2] + points[b + 2])
      ny += (points[a + 2] - points[b + 2]) * (points[a] + points[b])
      nz += (points[a] - points[b]) * (points[a + 1] + points[b + 1])
    }
    const length = Math.hypot(nx, ny, nz) || 1
    normals.push(nx / length, ny / length, nz / length)
  })
  const pointCount = points.length / 3
  // 모서리 → [처음 붙은 셀, 붙은 셀 수, 꺾였나]
  const edges = new Map<number, [number, number, boolean]>()
  forEachCell(flat, (cell, start, size) => {
    for (let offset = 0; offset < size; offset += 1) {
      const a = flat[start + offset]
      const b = flat[start + ((offset + 1) % size)]
      if (a === b) continue
      const key = a < b ? a * pointCount + b : b * pointCount + a
      const found = edges.get(key)
      if (!found) {
        edges.set(key, [cell, 1, false])
        continue
      }
      found[1] += 1
      const first = found[0] * 3
      const here = cell * 3
      const dot =
        normals[first] * normals[here] + normals[first + 1] * normals[here + 1] + normals[first + 2] * normals[here + 2]
      // 법선은 셀의 감김 방향을 따른다 — 이웃이 거꾸로 감겼어도 같은 평면이면 꺾인 것이 아니다.
      if (Math.abs(dot) < limit) found[2] = true
    }
  })
  const lines: number[] = []
  for (const [key, [, count, sharp]] of edges) {
    if (count === 1 || count > 2 || sharp) {
      lines.push(2, Math.floor(key / pointCount), key % pointCount)
    }
  }
  return Uint32Array.from(lines)
}
