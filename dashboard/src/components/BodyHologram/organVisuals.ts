/**
 * Maps a severity value in the 0..1 range (0 = normal, 1 = critical) to the
 * hologram's visual parameters: color (neutral -> warning -> danger) and glow
 * intensity.
 */

/** Clamps a severity value to the valid 0..1 range; `undefined`/`NaN` fall back to 0 (normal). */
export function clampSeverity(value: number | undefined): number {
  if (value === undefined || Number.isNaN(value)) return 0;
  return Math.min(1, Math.max(0, value));
}

/** Design-system tokens the hologram interpolates between: chart ink, warning, danger. */
const NORMAL = 'var(--chart-1)';
const WARNING = 'var(--status-warning)';
const CRITICAL = 'var(--status-danger)';

/** `color-mix` of two token colours, in oklab (the design system forbids oklch tints). */
function mix(to: string, from: string, pct: number, alpha = 1): string {
  const mixed = `color-mix(in oklab, ${to} ${Math.round(pct)}%, ${from})`;
  return alpha >= 1 ? mixed : `color-mix(in oklab, ${mixed} ${Math.round(alpha * 100)}%, transparent)`;
}

function severityMix(severity: number, alpha = 1): string {
  const s = clampSeverity(severity);
  return s <= 0.5 ? mix(WARNING, NORMAL, (s / 0.5) * 100, alpha) : mix(CRITICAL, WARNING, ((s - 0.5) / 0.5) * 100, alpha);
}

/**
 * Resolves a severity to a CSS colour built from the design tokens,
 * interpolated chart ink (0) -> warning (0.5) -> danger (1).
 *
 * @param severity - 0..1, 0 = normal, 1 = critical.
 */
export function severityColor(severity: number): string {
  return severityMix(severity);
}

/**
 * Same hue as {@link severityColor} with reduced alpha, for the optional halo.
 *
 * @param severity - 0..1, 0 = normal, 1 = critical.
 * @param alpha - Opacity of the returned color, 0..1.
 */
export function severityGlowColor(severity: number, alpha = 0.5): string {
  return severityMix(severity, alpha);
}

/**
 * Glow radius in px (SVG user units) around an organ. Kept small so the
 * glow doesn't bleed over anatomically adjacent organs (e.g. the heart
 * nestled between the lungs).
 *
 * @param severity - 0..1, 0 = normal, 1 = critical.
 */
export function glowRadius(severity: number): number {
  const s = clampSeverity(severity);
  return 1.0 + s * 1.6;
}
