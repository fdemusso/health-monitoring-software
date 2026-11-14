import './BodyHologram.css';
import type { BodyHologramProps } from './BodyHologram.types';
import { DEFAULT_SIZE, EMPTY_ORGAN_VITALS, useBodyHologramViewModel } from './useBodyHologram';

/**
 * Holographic front-view body scan with animated internal organs.
 *
 * Purely declarative: every render recomputes organ colors, glow and pulse
 * timing from the `organs` prop (via the internal `useBodyHologramViewModel`
 * hook). There is no internal state and no imperative animation driver — all
 * motion comes from CSS keyframes in `BodyHologram.css`, parameterized
 * through inline custom properties (`--organ-color`, `--pulse-duration`, ...).
 *
 * @example
 * ```tsx
 * <BodyHologram sex="male" organs={{ heart: 118, lungs: 22 }} />
 * ```
 */
export function BodyHologram({
  sex,
  organs = EMPTY_ORGAN_VITALS,
  size = DEFAULT_SIZE,
  showBase = true,
  className,
}: BodyHologramProps) {
  const model = useBodyHologramViewModel(sex, organs, size, showBase);

  return (
    <svg
      className={['bh-root', className].filter(Boolean).join(' ')}
      width={model.displayWidth}
      height={model.displayHeight}
      viewBox={model.viewBox}
      role="img"
      aria-label={`Holographic ${sex} body scan`}
    >
      <defs>
        <radialGradient id={model.baseGradientId} cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor="rgba(94,211,255,0.9)" />
          <stop offset="100%" stopColor="rgba(94,211,255,0)" />
        </radialGradient>
      </defs>

      {model.base && (
        <ellipse
          className="bh-base"
          cx={model.base.cx}
          cy={model.base.cy}
          rx={model.base.rx}
          ry={model.base.ry}
          fill={`url(#${model.baseGradientId})`}
        />
      )}

      <g className="bh-outline">
        {model.outline.map((path, i) => (
          <path key={i} d={path.d} transform={path.transform} />
        ))}
      </g>

      {model.organs.map((organ) => {
        const partClassName = organ.pulses
          ? 'bh-organ-part bh-organ-part--pulse'
          : 'bh-organ-part';

        return (
          <g key={organ.key} className="bh-organ" style={organ.style} data-organ={organ.key}>
            {organ.parts.map((part, i) => (
              // Each part (e.g. the left/right lung) pulses around its own
              // real center (transformOrigin), not the group's: otherwise
              // two parts pulsing together would drift toward/away from
              // each other instead of growing in place.
              <g key={i} className={partClassName} style={{ transformOrigin: part.transformOrigin }}>
                <path d={part.d} transform={part.transform} />
              </g>
            ))}
            {organ.mirrorFirstPart && (
              <g transform={`translate(${model.centerX * 2} 0) scale(-1 1)`}>
                <g
                  className={partClassName}
                  style={{ transformOrigin: organ.parts[0].transformOrigin }}
                >
                  <path d={organ.parts[0].d} transform={organ.parts[0].transform} />
                </g>
              </g>
            )}
          </g>
        );
      })}
    </svg>
  );
}
