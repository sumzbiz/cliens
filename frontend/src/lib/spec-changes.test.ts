import { describe, expect, it } from 'vitest';

import { complianceVerdict } from '@/lib/format';
import { specChanges } from '@/lib/spec-changes';
import type { ScoredSelection } from '@/types/api';

function selection(overrides: Partial<ScoredSelection> = {}): ScoredSelection {
  return {
    concrete: {
      grade: 'M30',
      cement_content_kg_m3: 340,
      water_cement_ratio: 0.42,
      cement_type: 'PPC',
      admixtures: [],
    },
    walling_material_id: 'fly_ash_brick',
    nominal_cover_mm: 45,
    member: 'beam',
    score: 80,
    rules_score: 80,
    band: 'good',
    compliant: true,
    findings: [],
    service_life: {
      years: 60,
      lower_years: 42,
      upper_years: 78,
      baseline_years: 50,
      basis: 'test',
    },
    ...overrides,
  };
}

describe('specChanges', () => {
  it('reports nothing when the advice is the user’s own specification', () => {
    expect(specChanges(selection(), selection())).toEqual([]);
  });

  it('ignores the scores themselves, which always differ by spec', () => {
    expect(specChanges(selection({ score: 60 }), selection({ score: 90 }))).toEqual([]);
  });

  it('lists each changed parameter, yours then ours', () => {
    const yours = selection({
      concrete: { ...selection().concrete, grade: 'M45' },
      nominal_cover_mm: 30,
      walling_material_id: 'burnt_clay_brick',
    });
    const ours = selection({
      concrete: { ...selection().concrete, grade: 'M45' },
      nominal_cover_mm: 45,
    });

    expect(specChanges(yours, ours)).toEqual([
      { label: 'Concrete cover', from: '30 mm', to: '45 mm' },
      { label: 'Walling', from: 'Burnt clay (red) brick', to: 'Fly ash brick' },
    ]);
  });

  it('shows an added admixture against “None”', () => {
    const ours = selection({
      concrete: { ...selection().concrete, admixtures: ['corrosion inhibitor'] },
    });

    expect(specChanges(selection(), ours)).toEqual([
      { label: 'Admixtures', from: 'None', to: 'corrosion inhibitor' },
    ]);
  });
});

describe('complianceVerdict', () => {
  const short = { parameter: 'nominal_cover_mm', compliant: false } as const;

  it('never says a failing specification meets the code, whatever its band', () => {
    const failing = selection({
      band: 'adequate',
      compliant: false,
      findings: [
        {
          ...short,
          label: 'Concrete cover',
          required: 45,
          provided: 30,
          margin_ratio: -0.33,
          standard: 'IS 456',
          message: '',
        },
      ],
    });

    expect(complianceVerdict(failing, 'Your specification')).toBe(
      'Your specification falls short of the code on 1 check.'
    );
  });

  it('describes the margin once every check is met', () => {
    expect(complianceVerdict(selection({ band: 'good' }), 'A typical local build')).toBe(
      'A typical local build clears the code comfortably.'
    );
  });
});
