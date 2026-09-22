/**
 * **결과를 못 받으면 화면이 그 사실을 말하는가.**
 *
 * 조용히 삼키면 「글과 표만 나오고 그림은 통째로 없는」 화면이 되고, 사람은 그것을 기능이 없는
 * 것으로 읽는다 — 실제로는 서버가 이유를 말하고 있었다(실측으로 겪었다).
 */

import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { simulationApi } from '@/modules/simulations/api'
import { ResultPanel } from '@/modules/simulations/ResultPanel'
import { ApiError } from '@/shared/api/client'

vi.mock('@/modules/simulations/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/modules/simulations/api')>()
  return { ...actual, simulationApi: { ...actual.simulationApi, result: vi.fn() } }
})

const asMock = () => vi.mocked(simulationApi.result)

describe('결과 패널', () => {
  beforeEach(() => {
    asMock().mockReset()
  })

  it('작업 폴더를 못 찾으면 서버가 준 말을 그대로 보여 준다', async () => {
    asMock().mockRejectedValue(
      new ApiError(403, {
        error: {
          code: 'SEB-SIMULATIONS-0007',
          message:
            '결과 요약 파일이 작업 폴더에 없습니다. 작업 폴더(WORK_DIR)가 함께 복구됐는지 확인하세요.',
        },
      }),
    )
    render(<ResultPanel simulationId="sim" status="done" artifacts={[]} />)
    // **무엇을 확인해야 하는지가 메시지에 있다** — 그것을 버리면 아무 데도 안 남는다.
    await waitFor(() => expect(screen.getByText(/WORK_DIR/)).toBeDefined())
  })

  it('도는 중에는 결과를 받지 않는다', () => {
    render(<ResultPanel simulationId="sim" status="modeling" artifacts={[]} />)
    expect(asMock()).not.toHaveBeenCalled()
  })
})
