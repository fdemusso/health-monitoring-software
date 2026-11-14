/**
 * Converts real vital-sign readings (heart rate, respiratory rate) into a
 * severity in the 0..1 range compatible with {@link organVisuals}
 * (0 = normal/blue, 0.5 = orange "borderline", 1 = red/critical), and into
 * the real duration of one pulse cycle.
 *
 * @remarks
 * Thresholds are indicative values for a resting adult, not a medical
 * device:
 * - Heart rate: 60-100 bpm is normal; 100-130 bpm is the "anxious/exertion"
 *   zone (mild tachycardia); above 130-160 bpm is critical. Symmetrically,
 *   below 60 bpm is bradycardia, critical below 40 bpm.
 * - Respiratory rate: 12-20 breaths/min is normal; 20-25 is the
 *   "anxious/exertion" zone (mild tachypnea); above 25-32 is critical.
 *   Below 12 is bradypnea, critical below 6.
 */

function lerp(a: number, b: number, t: number): number {
  return a + (b - a) * t;
}

/** Piecewise thresholds (in the vital sign's own unit) used by {@link vitalSeverity}. */
export interface VitalRange {
  /** At or below this value, severity is fully 1 (critical, low end — e.g. severe bradycardia). */
  criticalLow: number;
  /** Start of the normal band. */
  low: number;
  /** End of the normal band; still maps to severity 0. */
  normalHigh: number;
  /** End of the "borderline" band; maps to severity 0.5. */
  warningHigh: number;
  /** At or above this value, severity is fully 1 (critical, high end). */
  criticalHigh: number;
}

export const HEART_RATE_RANGE: VitalRange = {
  criticalLow: 40,
  low: 60,
  normalHigh: 100,
  warningHigh: 130,
  criticalHigh: 160,
};

export const RESPIRATORY_RATE_RANGE: VitalRange = {
  criticalLow: 6,
  low: 12,
  normalHigh: 20,
  warningHigh: 25,
  criticalHigh: 32,
};

/** Typical resting adult heart rate (bpm), used as the default when `organs.heart` is omitted. */
export const RESTING_HEART_RATE_BPM = 72;

/** Typical resting adult respiratory rate (breaths/min), used as the default when `organs.lungs` is omitted. */
export const RESTING_RESPIRATORY_RATE = 14;

/**
 * Maps a vital-sign reading to the 0..1 severity used for color and glow.
 *
 * The mapping is piecewise-linear: flat 0 across the whole normal band
 * (`low`..`normalHigh`, so even the high-normal end stays blue), ramping
 * linearly to 0.5 by `warningHigh` and to 1 by `criticalHigh`, with the same
 * ramp mirrored below `low` down to `criticalLow`. Values beyond the
 * critical thresholds clamp at severity 1.
 */
export function vitalSeverity(value: number, range: VitalRange): number {
  if (value <= range.criticalLow) return 1;
  if (value < range.low) {
    return lerp(1, 0.5, (value - range.criticalLow) / (range.low - range.criticalLow));
  }
  if (value <= range.normalHigh) return 0;
  if (value <= range.warningHigh) {
    return lerp(0, 0.5, (value - range.normalHigh) / (range.warningHigh - range.normalHigh));
  }
  if (value <= range.criticalHigh) {
    return lerp(0.5, 1, (value - range.warningHigh) / (range.criticalHigh - range.warningHigh));
  }
  return 1;
}

/**
 * Duration in seconds of one pulse cycle for a real rate (beats or breaths
 * per minute): one animation cycle = one heartbeat / one breath.
 *
 * @param ratePerMinute - The raw rate; clamped to `[min, max]` before conversion.
 * @param min - Safety clamp floor for the animation, not a clinical threshold.
 * @param max - Safety clamp ceiling for the animation, not a clinical threshold.
 */
export function cycleDuration(ratePerMinute: number, min: number, max: number): number {
  const clamped = Math.min(max, Math.max(min, ratePerMinute));
  return 60 / clamped;
}
