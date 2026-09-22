/**
 * 결과 화면이 **모드를 어떻게 보여 주는가.**
 *
 * 여기서 잡는 것은 숫자가 아니라 읽는 방식이다 — 강체 모드를 지우지 않고 접는가, 단위와
 * 정규화를 적는가, 모의 결과임을 말하는가. 셋 다 빠지면 화면은 그럴듯한데 틀린 말을 한다.
 */

import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { SimulationResult } from '@/modules/simulations/api'
import { ModalResult } from '@/modules/simulations/ModalResult'

function result(extra: Partial<SimulationResult> = {}): SimulationResult {
  return {
    recipe: 'modal',
    boundary: 'free-free',
    units: { frequency: 'Hz', system: 'MKS: m, kg, N, s' },
    normalization: 'mass',
    rigid_body_modes: 2,
    mesh: { nodes: 100, elements: 50 },
    modes: [
      { number: 1, elastic_number: null, frequency_hz: 0, rigid_body: true },
      { number: 2, elastic_number: null, frequency_hz: 0.002, rigid_body: true },
      {
        number: 3,
        elastic_number: 1,
        frequency_hz: 2583.12,
        rigid_body: false,
        dominant_direction: 'Y',
        effective_mass_ratio: 0.65,
      },
      { number: 4, elastic_number: 2, frequency_hz: 3315.16, rigid_body: false },
    ],
    ...extra,
  }
}

describe('모달 결과', () => {
  it('탄성 모드를 차수와 주파수로 보여 준다', () => {
    render(<ModalResult simulationId="sim" result={result()} artifacts={[]} />)
    expect(screen.getByText('1차')).toBeDefined()
    expect(screen.getByText('2,583.12')).toBeDefined()
    // 주 방향은 솔버의 말(Y)이 아니라 사람의 말로.
    expect(screen.getByText(/Y 이동/)).toBeDefined()
    expect(screen.getByText('65%')).toBeDefined()
  })

  it('유효질량비가 없으면 변위 비중으로 말하되 무엇으로 잰 값인지 적는다', () => {
    // **둘은 다른 뜻이다.** 자유-자유의 「Z 이동」 은 「Z 로 가진하면 울린다」 가 아니라
    // 「이 모드가 주로 Z 로 움직인다」 는 말이다.
    const freeFree = result({
      modes: [
        {
          number: 1,
          elastic_number: 1,
          frequency_hz: 2583.12,
          rigid_body: false,
          direction_share: { x: 0.05, y: 0.08, z: 0.87 },
          dominant_axis: 'Z',
          localization: 0.61,
          local_mode: false,
        },
      ],
    })
    render(<ModalResult simulationId="sim" result={freeFree} artifacts={[]} />)
    expect(screen.getByText(/Z 이동/)).toBeDefined()
    expect(screen.getByText(/변위 87%/)).toBeDefined()
    expect(screen.getByText(/전역/)).toBeDefined()
  })

  it('한 구석만 떠는 모드는 국부라고 적는다', () => {
    const local = result({
      modes: [
        {
          number: 1,
          elastic_number: 1,
          frequency_hz: 900,
          rigid_body: false,
          localization: 0.08,
          local_mode: true,
        },
      ],
    })
    render(<ModalResult simulationId="sim" result={local} artifacts={[]} />)
    expect(screen.getByText(/국부/)).toBeDefined()
  })

  it('강체 모드는 지우지 않고 접는다', () => {
    // 지우면 「왜 3번부터 시작하지」 를 묻고, 늘어놓으면 표의 절반이 0 이다.
    render(<ModalResult simulationId="sim" result={result()} artifacts={[]} />)
    expect(screen.getByText(/강체 모드 2개/)).toBeDefined()
  })

  it('단위와 정규화 방식을 함께 적는다', () => {
    render(<ModalResult simulationId="sim" result={result()} artifacts={[]} />)
    const caption = screen.getByText(/자유-자유/)
    expect(caption.textContent).toContain('Hz')
    expect(caption.textContent).toContain('질량')
  })

  it('모의 결과는 그렇다고 말한다', () => {
    // **진짜와 구별되지 않으면 안 된다** — fake 로 돈 값이 보고서에 실릴 수 있다.
    render(<ModalResult simulationId="sim" result={result({ fake: true })} artifacts={[]} />)
    expect(screen.getByText('모의 결과입니다')).toBeDefined()
  })

  it('강체 모드 수가 이상하면 경고를 띄운다', () => {
    const warned = result({ warning: '자유-자유인데 강체 모드가 12개입니다.' })
    render(<ModalResult simulationId="sim" result={warned} artifacts={[]} />)
    expect(screen.getByText(/강체 모드가 12개/)).toBeDefined()
  })

  it('형상이 없으면 이유를 말한다', () => {
    render(<ModalResult simulationId="sim" result={result()} artifacts={[]} />)
    expect(screen.getByText('모드 형상이 없습니다')).toBeDefined()
  })
})

describe('모드가 많을 때', () => {
  function many(count: number): SimulationResult {
    return {
      ...result(),
      rigid_body_modes: 0,
      modes: Array.from({ length: count }, (_, index) => ({
        number: index + 1,
        elastic_number: index + 1,
        frequency_hz: 100 * (index + 1),
        rigid_body: false,
      })),
    }
  }

  it('표를 쪽으로 나눈다', () => {
    // **없으면 20개가 넘는 순간 나머지를 볼 방법이 없다** — 모달은 모드 수십 개가 흔하다.
    render(<ModalResult simulationId="sim" result={many(45)} artifacts={[]} />)
    expect(screen.getByText('1차')).toBeDefined()
    expect(screen.queryByText('21차')).toBeNull()
    expect(screen.getByText(/45개 모드/)).toBeDefined()
  })
})
