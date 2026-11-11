/**
 * 계정 아이디 → 메일 「받는 사람」 칸에 붙여 넣을 한 줄.
 *
 * **아이디가 곧 메일 주소는 아니다** — 아이디는 이메일 형식을 강제하지 않아(`accounts/schemas.py`
 * 의 `_ID_FIELD`) 설치 때 만든 `admin` 같은 짧은 아이디가 있다. `@` 앞뒤가 비지 않은 것만 싣고
 * 뺀 것을 돌려준다 — 조용히 빼면 받는 사람이 하나 모자란 줄 아무도 모른다.
 *
 * 가르는 글자는 `; ` 다. Outlook 이 받는 사람을 가르는 글자이고, 웹 메일도 그대로 받는다.
 */
export interface MailLine {
  line: string
  count: number
  skipped: string[]
}

const ADDRESS = /^[^\s@]+@[^\s@]+$/

export function mailLine(ids: string[]): MailLine {
  const seen = new Set<string>()
  const addresses: string[] = []
  const skipped: string[] = []
  for (const raw of ids) {
    const id = raw.trim()
    const key = id.toLowerCase()
    if (!id || seen.has(key)) continue
    seen.add(key)
    if (ADDRESS.test(id)) addresses.push(id)
    else skipped.push(id)
  }
  return { line: addresses.join('; '), count: addresses.length, skipped }
}
