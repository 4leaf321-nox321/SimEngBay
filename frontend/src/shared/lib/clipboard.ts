/**
 * 복사 — **http 에서도 된다.** `navigator.clipboard` 는 보안 컨텍스트(https · localhost)에만 있어,
 * 메인 서버 없이 IP 로 직접 보는 동안(http)은 없다. 그때는 옛 방식(숨은 textarea + execCommand)으로.
 *
 * **표도 클립보드로 나른다** — 회사 PC 는 로컬에 저장한 파일에 DRM 이 걸려, 내려받은 양식 · 올리는
 * 표 파일이 다른 프로그램에서 안 열린다(2026-10-05). 그래서 엑셀과는 복사 · 붙여넣기로 주고받는다.
 * 엑셀이 복사하는 모양은 **탭으로 가른 줄**(TSV)이다(`toTsv` · `parseGrid`). 붙여넣기는 칸에서
 * Ctrl+V(붙여넣기 이벤트)가 늘 되고, 단추로 읽는 것(`readText`)은 https 에서만 된다.
 */
export async function copyText(text: string): Promise<void> {
  if (typeof navigator !== 'undefined' && navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text)
      return
    } catch {
      // 아래 폴백으로
    }
  }
  const area = document.createElement('textarea')
  area.value = text
  area.setAttribute('readonly', '')
  area.style.position = 'fixed'
  area.style.opacity = '0'
  document.body.appendChild(area)
  area.select()
  try {
    if (!document.execCommand('copy')) throw new Error('copy failed')
  } finally {
    document.body.removeChild(area)
  }
}

/** 클립보드의 글 — 못 읽으면(http · 권한) null. 그때는 칸에서 Ctrl+V 하게 한다. */
export async function readText(): Promise<string | null> {
  try {
    if (typeof navigator !== 'undefined' && navigator.clipboard?.readText) {
      return await navigator.clipboard.readText()
    }
  } catch {
    // 권한을 막았다.
  }
  return null
}

/** 표 → 탭으로 가른 줄(엑셀에 붙여넣는 모양). */
export function toTsv(rows: string[][]): string {
  return rows.map((row) => row.map((cell) => cell.replace(/[\t\r\n]+/g, ' ')).join('\t')).join('\n')
}

/** 쉼표로 가른 한 줄 — 따옴표 안의 쉼표는 가르지 않는다. */
function splitCsv(line: string): string[] {
  const out: string[] = []
  let cell = ''
  let quoted = false
  for (let at = 0; at < line.length; at += 1) {
    const char = line[at]
    if (quoted) {
      if (char === '"' && line[at + 1] === '"') {
        cell += '"'
        at += 1
      } else if (char === '"') {
        quoted = false
      } else {
        cell += char
      }
    } else if (char === '"') {
      quoted = true
    } else if (char === ',') {
      out.push(cell)
      cell = ''
    } else {
      cell += char
    }
  }
  out.push(cell)
  return out
}

/** 붙여넣은 글 → 칸들. 탭이 있으면 탭(엑셀), 없으면 쉼표(CSV 를 글로 복사). 끝의 빈 줄은 뺀다. */
export function parseGrid(text: string): string[][] {
  const lines = text.replace(/\r\n?/g, '\n').replace(/\n+$/, '').split('\n')
  const tabbed = lines.some((line) => line.includes('\t'))
  return lines.map((line) => (tabbed ? line.split('\t') : splitCsv(line)).map((cell) => cell.trim()))
}
