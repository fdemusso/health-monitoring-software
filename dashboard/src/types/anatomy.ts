/** Body silhouette variant. */
export type Sex = 'male' | 'female';

/** The six organs the hologram can render and color individually. */
export type OrganKey = 'heart' | 'lungs' | 'brain' | 'liver' | 'kidneys' | 'stomach';

/**
 * Per-organ input value. Units differ by organ:
 * - `heart`: heart rate in beats per minute (bpm)
 * - `lungs`: respiratory rate in breaths per minute
 * - `brain` / `liver` / `kidneys` / `stomach`: severity in the 0..1 range
 *   (0 = normal, 1 = critical)
 *
 * Omitted organs fall back to a normal/resting default.
 */
export type OrganVitals = Partial<Record<OrganKey, number>>;

/** All organ keys, in a stable order suitable for iteration (e.g. building UI controls). */
export const ORGAN_KEYS: OrganKey[] = ['heart', 'lungs', 'brain', 'liver', 'kidneys', 'stomach'];

/** A single closed SVG path plus the transform that places it in the body's coordinate space. */
export interface AnatomyPath {
  d: string;
  transform: string;
}

/** An {@link AnatomyPath} belonging to an organ, with its rendered center pre-computed. */
export interface OrganPath extends AnatomyPath {
  /**
   * Center of this path's bounding box, in viewBox coordinates, after
   * applying `transform`. Used as the `transform-origin` pivot for the
   * pulse animation so the organ scales in place instead of drifting.
   */
  cx: number;
  cy: number;
}

/** Full silhouette + organ dataset for one {@link Sex}, as extracted from gganatogram. */
export interface AnatomyData {
  sex: Sex;
  /** `[minX, minY, width, height]`, suitable for an SVG `viewBox` attribute. */
  viewBox: [number, number, number, number];
  /** Body's vertical axis of symmetry, in viewBox coordinates (used to mirror organs that only have one path). */
  centerX: number;
  outline: AnatomyPath[];
  organs: Record<OrganKey, OrganPath[]>;
}
