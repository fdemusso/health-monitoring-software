/**
 * Synthetic single-lead ECG (lead II) of one astronaut, in the spirit of McSharry's dynamical model (IEEE TBME 2003, ECGSYN):
 * the heart is a point going round a cycle at phase `theta` (theta' = omega = 2 pi / RR) and the ECG is a sum of Gaussians
 * centred on fixed angles (P, Q, R, S, T) plus a baseline that follows the breathing.
 *
 * What is ours: the angles and widths are not constants, they are recomputed at every beat from the intervals a cardiologist reads in
 * seconds (PR, QRS, QT corrected with Fridericia), so they stretch with the heart rate as a real ECG does; the heart rate, the beat-to-beat
 * variability (HRV, rmssd) and the rhythm (sinus or atrial fibrillation) come from the simulated vitals; the amplitudes and the QT depend on sex,
 * age and body mass (BMI). All the morphology numbers are ESTIMATES from textbook ranges (normal adult lead II), not measurements of a person.
 * Display only: the model never feeds anything back to the physiology.
 */

export interface EcgPerson { sex?: 'M' | 'F' | null; age_y?: number | null; height_cm?: number | null; body_mass_kg?: number | null }
/** What the wearable knows right now (updated by the caller; read at every sample). */
export interface EcgInput { hr: number; af: boolean; hrvMs: number; respPerMin: number; met: number }

export const ECG_FS = 250 // samples per second

const TWO_PI = 2 * Math.PI
const gauss = () => Math.sqrt(-2 * Math.log(1 - Math.random())) * Math.cos(TWO_PI * Math.random())
const clamp = (v: number, lo: number, hi: number) => Math.min(Math.max(v, lo), hi)
/** Angle difference wrapped to [-pi, pi). */
const wrap = (a: number) => a - TWO_PI * Math.floor((a + Math.PI) / TWO_PI)

interface Wave { t: number; sd: number; a: number } // seconds after the R peak, seconds, mV
interface Beat { rr: number; waves: Wave[] }

/** How the person's build changes the morphology (ESTIMATE): amplitude factor and corrected QT in seconds. */
export function ecgTraits(p: EcgPerson): { amp: number; qtc: number; prBase: number } {
  const age = p.age_y ?? 35
  const bmi = p.body_mass_kg && p.height_cm ? p.body_mass_kg / (p.height_cm / 100) ** 2 : 23
  const female = p.sex === 'F'
  return {
    // QRS voltage: lower in women, falls slowly with age and with body fat (more tissue between heart and electrode)
    amp: (female ? 0.85 : 1) * clamp(1 - 0.004 * Math.max(0, age - 35), 0.8, 1) * clamp(1 - 0.015 * (bmi - 23), 0.75, 1.1),
    qtc: (female ? 0.42 : 0.4) + 0.0004 * (age - 30),
    prBase: 0.15 + 0.0008 * Math.max(0, age - 30),
  }
}

export class EcgSynth {
  private theta = -Math.PI * 0.99
  private t = 0
  private beat: Beat
  private fPhase = Math.random() * TWO_PI
  private readonly traits: ReturnType<typeof ecgTraits>

  private readonly input: () => EcgInput

  constructor(person: EcgPerson, input: () => EcgInput) {
    this.input = input
    this.traits = ecgTraits(person)
    this.beat = this.newBeat(this.input())
  }

  private newBeat(i: EcgInput): Beat {
    const mean = 60 / clamp(i.hr, 30, 220)
    // sinus: white beat-to-beat jitter of std rmssd / sqrt(2); AF: irregularly irregular (about 20 % spread)
    const jitter = i.af ? mean * 0.2 * gauss() : (clamp(i.hrvMs, 5, 150) / 1000 / Math.SQRT2) * gauss()
    const rr = clamp(mean + jitter, i.af ? 0.3 : mean * 0.75, i.af ? 1.6 : mean * 1.25)
    const { amp, qtc, prBase } = this.traits
    const qt = qtc * Math.cbrt(rr) // Fridericia
    const pr = prBase * clamp(1.1 - 0.1 * rr, 0.85, 1) // PR shortens a little at high heart rate
    const tPeak = 0.72 * qt - 0.03
    const tAmp = 0.3 * clamp(1.35 - 0.25 / rr, 0.6, 1.1) // T flattens when the heart is fast
    return {
      rr,
      waves: [
        { t: -(pr - 0.04), sd: 0.022, a: i.af ? 0 : 0.15 * amp }, // P: absent in atrial fibrillation
        { t: -0.022, sd: 0.008, a: -0.12 * amp }, // Q
        { t: 0, sd: 0.011, a: 1.0 * amp }, // R
        { t: 0.024, sd: 0.009, a: -0.22 * amp }, // S
        { t: tPeak, sd: 0.04 * (qt / 0.4), a: tAmp * amp }, // T
      ],
    }
  }

  /** The next sample (mV), `dt` seconds after the previous one. */
  next(dt: number): number {
    const i = this.input()
    this.t += dt
    this.theta += (TWO_PI / this.beat.rr) * dt
    if (this.theta >= Math.PI) { // a beat is over: the next one starts at -pi with its own interval and shape
      this.theta -= TWO_PI
      this.beat = this.newBeat(i)
    }
    const k = TWO_PI / this.beat.rr
    let z = 0
    for (const w of this.beat.waves) {
      const d = wrap(this.theta - k * w.t)
      const b = k * w.sd
      z += w.a * Math.exp(-(d * d) / (2 * b * b))
    }
    const resp = Math.sin(TWO_PI * (i.respPerMin / 60) * this.t)
    z *= 1 + 0.04 * resp // breathing changes the QRS height a little
    z += 0.05 * resp // and moves the baseline
    if (i.af) { // fibrillatory waves, 4-9 Hz, small and never regular
      this.fPhase += TWO_PI * (5.5 + 1.5 * Math.sin(this.t * 0.7)) * dt
      z += 0.035 * (Math.sin(this.fPhase) + 0.6 * Math.sin(this.fPhase * 1.37 + 1))
    }
    return z + (0.006 + 0.012 * clamp(i.met - 1, 0, 6)) * gauss() // muscle and motion noise grow with effort
  }
}
