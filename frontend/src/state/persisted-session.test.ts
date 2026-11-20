import { beforeEach, describe, expect, it } from 'vitest';

import {
  loadSession,
  SESSION_STORAGE_KEY,
  saveSession,
  type PersistedSession,
} from '@/state/persisted-session';

const SESSION: PersistedSession = {
  spec: {
    district: 'Madurai',
    situation: 'buried',
    concrete: {
      grade: 'M35',
      cement_content_kg_m3: 360,
      water_cement_ratio: 0.4,
      cement_type: 'PPC',
      admixtures: ['corrosion inhibitor'],
    },
    wallingMaterialId: 'fly_ash_brick',
    evaluateOwnMaterials: true,
  },
  area: null,
};

const OUTLINE = [
  { latitude: 9.92, longitude: 78.12 },
  { latitude: 9.92, longitude: 78.1205 },
  { latitude: 9.9205, longitude: 78.1205 },
];

/** A Storage whose every call throws, as in a private window with storage blocked. */
const BLOCKED: Storage = {
  length: 0,
  clear: () => undefined,
  key: () => null,
  removeItem: () => undefined,
  getItem: () => {
    throw new Error('SecurityError');
  },
  setItem: () => {
    throw new Error('QuotaExceededError');
  },
};

describe('persisted session', () => {
  beforeEach(() => {
    sessionStorage.clear();
  });

  it('restores exactly what was saved', () => {
    saveSession(SESSION);
    expect(loadSession()).toEqual(SESSION);
  });

  it('restores a drawn outline', () => {
    const drawn = { spec: { ...SESSION.spec, district: '' }, area: OUTLINE };
    saveSession(drawn);
    expect(loadSession()).toEqual(drawn);
  });

  it('returns nothing when nothing was saved', () => {
    expect(loadSession()).toBeNull();
  });

  it('discards unparseable JSON instead of throwing', () => {
    sessionStorage.setItem(SESSION_STORAGE_KEY, '{not json');
    expect(loadSession()).toBeNull();
  });

  it.each([
    ['an unknown situation', { ...SESSION.spec, situation: 'underwater' }],
    [
      'a non-numeric cement content',
      { ...SESSION.spec, concrete: { ...SESSION.spec.concrete, cement_content_kg_m3: '360' } },
    ],
    ['a missing walling material', { ...SESSION.spec, wallingMaterialId: undefined }],
    [
      'a NaN-like water/cement ratio',
      { ...SESSION.spec, concrete: { ...SESSION.spec.concrete, water_cement_ratio: null } },
    ],
  ])('discards a specification with %s', (_label, spec) => {
    sessionStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify({ spec, area: null }));
    expect(loadSession()).toBeNull();
  });

  it('discards a malformed outline', () => {
    const bad = { spec: SESSION.spec, area: [{ latitude: 'north', longitude: 78 }] };
    sessionStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify(bad));
    expect(loadSession()).toBeNull();
  });

  it('survives storage that refuses every call', () => {
    expect(() => {
      saveSession(SESSION, BLOCKED);
    }).not.toThrow();
    expect(loadSession(BLOCKED)).toBeNull();
  });
});
