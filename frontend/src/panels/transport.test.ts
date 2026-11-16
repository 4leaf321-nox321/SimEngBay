/**
 * 패널의 요청 길 — API 클라이언트의 요청이 `panel_data` 도구 호출로 바뀌고, 답이 웹과 같은 `Response`
 * 로 돌아오는가. 바꾸는 요청(저장 · 삭제 · 파일 올리기)은 도구를 부르지 않고 막는다.
 */

import { afterEach, describe, expect, it, vi } from 'vitest'

import type { ToolResult } from '@/panels/bridge'
import { panelTransport } from '@/panels/transport'
import { api, setTransport } from '@/shared/api/client'

function answer(status: number, body: unknown): ToolResult {
  return { content: [{ type: 'text', text: JSON.stringify({ status, body }) }] }
}

afterEach(() => setTransport(null))

describe('panelTransport', () => {
  it('GET 은 경로만, 읽기인 POST 는 본문까지 싣고 백엔드의 상태 · 본문을 그대로 돌려준다', async () => {
    const call = vi.fn().mockResolvedValueOnce(answer(200, { study_id: 's' })).mockResolvedValueOnce(answer(200, { counts: {} }))
    const send = panelTransport(call, 'simengbay_panel_data')
    const got = await send('/simulations/studies/s/frequency')
    expect(call).toHaveBeenLastCalledWith('simengbay_panel_data', { path: '/simulations/studies/s/frequency' })
    expect(got.status).toBe(200)
    expect(await got.json()).toEqual({ study_id: 's' })
    await send('/simulations/studies/s/frequency/check', { method: 'POST', body: JSON.stringify({ requirements: [] }) })
    expect(call).toHaveBeenLastCalledWith('simengbay_panel_data', {
      path: '/simulations/studies/s/frequency/check',
      body: { requirements: [] },
    })
  })

  it('바꾸는 요청은 부르지 않고 405 — 패널은 읽기만 한다', async () => {
    const call = vi.fn()
    const send = panelTransport(call)
    const put = await send('/simulations/studies/s/frequency', { method: 'PUT', body: '{}' })
    expect(put.status).toBe(405)
    expect((await put.json()).error.message).toMatch('읽기만')
    expect((await send('/simulations/x/measurements', { method: 'POST', body: new FormData() })).status).toBe(405)
    expect(call).not.toHaveBeenCalled()
  })

  it('산출물 파일(3D 형상)은 받지 않고 빈 것을 준다', async () => {
    const call = vi.fn()
    const got = await panelTransport(call)('/simulations/j/artifacts/a/content')
    expect(got.status).toBe(200)
    expect((await got.arrayBuffer()).byteLength).toBe(0)
    expect(call).not.toHaveBeenCalled()
  })

  it('백엔드 오류는 봉투째, 도구 오류는 문구 속 상태로 — 화면의 오류 표시가 웹과 같다', async () => {
    const call = vi
      .fn()
      .mockResolvedValueOnce(answer(404, { error: { code: 'SEB-SIMULATIONS-0404', message: '없습니다' } }))
      .mockResolvedValueOnce({ isError: true, content: [{ type: 'text', text: 'Error executing tool panel_data: GET /api/simulations/x → HTTP 401: 만료' }] })
      .mockRejectedValueOnce(new Error('호스트가 답하지 않았습니다'))
    const send = panelTransport(call)
    const missing = await send('/simulations/x')
    expect(missing.status).toBe(404)
    expect((await missing.json()).error.code).toBe('SEB-SIMULATIONS-0404')
    expect((await send('/simulations/x')).status).toBe(401)
    const lost = await send('/simulations/x')
    expect(lost.status).toBe(502)
    expect((await lost.json()).error.message).toBe('호스트가 답하지 않았습니다')
  })
})

describe('API 클라이언트의 길 바꾸기', () => {
  it('길을 바꾸면 같은 api.get 이 그 길로 가고, 오류는 ApiError 로 읽힌다', async () => {
    const call = vi.fn().mockResolvedValueOnce(answer(200, { ok: 1 })).mockResolvedValueOnce(answer(403, { error: { code: 'X', message: '권한 없음' } }))
    setTransport(panelTransport(call))
    expect(await api.get('/simulations/a')).toEqual({ ok: 1 })
    await expect(api.get('/simulations/b')).rejects.toMatchObject({ status: 403, message: '권한 없음' })
  })
})
