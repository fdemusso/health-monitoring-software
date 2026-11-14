import { useId, useMemo, type CSSProperties } from 'react';
import { getAnatomy } from '../../data/anatomy';
import type { OrganKey, OrganVitals, Sex } from '../../types/anatomy';
import { clampSeverity, glowRadius, severityColor, severityGlowColor } from './organVisuals';
import {
  HEART_RATE_RANGE,
  RESPIRATORY_RATE_RANGE,
  RESTING_HEART_RATE_BPM,
  RESTING_RESPIRATORY_RATE,
  cycleDuration,
  vitalSeverity,
} from './vitals';
import type {
  BodyHologramViewModel,
  OrganPartRenderData,
  OrganRenderData,
} from './BodyHologram.types';

/** Default rendered width (px) when {@link BodyHologramProps.size} is omitted. */
export const DEFAULT_SIZE = 420;

/**
 * Stable empty object used as the default for the `organs` prop. Using `{}`
 * directly as a default parameter value would create a new object on every
 * render, which would defeat the `useMemo` below (it would see a changed
 * dependency on every render and recompute regardless).
 */
export const EMPTY_ORGAN_VITALS: OrganVitals = {};

/** Draw order, back to front. The kidneys sit behind the liver/stomach, and the lungs behind the heart. */
const ORGAN_RENDER_ORDER: readonly OrganKey[] = [
  'kidneys',
  'liver',
  'stomach',
  'lungs',
  'heart',
  'brain',
];

/**
 * Only organs with a physiological rhythm pulse: the heartbeat and the
 * breathing cycle. The rest change color and glow with their severity but
 * stay visually static.
 */
const PULSING_ORGANS: ReadonlySet<OrganKey> = new Set(['heart', 'lungs']);

interface ResolvedOrganVitals {
  /** 0..1, 0 = normal/blue, 1 = critical/red. */
  severity: number;
  /** Seconds per pulse cycle. Unused (but still populated) for non-pulsing organs. */
  pulseDurationSeconds: number;
}

/**
 * Converts one organ's raw prop value into a severity and, for the heart and
 * lungs, a real pulse-cycle duration derived from the actual rate (one
 * animation cycle = one heartbeat / one breath).
 */
function resolveOrganVitals(key: OrganKey, organVitals: OrganVitals): ResolvedOrganVitals {
  if (key === 'heart') {
    const bpm = organVitals.heart ?? RESTING_HEART_RATE_BPM;
    return {
      severity: vitalSeverity(bpm, HEART_RATE_RANGE),
      pulseDurationSeconds: cycleDuration(bpm, 30, 220),
    };
  }

  if (key === 'lungs') {
    const breathsPerMinute = organVitals.lungs ?? RESTING_RESPIRATORY_RATE;
    return {
      severity: vitalSeverity(breathsPerMinute, RESPIRATORY_RATE_RANGE),
      pulseDurationSeconds: cycleDuration(breathsPerMinute, 4, 60),
    };
  }

  // Non-pulsing organ: no `.bh-organ-part--pulse` class is applied, so
  // `--pulse-duration` is never read by CSS. Any positive placeholder works.
  return { severity: clampSeverity(organVitals[key]), pulseDurationSeconds: 1 };
}

function buildOrganStyle(severity: number, pulseDurationSeconds: number): CSSProperties {
  return {
    ['--organ-color' as string]: severityColor(severity),
    ['--organ-glow-color' as string]: severityGlowColor(severity),
    ['--organ-glow' as string]: `${glowRadius(severity)}px`,
    ['--pulse-duration' as string]: `${pulseDurationSeconds}s`,
  };
}

/**
 * Derives the full {@link BodyHologramViewModel} for `<BodyHologram>` from
 * its props. Kept separate from the `.tsx` file so the component itself
 * stays a thin, declarative mapping from data to SVG markup, while this pure
 * derivation logic (and its `useMemo` dependency on `sex`/`organVitals`) is
 * readable and testable on its own.
 */
export function useBodyHologramViewModel(
  sex: Sex,
  organVitals: OrganVitals,
  size: number,
  showBase: boolean,
): BodyHologramViewModel {
  const instanceId = useId();

  return useMemo(() => {
    const anatomy = getAnatomy(sex);
    const [minX, minY, width, height] = anatomy.viewBox;
    const displayHeight = size * (height / width);

    const organs: OrganRenderData[] = ORGAN_RENDER_ORDER.flatMap((key) => {
      const organPaths = anatomy.organs[key];
      if (!organPaths || organPaths.length === 0) return [];

      const { severity, pulseDurationSeconds } = resolveOrganVitals(key, organVitals);

      const parts: OrganPartRenderData[] = organPaths.map((path) => ({
        d: path.d,
        transform: path.transform,
        transformOrigin: `${path.cx}px ${path.cy}px`,
      }));

      // gganatogram's female dataset only has a single kidney path, where
      // the male one has a left/right pair. We mirror that one path across
      // the body's centerline to render a matching pair for the female
      // figure too.
      const mirrorFirstPart = sex === 'female' && key === 'kidneys' && organPaths.length === 1;

      return [
        {
          key,
          parts,
          mirrorFirstPart,
          style: buildOrganStyle(severity, pulseDurationSeconds),
          pulses: PULSING_ORGANS.has(key),
        },
      ];
    });

    return {
      viewBox: `${minX} ${minY} ${width} ${height}`,
      displayWidth: size,
      displayHeight,
      centerX: anatomy.centerX,
      outline: anatomy.outline,
      organs,
      base: showBase
        ? {
            cx: anatomy.centerX,
            cy: minY + height - height * 0.015,
            rx: width * 0.24,
            ry: height * 0.018,
          }
        : null,
      baseGradientId: `${instanceId}-base`,
    };
  }, [sex, organVitals, size, showBase, instanceId]);
}
