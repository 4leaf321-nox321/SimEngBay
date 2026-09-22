/** 해석 작업 화면이 쓰는 이름표 — 코드값을 사람의 말로. 한 곳에 두어 목록과 상세가 같은 말을 한다. */

export const STAGE_LABELS: Record<string, string> = {
  fetching: '형상 준비',
  modeling: 'FE 모델링',
  solving: '솔버',
  extracting: '결과 추출',
}

export const RECIPE_LABELS: Record<string, string> = {
  modal: '모달(고유진동수)',
  static: '정적',
}

export const ARTIFACT_LABELS: Record<string, string> = {
  input_step: '입력 형상',
  spec: '스펙',
  mechdb: 'Mechanical DB',
  dat: '솔버 입력(.dat)',
  solve_out: '솔버 로그',
  rst: '결과(.rst)',
  result_json: '결과 요약',
  mode_png: '모드 그림',
  mode_vtp: '모드 메시',
  log: '로그',
}

/** 실패 코드 → 사람이 무엇을 봐야 하는지. 코드만 보여 주면 「license」 를 읽고도 다음 할 일을 모른다. */
export const FAILURE_LABELS: Record<string, string> = {
  geometry_import: '형상을 읽지 못했습니다 — CAD 쪽 파일을 확인합니다',
  region_unresolved: '영역을 형상에서 찾지 못했습니다 — topology 와 형상이 같은 버전인지 확인합니다',
  mesh_failed: '메시 생성에 실패했습니다 — 요소 크기를 키우거나 형상을 확인합니다',
  solver_failed: '솔버가 실패했습니다 — 솔버 로그를 확인합니다',
  license: '라이선스를 받지 못했습니다 — 동시에 도는 작업 수와 라이선스 서버를 확인합니다',
  timeout: '제한 시간을 넘겼습니다',
  worker_lost: '워커가 응답하지 않았습니다 — 워커 프로세스를 확인합니다',
  internal: '내부 오류입니다 — 서버 로그를 확인합니다',
}

export function shownSize(bytes: number): string {
  if (bytes < 1024) return `${bytes}B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)}KB`
  return `${(bytes / 1024 / 1024).toFixed(1)}MB`
}

/** 걸린 시간 「1분 12초」. 초 단위까지만 — 해석은 분 · 시간 단위다. */
export function shownDuration(start: string | null | undefined, end: string | null | undefined): string {
  if (!start) return '—'
  const from = new Date(start).getTime()
  const to = end ? new Date(end).getTime() : Date.now()
  const seconds = Math.max(0, Math.round((to - from) / 1000))
  if (seconds < 60) return `${seconds}초`
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}분 ${seconds % 60}초`
  return `${Math.floor(minutes / 60)}시간 ${minutes % 60}분`
}
