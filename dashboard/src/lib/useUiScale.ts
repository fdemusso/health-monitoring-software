import { useSyncExternalStore } from 'react'

/** Root font size over the 16 px the design is drawn at (see `html` in index.css): 1 on an iPad 9, more on bigger screens. */
const read = () => parseFloat(getComputedStyle(document.documentElement).fontSize) / 16 || 1
const subscribe = (cb: () => void) => {
  window.addEventListener('resize', cb)
  return () => window.removeEventListener('resize', cb)
}

/** For the few sizes that are computed in JS pixels (SVG, the corner menu's arc): multiply them by this, everything else uses rem. */
export const useUiScale = () => useSyncExternalStore(subscribe, read, () => 1)
