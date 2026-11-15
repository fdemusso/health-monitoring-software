import { CAUSE_TEXT } from './causeText'
import { moduleName } from './names'

/** Human words for what the monitoring ML says. The backend sends sensor ids, feature names and (for the crew baseline) Italian sentences: this is the translation layer. */

/** The subsystems of the stage-A anomaly detectors (tools/ml/groups.yaml). */
const GROUP_TITLE: Record<string, string> = {
  atmosphere_pressure: 'Cabin pressure is behaving unusually',
  atmosphere_co2: 'Carbon dioxide removal is behaving unusually',
  atmosphere_o2: 'Oxygen supply is behaving unusually',
  thermal_humidity: 'Temperature and humidity are behaving unusually',
  ventilation: 'Air circulation is behaving unusually',
}

const METRIC: Record<string, string> = { T: 'temperature', RH: 'humidity', P: 'pressure', ppO2: 'oxygen', ppCO2: 'carbon dioxide', ppN2: 'nitrogen', ppH2O: 'water vapour' }
const CDRA: Record<string, string> = { T_letto_1: 'bed 1 temperature', T_letto_2: 'bed 2 temperature', I_soffiante: 'blower current', pos_ASV: 'valve position', P_W: 'power' }
const OGA: Record<string, string> = { V_stack: 'stack voltage', I_stack: 'stack current', H2_in_O2: 'hydrogen in the oxygen', Q_O2: 'oxygen flow' }
const FAN: Record<string, string> = { rpm: 'speed', I: 'current', Q: 'air flow', T_out: 'outlet temperature', cond: 'condensate', liq: 'liquid water' }
const OTHER: Record<string, string> = { pos_N2: 'nitrogen valve', P_tank_N2: 'nitrogen tank pressure', T_rad_out: 'radiator outlet temperature', Q_tot: 'heat load', P_gen: 'power generated', SOC_bat: 'battery charge' }

/** Plain name of a sensor id of scenarios/station/sensors.yaml: "imv_usl_fwd_rpm" -> "Air fan between modules (usl fwd), speed". */
function sensorName(id: string): string {
  const p = id.split('_')
  const head = p[0]
  const rest = p.slice(1)
  const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1)
  if (/^mca[AB]$/.test(head)) return `Air analyser ${head.slice(3)}, ${METRIC[rest[0]] ?? rest[0]}`
  if (/^cdra[AB]$/.test(head)) return `CO₂ scrubber ${head.slice(4)}, ${CDRA[rest.join('_')] ?? rest.join(' ')}`
  if (head === 'oga') return `Oxygen generator, ${OGA[rest.join('_')] ?? rest.join(' ')}`
  if (head === 'ccaa') return `Cabin cooler (${moduleName(rest[0])}), ${FAN[rest.slice(1).join('_')] ?? rest.slice(1).join(' ')}`
  if (head === 'imv') { const ch = rest[rest.length - 1]; return `Air fan between modules (${rest.slice(0, -1).join(' ')}), ${FAN[ch] ?? ch}` }
  if (head === 'pca' || head === 'tcs' || head === 'eps') return `${{ pca: 'Pressure control', tcs: 'Thermal loop', eps: 'Power' }[head]}, ${OTHER[rest.join('_')] ?? rest.join(' ')}`
  if (rest.length && METRIC[rest[0]]) return `${moduleName(head)}, ${METRIC[rest[0]]} sensor`
  return cap(id)
}

const STAT: Record<string, string> = {
  'change over 10 min': 'changed fast in 10 min', 'change over 1 h': 'changed over the last hour', noise: 'is unusually noisy',
  'samples in 10 min': 'is losing samples', 'slope over 1 h': 'is drifting over the last hour', 'slope over 6 h': 'is drifting over the last 6 hours',
}

const IT: [RegExp, string][] = [
  [/\binfermi\b/g, ''], [/^FC\b/, 'Heart rate'], [/^FR\b/, 'Breathing rate'], [/^SpO2\b/, 'Blood oxygen'], [/^HRV\b/, 'Heart-rate variability'],
  [/^temperatura centrale/, 'Body temperature'], [/^temperatura cutanea/, 'Skin temperature'], [/^irregolarità della FC/, 'Heart-rate irregularity'],
  [/atti\/min/g, '/min'], [/attesi/g, 'expected'], [/a riposo/g, 'at rest'], [/\ba ([\d,]+) MET/g, 'at $1 MET'], [/\s*\(z [^)]*\)/g, ''],
]

/** One line of `Emergency.evidence` in words: ML feature phrases ("imv_usl_fwd_rpm: slope over 6 h (+4.1 sigma)") and the Italian crew-baseline sentences. */
export function humanEvidence(line: string): string {
  const m = /^(\S+?): (.+?) \(([+-]?[\d.]+) sigma\)$/.exec(line)
  if (m) {
    const [, id, stat, z] = m
    return `${sensorName(id)} ${STAT[stat] ?? stat}, ${Number(z) >= 0 ? 'above' : 'below'} what is normal`
  }
  if (/\battesi\b/.test(line)) {
    let out = line
    for (const [re, to] of IT) out = out.replace(re, to)
    return out.replace(/(\d),(\d)/g, '$1.$2').replace(/\s+/g, ' ').trim()
  }
  return line
}

/** The sentence for a cause the diagnoser can name (tools/ml/classes.yaml). */
export const causeText = (cause: string | null | undefined): string | null => (cause ? CAUSE_TEXT[cause] ?? null : null)

/** Title of an anomaly emergency, read from the group in its `detail` ("ventilation: score 13.4; ..."). */
export function anomalyTitle(detail: string): string {
  const g = /^(\w+):/.exec(detail)?.[1]
  return (g && GROUP_TITLE[g]) || 'Something on the station is behaving unusually'
}
