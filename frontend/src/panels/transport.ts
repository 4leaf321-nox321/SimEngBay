/**
 * 패널의 요청 길 — `simulationApi` 가 보내는 `/simulations/…` 요청을 MCP 도구 `panel_data` 호출로
 * 바꾼다(호스트가 대신 부른다). 답(`{status, body}`)을 `Response` 로 되돌려 API 클라이언트가 웹과
 * 똑같이 읽는다 — 오류 봉투도 그대로라 화면의 오류 표시가 같다.
 *
 * **읽기만 한다.** GET 과 읽기인 POST(판정 미리 보기)만 보내고, 저장 · 삭제는 여기서 막는다 —
 * 패널에서 바꾸는 일은 웹 화면에서 한다.
 */

import type { Transport } from '@/shared/api/client'
import type { ToolResult } from '@/panels/bridge'
import { resultData, resultText } from '@/panels/bridge'

export type CallTool = (name: string, args: Record<string, unknown>) => Promise<ToolResult>

function envelope(status: number, message: string): Response {
  return new Response(JSON.stringify({ error: { code: 'MCP-PANEL-0002', message } }), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

/** 오류 결과의 문구에서 백엔드의 상태를 읽는다 — `GET /api/… → HTTP 401: …` 꼴(게이트웨이 신호). */
function statusOf(text: string): number {
  const found = /→ HTTP (\d{3})/.exec(text)
  return found ? Number(found[1]) : 502
}

/** 산출물 파일(3D 형상 VTP 등) — 패널은 받지 않는다. 바이너리를 도구 결과(JSON 글)로 옮길 수 없고, 받아도
 *  그릴 뷰어(vtk.js)가 패널 묶음에 없다(`MeshNote` 가 그 자리에 선다). */
const ARTIFACT_CONTENT = /^\/simulations\/[^/]+\/artifacts(\.zip|\/[^/]+\/content)/

export function panelTransport(call: CallTool, tool = 'panel_data'): Transport {
  return async (path, init) => {
    // 빈 것을 준다 — 형상을 받는 부품이 오류 대신 「뷰어 자리」 로 넘어가 거기 MeshNote 가 선다.
    if (ARTIFACT_CONTENT.test(path)) return new Response(new ArrayBuffer(0), { status: 200 })
    const method = (init?.method ?? 'GET').toUpperCase()
    if ((method !== 'GET' && method !== 'POST') || init?.body instanceof FormData) {
      return envelope(405, '대화 안의 화면에서는 읽기만 합니다 — 바꾸는 일은 SimEngBay 화면에서 하세요.')
    }
    const args: Record<string, unknown> = { path }
    if (method === 'POST') {
      try {
        args.body = init?.body ? JSON.parse(String(init.body)) : {}
      } catch {
        return envelope(400, '요청 본문을 읽지 못했습니다.')
      }
    }
    let result: ToolResult
    try {
      result = await call(tool, args)
    } catch (caught) {
      return envelope(502, caught instanceof Error ? caught.message : '호스트가 자료를 가져오지 못했습니다.')
    }
    if (result.isError) {
      const text = resultText(result)
      return envelope(statusOf(text), text || '자료를 가져오지 못했습니다.')
    }
    const data = resultData(result) as { status?: unknown; body?: unknown } | undefined
    const status = typeof data?.status === 'number' && data.status >= 200 && data.status <= 599 ? data.status : 502
    if (status === 204 || data?.body == null) return new Response(null, { status: status === 200 ? 204 : status })
    return new Response(JSON.stringify(data.body), { status, headers: { 'Content-Type': 'application/json' } })
  }
}
