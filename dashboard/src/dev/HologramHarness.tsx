import { useState } from 'react';
import {
  BodyHologram,
  RESTING_HEART_RATE_BPM,
  RESTING_RESPIRATORY_RATE,
} from '../components/BodyHologram';
import { ORGAN_KEYS, type OrganKey, type OrganVitals, type Sex } from '../types/anatomy';
import './HologramHarness.css';

const ORGAN_LABELS: Record<OrganKey, string> = {
  heart: 'Cuore',
  lungs: 'Polmoni',
  brain: 'Cervello',
  liver: 'Fegato',
  kidneys: 'Reni',
  stomach: 'Stomaco',
};

interface SliderConfig {
  min: number;
  max: number;
  step: number;
  unit: string;
  format: (value: number) => string;
}

const RATE_SLIDER: Omit<SliderConfig, 'min' | 'max' | 'unit'> = {
  step: 1,
  format: (v) => String(Math.round(v)),
};

const SLIDER_CONFIG: Record<OrganKey, SliderConfig> = {
  heart: { min: 30, max: 200, unit: 'bpm', ...RATE_SLIDER },
  lungs: { min: 4, max: 40, unit: 'atti/min', ...RATE_SLIDER },
  brain: { min: 0, max: 1, step: 0.01, unit: '%', format: (v) => `${Math.round(v * 100)}%` },
  liver: { min: 0, max: 1, step: 0.01, unit: '%', format: (v) => `${Math.round(v * 100)}%` },
  kidneys: { min: 0, max: 1, step: 0.01, unit: '%', format: (v) => `${Math.round(v * 100)}%` },
  stomach: { min: 0, max: 1, step: 0.01, unit: '%', format: (v) => `${Math.round(v * 100)}%` },
};

export default function HologramHarness() {
  const [sex, setSex] = useState<Sex>('male');
  const [organs, setOrgans] = useState<OrganVitals>({
    heart: RESTING_HEART_RATE_BPM,
    lungs: RESTING_RESPIRATORY_RATE,
    brain: 0,
    liver: 0,
    kidneys: 0,
    stomach: 0,
  });

  const setValue = (key: OrganKey, value: number) =>
    setOrgans((prev: OrganVitals) => ({ ...prev, [key]: value }));

  return (
    <div className="demo-page">
      <aside className="demo-panel">
        <h1>Body Hologram</h1>
        <p className="demo-hint">
          Demo di <code>&lt;BodyHologram /&gt;</code>: componente puro,
          pilotato interamente dalle props <code>sex</code> e{' '}
          <code>organs</code> (cuore in bpm, polmoni in atti/min, gli altri
          organi come severity 0-1). Gli slider qui sotto sono solo per
          questo harness di sviluppo.
        </p>

        <div className="sex-toggle" role="radiogroup" aria-label="Sesso">
          <button
            type="button"
            className={sex === 'male' ? 'active' : ''}
            onClick={() => setSex('male')}
          >
            Uomo
          </button>
          <button
            type="button"
            className={sex === 'female' ? 'active' : ''}
            onClick={() => setSex('female')}
          >
            Donna
          </button>
        </div>

        {ORGAN_KEYS.map((key) => {
          const cfg = SLIDER_CONFIG[key];
          const value = organs[key] ?? cfg.min;
          return (
            <label key={key} className="organ-slider">
              <span>
                {ORGAN_LABELS[key]}
                {(key === 'heart' || key === 'lungs') && ` (${cfg.unit})`}
                <strong>{cfg.format(value)}</strong>
              </span>
              <input
                type="range"
                min={cfg.min}
                max={cfg.max}
                step={cfg.step}
                value={value}
                onChange={(e) => setValue(key, Number(e.target.value))}
              />
            </label>
          );
        })}
      </aside>

      <main className="demo-stage">
        <BodyHologram sex={sex} organs={organs} size={380} />
      </main>
    </div>
  );
}
