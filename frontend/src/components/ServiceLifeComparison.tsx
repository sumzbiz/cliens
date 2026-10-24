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
import { useLanguage } from '@/state/language-context';

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
  const { language } = useLanguage();
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
          {language === 'ta' ? 'ஆண்டுகள்' : 'years'}
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
        {language === 'ta' ? `எதிர்பார்க்கப்படும் காலம்: ${String(Math.round(life.lower_years))}–${String(Math.round(life.upper_years))} ஆண்டுகள்` : `likely ${String(Math.round(life.lower_years))}–${String(Math.round(life.upper_years))} years`}
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
  const { language } = useLanguage();
  const gained = Math.round(recommended.service_life.years - proposed.service_life.years);
  const baseline = proposed.service_life.baseline_years;
  const rangesOverlap =
    proposed.service_life.lower_years <= recommended.service_life.upper_years &&
    recommended.service_life.lower_years <= proposed.service_life.upper_years;
  const difference = Math.abs(gained);

  return (
    <section aria-labelledby="life-heading" className="glass rounded-2xl p-6 sm:p-8">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <h2 id="life-heading" className="text-base font-semibold text-ink-1">
          {language === 'ta' ? 'மதிப்பிடப்பட்ட சேவை ஆயுள்' : 'Estimated service life'}
        </h2>
        <p className="tabular text-xs text-ink-3">
          {language === 'ta' ? `விதிமுறை வடிவமைப்பு ஆயுள்: ${String(Math.round(baseline))} ஆண்டுகள்` : `code design life ${String(Math.round(baseline))} years`}
        </p>
      </div>

      <div className="mt-5 space-y-5">
        <LifeBar
          label={language === 'ta' ? (evaluatedOwnMaterials ? 'உங்கள் விவரக்குறிப்பு' : 'வழக்கமான உள்ளூர் கட்டுமானம்') : evaluatedOwnMaterials ? 'Your specification' : 'Typical local build'}
          life={proposed.service_life}
          accent={false}
          emphasis={evaluatedOwnMaterials}
          delay={0.1}
        />
        <LifeBar
          label={language === 'ta' ? 'எங்கள் பரிந்துரை' : "What we'd specify"}
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
        <span>{AXIS_MAX_YEARS / 2} {language === 'ta' ? 'ஆண்டுகள்' : 'years'}</span>
        <span>{AXIS_MAX_YEARS}+</span>
      </div>

      <p className="mt-5 border-t border-white/10 pt-4 text-sm leading-relaxed text-ink-2">
        {language === 'ta'
          ? rangesOverlap
            ? gained < 0
              ? 'உங்கள் கலவையின் மைய மதிப்பீடு அதிகம்; ஆனால் மதிப்பிடப்பட்ட கால வரம்புகள் ஒன்றுடன் ஒன்று பொருந்துவதால் தெளிவான ஆயுள் வேறுபாட்டைக் காட்டவில்லை. பரிந்துரை உள்ளூர் காலநிலைக்கான விதிமுறைத் தேவைகளைப் பூர்த்தி செய்ய உருவாக்கப்பட்டது; அதிகபட்ச ஆயுளை நோக்கி அல்ல.'
              : gained > 0
                ? 'பரிந்துரைக்கப்பட்ட கலவையின் மைய மதிப்பீடு அதிகம்; ஆனால் மதிப்பிடப்பட்ட கால வரம்புகள் ஒன்றுடன் ஒன்று பொருந்துவதால் தெளிவான ஆயுள் வேறுபாட்டைக் காட்டவில்லை. பரிந்துரை உள்ளூர் காலநிலைக்கான விதிமுறைத் தேவைகளைப் பூர்த்தி செய்ய உருவாக்கப்பட்டது; அதிகபட்ச ஆயுளை நோக்கி அல்ல.'
                : 'மதிப்பிடப்பட்ட கால வரம்புகள் ஒன்றுடன் ஒன்று பொருந்துகின்றன; எனவே தெளிவான ஆயுள் வேறுபாட்டைக் காட்டவில்லை. பரிந்துரை உள்ளூர் காலநிலைக்கான விதிமுறைத் தேவைகளைப் பூர்த்தி செய்ய உருவாக்கப்பட்டது; அதிகபட்ச ஆயுளை நோக்கி அல்ல.'
            : gained > 0
              ? `பரிந்துரைக்கப்பட்ட விவரக்குறிப்பின் மதிப்பீடு சுமார் ${String(difference)} ஆண்டுகள் அதிகம்; இருப்பினும் இது கணிக்கப்பட்ட மதிப்பீடு மட்டுமே, உறுதியான ஆயுள் கணிப்பு அல்ல.`
              : `உங்கள் விவரக்குறிப்பின் மதிப்பீடு சுமார் ${String(difference)} ஆண்டுகள் அதிகம். பரிந்துரை காலநிலை சார்ந்த விதிமுறைத் தேவைகளைப் பூர்த்தி செய்ய உருவாக்கப்பட்டது; அதிகபட்ச மதிப்பிடப்பட்ட ஆயுளுக்காக அல்ல.`
          : rangesOverlap
            ? gained < 0
              ? 'Your mix has a higher point estimate, but the ranges overlap, so this does not show a clear service-life difference. The recommendation targets this climate’s code requirements; it is not designed to maximize this estimate.'
              : gained > 0
                ? 'The recommended mix has a higher point estimate, but the ranges overlap, so this does not show a clear service-life difference. The recommendation targets this climate’s code requirements; it is not designed to maximize this estimate.'
                : 'The estimated ranges overlap and the point estimates are similar, so this does not show a clear service-life difference. The recommendation targets this climate’s code requirements; it is not designed to maximize this estimate.'
            : gained > 0
              ? `The recommended specification has an estimate about ${String(difference)} years higher. This is a code-anchored estimate, not a prediction of a building’s actual lifespan.`
              : `Your specification has an estimate about ${String(difference)} years higher. The recommendation targets this climate’s code requirements; it is not designed to maximize this estimate.`}
      </p>
      <p className="mt-2 text-xs leading-relaxed text-ink-3">{proposed.service_life.basis}</p>
    </section>
  );
}
