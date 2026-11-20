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

/** Concrete grades offered in the form, spanning the IS 456 exposure minimums. */
export const CONCRETE_GRADES = ['M15', 'M20', 'M25', 'M30', 'M35', 'M40', 'M45'] as const;

/** Cement types the reference tables distinguish between. */
export const CEMENT_TYPES = [
  { value: 'OPC', label: 'OPC — Ordinary Portland' },
  { value: 'PPC', label: 'PPC — Portland Pozzolana' },
  { value: 'PSC', label: 'PSC — Portland Slag' },
] as const;

/** Walling materials in the reference tables. */
export const WALLING_MATERIALS = [
  { value: 'burnt_clay_brick', label: 'Burnt clay (red) brick' },
  { value: 'fly_ash_brick', label: 'Fly ash brick' },
  { value: 'aac_block', label: 'AAC block' },
  { value: 'concrete_solid_block', label: 'Concrete / solid block' },
  { value: 'engineering_brick', label: 'Engineering brick' },
] as const;
