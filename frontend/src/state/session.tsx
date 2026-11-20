/**
 * The one piece of state that outlives a page.
 *
 * The flow is five routes, so the answers cannot live in a screen component —
 * navigating would discard them. This holds the accumulating specification and the
 * district catalogue, and nothing else. It deliberately does *not* hold the score:
 * that belongs to the results page, which fetches it, so a stale score can never be
 * shown next to freshly edited inputs.
 */
import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';

import { apiClient } from '@/lib/api-client';
import {
  SessionContext,
  type Area,
  type SessionValue,
  type SiteSpecification,
} from '@/state/session-context';
import type { ConcreteMixInput, DistrictList } from '@/types/api';

/**
 * A conventional, unremarkable specification — M20 at 300 kg/m3 and w/c 0.55 with
 * red brick. Chosen as the starting point precisely because it is what gets built
 * by default, so the first score a user sees is a fair reading of the status quo
 * rather than a strawman or a ringer.
 */
const DEFAULT_SPECIFICATION: SiteSpecification = {
  district: '',
  situation: 'exposed',
  concrete: {
    grade: 'M20',
    cement_content_kg_m3: 300,
    water_cement_ratio: 0.55,
    cement_type: 'OPC',
    admixtures: [],
  },
  wallingMaterialId: 'burnt_clay_brick',
  evaluateOwnMaterials: true,
};

export function SessionProvider({ children }: { children: ReactNode }) {
  const [spec, setSpec] = useState<SiteSpecification>(DEFAULT_SPECIFICATION);
  const [area, setArea] = useState<Area | null>(null);
  const [districts, setDistricts] = useState<DistrictList | null>(null);
  const [districtsError, setDistrictsError] = useState<unknown>(null);

  // Fetched once for the whole session rather than per page: the globe, the
  // search popup and the results page all need it, and it does not change.
  useEffect(() => {
    let cancelled = false;
    apiClient
      .getDistricts()
      .then((data) => {
        if (!cancelled) {
          setDistricts(data);
        }
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setDistrictsError(error);
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const update = useCallback((patch: Partial<SiteSpecification>) => {
    setSpec((current) => ({ ...current, ...patch }));
  }, []);

  const updateConcrete = useCallback((patch: Partial<ConcreteMixInput>) => {
    setSpec((current) => ({ ...current, concrete: { ...current.concrete, ...patch } }));
  }, []);

  const reset = useCallback(() => {
    setSpec(DEFAULT_SPECIFICATION);
  }, []);

  const value = useMemo<SessionValue>(
    () => ({
      spec,
      update,
      updateConcrete,
      reset,
      area,
      setArea,
      districts,
      districtsError,
    }),
    [spec, update, updateConcrete, reset, area, districts, districtsError]
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}
