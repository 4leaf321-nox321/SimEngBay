/**
 * 대기 중인 작업의 줄 — 「앞에 선 남의 작업 수」 가 아니라 내 앞의 내 작업 · 나눠 쓰는 사람 수로
 * 말하고, 집을 워커가 없으면 기다리라고 하지 않는다(ADR 0011).
 */
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { SOLVER_LABELS } from './labels'
import { QueueNotice, queueLine } from './QueueNotice'
import type { Queue } from './QueueNotice'

const line: Queue = {
  solver: 'calculix',
  queued: 37,
  mine_ahead: 2,
  people: 3,
  running: 4,
  workers_alive: 4,
}

describe('QueueNotice', () => {
  it('줄을 한 줄로 — 솔버 · 대기 · 내 앞 · 사람 수 · 도는 것 · 워커', () => {
    const solver = SOLVER_LABELS.calculix
    expect(queueLine(line)).toBe(
      `${solver} 줄에 37건 대기 · 내 앞의 내 작업 2건 · 3명이 번갈아 씁니다 · 지금 도는 것 4건 · 워커 4개`,
    )
    // 혼자 쓰는 줄 · 워커를 모르는 설치(-1)면 그 조각을 뺀다.
    expect(queueLine({ ...line, mine_ahead: 0, people: 1, workers_alive: -1 })).toBe(
      `${solver} 줄에 37건 대기 · 내 작업 중 다음 차례 · 지금 도는 것 4건`,
    )
  })

  it('STE 동시 한도에 걸렸으면 그 까닭을 앞에 보인다', () => {
    const held = 'STE 동시 작업 한도(이 서버 전체 8개)가 찼습니다 — 도는 STE 작업이 끝나면 집힙니다.'
    render(<QueueNotice queue={{ ...line, held }} />)
    expect(screen.getByText('STE 동시 한도에 걸려 기다립니다')).toBeInTheDocument()
    expect(screen.getByText(/이 서버 전체 8개\)가 찼습니다/)).toBeInTheDocument()
  })

  it('집을 워커가 없으면 기다리라고 하지 않고 경고한다', () => {
    render(<QueueNotice queue={{ ...line, workers_alive: 0 }} />)
    expect(screen.getByText('이 솔버를 집는 워커가 없습니다')).toBeInTheDocument()
  })
})
