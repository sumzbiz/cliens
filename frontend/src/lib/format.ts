/**
 * Display formatting, defined once so the same quantity never appears two ways.
 */
import type { ScoreBand, ScoredSelection } from '@/types/api';

/** Tailwind text colour for a score band. */
export function bandTextClass(band: ScoreBand): string {
  return {
    poor: 'text-band-poor',
    marginal: 'text-band-marginal',
    adequate: 'text-band-adequate',
    good: 'text-band-good',
    excellent: 'text-band-excellent',
  }[band];
}

/** Tailwind background colour for a score band. */
export function bandFillClass(band: ScoreBand): string {
  return {
    poor: 'bg-band-poor',
    marginal: 'bg-band-marginal',
    adequate: 'bg-band-adequate',
    good: 'bg-band-good',
    excellent: 'bg-band-excellent',
  }[band];
}

/**
 * Whether a finding's `required`/`provided` really are "the limit" and "what you
 * specified".
 *
 * For grade, cement content and water/cement ratio they are. The walling check is
 * different: it reports the *climate's* humidity against the threshold at which
 * corrosion accelerates, and decides compliance from whether the chosen material
 * suits that climate. Rendering those two numbers under "Code needs" and "You
 * have" said the user supplied 81.4 where 75 was required and still failed, which
 * is not what happened. Rows like that show their message instead.
 */
export function isSpecComparison(parameter: string): boolean {
  return parameter !== 'walling_climate_suitability';
}

/**
 * Below this fractional margin on any spec-versus-limit check, a compliant
 * specification is described as having "little margin". Five percent is roughly
 * one step of the form's own controls (M25 -> M30 is +20%, 300 -> 320 kg/m³ is
 * +7%), so a specification within it is sitting on the minimum.
 */
const LITTLE_MARGIN_RATIO = 0.05;

/**
 * One-line plain-language verdict on a scored specification.
 *
 * Compliance comes from the checks themselves, not from the score band. Worded
 * from the band alone, a specification failing its cover check but scoring in the
 * "adequate" band was told it "meets the code". The band only describes the
 * margin once every check is met.
 */
export function complianceVerdict(scored: ScoredSelection, subject: string): string {
  if (!scored.compliant) {
    const unmet = scored.findings.filter((finding) => !finding.compliant).length;
    const checks = `${String(unmet)} check${unmet === 1 ? '' : 's'}`;
    return scored.band === 'poor'
      ? `${subject} falls well short of the code for this site, on ${checks}.`
      : `${subject} falls short of the code on ${checks}.`;
  }
  // The margin comes from the checks, not the band: every compliant specification
  // scores at least 78, inside "good", so one sitting exactly on every minimum was
  // told it "clears the code comfortably".
  const margins = scored.findings
    .filter((finding) => isSpecComparison(finding.parameter))
    .map((finding) => finding.margin_ratio);
  if (margins.length > 0 && Math.min(...margins) < LITTLE_MARGIN_RATIO) {
    return `${subject} meets the code, with little margin.`;
  }
  return scored.band === 'excellent'
    ? `${subject} is well ahead of the code minimum.`
    : `${subject} clears the code comfortably.`;
}

/** Format a 0-100 score for display. */
export function formatScore(score: number): string {
  return score.toFixed(0);
}

/** Format a signed score change. */
export function formatDelta(delta: number): string {
  return `${delta > 0 ? '+' : ''}${delta.toFixed(0)}`;
}

/** Format a fraction as a percentage. */
export function formatPercent(fraction: number): string {
  return `${(fraction * 100).toFixed(0)}%`;
}

/** Human-readable label for a compliance parameter. */
export function formatParameter(parameter: string): string {
  return (
    {
      concrete_grade_mpa: 'Concrete grade',
      cement_content_kg_m3: 'Cement content',
      water_cement_ratio: 'Water/cement ratio',
      nominal_cover_mm: 'Concrete cover',
      walling_climate_suitability: 'Walling material',
    }[parameter] ?? parameter
  );
}
