/**
 * 겉면 셈 — **이어진 덩어리로 파트를 나누고, 외곽선은 형상의 윤곽만 남긴다**(요소 경계 · 사각형을
 * 쪼갠 대각선은 빼고).
 */

import { describe, expect, it } from 'vitest'

import { cellCount, components, featureEdges, groupCells } from '@/shared/viewer/surfaceParts'

/** 한 변 1 짜리 정육면체 — 점 여덟(좌표), 사각형 여섯(셀 배열). */
function cube(offset = 0, shift = 0): { points: number[]; quads: number[] } {
  const points: number[] = []
  for (const z of [0, 1]) for (const y of [0, 1]) for (const x of [0, 1]) points.push(x + shift, y, z)
  const faces = [
    [0, 2, 3, 1],
    [4, 5, 7, 6],
    [0, 1, 5, 4],
    [2, 6, 7, 3],
    [0, 4, 6, 2],
    [1, 3, 7, 5],
  ]
  return { points, quads: faces.flatMap((face) => [4, ...face.map((one) => one + offset)]) }
}

/** 사각형마다 삼각형 둘로 — Ansys 옛 그림이 이 모양이다. */
function triangulated(quads: number[]): number[] {
  const out: number[] = []
  for (let at = 0; at < quads.length; at += 5) {
    const [a, b, c, d] = quads.slice(at + 1, at + 5)
    out.push(3, a, b, c, 3, a, c, d)
  }
  return out
}

function lineCount(lines: Uint32Array): number {
  return lines.length / 3
}

describe('겉면 셈', () => {
  it('정육면체의 외곽선은 모서리 열두 개다 — 사각형을 쪼갠 대각선은 그리지 않는다', () => {
    const { points, quads } = cube()
    expect(lineCount(featureEdges(quads, points))).toBe(12)
    expect(lineCount(featureEdges(triangulated(quads), points))).toBe(12)
  })

  it('판(열린 면)은 테두리가 외곽선이다', () => {
    const points = [0, 0, 0, 1, 0, 0, 1, 1, 0, 0, 1, 0]
    const square = [3, 0, 1, 2, 3, 0, 2, 3]
    const lines = featureEdges(square, points)
    expect(lineCount(lines)).toBe(4)
  })

  it('이어지지 않은 덩어리마다 파트 번호를 큰 것부터 준다', () => {
    const left = cube(0, 0)
    const right = cube(8, 5)
    // 오른쪽 정육면체를 삼각형으로 — 셀이 더 많아 0 번이 된다.
    const flat = [...left.quads, ...triangulated(right.quads)]
    const labels = components(flat, 16)
    expect(cellCount(flat)).toBe(18)
    expect(Array.from(labels)).toEqual([...Array(6).fill(1), ...Array(12).fill(0)])
    const groups = groupCells(flat, labels)
    expect(cellCount(groups.get(0) as Uint32Array)).toBe(12)
    expect(Array.from(groups.get(1) as Uint32Array)).toEqual(left.quads)
  })
})
