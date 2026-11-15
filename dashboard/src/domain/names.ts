/** Human names for everything the engine calls by an id. One place, so the whole UI speaks the same way. */

/** ISS volumes (scenarios/station/modules.yaml) plus our own `lifeboat` and `eva`. Unknown ids are shown as they are. */
const MODULE_NAME: Record<string, string> = {
  NOD1: 'Unity', USL: 'Destiny Lab', NOD2: 'Harmony', NOD3: 'Tranquility', COL: 'Columbus Lab', JPM: 'Kibo Lab', CUP: 'Cupola',
  AL: 'Airlock', SM: 'Service Module', PRK: 'Transfer Chamber',
  CQ1: 'Crew Quarters 1', CQ2: 'Crew Quarters 2', CQ3: 'Crew Quarters 3', CQ4: 'Crew Quarters 4',
  LIFEBOAT: 'Lifeboat', EVA: 'Spacewalk',
}
export const moduleName = (id: string) => MODULE_NAME[id.toUpperCase()] ?? id.toUpperCase()

/** The engine's own words for what it is looking at (alarm `metric`), in plain language. Technical name stays in `tech`. */
export const METRIC_NAME: Record<string, { label: string; tech: string }> = {
  temp: { label: 'Temperature', tech: 'Air temperature' },
  rh: { label: 'Humidity', tech: 'Relative humidity' },
  pio2: { label: 'Breathable oxygen', tech: 'PIO₂, inspired oxygen pressure' },
  ppco2: { label: 'Carbon dioxide', tech: 'ppCO₂, CO₂ partial pressure' },
  pressure: { label: 'Cabin pressure', tech: 'Total air pressure' },
  co: { label: 'Carbon monoxide', tech: 'CO, parts per million' },
}

/** How hard a person is working, from the metabolic equivalent (1 MET = sitting still). */
export function effortLabel(met: number): string {
  if (!Number.isFinite(met)) return '—'
  return met < 1.6 ? 'Resting' : met < 3 ? 'Light effort' : met < 6 ? 'Moderate effort' : 'Hard effort'
}
