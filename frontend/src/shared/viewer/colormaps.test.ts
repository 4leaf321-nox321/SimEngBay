/**
 * 3D 뷰어의 색 지도 — **기본은 Ansys 식 무지개, 고른 것은 모든 뷰어가 함께 쓰고 브라우저가 기억한다.**
 */

import { act, renderHook } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { STORAGE_PREFIX } from '@/shared/branding'
import {
  COLORMAPS,
  DEFAULT_COLORMAP,
  colormapChoice,
  colormapOf,
  gradientOf,
  plotlyScale,
  setColormap,
  useChosenColormap,
  useColormap,
} from '@/shared/viewer/colormaps'

describe('색 지도', () => {
  it('기본은 Ansys 식 무지개 — 0 은 파랑, 최대는 빨강', () => {
    const map = colormapOf(DEFAULT_COLORMAP)
    expect(map.key).toBe('ansys')
    expect(map.stops[0]).toEqual([0, 0, 0, 1])
    expect(map.stops.at(-1)).toEqual([1, 1, 0, 0])
    // 모르는 열쇠(지운 색 · 손댄 저장값)는 기본으로.
    expect(colormapOf('없는색').key).toBe('ansys')
  })

  it('마디는 0 에서 시작해 1 에서 끝나고 거꾸로 가지 않는다', () => {
    for (const map of COLORMAPS) {
      const places = map.stops.map(([at]) => at)
      expect(places[0], map.key).toBe(0)
      expect(places.at(-1), map.key).toBe(1)
      expect([...places].sort((a, b) => a - b), map.key).toEqual(places)
      for (const [, ...rgb] of map.stops) for (const value of rgb) expect(value >= 0 && value <= 1, map.key).toBe(true)
    }
  })

  it('범례 띠는 3D 와 같은 마디로 그린다', () => {
    expect(gradientOf(colormapOf('gray'))).toBe(
      'linear-gradient(to right, rgb(38, 38, 38) 0.0%, rgb(235, 235, 235) 100.0%)',
    )
  })

  it('고르면 모든 뷰어가 따르고 브라우저가 기억한다', () => {
    const first = renderHook(() => useColormap())
    const second = renderHook(() => useColormap())
    act(() => setColormap('viridis'))
    expect(first.result.current.key).toBe('viridis')
    expect(second.result.current.key).toBe('viridis')
    expect(window.localStorage.getItem(`${STORAGE_PREFIX}.viewer.colormap`)).toBe('viridis')
    act(() => setColormap(DEFAULT_COLORMAP))
  })

  it('plotly 의 colorscale 도 같은 마디로 — DOE 그림의 색 막대', () => {
    expect(plotlyScale(colormapOf('gray'))).toEqual([
      [0, 'rgb(38, 38, 38)'],
      [1, 'rgb(235, 235, 235)'],
    ])
  })

  it('자리마다 따로 기억한다 — DOE 그림을 바꿔도 3D 뷰어의 색은 그대로', () => {
    const doe = colormapChoice('test.doe.colormap', 'viridis')
    const chart = renderHook(() => useChosenColormap(doe))
    const viewer = renderHook(() => useColormap())
    expect(chart.result.current.key).toBe('viridis')
    act(() => doe.set('turbo'))
    expect(chart.result.current.key).toBe('turbo')
    expect(viewer.result.current.key).toBe(DEFAULT_COLORMAP)
    expect(window.localStorage.getItem(`${STORAGE_PREFIX}.test.doe.colormap`)).toBe('turbo')
    // 모르는 값은 그 자리의 기본으로 — 3D 의 기본(Ansys)이 아니다.
    act(() => doe.set('없는색'))
    expect(chart.result.current.key).toBe('viridis')
  })
})
