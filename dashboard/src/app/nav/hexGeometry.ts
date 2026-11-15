export const CLIP = 'polygon(50% 0,100% 25%,100% 75%,50% 100%,0 75%,0 25%)'

/** Closed menu button (pointy-top hexagon) and its centre from the screen corner. */
export const TRIGGER = { w: 84, h: 97, cx: 62, cy: 62 }
/** Open menu cells, on one arc centred on the trigger. */
export const CELL = { w: 88, h: 101 }
const ARC = { R: 335, startDeg: 10, stepDeg: 18 }

export type CellId = 'status' | 'crew' | 'alerts' | 'protocols' | 'history'
/** In arc order, from the bottom. */
export const CELLS: { id: CellId; label: string }[] = [
  { id: 'status', label: 'Status' },
  { id: 'crew', label: 'Crew' },
  { id: 'alerts', label: 'Alarms' },
  { id: 'protocols', label: 'Protocols' },
  { id: 'history', label: 'History' },
]

/** Offset of cell `k` from the trigger centre (x right, y up), px. */
export function cellOffset(k: number) {
  const rad = ((ARC.startDeg + k * ARC.stepDeg) * Math.PI) / 180
  return { x: ARC.R * Math.cos(rad), y: ARC.R * Math.sin(rad) }
}
