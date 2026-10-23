/**
 * 3D satellite globe. Drag the earth to look around; plot a site by clicking.
 *
 * IMAGERY
 * A tile engine rather than a single texture. One equirectangular JPEG is 2048 px
 * wide for the whole planet — about 20 km per pixel, so a district is a smudge.
 * `globeTileEngineUrl` streams standard slippy-map tiles instead, so resolution
 * increases as the camera descends and the imagery stays sharp all the way down to
 * building scale, over the whole globe.
 *
 * ZOOM
 * Unrestricted, from the full disc to close-in. An earlier version floored the zoom
 * at the climate grid resolution to stop the imagery implying per-building
 * precision. That guard now lives where it belongs — on the result, which states
 * how many measured cells stand behind the number and whether any of it was
 * interpolated — rather than by crippling navigation.
 *
 * SELECTION
 * Drawing is opt-in, armed by the pencil button on the page, and works by
 * plotting an outline: click each corner in turn, then click the first vertex
 * again to close the shape. Rotation is frozen for the duration — not just
 * during a captured drag — so a click can never also spin the globe out from
 * under the point being placed. That is also why this is a plot and not a drag:
 * a single continuous gesture has no natural moment to say "this corner is where
 * I meant," whereas a deliberate click does.
 *
 * A polygon rather than a rectangle because real plots are rarely square, and a
 * box around a triangular corner plot claims roughly double its true area.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Globe, { type GlobeMethods } from 'react-globe.gl';

import type { LatLon } from '@/lib/geo';

/** Earth radius in the units react-globe.gl uses for camera altitude. */
const GLOBE_RADIUS_UNITS = 100;

const HOME_VIEW = { lat: 10.9, lng: 78.2, altitude: 1.6 };
const INITIAL_VIEW = { lat: 14, lng: 40, altitude: 3.2 };

/**
 * Closest the camera may come to the surface, as a multiple of Earth's radius.
 *
 * 0.00005 x 6371 km is about 320 m up — low enough to read a street layout and
 * pick out individual roofs. The previous value of 0.0015 worked out at 9.5 km,
 * which is why zooming appeared to stop early and then just magnified blur: the
 * camera physically could not get closer, so no deeper tiles were ever requested.
 */
const MIN_ALTITUDE = 0.00005;
const MAX_ALTITUDE = 4.5;

/**
 * Deepest tile level the engine may request, when the server has not said.
 *
 * three-globe defaults this to 17 and never asks for anything sharper, so past
 * that point zooming stretched level-17 tiles instead of loading deeper ones —
 * the "pixels breaking" effect. The real ceiling comes from the API, because it
 * depends on which imagery providers are configured; this is only the value used
 * before that answer arrives.
 *
 * It is passed as a spread prop because react-globe.gl's bundled type
 * declarations lag its runtime and omit this one. Spreading is not a workaround
 * for a missing feature: react-kapsule applies every prop it receives to the
 * underlying instance, while the component ref only exposes explicitly declared
 * methods — so a prop is the supported route and a ref call would silently do
 * nothing.
 */
const FALLBACK_TILE_LEVEL = 19;

/**
 * Tiles come from our own API, not straight from the imagery provider.
 *
 * The globe paints one image layer, but satellite imagery and its place names are
 * published as two. The backend fetches both and flattens them into a single JPEG,
 * so what arrives here already has roads, boundaries and place names on it — which
 * is what makes it possible to find an actual plot rather than an anonymous field.
 *
 * The tradeoff, stated rather than buried: this needs the network, and the imagery
 * is Esri's, whose terms require the attribution rendered in the corner. Nothing
 * about the score depends on it — the climate data is bundled locally — so if tiles
 * fail the globe still works as a picker; it just looks plain.
 */
const TILE_URL = (x: number, y: number, level: number): string =>
  `/api/tiles/${String(level)}/${String(x)}/${String(y)}`;

/** How close, in pixels, a click must land to the first vertex to close a ring. */
const CLOSE_RING_PIXELS = 14;

function prefersReducedMotion(): boolean {
  return (
    typeof window !== 'undefined' &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches
  );
}

/** A drawn outline as a closed GeoJSON ring, in (lon, lat) order. */
function ringFor(vertices: readonly LatLon[]): number[][] {
  const ring = vertices.map((vertex) => [vertex.longitude, vertex.latitude]);
  const first = ring[0];
  if (first !== undefined) {
    ring.push([...first]);
  }
  return ring;
}

/** Where the camera should be looking. Changing this flies the globe there. */
export interface CameraTarget {
  latitude: number;
  longitude: number;
  /** Camera height as a multiple of Earth's radius. */
  altitude: number;
  /** Bumped to re-trigger a flight to the same place. */
  nonce: number;
}

export function DistrictGlobe({
  outline,
  drawing,
  onDraw,
  onPreview,
  target,
  maxZoom,
  attribution,
  onDescendBelow,
  handoverAltitude,
  fullScreen = false,
}: {
  /** The committed site outline, if one has been drawn. */
  outline: readonly LatLon[] | null;
  /** Whether plotting is armed. When false, dragging always rotates. */
  drawing: boolean;
  onDraw: (outline: LatLon[]) => void;
  /**
   * Fired on every vertex placed and every move, and with `null` the moment the
   * outline is committed or cancelled. Exists so the page can show a live area
   * estimate before there is anything to save.
   */
  onPreview?: ((outline: readonly LatLon[] | null) => void) | undefined;
  /** Set by a place search. Null leaves the camera where the user put it. */
  target: CameraTarget | null;
  /** Deepest zoom the server's imagery actually reaches. */
  maxZoom?: number | undefined;
  /** Credit line for whichever providers are active. */
  attribution?: string | undefined;
  /**
   * Fired once the camera drops below `handoverAltitude`.
   *
   * The globe does not switch views itself — it reports the descent and lets the
   * page decide, so the two views stay independent of each other.
   */
  onDescendBelow?: ((latitude: number, longitude: number, altitude: number) => void) | undefined;
  handoverAltitude?: number | undefined;
  fullScreen?: boolean;
}) {
  const globeRef = useRef<GlobeMethods | undefined>(undefined);
  const containerRef = useRef<HTMLDivElement>(null);
  const [ready, setReady] = useState(false);
  const [size, setSize] = useState({ width: 0, height: 0 });
  /** The outline currently being plotted, shown live. */
  const [preview, setPreview] = useState<readonly LatLon[] | null>(null);
  /** Vertices placed so far in the outline currently being drawn. */
  const verticesRef = useRef<LatLon[]>([]);

  // The WebGL canvas needs explicit pixel dimensions — it cannot be sized in
  // percentages — so the container is measured and the canvas follows it. This
  // also covers window resize and device rotation for free.
  useEffect(() => {
    const element = containerRef.current;
    if (element === null) {
      return;
    }
    const observer = new ResizeObserver(([entry]) => {
      if (entry !== undefined) {
        setSize({ width: entry.contentRect.width, height: entry.contentRect.height });
      }
    });
    observer.observe(element);
    return () => {
      observer.disconnect();
    };
  }, []);

  const handleReady = useCallback(() => {
    const globe = globeRef.current;
    if (globe === undefined) {
      return;
    }

    const controls = globe.controls();
    controls.enableDamping = true; // inertia, so drags coast rather than stop dead
    controls.dampingFactor = 0.08;
    controls.rotateSpeed = 0.4;
    // Zoom speed is constant in OrbitControls, which makes the last few metres
    // crawl and the first few thousand kilometres lurch. Damping plus a moderate
    // rate is the closest this control model gets to a proportional zoom.
    controls.zoomSpeed = 1.1;
    controls.minDistance = GLOBE_RADIUS_UNITS * (1 + MIN_ALTITUDE);
    controls.maxDistance = GLOBE_RADIUS_UNITS * (1 + MAX_ALTITUDE);

    if (!prefersReducedMotion()) {
      controls.autoRotate = true;
      controls.autoRotateSpeed = 0.28;
      controls.addEventListener('start', () => {
        controls.autoRotate = false;
      });
    }

    globe.pointOfView(INITIAL_VIEW, 0);
    globe.pointOfView(HOME_VIEW, prefersReducedMotion() ? 0 : 3000);
    setReady(true);
  }, []);

  // Report a descent past the handover point. `onZoom` fires continuously during
  // a zoom, so the guard is on altitude alone — the page unmounts this component
  // in response, which is what stops it firing repeatedly.
  const handleZoom = useCallback(
    (pov: { lat: number; lng: number; altitude: number }) => {
      if (
        onDescendBelow !== undefined &&
        handoverAltitude !== undefined &&
        pov.altitude < handoverAltitude
      ) {
        onDescendBelow(pov.lat, pov.lng, pov.altitude);
      }
    },
    [onDescendBelow, handoverAltitude]
  );

  // A search result moves the camera. `nonce` is in the dependency list so
  // searching the same place twice flies there twice, rather than being skipped
  // because the coordinates did not change.
  useEffect(() => {
    if (target === null || !ready) {
      return;
    }
    globeRef.current?.pointOfView(
      { lat: target.latitude, lng: target.longitude, altitude: target.altitude },
      prefersReducedMotion() ? 0 : 1800
    );
  }, [target, ready]);

  /**
   * Outline plotting: click each corner in turn, then click the first vertex
   * again — or press Enter — to close the shape.
   *
   * `toGlobeCoords` converts a screen position to a point on the sphere, returning
   * null where the ray misses the globe — a corner can only ever be placed on the
   * earth itself, never off its edge.
   *
   * OrbitControls is frozen for as long as drawing is armed, not just mid-plot.
   * A globe that kept spinning between clicks would put the next vertex somewhere
   * other than where the user was looking when they clicked it.
   *
   * `drawing` is shared with the flat map — one pencil button drives both — so
   * this runs just as much while the globe is hidden behind the map as while it
   * is on screen. `!globe` (rather than `=== undefined`) is deliberate: once the
   * `<Globe>` element unmounts, which it does here because its hidden container
   * collapses to zero size, react-globe.gl clears the ref to `null`, not
   * `undefined`, and this effect must not act on a torn-down instance either way.
   */
  useEffect(() => {
    const element = containerRef.current;
    const globe = globeRef.current;
    if (element === null || !globe || !ready) {
      return;
    }

    if (!drawing) {
      // Covers leaving draw mode mid-plot (switching to pan, or navigating away):
      // half-placed vertices must not linger as a stuck shape on the globe, and
      // the page's live estimate must be told there is nothing to show any more.
      globe.controls().enabled = true;
      if (verticesRef.current.length > 0) {
        verticesRef.current = [];
        setPreview(null);
        onPreview?.(null);
      }
      return;
    }

    globe.controls().enabled = false;

    const toCoords = (event: PointerEvent): LatLon | null => {
      const rect = element.getBoundingClientRect();
      const point = globe.toGlobeCoords(
        event.clientX - rect.left,
        event.clientY - rect.top
      );
      return point === null ? null : { latitude: point.lat, longitude: point.lng };
    };

    const cancelPending = () => {
      if (verticesRef.current.length > 0) {
        verticesRef.current = [];
        setPreview(null);
        onPreview?.(null);
      }
    };

    const commit = () => {
      const vertices = verticesRef.current;
      // Fewer than three points is a line, not a plot.
      if (vertices.length < 3) {
        return;
      }
      const finished = [...vertices];
      cancelPending();
      onDraw(finished);
    };

    const onPointerMove = (event: PointerEvent) => {
      if (verticesRef.current.length === 0) {
        return;
      }
      const current = toCoords(event);
      if (current === null) {
        return;
      }
      // The live shape includes the point under the cursor, so what is drawn and
      // what the panel reports are the same shape.
      const live = [...verticesRef.current, current];
      setPreview(live);
      onPreview?.(live);
    };

    const onPointerDown = (event: PointerEvent) => {
      const point = toCoords(event);
      if (point === null) {
        return;
      }

      const vertices = verticesRef.current;
      const first = vertices[0];
      if (first !== undefined && vertices.length >= 3) {
        const firstScreen = globe.getScreenCoords(first.latitude, first.longitude);
        const rect = element.getBoundingClientRect();
        const dx = firstScreen.x - (event.clientX - rect.left);
        const dy = firstScreen.y - (event.clientY - rect.top);
        if (Math.hypot(dx, dy) <= CLOSE_RING_PIXELS) {
          commit();
          return;
        }
      }

      verticesRef.current = [...vertices, point];
      setPreview(verticesRef.current);
      onPreview?.(verticesRef.current);
    };

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        cancelPending();
        return;
      }
      if (event.key === 'Enter') {
        commit();
        return;
      }
      // Undo the last vertex rather than the whole outline: a misplaced corner
      // five clicks in should not cost the other four.
      if (event.key === 'Backspace' && verticesRef.current.length > 0) {
        event.preventDefault();
        verticesRef.current = verticesRef.current.slice(0, -1);
        const remaining = verticesRef.current;
        setPreview(remaining.length === 0 ? null : remaining);
        onPreview?.(remaining.length === 0 ? null : remaining);
      }
    };

    element.addEventListener('pointerdown', onPointerDown);
    element.addEventListener('pointermove', onPointerMove);
    window.addEventListener('keydown', onKeyDown);
    return () => {
      element.removeEventListener('pointerdown', onPointerDown);
      element.removeEventListener('pointermove', onPointerMove);
      window.removeEventListener('keydown', onKeyDown);
      cancelPending();
    };
  }, [ready, drawing, onDraw, onPreview]);

  /** The live preview wins over the committed outline while plotting. */
  const shown = preview ?? outline;

  const polygons = useMemo(
    () =>
      // Two vertices are an edge, not a polygon — three.js would render a
      // degenerate face, so nothing is drawn until there is a real shape.
      shown === null || shown.length < 3
        ? []
        : [
            {
              geometry: { type: 'Polygon' as const, coordinates: [ringFor(shown)] },
              committed: preview === null,
            },
          ],
    [shown, preview]
  );

  return (
    <div
      ref={containerRef}
      className={`relative bg-void ${fullScreen ? 'h-full w-full' : 'h-[320px] w-full overflow-hidden rounded-xl border border-white/10'} ${
        drawing ? 'cursor-crosshair' : 'cursor-grab active:cursor-grabbing'
      }`}
      // The browser's own drag-to-pan would fight the rectangle drag on touch.
      style={{ touchAction: 'none' }}
    >
      {size.width > 0 && size.height > 0 && (
        <Globe
          ref={globeRef}
          width={size.width}
          height={size.height}
          globeTileEngineUrl={TILE_URL}
          // More segments across the sphere. At the default the horizon visibly
          // facets once the camera is low, because a coarse mesh cannot follow the
          // curvature at that scale.
          globeCurvatureResolution={1}
          {...({ globeTileEngineMaxLevel: maxZoom ?? FALLBACK_TILE_LEVEL } as Record<string, unknown>)}
          backgroundColor="rgba(0,0,0,0)"
          atmosphereColor="#7cc7f0"
          atmosphereAltitude={0.14}
          onGlobeReady={handleReady}
          onZoom={handleZoom}
          polygonsData={polygons}
          polygonGeoJsonGeometry="geometry"
          // The preview is fainter than the committed selection, so the moment the
          // drag is released reads as the boundary being accepted.
          polygonCapColor={(d) =>
            (d as { committed: boolean }).committed
              ? 'rgba(124, 199, 240, 0.20)'
              : 'rgba(124, 199, 240, 0.10)'
          }
          polygonSideColor={() => 'rgba(124, 199, 240, 0.22)'}
          polygonStrokeColor={() => '#7cc7f0'}
          polygonAltitude={0.004}
          polygonsTransitionDuration={0}
        />
      )}

      {/* Covers the canvas until the scene is genuinely up, rather than showing a
          spinner over a half-drawn globe. */}
      {!ready && (
        <div
          role="status"
          className="absolute inset-0 flex flex-col items-center justify-center gap-4 bg-void"
        >
          <div className="h-24 w-24 animate-pulse rounded-full bg-gradient-to-br from-atmos/30 to-transparent" />
          <p className="text-sm text-ink-3">Loading satellite imagery…</p>
        </div>
      )}

      {/* Attribution is a condition of using the tile service, so it is part of the
          component rather than something a page can forget. */}
      <p className="pointer-events-none absolute bottom-3 right-4 text-[10px] text-ink-3/60">
        {attribution ?? 'Imagery © Esri, Maxar, Earthstar Geographics'}
      </p>
    </div>
  );
}
