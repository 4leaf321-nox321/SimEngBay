/**
 * 실측 표 — **엑셀과 클립보드로 주고받는다**(로컬 파일은 DRM 이 걸린다). 붙여넣기는 그 칸부터
 * 채우고, 머리줄이 있으면 열 이름으로 맞춘다. 복사는 머리줄과 함께 탭으로 가른 줄로.
 */

import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { EXAMPLE, MeasurementEntry, errorRows, headerColumns, pasted } from '@/modules/simulations/MeasurementEntry'
import { parseGrid, toTsv } from '@/shared/lib/clipboard'

const blank = () => Array(6).fill('')

describe('실측 표', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('엑셀이 복사한 칸(탭)과 글로 복사한 CSV(쉼표 · 따옴표)를 읽는다', () => {
    expect(parseGrid('측정점\t공진\t1250\r\n끝\tFRF\t1200\r\n')).toEqual([
      ['측정점', '공진', '1250'],
      ['끝', 'FRF', '1200'],
    ])
    expect(parseGrid('"입구, 위판",변위,,0.04')).toEqual([['입구, 위판', '변위', '', '0.04']])
    expect(toTsv([['a', 'b\tc']])).toBe('a\tb c')
  })

  it('머리줄은 장비 열 이름(별칭)으로도 알아보고 열 순서를 맞춘다', () => {
    expect(headerColumns(['Frequency (Hz)', 'Sensor', 'Value'])).toEqual([2, 0, 3])
    expect(headerColumns(['1250', '공진'])).toBeNull()
    const rows = pasted([blank()], [['Type', 'Freq', 'Probe'], ['공진', '1250', '끝']], { row: 0, column: 0 })
    expect(rows).toEqual([['끝', '공진', '1250', '', '', '']])
  })

  it('머리줄이 없으면 누른 칸부터 채우고 모자라면 줄을 늘린다', () => {
    const rows = pasted([blank()], [['1250', '0.4'], ['1300', '0.1']], { row: 0, column: 2 })
    expect(rows).toEqual([
      ['', '', '1250', '0.4', '', ''],
      ['', '', '1300', '0.1', '', ''],
    ])
  })

  it('서버의 줄 번호(머리가 1 줄)를 표의 줄 번호로 옮긴다', () => {
    expect([...errorRows(['2줄: 모르는 종류', '5줄: 값이 없습니다', '표가 비었습니다.'])]).toEqual([1, 4])
  })

  it('칸에 여러 줄을 붙여 넣으면 표로 편다', () => {
    render(<MeasurementEntry onSubmit={async () => {}} />)
    const first = screen.getByLabelText('1번 줄 측정점')
    fireEvent.paste(first, {
      clipboardData: { getData: () => '측정점\t종류\t주파수\n끝\t공진\t1250\n끝\t공진\t3410\n' },
    })
    expect((screen.getByLabelText('2번 줄 주파수 (Hz)') as HTMLInputElement).value).toBe('3410')
    expect(screen.queryByLabelText('3번 줄 측정점')).toBeNull()
    expect(screen.getByText('2줄')).toBeDefined()
  })

  it('표 복사는 머리줄과 함께 탭으로 가른 줄로 클립보드에 넣는다', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText } })
    render(<MeasurementEntry onSubmit={async () => {}} />)
    await userEvent.click(screen.getByRole('button', { name: '예시 넣기' }))
    await userEvent.click(screen.getByRole('button', { name: /표 복사/ }))
    const copied = writeText.mock.calls[0][0] as string
    expect(copied.split('\n')[0]).toBe('측정점\t종류\t주파수\t값\t단위\t성분')
    expect(copied.split('\n')).toHaveLength(EXAMPLE.length + 1)
    expect(screen.getByText(/엑셀에 붙여 넣으면 됩니다/)).toBeDefined()
  })
})
