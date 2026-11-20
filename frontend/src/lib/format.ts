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
  return {
    poor: `${subject} meets the code, with little margin.`,
    marginal: `${subject} meets the code, with little margin.`,
    adequate: `${subject} meets the code, with little margin.`,
    good: `${subject} clears the code comfortably.`,
    excellent: `${subject} is well ahead of the code minimum.`,
  }[scored.band];
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
