/**
 * **여러 3D 뷰어의 시점을 하나로** — 한 칸에서 돌리거나 확대하면 다른 칸이 같은 시점을 따른다.
 *
 * 모달 결과의 「여러 개 보기」 가 쓴다. 모드끼리 견주려면 같은 쪽에서 같은 크기로 봐야 하는데, 칸마다
 * 따로 돌려 맞추는 것은 사람이 할 일이 아니다. 모든 칸이 **같은 형상(같은 좌표계)** 을 그리므로
 * 카메라 상태를 그대로 옮기면 된다.
 *
 * - 꺼 둔 동안에도 마지막으로 움직인 시점은 기억한다 — 다시 켜면 모두 그 시점으로 모인다.
 * - 새로 뜬 뷰어(쪽을 넘겼다)는 켜져 있으면 지금 시점으로 시작한다.
 * - 옮겨 받은 뷰어는 다시 퍼뜨리지 않는다(뷰어 쪽 `applying` 표시) — 안 그러면 서로 되받아 돈다.
 *
 * **vtk.js 를 부르지 않는다** — 화면이 이것을 만들 때 vtk.js 덩어리가 따라오면 안 된다
 * (`MeshViewer` 만 vtk.js 를, 그것도 쓸 때만 받는다).
 */

export interface CameraState {
  position: number[]
  focalPoint: number[]
  viewUp: number[]
  viewAngle: number
  parallelScale: number
}

export interface CameraMember {
  /** 이 시점으로 맞추고 다시 그린다. */
  apply: (state: CameraState) => void
  /** 처음 시점(비스듬히)으로 돌린다. */
  reset: () => void
}

export class CameraSync {
  private readonly members = new Set<CameraMember>()
  private last: CameraState | null = null
  private on: boolean

  constructor(enabled = true) {
    this.on = enabled
  }

  get enabled(): boolean {
    return this.on
  }

  /** 뷰어가 들어온다 — 켜져 있고 기억한 시점이 있으면 그것으로 시작한다. 나갈 때 부를 함수를 준다. */
  join(member: CameraMember): () => void {
    this.members.add(member)
    if (this.on && this.last) member.apply(this.last)
    return () => {
      this.members.delete(member)
    }
  }

  /** 한 뷰어의 시점이 바뀌었다 — 기억하고, 켜져 있으면 나머지에 옮긴다. */
  publish(from: CameraMember, state: CameraState): void {
    this.last = state
    if (!this.on) return
    for (const one of this.members) {
      if (one !== from) one.apply(state)
    }
  }

  /** 켜면 마지막으로 움직인 시점으로 모두 모은다. */
  setEnabled(on: boolean): void {
    this.on = on
    if (on && this.last) {
      for (const one of this.members) one.apply(this.last)
    }
  }

  /** 모두 처음 시점으로. */
  resetAll(): void {
    this.last = null
    for (const one of this.members) one.reset()
  }
}
