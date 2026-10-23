/**
 * 고른 것 여럿에 같은 일을 — 목록의 체크박스(게시 · 게시 해제 · 삭제).
 *
 * **하나씩 부르고, 못 한 것은 까닭을 모은다** — 하나가 막혔다고 멈추면 나머지가 안 되고, 까닭을
 * 버리면 사람은 무엇이 남았는지 모른다(끝나지 않은 작업은 게시가 안 되고, 도는 작업은 지우지 않는다
 * — 서버가 그 말을 한다). 권한 · 상태 판정은 서버가 한다 — 화면이 미리 거르면 두 벌이 된다.
 */

export interface BulkTarget {
  id: string
  name: string
}

export interface BulkResult {
  done: number
  failed: { name: string; message: string }[]
}

export async function eachOf(
  targets: BulkTarget[],
  run: (id: string) => Promise<unknown>,
): Promise<BulkResult> {
  const result: BulkResult = { done: 0, failed: [] }
  for (const one of targets) {
    try {
      await run(one.id)
      result.done += 1
    } catch (caught) {
      result.failed.push({ name: one.name, message: caught instanceof Error ? caught.message : '실패' })
    }
  }
  return result
}

/** 「3개를 게시했습니다. 하지 못한 것: 이름 — 까닭 · …」 */
export function bulkNotice(verb: string, noun: string, result: BulkResult): string {
  const head = `${noun} ${result.done}개를 ${verb}했습니다.`
  if (result.failed.length === 0) return head
  return `${head} 하지 못한 것 ${result.failed.length}개: ${result.failed
    .map((one) => `${one.name} — ${one.message}`)
    .join(' · ')}`
}
