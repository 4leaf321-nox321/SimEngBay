/**
 * 변형 그림의 위상 — 흔들 때는 sin, 멈췄거나 **흔들지 않는 그림(주기 0 — 정적)** 이면 1(최대 변형).
 *
 * 주기 0 을 그대로 나누면 sin(∞) = NaN 이고, 모든 좌표가 NaN 이 되어 **그림이 통째로 사라진다** —
 * 오류도 안 난다. 정적 결과의 3D 가 범례 · 단추만 남은 빈 상자이던 까닭이다(2026-10-23).
 */
export function warpPhase(elapsedMs: number, periodMs: number, playing: boolean): number {
  if (!playing || !animates(periodMs)) return 1
  const phase = Math.sin((2 * Math.PI * elapsedMs) / periodMs)
  return Number.isFinite(phase) ? phase : 1
}

/** 흔드는 그림인가 — 주기가 양수일 때만. 아니면 재생 단추도 뜻이 없다. */
export function animates(periodMs: number): boolean {
  return Number.isFinite(periodMs) && periodMs > 0
}
