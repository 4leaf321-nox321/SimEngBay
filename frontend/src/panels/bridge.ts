/**
 * 대화 안 결과 화면(MCP Apps 패널)의 **호스트 다리** — JSON-RPC 2.0 · postMessage, 판 `2026-01-26`.
 *
 * 패널은 HWAX 챗 · Claude 데스크톱 · 웹이 도구 결과 아래에 띄운 **격리 창**(srcdoc ·
 * `sandbox="allow-scripts"` · CSP `connect-src 'none'`) 안에서 돈다. 서버에 직접 닿지 못하고, 할 수
 * 있는 것은 부모 창(호스트)과 메시지를 주고받는 것뿐이다.
 *
 *   패널 → 호스트  `ui/initialize`(답: 판 · 테마 · 언어 · 연 도구 이름) → `ui/notifications/initialized`
 *   호스트 → 패널  `ui/notifications/tool-input`(인자) · `ui/notifications/tool-result`(결과) — 열 때 한 번
 *   패널 → 호스트  `tools/call`(호스트가 그 앱의 도구를 대신 부른다) · `ui/open-link` ·
 *                  `ui/notifications/size-changed`
 *   호스트 → 패널  `ui/resource-teardown`(닫는다) · `ping` · `ui/notifications/host-context-changed`
 *
 * HWAX 가 받지 않는 것(`ui/message` · `ui/update-model-context` · 표시 모드)은 쓰지 않는다 — 두
 * 호스트에서 같은 코드가 돈다(HWAXPortal `docs/chat-embeds/stepforge-request.md` 3절).
 */

export const PROTOCOL_VERSION = '2026-01-26'

export interface ToolContent {
  type: string
  text?: string
}

export interface ToolResult {
  content?: ToolContent[]
  structuredContent?: unknown
  isError?: boolean
  _meta?: unknown
}

export interface HostContext {
  theme?: 'light' | 'dark'
  locale?: string
  timeZone?: string
  /** 이 패널을 연 도구 — 게이트웨이가 붙인 이름 그대로다(접두가 붙을 수 있다). */
  toolInfo?: { tool?: { name?: string } }
}

interface Message {
  jsonrpc: '2.0'
  id?: string | number
  method?: string
  params?: Record<string, unknown>
  result?: unknown
  error?: { code: number; message: string }
}

interface Pending {
  resolve: (value: unknown) => void
  reject: (reason: Error) => void
  timer: number
}

type Listener<T> = (value: T) => void

export class BridgeError extends Error {
  readonly code: number
  constructor(code: number, message: string) {
    super(message)
    this.name = 'BridgeError'
    this.code = code
  }
}

function isMessage(data: unknown): data is Message {
  return !!data && typeof data === 'object' && (data as Message).jsonrpc === '2.0'
}

/**
 * 결과의 자료 — `structuredContent` 가 있으면 그것, 없으면 첫 글 조각을 JSON 으로. SimEngBay 도구는
 * dict 를 돌려주고 FastMCP 는 그것을 JSON 글 조각으로 싣는다.
 */
export function resultData(result: ToolResult | null | undefined): unknown {
  if (!result) return undefined
  if (result.structuredContent && typeof result.structuredContent === 'object') return result.structuredContent
  const text = result.content?.find((one) => one.type === 'text' && typeof one.text === 'string')?.text
  if (text == null) return undefined
  try {
    return JSON.parse(text)
  } catch {
    return text
  }
}

/** 결과의 첫 글 — 오류 결과(`isError`)의 문구를 사람에게 보일 때. */
export function resultText(result: ToolResult | null | undefined): string {
  return result?.content?.find((one) => one.type === 'text')?.text ?? ''
}

/**
 * 게이트웨이가 도구 이름에 붙인 접두 — 연 도구가 `simengbay_study_frequency` 로 보였다면 패널이
 * 부르는 `panel_data` 도 `simengbay_panel_data` 다(겹치는 이름에만 붙는다). 모르면 빈 접두.
 */
export function toolPrefix(hostName: string | undefined, base: string): string {
  if (!hostName || !hostName.endsWith(base)) return ''
  return hostName.slice(0, hostName.length - base.length)
}

export class Bridge {
  hostContext: HostContext = {}
  private seq = 0
  private readonly pending = new Map<string | number, Pending>()
  private readonly inputs = new Set<Listener<Record<string, unknown>>>()
  private readonly results = new Set<Listener<ToolResult>>()
  private readonly contexts = new Set<Listener<HostContext>>()
  private readonly teardowns = new Set<Listener<void>>()
  private readonly target: Window

  constructor(target: Window = window.parent) {
    this.target = target
    window.addEventListener('message', this.onMessage)
  }

  /** 호스트와 손을 잡는다 — 답이 없으면(호스트 밖에서 열었다) 오류. */
  async connect(appInfo: { name: string; version: string }, timeoutMs = 8000): Promise<HostContext> {
    // 맨 위 창이다 — 파일을 브라우저로 바로 열었다. 기다리지 않는다.
    if (this.target === window) throw new BridgeError(-32000, '호스트(부모 창)가 없습니다')
    const answer = (await this.request(
      'ui/initialize',
      { protocolVersion: PROTOCOL_VERSION, appInfo, appCapabilities: {} },
      timeoutMs,
    )) as { hostContext?: HostContext } | null
    this.hostContext = answer?.hostContext ?? {}
    this.notify('ui/notifications/initialized', {})
    return this.hostContext
  }

  request(method: string, params: Record<string, unknown>, timeoutMs = 120_000): Promise<unknown> {
    this.seq += 1
    const id = `p${this.seq}`
    return new Promise((resolve, reject) => {
      const timer = window.setTimeout(() => {
        this.pending.delete(id)
        reject(new BridgeError(-32000, `호스트가 ${method} 에 답하지 않았습니다`))
      }, timeoutMs)
      this.pending.set(id, { resolve, reject, timer })
      this.post({ jsonrpc: '2.0', id, method, params })
    })
  }

  notify(method: string, params: Record<string, unknown>): void {
    this.post({ jsonrpc: '2.0', method, params })
  }

  /** 호스트가 그 앱의 도구를 대신 부른다 — 이름은 접두까지 붙인 노출 이름이다. */
  async callTool(name: string, args: Record<string, unknown>): Promise<ToolResult> {
    return ((await this.request('tools/call', { name, arguments: args })) ?? {}) as ToolResult
  }

  openLink(url: string): Promise<unknown> {
    return this.request('ui/open-link', { url }, 10_000)
  }

  sendSize(height: number): void {
    this.notify('ui/notifications/size-changed', { height: Math.ceil(height) })
  }

  onInput(listener: Listener<Record<string, unknown>>): () => void {
    this.inputs.add(listener)
    return () => this.inputs.delete(listener)
  }

  onResult(listener: Listener<ToolResult>): () => void {
    this.results.add(listener)
    return () => this.results.delete(listener)
  }

  onContext(listener: Listener<HostContext>): () => void {
    this.contexts.add(listener)
    return () => this.contexts.delete(listener)
  }

  onTeardown(listener: Listener<void>): () => void {
    this.teardowns.add(listener)
    return () => this.teardowns.delete(listener)
  }

  close(): void {
    window.removeEventListener('message', this.onMessage)
    for (const one of this.pending.values()) {
      window.clearTimeout(one.timer)
      one.reject(new BridgeError(-32000, '패널이 닫혔습니다'))
    }
    this.pending.clear()
  }

  private post(message: Message): void {
    // 격리 창이라 우리 출처는 'null' 이고 호스트의 출처도 모른다 — 받는 쪽이 창(event.source)으로 가린다.
    this.target.postMessage(message, '*')
  }

  private reply(id: string | number, result: unknown): void {
    this.post({ jsonrpc: '2.0', id, result })
  }

  private readonly onMessage = (event: MessageEvent): void => {
    // 부모 창(호스트)이 보낸 것만 — 같은 창 안의 다른 것(확장 등)이 흉내 내지 못하게.
    if (event.source !== this.target || !isMessage(event.data)) return
    const message = event.data
    if (message.method === undefined) {
      if (message.id === undefined) return
      const waiting = this.pending.get(message.id)
      if (!waiting) return
      this.pending.delete(message.id)
      window.clearTimeout(waiting.timer)
      if (message.error) waiting.reject(new BridgeError(message.error.code, message.error.message))
      else waiting.resolve(message.result)
      return
    }
    const params = message.params ?? {}
    switch (message.method) {
      case 'ui/notifications/tool-input': {
        const args = params.arguments
        const value = args && typeof args === 'object' && !Array.isArray(args) ? (args as Record<string, unknown>) : {}
        this.inputs.forEach((listener) => listener(value))
        return
      }
      case 'ui/notifications/tool-result':
        this.results.forEach((listener) => listener(params as ToolResult))
        return
      case 'ui/notifications/host-context-changed':
        this.hostContext = { ...this.hostContext, ...(params as HostContext) }
        this.contexts.forEach((listener) => listener(this.hostContext))
        return
      case 'ui/resource-teardown':
        this.teardowns.forEach((listener) => listener())
        if (message.id !== undefined) this.reply(message.id, {})
        return
      case 'ping':
        if (message.id !== undefined) this.reply(message.id, {})
        return
      default:
        // 모르는 요청은 오류로 답한다 — 조용히 삼키면 호스트가 기다리다 끝난다.
        if (message.id !== undefined)
          this.post({ jsonrpc: '2.0', id: message.id, error: { code: -32601, message: `모르는 메서드: ${message.method}` } })
    }
  }
}
