/**
 * Display formatting, defined once so the same quantity never appears two ways.
 */
import type { ScoreBand } from '@/types/api';

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

/** One-line plain-language verdict for a band, addressed to the user. */
export function bandVerdict(band: ScoreBand): string {
  return {
    poor: 'Your specification falls well short of the code for this site.',
    marginal: 'Your specification is below the code minimum in places.',
    adequate: 'Your specification meets the code, with little margin.',
    good: 'Your specification clears the code comfortably.',
    excellent: 'Your specification is well ahead of the code minimum.',
  }[band];
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
      walling_climate_suitability: 'Walling material',
    }[parameter] ?? parameter
  );
}
