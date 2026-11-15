export const CLIP = 'polygon(50% 0,100% 25%,100% 75%,50% 100%,0 75%,0 25%)'

/** Closed menu button (pointy-top hexagon) and its centre from the screen corner. */
export const TRIGGER = { w: 84, h: 97, cx: 62, cy: 62 }
/** Open menu cells. */
export const CELL = { w: 88, h: 101 }

export type CellId = 'status' | 'crew' | 'alerts' | 'protocols' | 'history'
/** Nearest to the thumb first (see `cellOffset`). */
export const CELLS: { id: CellId; label: string }[] = [
  { id: 'status', label: 'Status' },
  { id: 'crew', label: 'Crew' },
  { id: 'alerts', label: 'Alarms' },
  { id: 'protocols', label: 'Protocols' },
  { id: 'history', label: 'History' },
]

/**
 * The open menu is a small honeycomb packed against the corner (it used to be an arc of radius 335 px: out of a thumb's reach when the
 * iPad is held with both hands). Hexagons tile with a pitch `P` along 0 deg and 60 deg; the five cells fill the nearest spots, so the
 * farthest centre is ~190 px from the trigger (about 4 cm on an iPad 9, a comfortable thumb stretch).
 */
const P = CELL.w + 6
const U = { x: P, y: 0 }
const V = { x: P / 2, y: (P * Math.sqrt(3)) / 2 }
/** In `CELLS` order, nearest first: the two neighbours of the trigger, then the ring behind them. */
const SPOTS = [U, V, { x: U.x + V.x, y: V.y }, { x: 2 * U.x, y: 0 }, { x: 2 * V.x, y: 2 * V.y }]

/** Offset of cell `k` from the trigger centre (x right, y up), px. */
export function cellOffset(k: number) {
  return SPOTS[k]
}
