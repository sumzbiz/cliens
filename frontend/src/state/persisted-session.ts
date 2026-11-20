/**
 * Keeps the wizard's answers across a page refresh.
 *
 * Without this, refreshing any step after the first dropped the user back at step
 * one with every answer gone. `sessionStorage` rather than `localStorage`: the
 * answers belong to this tab's visit, and a new tab should start fresh.
 *
 * What comes back out of storage is untrusted — an older build may have written a
 * different shape, or the user may have edited it — so it is validated field by
 * field, and anything that does not match is discarded in favour of the defaults.
 * A partially restored specification would put placeholder inputs into a score.
 */
import type { LatLon } from '@/lib/geo';
import type { Area, SiteSpecification } from '@/state/session-context';
import { ELEMENT_SITUATIONS, MEMBER_TYPES } from '@/types/api';

/** Versioned, so a future shape change cannot be misread as this one. */
export const SESSION_STORAGE_KEY = 'cliens.session.v2';

export interface PersistedSession {
  spec: SiteSpecification;
  area: Area | null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

function isSpecification(value: unknown): value is SiteSpecification {
  if (!isRecord(value) || !isRecord(value.concrete)) {
    return false;
  }
  const concrete = value.concrete;
  return (
    typeof value.district === 'string' &&
    ELEMENT_SITUATIONS.some((situation) => situation.value === value.situation) &&
    MEMBER_TYPES.some((member) => member.value === value.member) &&
    isFiniteNumber(value.coverMm) &&
    typeof value.wallingMaterialId === 'string' &&
    typeof value.evaluateOwnMaterials === 'boolean' &&
    typeof concrete.grade === 'string' &&
    isFiniteNumber(concrete.cement_content_kg_m3) &&
    isFiniteNumber(concrete.water_cement_ratio) &&
    (concrete.cement_type === undefined || typeof concrete.cement_type === 'string') &&
    (concrete.admixtures === undefined ||
      (Array.isArray(concrete.admixtures) &&
        concrete.admixtures.every((item) => typeof item === 'string')))
  );
}

function isLatLon(value: unknown): value is LatLon {
  return isRecord(value) && isFiniteNumber(value.latitude) && isFiniteNumber(value.longitude);
}

function isArea(value: unknown): value is Area {
  return Array.isArray(value) && value.length > 0 && value.every(isLatLon);
}

/** The saved session, or null when there is none or it cannot be trusted. */
export function loadSession(storage: Storage = globalThis.sessionStorage): PersistedSession | null {
  try {
    const raw = storage.getItem(SESSION_STORAGE_KEY);
    if (raw === null) {
      return null;
    }
    const parsed: unknown = JSON.parse(raw);
    if (!isRecord(parsed) || !isSpecification(parsed.spec)) {
      return null;
    }
    if (parsed.area !== null && !isArea(parsed.area)) {
      return null;
    }
    return { spec: parsed.spec, area: parsed.area };
  } catch {
    // Storage blocked (private mode, disabled site data) or unparseable JSON:
    // either way there is nothing trustworthy to restore.
    return null;
  }
}

/** Save the session. A storage failure is ignored: persistence is a convenience. */
export function saveSession(
  session: PersistedSession,
  storage: Storage = globalThis.sessionStorage
): void {
  try {
    storage.setItem(SESSION_STORAGE_KEY, JSON.stringify(session));
  } catch {
    // Quota exceeded or storage blocked; the in-memory session still works.
  }
}
