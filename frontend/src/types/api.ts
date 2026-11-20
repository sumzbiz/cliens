/**
 * Convenient aliases over the generated OpenAPI types.
 *
 * `api.generated.ts` is produced from the backend's live spec by
 * `npm run generate:types` and is never hand-edited. These aliases keep use sites
 * readable while still failing to compile if a backend schema changes.
 */
import type { components } from './api.generated';

type Schemas = components['schemas'];

export type ScoreRequest = Schemas['ScoreRequest'];
export type ScoreResponse = Schemas['ScoreResponse'];
export type ScoredSelection = Schemas['ScoredSelectionResponse'];
export type ComplianceFinding = Schemas['ComplianceFindingResponse'];
export type Recommendation = Schemas['RecommendationResponse'];
export type ClimateProfile = Schemas['ClimateProfileResponse'];
export type DistrictList = Schemas['DistrictListResponse'];
export type DistrictLocation = Schemas['DistrictLocation'];
export type CoverageBounds = Schemas['CoverageBounds'];
export type PinResolution = Schemas['PinResolutionResponse'];
export type AreaBounds = Schemas['AreaBoundsInput'];
export type ClimateProvenance = Schemas['ClimateProvenanceResponse'];
export type BasemapCapabilities = Schemas['BasemapCapabilities'];
export type VoiceCapabilities = Schemas['VoiceCapabilities'];
export type SiteResponse = Schemas['SiteResponse'];
export type GeocodeResults = Schemas['GeocodeResponse'];
export type GeocodeMatch = Schemas['GeocodeMatch'];
export type MaterialSelectionInput = Schemas['MaterialSelectionInput'];
export type ConcreteMixInput = Schemas['ConcreteMixInput'];
// Inlined by openapi-typescript rather than emitted as named schemas, so these
// are derived from the fields that use them and stay in sync automatically.
export type ElementSituation = MaterialSelectionInput['element_situation'];
export type ScoreBand = ScoredSelection['band'];
export type MemberType = ScoredSelection['member'];

export type MaterialCatalogue = Schemas['MaterialCatalogueResponse'];
export type MaterialResponse = Schemas['MaterialResponse'];
export type ErrorResponse = Schemas['ErrorResponse'];

/** How the element sits relative to the weather, with plain-language labels. */
export const ELEMENT_SITUATIONS: { value: ElementSituation; label: string; hint: string }[] = [
  { value: 'enclosed', label: 'Enclosed', hint: 'Inside, never touched by rain' },
  { value: 'sheltered', label: 'Sheltered', hint: 'Under cover, normal humidity' },
  { value: 'exposed', label: 'Exposed', hint: 'Open to rain and sun' },
  { value: 'buried', label: 'Buried', hint: 'In contact with soil' },
  { value: 'tidal', label: 'Tidal', hint: 'In the tidal zone' },
];

/**
 * Which reinforced-concrete member is being specified. It sets the cover the code
 * requires: IS 456 clause 26.4.2 raises Table 16's figure for columns and footings.
 */
export const MEMBER_TYPES: { value: MemberType; label: string; hint: string }[] = [
  { value: 'slab', label: 'Slab', hint: 'A floor or roof slab' },
  { value: 'beam', label: 'Beam', hint: 'Spans between columns or walls' },
  { value: 'column', label: 'Column', hint: 'Vertical, carries the floors above' },
  { value: 'footing', label: 'Footing', hint: 'The foundation, in the ground' },
];

/** Concrete grades offered in the form, spanning the IS 456 exposure minimums. */
export const CONCRETE_GRADES = ['M15', 'M20', 'M25', 'M30', 'M35', 'M40', 'M45'] as const;

/** Cement types the reference tables distinguish between. */
export const CEMENT_TYPES = [
  { value: 'OPC', label: 'OPC — Ordinary Portland' },
  { value: 'PPC', label: 'PPC — Portland Pozzolana' },
  { value: 'PSC', label: 'PSC — Portland Slag' },
] as const;

/**
 * Admixtures the rules give credit for, by the exact names the backend matches on
 * (`ADMIXTURE_FEATURES` in app/ml/quality_score.py). The form had no way to choose
 * them, so a recommendation that added one always looked better than any
 * specification a user could enter.
 */
export const ADMIXTURES = [
  {
    value: 'corrosion inhibitor',
    label: 'Corrosion inhibitor',
    hint: 'Protects the steel from chlorides. Advised near the coast.',
  },
  {
    value: 'waterproofing admixture',
    label: 'Waterproofing admixture',
    hint: 'Lowers water absorption. Advised where it rains often.',
  },
] as const;

/** Walling materials in the reference tables. */
export const WALLING_MATERIALS = [
  { value: 'burnt_clay_brick', label: 'Burnt clay (red) brick' },
  { value: 'fly_ash_brick', label: 'Fly ash brick' },
  { value: 'aac_block', label: 'AAC block' },
  { value: 'concrete_solid_block', label: 'Concrete / solid block' },
  { value: 'engineering_brick', label: 'Engineering brick' },
] as const;
