/**
 * **서버가 만든 VTP 를 화면이 읽을 수 있는가.**
 *
 * 이 계약은 두 언어에 걸쳐 있다 — PyVista 가 쓰고(`app/core/dpf/shapes.py`) vtk.js 가 읽는다.
 * 한쪽이 형식을 바꾸면(ASCII 로, 압축 방식으로, 배열 이름으로) 화면은 **빈 상자**를 그리고 그
 * 사실은 오류로 드러나지 않는다. 그래서 진짜 산출물 한 장을 붙들어 두고 여기서 읽어 본다.
 *
 * 붙박이 파일은 Ansys 2025 R2 로 만든 L 브래킷의 1차 탄성 모드다(`tests/ansys` 가 만든 것).
 */

import { readFileSync } from 'node:fs'

import vtkXMLPolyDataReader from '@kitware/vtk.js/IO/XML/XMLPolyDataReader'
import { describe, expect, it } from 'vitest'

function readFixture(): ArrayBuffer {
  const buffer = readFileSync('src/shared/viewer/__fixtures__/mode.vtp')
  return buffer.buffer.slice(buffer.byteOffset, buffer.byteOffset + buffer.byteLength)
}

describe('모드 형상 VTP', () => {
  const reader = vtkXMLPolyDataReader.newInstance()
  reader.parseAsArrayBuffer(readFixture())
  const polyData = reader.getOutputData(0)

  it('점과 면이 들어 있다', () => {
    expect(polyData.getNumberOfPoints()).toBeGreaterThan(0)
    expect(polyData.getNumberOfCells()).toBeGreaterThan(0)
  })

  it('변위와 크기 배열을 이름으로 찾을 수 있다', () => {
    // **뷰어가 이 이름으로 찾는다.** 서버가 이름을 바꾸면 뷰어는 「변위가 없습니다」 를 띄운다.
    const displacement = polyData.getPointData().getArrayByName('displacement')
    const magnitude = polyData.getPointData().getArrayByName('magnitude')
    expect(displacement).not.toBeNull()
    expect(magnitude).not.toBeNull()
    expect(displacement?.getNumberOfComponents()).toBe(3)
    expect(displacement?.getData().length).toBe(polyData.getNumberOfPoints() * 3)
  })

  it('솎아 낸 보조 배열은 실려 있지 않다', () => {
    // 파일만 키우고 화면에는 쓸모가 없다.
    expect(polyData.getPointData().getArrayByName('vtkOriginalPointIds')).toBeNull()
  })

  it('변위가 0 이 아니다', () => {
    const magnitude = polyData.getPointData().getArrayByName('magnitude')?.getData()
    expect(magnitude).toBeDefined()
    expect(Math.max(...(magnitude as Float32Array))).toBeGreaterThan(0)
  })
})
