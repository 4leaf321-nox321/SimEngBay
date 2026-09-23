/**
 * 영역 지문을 **브라우저에서 읽는다** — 서버에 먼저 보내고 물어보면 영역을 고르기도 전에
 * 작업이 하나 생긴다.
 *
 * 붙박이 값은 CompCore 가 제 코드로 낸 것이다(`backend/tests/fixtures/topology`). 손으로
 * 지어낸 모양으로 시험하면 계약이 바뀌어도 여기는 계속 초록이다.
 */

import { readFileSync } from 'node:fs'

import { describe, expect, it } from 'vitest'

import { readTopology } from '@/modules/simulations/api'

function fixture(name: string): File {
  const text = readFileSync(`../backend/tests/fixtures/topology/${name}.topology.json`, 'utf8')
  return new File([text], `${name}.topology.json`, { type: 'application/json' })
}

describe('영역 지문 읽기', () => {
  it('영역 이름과 면 수를 낸다', async () => {
    const read = await readTopology(fixture('plate_holes'))
    expect(read.regions).toEqual([
      { name: 'fixed_base', faces: 1 },
      { name: 'bolt_holes', faces: 4 },
    ])
    expect(read.bodies).toBe(1)
    expect(read.unresolved).toEqual([])
  })

  it('볼트로 고정하는 브래킷도 같은 모양으로 읽는다', async () => {
    const read = await readTopology(fixture('bracket_bolted'))
    expect(read.regions.map((one) => one.name)).toContain('bolt_holes')
  })

  it('지문이 아니면 이유를 말한다', async () => {
    const wrong = new File(['{"hello": 1}'], 'x.json', { type: 'application/json' })
    await expect(readTopology(wrong)).rejects.toThrow(/regions/)
  })
})
