/**
 * 패널의 호스트 다리 — HWAX 포털 · Claude 가 패널과 주고받는 JSON-RPC(판 2026-01-26)를 흉내 낸다.
 * 호스트는 iframe 의 창으로 세운다(jsdom 의 MessageEvent 는 source 에 진짜 창만 받는다).
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { Bridge, BridgeError, PROTOCOL_VERSION, resultData, resultText, toolPrefix } from '@/panels/bridge'

let host: Window
let sent: Record<string, unknown>[]
let bridge: Bridge

function fromHost(data: unknown, source: Window = host) {
  window.dispatchEvent(new MessageEvent('message', { data, source }))
}

beforeEach(() => {
  const frame = document.createElement('iframe')
  document.body.append(frame)
  host = frame.contentWindow as Window
  sent = []
  vi.spyOn(host, 'postMessage').mockImplementation((message: unknown) => {
    sent.push(message as Record<string, unknown>)
  })
  bridge = new Bridge(host)
})

afterEach(() => {
  bridge.close()
  document.body.innerHTML = ''
  vi.restoreAllMocks()
})

describe('손잡기', () => {
  it('ui/initialize 를 보내고 답의 테마 · 연 도구를 쥔 뒤 initialized 를 알린다', async () => {
    const connected = bridge.connect({ name: 'simengbay-panel', version: 'v1' })
    expect(sent[0]).toMatchObject({ jsonrpc: '2.0', method: 'ui/initialize', params: { protocolVersion: PROTOCOL_VERSION } })
    fromHost({
      jsonrpc: '2.0',
      id: sent[0].id,
      result: { protocolVersion: PROTOCOL_VERSION, hostContext: { theme: 'dark', toolInfo: { tool: { name: 'simengbay_study_frequency' } } } },
    })
    const context = await connected
    expect(context.theme).toBe('dark')
    expect(sent[1]).toEqual({ jsonrpc: '2.0', method: 'ui/notifications/initialized', params: {} })
  })

  it('다른 창이 보낸 답은 받지 않는다 — 같은 페이지의 다른 것이 흉내 내지 못하게', async () => {
    const connected = bridge.connect({ name: 'p', version: 'v' }, 50)
    fromHost({ jsonrpc: '2.0', id: sent[0].id, result: {} }, window)
    await expect(connected).rejects.toBeInstanceOf(BridgeError)
  })
})

describe('호스트 → 패널', () => {
  it('도구 인자 · 결과 · 테마 바뀜을 알린다', () => {
    const inputs: unknown[] = []
    const results: unknown[] = []
    const themes: unknown[] = []
    bridge.onInput((args) => inputs.push(args))
    bridge.onResult((result) => results.push(resultData(result)))
    bridge.onContext((context) => themes.push(context.theme))
    fromHost({ jsonrpc: '2.0', method: 'ui/notifications/tool-input', params: { arguments: { study_id: 's1' } } })
    fromHost({ jsonrpc: '2.0', method: 'ui/notifications/tool-result', params: { content: [{ type: 'text', text: '{"study_id":"s1"}' }] } })
    fromHost({ jsonrpc: '2.0', method: 'ui/notifications/host-context-changed', params: { theme: 'light' } })
    expect(inputs).toEqual([{ study_id: 's1' }])
    expect(results).toEqual([{ study_id: 's1' }])
    expect(themes).toEqual(['light'])
  })

  it('닫기(teardown)와 ping 에 답하고, 모르는 요청은 오류로 답한다', () => {
    const closed = vi.fn()
    bridge.onTeardown(closed)
    fromHost({ jsonrpc: '2.0', id: 't1', method: 'ui/resource-teardown', params: {} })
    fromHost({ jsonrpc: '2.0', id: 't2', method: 'ping' })
    fromHost({ jsonrpc: '2.0', id: 't3', method: 'ui/unknown' })
    expect(closed).toHaveBeenCalledOnce()
    expect(sent).toEqual([
      { jsonrpc: '2.0', id: 't1', result: {} },
      { jsonrpc: '2.0', id: 't2', result: {} },
      { jsonrpc: '2.0', id: 't3', error: { code: -32601, message: '모르는 메서드: ui/unknown' } },
    ])
  })
})

describe('패널 → 호스트', () => {
  it('도구를 대신 부르게 하고 답을 돌려준다 — 오류면 BridgeError', async () => {
    const called = bridge.callTool('simengbay_panel_data', { path: '/simulations/x' })
    expect(sent[0]).toMatchObject({ method: 'tools/call', params: { name: 'simengbay_panel_data', arguments: { path: '/simulations/x' } } })
    fromHost({ jsonrpc: '2.0', id: sent[0].id, result: { content: [{ type: 'text', text: '{"status":200}' }] } })
    expect(resultData(await called)).toEqual({ status: 200 })

    const refused = bridge.callTool('job_cancel', {})
    fromHost({ jsonrpc: '2.0', id: sent[1].id, error: { code: -32000, message: '이 패널은 job_cancel 을(를) 부를 수 없다' } })
    await expect(refused).rejects.toThrow('부를 수 없다')
  })

  it('높이를 알린다', () => {
    bridge.sendSize(812.3)
    expect(sent[0]).toEqual({ jsonrpc: '2.0', method: 'ui/notifications/size-changed', params: { height: 813 } })
  })
})

describe('결과 읽기 · 접두', () => {
  it('structuredContent 가 있으면 그것, 없으면 첫 글 조각을 JSON 으로', () => {
    expect(resultData({ structuredContent: { a: 1 }, content: [{ type: 'text', text: '{"a":2}' }] })).toEqual({ a: 1 })
    expect(resultData({ content: [{ type: 'text', text: '{"a":2}' }] })).toEqual({ a: 2 })
    expect(resultData({ content: [{ type: 'text', text: '글' }] })).toBe('글')
    expect(resultData(undefined)).toBeUndefined()
    expect(resultText({ isError: true, content: [{ type: 'text', text: '실패' }] })).toBe('실패')
  })

  it('게이트웨이가 붙인 접두를 연 도구 이름에서 가려낸다', () => {
    expect(toolPrefix('simengbay_study_frequency', 'study_frequency')).toBe('simengbay_')
    expect(toolPrefix('study_frequency', 'study_frequency')).toBe('')
    expect(toolPrefix(undefined, 'study_frequency')).toBe('')
    expect(toolPrefix('other_tool', 'study_frequency')).toBe('')
  })
})
