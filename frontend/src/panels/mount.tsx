/**
 * 결과 화면(패널) 한 장의 틀 — 화면마다 `views/<화면>.tsx` 가 이것을 부른다.
 *
 * 1. 호스트와 손을 잡는다(`ui/initialize`). 답이 없으면 호스트 밖에서 연 것이다 — 그렇다고 말한다.
 * 2. 호스트의 테마(밝게 · 어둡게)를 따른다 — 패널만 하얗게 뜨지 않게.
 * 3. API 클라이언트의 길을 `panel_data` 로 바꾼다 — 화면 부품은 웹과 같은 `simulationApi` 를 부른다.
 * 4. 도구의 인자 · 결과를 기다려 화면이 필요한 것(스터디 id 등)을 고르면 그린다.
 * 5. 높이가 바뀔 때마다 호스트에 알린다(호스트가 창 높이를 맞춘다 — HWAX 는 120 ~ 1,200px).
 * 6. 링크를 누르면 패널 안에서 옮겨 가지 않는다 — 바깥 주소만 호스트에 열어 달라고 한다.
 */

import '@/index.css'

import { Component, useEffect, useState } from 'react'
import type { ErrorInfo, ReactNode } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'

import type { HostContext } from '@/panels/bridge'
import { Bridge, resultData, resultText, toolPrefix } from '@/panels/bridge'
import { panelTransport } from '@/panels/transport'
import { setTransport } from '@/shared/api/client'
import { NoUserProvider } from '@/shared/auth/AuthContext'

export interface PanelInput {
  /** 모델이 도구에 준 인자. */
  args: Record<string, unknown>
  /** 도구 결과의 자료(JSON). 아직 안 왔거나 호스트가 상한으로 뺐으면 undefined. */
  result: unknown
  /** 도구가 오류로 끝났으면 그 문구. */
  failed: string | null
}

export interface PanelSpec<T> {
  /** 이 화면을 여는 도구(접두 없는 이름) — 게이트웨이가 붙인 접두를 이것으로 가려낸다. */
  tool: string
  title: string
  /** 인자 · 결과에서 화면이 그릴 것을 고른다 — 아직 모자라면 null. */
  pick: (input: PanelInput) => T | null
  render: (picked: T) => ReactNode
}

/** 인자 · 결과를 이만큼 기다려도 못 고르면 그렇다고 말한다(받으면 그때 그린다). */
const WAIT_MS = 6000

export function text(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value.trim() : null
}

/** 결과(JSON 객체)의 칸 하나 — 고르기에서 쓴다. */
export function field(value: unknown, key: string): unknown {
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>)[key] : undefined
}

function applyTheme(context: HostContext): void {
  const dark = context.theme === 'dark'
  document.documentElement.classList.toggle('dark', dark)
  document.documentElement.style.colorScheme = dark ? 'dark' : 'light'
}

class Guard extends Component<{ children: ReactNode }, { error: Error | null }> {
  state: { error: Error | null } = { error: null }

  static getDerivedStateFromError(error: Error) {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('패널 화면 오류', error, info.componentStack)
  }

  render() {
    if (!this.state.error) return this.props.children
    return (
      <p className="text-destructive text-sm">
        화면을 그리다 멈췄습니다 — {this.state.error.message}. 결과 숫자는 대화의 도구 결과에 그대로 있습니다.
      </p>
    )
  }
}

function Note({ children }: { children: ReactNode }) {
  return <p className="text-muted-foreground text-sm">{children}</p>
}

function Panel<T>({ spec, bridge }: { spec: PanelSpec<T>; bridge: Bridge }) {
  const [phase, setPhase] = useState<'connecting' | 'open' | 'outside'>('connecting')
  const [input, setInput] = useState<PanelInput>({ args: {}, result: undefined, failed: null })
  const [late, setLate] = useState(false)

  useEffect(() => {
    // 듣기를 먼저 단다 — 호스트는 initialized 를 받자마자 인자 · 결과를 보낸다.
    const offInput = bridge.onInput((args) => setInput((now) => ({ ...now, args })))
    const offResult = bridge.onResult((result) =>
      setInput((now) => ({
        ...now,
        result: resultData(result),
        failed: result.isError ? resultText(result) || '도구가 오류로 끝났습니다.' : null,
      })),
    )
    const offContext = bridge.onContext(applyTheme)
    bridge
      .connect({ name: 'simengbay-panel', version: __APP_VERSION__ })
      .then((context) => {
        applyTheme(context)
        const prefix = toolPrefix(context.toolInfo?.tool?.name, spec.tool)
        setTransport(panelTransport((name, args) => bridge.callTool(`${prefix}${name}`, args)))
        setPhase('open')
      })
      .catch(() => setPhase('outside'))
    return () => {
      offInput()
      offResult()
      offContext()
    }
  }, [bridge, spec.tool])

  useEffect(() => {
    const timer = window.setTimeout(() => setLate(true), WAIT_MS)
    return () => window.clearTimeout(timer)
  }, [])

  if (phase === 'outside')
    return <Note>이 화면은 대화 안(HWAX 챗 · Claude)에서 도구 결과와 함께 열립니다.</Note>
  if (phase === 'connecting') return <Note>여는 중…</Note>
  if (input.failed) return <p className="text-destructive text-sm">{input.failed}</p>
  const picked = spec.pick(input)
  if (picked == null)
    return (
      <Note>
        {late
          ? '이 화면에 넘어온 도구 인자가 없습니다 — 대화에서 도구를 다시 부르면 그 결과로 열립니다.'
          : '도구 결과를 기다리는 중…'}
      </Note>
    )
  return <Guard>{spec.render(picked)}</Guard>
}

/**
 * 높이를 호스트에 알린다 — 그릴 때마다가 아니라 한 프레임에 한 번. **본문(body)의 높이**를 잰다 — 문서의
 * scrollHeight 는 창 높이 아래로 내려가지 않아, 짧은 탭으로 옮겨도 창이 줄지 않는다.
 */
function reportSize(bridge: Bridge): void {
  let queued = false
  let last = 0
  const send = () => {
    queued = false
    const height = document.body.offsetHeight
    if (Math.abs(height - last) < 2) return
    last = height
    bridge.sendSize(height)
  }
  new ResizeObserver(() => {
    if (queued) return
    queued = true
    window.requestAnimationFrame(send)
  }).observe(document.body)
}

/**
 * 링크 — 패널 안에서는 옮겨 가지 않는다(격리 창의 이동은 호스트가 패널을 닫는 신호다). 바깥
 * 주소(http · https)만 호스트에 열어 달라고 하고(호스트가 허용한 출처만 연다), 앱 안 경로는 막는다.
 */
function guardLinks(bridge: Bridge): void {
  document.addEventListener(
    'click',
    (event) => {
      const anchor = (event.target as Element | null)?.closest?.('a[href]')
      if (!anchor) return
      event.preventDefault()
      event.stopPropagation()
      const href = anchor.getAttribute('href') ?? ''
      if (/^https?:\/\//i.test(href)) void bridge.openLink(href).catch(() => undefined)
    },
    true,
  )
}

/** 앱 안 경로 링크는 패널에서 갈 곳이 없다 — 누르는 모양을 지워 글처럼 보인다(누름은 guardLinks 가 막는다). */
const INERT_LINKS = 'a[href^="/"]{pointer-events:none;cursor:default;text-decoration:none!important}'

export function mountPanel<T>(spec: PanelSpec<T>): void {
  document.title = `${spec.title} — SimEngBay`
  const style = document.createElement('style')
  style.textContent = INERT_LINKS
  document.head.append(style)
  const container = document.getElementById('root')
  if (!container) throw new Error('#root 를 찾을 수 없습니다')
  const bridge = new Bridge()
  bridge.onTeardown(() => setTransport(null))
  reportSize(bridge)
  guardLinks(bridge)
  // StrictMode 는 쓰지 않는다 — 개발에서 effect 를 두 번 돌려 호스트와 두 번 손을 잡는다.
  createRoot(container).render(
    <NoUserProvider>
      <MemoryRouter>
        <Panel spec={spec} bridge={bridge} />
      </MemoryRouter>
    </NoUserProvider>,
  )
}
