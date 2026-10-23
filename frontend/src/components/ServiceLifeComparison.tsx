/**
 * How long each specification is expected to serve, side by side.
 *
 * Two bars on a shared timeline rather than two numbers, because the question a
 * builder is actually asking — "how much longer does the better mix buy me" — is
 * a comparison, and a comparison is easier to see as length than to compute from
 * two figures.
 *
 * The bars are scaled against a fixed ceiling, not against each other. Scaling to
 * the larger of the two would make every pair look equally dramatic: a 48-vs-52
 * year comparison would fill the track the same way a 13-vs-60 one does. A fixed
 * axis keeps the visual honest across every result.
 *
 * The uncertainty band is drawn, not hidden behind a tooltip. This estimate is
 * anchored on the code's design life and adjusted by diffusion physics — it is
 * not fitted to observed failures, and a bar with a hard end would claim a
 * precision it does not have.
 */
import { motion, useReducedMotion } from 'motion/react';

import type { ScoredSelection } from '@/types/api';

/**
 * Top of the axis, in years.
 *
 * Matches the backend's own cap on the estimate, so a maximum-life result fills
 * the track exactly rather than overflowing it or stopping short.
 */
const AXIS_MAX_YEARS = 100;

function percent(years: number): number {
  return Math.min((years / AXIS_MAX_YEARS) * 100, 100);
}

function LifeBar({
  label,
  life,
  accent,
  emphasis,
  delay,
}: {
  label: string;
  life: ScoredSelection['service_life'];
  accent: boolean;
  emphasis: boolean;
  delay: number;
}) {
  const reduced = useReducedMotion();

  const start = percent(life.lower_years);
  const width = Math.max(percent(life.upper_years) - start, 0.5);

  return (
    <div>
      <div className="flex items-baseline justify-between gap-3">
        <p className={`text-sm ${emphasis ? 'font-semibold text-ink-1' : 'text-ink-2'}`}>
          {label}
        </p>
        <p className="tabular text-sm text-ink-3">
          <span
            className={`text-lg font-semibold ${accent ? 'text-band-good' : 'text-ink-1'}`}
          >
            {Math.round(life.years)}
          </span>{' '}
          years
        </p>
      </div>

      <div
        className="relative mt-2 h-3 w-full overflow-hidden rounded-full bg-white/[0.05]"
        // The figures either side are the accessible version; the bar is a
        // redrawing of them, so it is not announced twice.
        aria-hidden="true"
      >
        {/* The plausible band, drawn behind the point estimate. */}
        <motion.div
          className={`absolute inset-y-0 rounded-full ${accent ? 'bg-band-good/25' : 'bg-ink-3/25'}`}
          initial={reduced === true ? false : { width: 0 }}
          animate={{ width: `${String(width)}%` }}
          style={{ left: `${String(start)}%` }}
          transition={
            reduced === true ? { duration: 0 } : { duration: 0.5, delay: delay + 0.1 }
          }
        />
        {/* The point estimate itself. */}
        <motion.div
          className={`absolute inset-y-0 left-0 rounded-full ${accent ? 'bg-band-good' : 'bg-ink-3'}`}
          initial={reduced === true ? false : { width: 0 }}
          animate={{ width: `${String(percent(life.years))}%` }}
          transition={
            reduced === true
              ? { duration: 0 }
              : { type: 'spring', stiffness: 90, damping: 18, delay }
          }
        />
      </div>

      <p className="tabular mt-1 text-[11px] text-ink-3">
        likely {Math.round(life.lower_years)}–{Math.round(life.upper_years)} years
      </p>
    </div>
  );
}

export function ServiceLifeComparison({
  proposed,
  recommended,
  evaluatedOwnMaterials,
}: {
  proposed: ScoredSelection;
  recommended: ScoredSelection;
  evaluatedOwnMaterials: boolean;
}) {
  const gained = Math.round(recommended.service_life.years - proposed.service_life.years);
  const baseline = proposed.service_life.baseline_years;

  return (
    <section aria-labelledby="life-heading" className="glass rounded-2xl p-6 sm:p-8">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <h2 id="life-heading" className="text-base font-semibold text-ink-1">
          How long it should last
        </h2>
        <p className="tabular text-xs text-ink-3">
          code design life {Math.round(baseline)} years
        </p>
      </div>

      <div className="mt-5 space-y-5">
        <LifeBar
          label={evaluatedOwnMaterials ? 'Your specification' : 'Typical local build'}
          life={proposed.service_life}
          accent={false}
          emphasis={evaluatedOwnMaterials}
          delay={0.1}
        />
        <LifeBar
          label="What we'd specify"
          life={recommended.service_life}
          accent
          emphasis={!evaluatedOwnMaterials}
          delay={0.25}
        />
      </div>

      {/* The axis is only meaningful if its scale is stated. */}
      <div
        aria-hidden="true"
        className="tabular mt-2 flex justify-between text-[10px] text-ink-3/60"
      >
        <span>0</span>
        <span>{AXIS_MAX_YEARS / 2} years</span>
        <span>{AXIS_MAX_YEARS}+</span>
      </div>

      <p className="mt-5 border-t border-white/10 pt-4 text-sm leading-relaxed text-ink-2">
        {gained > 0
          ? `The recommended specification should serve about ${String(gained)} years longer.`
          : 'The recommended specification would not extend this further.'}
      </p>
      <p className="mt-2 text-xs leading-relaxed text-ink-3">{proposed.service_life.basis}</p>
    </section>
  );
}
