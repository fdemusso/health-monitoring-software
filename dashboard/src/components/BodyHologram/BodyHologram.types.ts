import type { CSSProperties } from 'react';
import type { AnatomyPath, OrganKey, OrganVitals, Sex } from '../../types/anatomy';

/** Props for the {@link BodyHologram} component. */
export interface BodyHologramProps {
  /** Male or female body silhouette. */
  sex: Sex;
  /**
   * Per-organ input values. Units differ by organ:
   * - `heart`: heart rate in beats per minute (bpm)
   * - `lungs`: respiratory rate in breaths per minute
   * - `brain` / `liver` / `kidneys` / `stomach`: severity in the 0..1 range
   *   (0 = normal, 1 = critical)
   *
   * Omitted organs fall back to a normal/resting value.
   */
  organs?: OrganVitals;
  /** Rendered width in pixels. Height is derived to preserve the body's real aspect ratio. */
  size?: number;
  /** Whether to render the soft glow ellipse under the feet (hologram projector base). */
  showBase?: boolean;
  className?: string;
}

/**
 * One SVG sub-path of an organ (e.g. the left lobe of a pair of lungs),
 * pre-resolved for rendering: `transformOrigin` is the part's real center in
 * viewBox coordinates, ready to drop into an inline style.
 */
export interface OrganPartRenderData {
  d: string;
  transform: string;
  /** `"<x>px <y>px"` — anchors the CSS pulse animation on this part's real center. */
  transformOrigin: string;
}

/** Fully resolved render data for one organ group (all its sub-paths plus shared styling). */
export interface OrganRenderData {
  key: OrganKey;
  parts: OrganPartRenderData[];
  /**
   * Whether a horizontally-mirrored duplicate of `parts[0]` should also be
   * rendered. Used for the female kidney dataset, which only has one path
   * where the male one has a left/right pair (see the internal
   * `useBodyHologramViewModel` hook for the mirroring logic).
   */
  mirrorFirstPart: boolean;
  /** CSS custom properties (`--organ-color`, `--organ-glow`, ...) consumed by BodyHologram.css. */
  style: CSSProperties;
  /** Whether this organ has a physiological rhythm and should pulse (heart, lungs only). */
  pulses: boolean;
}

/** Geometry of the soft glow ellipse rendered under the figure's feet. */
interface BaseGlowGeometry {
  cx: number;
  cy: number;
  rx: number;
  ry: number;
}

/** Everything {@link BodyHologram} needs to render, derived from its props by {@link useBodyHologramViewModel}. */
export interface BodyHologramViewModel {
  /** SVG `viewBox` attribute value, e.g. `"-4.3 -4.9 114.7 204.3"`. */
  viewBox: string;
  displayWidth: number;
  displayHeight: number;
  /** Body's vertical axis of symmetry, in viewBox coordinates (used to mirror the kidney). */
  centerX: number;
  outline: AnatomyPath[];
  /** One entry per organ that has path data, in back-to-front draw order. */
  organs: OrganRenderData[];
  /** `null` when `showBase` is false. */
  base: BaseGlowGeometry | null;
  /** Unique id for this instance's `<radialGradient>`, so multiple `BodyHologram`s on one page don't collide. */
  baseGradientId: string;
}
