/**
 * Quick, local approximations for a drawn boundary, used only for live feedback
 * while the user is still plotting.
 *
 * These are deliberately not the number that gets saved. The authoritative area
 * is computed server-side by PostGIS on the WGS84 spheroid once the boundary is
 * committed — see `apiClient.saveSite` — because that calculation accounts for
 * the Earth's curvature properly, and re-deriving it in the browser would be
 * exactly the kind of duplicated calculation CLAUDE.md's DRY rule forbids. This
 * exists only so the panel shows *a* number while the outline is still being
 * drawn, rather than nothing, and it is replaced by the real figure the moment
 * saving completes.
 */

/** Metres per degree of latitude, WGS84 mean — matches the backend's own figure. */
const METRES_PER_DEGREE_LATITUDE = 111_320;

/** Exact by definition: 1 sq ft = 0.09290304 sq m. */
const SQ_FT_PER_SQ_M = 1 / 0.09290304;

/** One vertex of a drawn outline. */
export interface LatLon {
  latitude: number;
  longitude: number;
}

export interface LatLonBox {
  south: number;
  north: number;
  west: number;
  east: number;
}

/**
 * The bounding box of a drawn outline.
 *
 * Used for the climate lookup, which resolves to 27 km grid cells — at that
 * scale the difference between a plot's true outline and the box around it is
 * far below the resolution of the data, so sending the box costs nothing. The
 * *area*, by contrast, is computed from the real outline, because there the
 * difference is the whole point.
 */
export function boundsOf(vertices: readonly LatLon[]): LatLonBox | null {
  if (vertices.length === 0) {
    return null;
  }
  const latitudes = vertices.map((vertex) => vertex.latitude);
  const longitudes = vertices.map((vertex) => vertex.longitude);
  return {
    south: Math.min(...latitudes),
    north: Math.max(...latitudes),
    west: Math.min(...longitudes),
    east: Math.max(...longitudes),
  };
}

/**
 * Equirectangular estimate of a drawn outline's ground area, in square feet.
 *
 * The shoelace formula on locally projected metres. Accurate to a fraction of a
 * percent for anything under a few kilometres across — every real building site —
 * because the projection only breaks down at scales where the Earth's curvature
 * matters within the outline itself.
 *
 * Returns 0 for fewer than three vertices, which is not an error: it is what a
 * half-drawn outline is worth, and the panel shows it as such.
 */
export function estimateAreaSqFt(vertices: readonly LatLon[]): number {
  if (vertices.length < 3) {
    return 0;
  }

  // Project to metres about the outline's own mean latitude, so the longitude
  // scaling is right for where the plot actually is.
  const meanLatitude =
    vertices.reduce((total, vertex) => total + vertex.latitude, 0) / vertices.length;
  const metresPerDegreeLongitude =
    METRES_PER_DEGREE_LATITUDE * Math.cos(meanLatitude * (Math.PI / 180));

  const points = vertices.map((vertex) => ({
    x: vertex.longitude * metresPerDegreeLongitude,
    y: vertex.latitude * METRES_PER_DEGREE_LATITUDE,
  }));

  let twiceSignedArea = 0;
  for (let index = 0; index < points.length; index++) {
    const current = points[index];
    const next = points[(index + 1) % points.length];
    if (current === undefined || next === undefined) {
      continue;
    }
    twiceSignedArea += current.x * next.y - next.x * current.y;
  }

  // Absolute value: the sign only encodes winding direction, which is not
  // something the user chose or should be penalised for.
  return (Math.abs(twiceSignedArea) / 2) * SQ_FT_PER_SQ_M;
}

/** Formats a square-foot figure with thousands separators, no decimal noise. */
export function formatAreaSqFt(areaSqFt: number): string {
  return `${new Intl.NumberFormat('en-IN', { maximumFractionDigits: 0 }).format(areaSqFt)} sq ft`;
}

/**
 * A closed GeoJSON ring for the API, in (lon, lat) order per RFC 7946.
 *
 * The closing vertex is appended here rather than left to the caller, because
 * forgetting it is the classic GeoJSON bug and the backend would otherwise have
 * to guess whether an unclosed ring was a mistake or a short polygon.
 */
export function toGeoJsonRing(vertices: readonly LatLon[]): number[][] {
  const ring = vertices.map((vertex) => [vertex.longitude, vertex.latitude]);
  const first = ring[0];
  if (first !== undefined) {
    ring.push([...first]);
  }
  return ring;
}

/**
 * The longer side of an outline's bounding box, in whichever unit reads sensibly.
 *
 * Building sites are tens of metres across, so a kilometres-only version rounds
 * every real plot to "0 km" — a number that tells the user nothing about what
 * they just drew.
 */
export function formatSpan(box: LatLonBox): string {
  const latitudeMetres = (box.north - box.south) * METRES_PER_DEGREE_LATITUDE;
  const midLatitude = ((box.south + box.north) / 2) * (Math.PI / 180);
  const longitudeMetres =
    (box.east - box.west) * METRES_PER_DEGREE_LATITUDE * Math.cos(midLatitude);
  const metres = Math.max(latitudeMetres, longitudeMetres);

  return metres < 1000 ? `${metres.toFixed(0)} m` : `${(metres / 1000).toFixed(1)} km`;
}
