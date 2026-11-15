export const HEX_W = 108, HEX_H = 125 // pointy-top
export const ORIGIN = { x: 8, y: 8 } // arcs are centred on the screen corner
export const CLIP = 'polygon(50% 0,100% 25%,100% 75%,50% 100%,0 75%,0 25%)'

export type CellId = 'alerts' | 'protocols' | 'history' | 'status' | 'crew' | 'env'
/** R = radius, deg = angle from the bottom edge. */
export const CELLS: { id: CellId; label: string; R: number; deg: number }[] = [
  { id: 'alerts', label: 'Allarmi', R: 295, deg: 79 },
  { id: 'protocols', label: 'Protocolli', R: 175, deg: 25 },
  { id: 'history', label: 'Storico', R: 175, deg: 65 },
  { id: 'status', label: 'Stato', R: 295, deg: 13 },
  { id: 'crew', label: 'Crew', R: 295, deg: 35 },
  { id: 'env', label: 'Ambiente', R: 295, deg: 57 },
]

export function cellPosition(R: number, deg: number) {
  const rad = (deg * Math.PI) / 180
  const cx = ORIGIN.x + R * Math.cos(rad)
  const cy = ORIGIN.y + R * Math.sin(rad)
  return { left: cx - HEX_W / 2, bottom: cy - HEX_H / 2 }
}
