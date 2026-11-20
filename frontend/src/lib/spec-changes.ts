/**
 * What "What we'd specify" actually changes, parameter by parameter.
 *
 * The score page used to show the recommended specification only as a number, so
 * a user could see that it scored higher but not what to change to get there.
 * This lists every parameter where the recommendation differs from theirs. One
 * function, so the change list, the comparison message and the Tamil narration
 * cannot disagree about whether anything changes.
 */
import { CEMENT_TYPES, WALLING_MATERIALS, type ScoredSelection } from '@/types/api';

export interface SpecChange {
  label: string;
  from: string;
  to: string;
}

function wallingLabel(id: string): string {
  return WALLING_MATERIALS.find((material) => material.value === id)?.label ?? id;
}

function cementTypeLabel(type: string): string {
  return CEMENT_TYPES.find((option) => option.value === type)?.label ?? type;
}

function admixtureList(admixtures: readonly string[]): string {
  return admixtures.length === 0 ? 'None' : admixtures.join(', ');
}

/** The parameters that differ, in the order a builder reads a specification. */
export function specChanges(yours: ScoredSelection, ours: ScoredSelection): SpecChange[] {
  const changes: SpecChange[] = [];
  const add = (label: string, from: string, to: string) => {
    if (from !== to) {
      changes.push({ label, from, to });
    }
  };

  add('Concrete grade', yours.concrete.grade, ours.concrete.grade);
  add(
    'Cement content',
    `${yours.concrete.cement_content_kg_m3.toFixed(0)} kg/m³`,
    `${ours.concrete.cement_content_kg_m3.toFixed(0)} kg/m³`
  );
  add(
    'Water / cement ratio',
    yours.concrete.water_cement_ratio.toFixed(2),
    ours.concrete.water_cement_ratio.toFixed(2)
  );
  add(
    'Cement type',
    cementTypeLabel(yours.concrete.cement_type),
    cementTypeLabel(ours.concrete.cement_type)
  );
  add(
    'Admixtures',
    admixtureList(yours.concrete.admixtures),
    admixtureList(ours.concrete.admixtures)
  );
  add(
    'Concrete cover',
    `${yours.nominal_cover_mm.toFixed(0)} mm`,
    `${ours.nominal_cover_mm.toFixed(0)} mm`
  );
  add('Walling', wallingLabel(yours.walling_material_id), wallingLabel(ours.walling_material_id));
  return changes;
}
