/**
 * The single typed API client. Every request in the app goes through here.
 *
 * No component calls `fetch` directly — that rule is what stops error handling and
 * base URLs from being reimplemented slightly differently in a dozen places.
 * Backend errors share one envelope, decoded once here and thrown as `ApiError`.
 */
import type {
  AreaBounds,
  BasemapCapabilities,
  DistrictList,
  GeocodeResults,
  MaterialSelectionInput,
  PinResolution,
  ScoreResponse,
  SiteResponse,
  VoiceCapabilities,
} from '@/types/api';

/** Same origin; Vite proxies `/api` to the backend in development. */
const API_BASE = '/api';

/** A structured failure from the backend, or a transport failure. */
export class ApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly details: Record<string, unknown> | undefined;
  readonly requestId: string | undefined;

  constructor(
    message: string,
    options: {
      code: string;
      status: number;
      details?: Record<string, unknown> | undefined;
      requestId?: string | undefined;
    }
  ) {
    super(message);
    this.name = 'ApiError';
    this.code = options.code;
    this.status = options.status;
    this.details = options.details;
    this.requestId = options.requestId;
  }

  /** Whether this is a setup gap rather than a fault in the request. */
  get isSetupIssue(): boolean {
    return (
      this.code === 'CLIMATE_PROFILE_UNAVAILABLE' ||
      this.code === 'MODEL_UNAVAILABLE' ||
      this.code === 'KNOWLEDGE_BASE_UNAVAILABLE'
    );
  }
}

function isErrorEnvelope(value: unknown): value is {
  error: {
    code: string;
    message: string;
    details?: Record<string, unknown>;
    request_id?: string;
  };
} {
  return (
    typeof value === 'object' &&
    value !== null &&
    'error' in value &&
    typeof value.error === 'object'
  );
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  // Built via Headers rather than object spread: HeadersInit may be an array or a
  // Headers instance, and spreading either into an object yields index keys.
  const headers = new Headers(init?.headers);
  headers.set('Content-Type', 'application/json');

  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, { ...init, headers });
  } catch (cause) {
    // A transport failure has no envelope to decode, so it is given one here
    // rather than surfacing as a bare TypeError inside a component.
    throw new ApiError('Could not reach the server. Is the backend running?', {
      code: 'NETWORK_ERROR',
      status: 0,
      details: { cause: cause instanceof Error ? cause.message : String(cause) },
    });
  }

  const requestId = response.headers.get('X-Request-ID') ?? undefined;
  const body: unknown = await response.json().catch(() => null);

  if (!response.ok) {
    if (isErrorEnvelope(body)) {
      throw new ApiError(body.error.message, {
        code: body.error.code,
        status: response.status,
        details: body.error.details,
        requestId: body.error.request_id ?? requestId,
      });
    }
    throw new ApiError(`Request failed with status ${String(response.status)}.`, {
      code: 'UNKNOWN_ERROR',
      status: response.status,
      requestId,
    });
  }

  return body as T;
}

export const apiClient = {
  /** Districts that have a measured climate profile. */
  getDistricts(): Promise<DistrictList> {
    return request<DistrictList>('/score/districts');
  },

  /**
   * Resolve a point on the globe to the grid cell whose reading applies there.
   *
   * Throws `CLIMATE_PROFILE_UNAVAILABLE` for a point outside the observed region.
   * That rejection is the feature, not an edge case: nearest-cell lookup would
   * otherwise answer a pin in the Atlantic with a confident inland district.
   */
  resolvePin(latitude: number, longitude: number): Promise<PinResolution> {
    return request<PinResolution>('/score/resolve', {
      method: 'POST',
      body: JSON.stringify({ latitude, longitude }),
    });
  },

  /**
   * What the map can actually do with the imagery configured on the server.
   *
   * Fetched rather than hardcoded: the zoom ceiling and the attribution both
   * change with which providers have credentials, and guessing the deeper limit
   * would let the user zoom into blank tiles.
   */
  getBasemapCapabilities(): Promise<BasemapCapabilities> {
    return request<BasemapCapabilities>('/basemap');
  },

  /**
   * Save a drawn outline and get back its authoritative area.
   *
   * Takes the real polygon, not a bounding box: the area returned here is the
   * figure shown to the user, and a box around a triangular plot would claim
   * roughly double its true size.
   *
   * A side effect, not part of scoring: the score endpoints stay pure functions
   * of their inputs, and this is the one call in the app that writes to the
   * database. Its own failure (an implausible area, the database being down) is
   * shown as its own state, never as a reason to block the scoring flow — the
   * user can carry on with the site they drew whether or not it saved.
   */
  saveSite(ring: number[][], label?: string): Promise<SiteResponse> {
    return request<SiteResponse>('/sites', {
      method: 'POST',
      body: JSON.stringify({
        geometry: { type: 'Polygon', coordinates: [ring] },
        label: label ?? null,
      }),
    });
  },

  /** Whether the server can synthesise Tamil narration at all. */
  getVoiceCapabilities(): Promise<VoiceCapabilities> {
    return request<VoiceCapabilities>('/voice/capabilities');
  },

  /**
   * Fetch spoken Tamil for a question and its options.
   *
   * Goes direct rather than through `request`, which decodes JSON — this endpoint
   * returns a WAV file. A failure here is deliberately thrown plain: the caller
   * hides the control rather than showing an error, because the question is
   * already on screen as text.
   */
  async narrate(text: string): Promise<Blob> {
    const response = await fetch(`${API_BASE}/voice/narrate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text }),
    });
    if (!response.ok) {
      throw new ApiError('Voice narration is unavailable.', {
        code: 'VOICE_UNAVAILABLE',
        status: response.status,
      });
    }
    return response.blob();
  },

  /** Find a place, address or postcode anywhere on Earth. */
  geocode(query: string): Promise<GeocodeResults> {
    return request<GeocodeResults>(`/geocode?q=${encodeURIComponent(query)}`);
  },

  /**
   * Score a boundary drawn on the map.
   *
   * The response carries `climate_provenance`, which says whether the climate was
   * measured inside the drawn area or interpolated from surrounding cells. Callers
   * must surface that — an interpolated reading may not be presented as a measured
   * one.
   */
  scoreArea(
    area: AreaBounds,
    materials: MaterialSelectionInput | null,
    situation: MaterialSelectionInput['element_situation']
  ): Promise<ScoreResponse> {
    return request<ScoreResponse>('/score/area', {
      method: 'POST',
      body: JSON.stringify({ area, materials, element_situation: situation }),
    });
  },

  /**
   * Score a district.
   *
   * Passing `materials` evaluates them; omitting it asks for a recommendation
   * against a conventional baseline. Either way the reply carries both sides.
   */
  score(
    district: string,
    materials: MaterialSelectionInput | null,
    situation: MaterialSelectionInput['element_situation']
  ): Promise<ScoreResponse> {
    return request<ScoreResponse>('/score', {
      method: 'POST',
      body: JSON.stringify({
        district,
        materials,
        element_situation: situation,
      }),
    });
  },

  /**
   * Download the client report as a PDF.
   *
   * Goes direct rather than through `request`, which decodes JSON — this endpoint
   * streams a binary file.
   */
  async downloadReport(
    district: string,
    materials: MaterialSelectionInput | null,
    situation: MaterialSelectionInput['element_situation']
  ): Promise<Blob> {
    return reportBlob('/reports', { district, materials, element_situation: situation });
  },

  /**
   * The same report for a drawn outline.
   *
   * A separate endpoint because a drawn site has no district name, and the
   * district report requires one — sending an empty string failed validation
   * before it reached the engine.
   */
  async downloadAreaReport(
    area: AreaBounds,
    materials: MaterialSelectionInput | null,
    situation: MaterialSelectionInput['element_situation']
  ): Promise<Blob> {
    return reportBlob('/reports/area', { area, materials, element_situation: situation });
  },
};

/**
 * Fetch a PDF.
 *
 * Goes direct rather than through `request`, which decodes JSON — these endpoints
 * stream a binary file.
 */
async function reportBlob(path: string, payload: unknown): Promise<Blob> {
  const response = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null);
    if (isErrorEnvelope(body)) {
      throw new ApiError(body.error.message, {
        code: body.error.code,
        status: response.status,
      });
    }
    throw new ApiError('The report could not be generated.', {
      code: 'REPORT_FAILED',
      status: response.status,
    });
  }
  return response.blob();
}
