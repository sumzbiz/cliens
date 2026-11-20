/**
 * What the code requires at this site, for one element situation.
 *
 * The Exposure and Materials steps used to ask for inputs blind: the user picked a
 * situation without seeing which class it produced, then chose a grade without
 * knowing the minimum it would be judged against, and only learned either on the
 * score page. This asks the server — the only place the IS 456 rules live — and
 * returns the class and the three Table 5 limits, so both steps can show them
 * while the choice is being made.
 *
 * It reuses the scoring endpoint in recommend mode (no materials), whose reply
 * carries the exposure class and the requirements the recommendation was checked
 * against. No second copy of the rules exists in the browser.
 */
import { useEffect, useState } from 'react';

import { apiClient } from '@/lib/api-client';
import { boundsOf } from '@/lib/geo';
import type { Area } from '@/state/session-context';
import type { ElementSituation, ScoreResponse } from '@/types/api';

export interface SiteRequirements {
  exposureLabel: string;
  reasons: readonly string[];
  /** Characteristic strength in N/mm², e.g. 30 for M30. */
  minGradeMpa: number;
  minCementKgM3: number;
  maxWaterCementRatio: number;
}

export type SiteRequirementsState =
  | { status: 'loading' }
  | { status: 'ready'; requirements: SiteRequirements }
  | { status: 'error'; error: unknown };

/**
 * Answers already fetched this session, by site and situation.
 *
 * Flicking between situation cards would otherwise re-request each one, and the
 * answer cannot change within a session: the climate is fixed per site.
 */
const cache = new Map<string, SiteRequirements>();

function requirementsFrom(response: ScoreResponse): SiteRequirements | null {
  const required = (parameter: string): number | undefined =>
    response.recommended.findings.find((finding) => finding.parameter === parameter)?.required;

  const grade = required('concrete_grade_mpa');
  const cement = required('cement_content_kg_m3');
  const ratio = required('water_cement_ratio');
  if (grade === undefined || cement === undefined || ratio === undefined) {
    return null;
  }
  return {
    exposureLabel: response.exposure_label,
    reasons: response.exposure_reasons,
    minGradeMpa: grade,
    minCementKgM3: cement,
    maxWaterCementRatio: ratio,
  };
}

export function useSiteRequirements(
  district: string,
  area: Area | null,
  situation: ElementSituation
): SiteRequirementsState {
  const bounds = area === null ? null : boundsOf(area);
  const key = `${district}|${JSON.stringify(bounds)}|${situation}`;
  const cached = cache.get(key);

  const [state, setState] = useState<SiteRequirementsState>(
    cached === undefined ? { status: 'loading' } : { status: 'ready', requirements: cached }
  );

  useEffect(() => {
    const hit = cache.get(key);
    if (hit !== undefined) {
      setState({ status: 'ready', requirements: hit });
      return;
    }

    let cancelled = false;
    setState({ status: 'loading' });
    const pending =
      bounds !== null
        ? apiClient.scoreArea(bounds, null, situation)
        : apiClient.score(district, null, situation);

    pending
      .then((response) => {
        if (cancelled) {
          return;
        }
        const requirements = requirementsFrom(response);
        if (requirements === null) {
          setState({
            status: 'error',
            error: new Error('The server did not report the requirements for this site.'),
          });
          return;
        }
        cache.set(key, requirements);
        setState({ status: 'ready', requirements });
      })
      .catch((cause: unknown) => {
        if (!cancelled) {
          setState({ status: 'error', error: cause });
        }
      });

    return () => {
      cancelled = true;
    };
    // `key` encodes district, bounds and situation; listing those objects
    // directly would refire on every render, since `bounds` is rebuilt each time.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  return state;
}

/** "M30" from 30. */
export function gradeLabel(mpa: number): string {
  return `M${mpa.toFixed(0)}`;
}
