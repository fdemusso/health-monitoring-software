/**
 * Maps a severity value in the 0..1 range (0 = normal, 1 = critical) to the
 * hologram's visual parameters: color (cyan -> orange -> red) and glow
 * intensity.
 */

type RGB = [number, number, number];

const COLOR_NORMAL: RGB = [34, 211, 238]; // cyan (hologram baseline)
const COLOR_WARNING: RGB = [251, 146, 60]; // orange
const COLOR_CRITICAL: RGB = [255, 36, 64]; // red

function lerp(a: number, b: number, t: number): number {
  return a + (b - a) * t;
}

function lerpColor(a: RGB, b: RGB, t: number): RGB {
  return [lerp(a[0], b[0], t), lerp(a[1], b[1], t), lerp(a[2], b[2], t)];
}

/** Clamps a severity value to the valid 0..1 range; `undefined`/`NaN` fall back to 0 (normal). */
export function clampSeverity(value: number | undefined): number {
  if (value === undefined || Number.isNaN(value)) return 0;
  return Math.min(1, Math.max(0, value));
}

function severityRGB(severity: number): RGB {
  const s = clampSeverity(severity);
  return s <= 0.5
    ? lerpColor(COLOR_NORMAL, COLOR_WARNING, s / 0.5)
    : lerpColor(COLOR_WARNING, COLOR_CRITICAL, (s - 0.5) / 0.5);
}

/**
 * Resolves a severity to an opaque `rgb()` color string, interpolated
 * cyan (0) -> orange (0.5) -> red (1).
 *
 * @param severity - 0..1, 0 = normal, 1 = critical.
 */
export function severityColor(severity: number): string {
  const [r, g, b] = severityRGB(severity);
  return `rgb(${Math.round(r)}, ${Math.round(g)}, ${Math.round(b)})`;
}

/**
 * Same hue as {@link severityColor} but with reduced alpha, meant for the
 * glow (`drop-shadow`): the organ's fill is one thing, its halo is another —
 * if the halo were as opaque as the fill, two adjacent organs would bleed
 * into each other at the edges.
 *
 * @param severity - 0..1, 0 = normal, 1 = critical.
 * @param alpha - Opacity of the returned color, 0..1.
 */
export function severityGlowColor(severity: number, alpha = 0.5): string {
  const [r, g, b] = severityRGB(severity);
  return `rgba(${Math.round(r)}, ${Math.round(g)}, ${Math.round(b)}, ${alpha})`;
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
