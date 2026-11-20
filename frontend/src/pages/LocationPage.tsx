/**
 * Step 1 — the globe, full viewport.
 *
 * The globe is the page rather than a widget on it: it is the only screen where
 * the thing being chosen is a place, and a place is best shown at scale. All chrome
 * floats over it on glass so nothing crops the earth.
 *
 * Picking is by plotting an outline around the site — click each corner, then
 * click the first one again to close it. Whether that area has measured climate
 * is decided by the backend at scoring time, not guessed here — this page never
 * substitutes a nearby district for one that has no data.
 */
import { AnimatePresence, motion, useReducedMotion } from 'motion/react';
import { Suspense, lazy, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import type { CameraTarget } from '@/components/globe/DistrictGlobe';
import { MapControls, type MapMode } from '@/components/globe/MapControls';
import { PlaceSearch } from '@/components/globe/PlaceSearch';
import { StepRail } from '@/components/Shell';
import { VoiceExplainer } from '@/components/VoiceExplainer';
import { buildNarration, TA } from '@/lib/narration.ta';
import { useVoice } from '@/state/voice-context';
import { Button, CONTROL, ErrorNotice, Panel, Popup, SPRING, Spinner } from '@/components/ui';
import { apiClient, ApiError } from '@/lib/api-client';
import {
  boundsOf,
  estimateAreaSqFt,
  formatAreaSqFt,
  formatSpan,
  toGeoJsonRing,
  type LatLon,
} from '@/lib/geo';
import { useSession } from '@/state/session-context';
import type { BasemapCapabilities } from '@/types/api';

/** Where saving the drawn boundary to the database currently stands. */
type SaveStatus = 'idle' | 'saving' | 'saved' | 'error';

/**
 * three.js is roughly 1.6 MB. Lazily importing it lets this page's chrome paint
 * and the search box become usable while the graphics stack is still arriving.
 */
const DistrictGlobe = lazy(() =>
  import('@/components/globe/DistrictGlobe').then((module) => ({
    default: module.DistrictGlobe,
  }))
);

/** Leaflet and its stylesheet are only needed once the user goes in close. */
const loadSiteMap = () => import('@/components/globe/SiteMap');
const SiteMap = lazy(() =>
  loadSiteMap().then((module) => ({ default: module.SiteMap }))
);

/**
 * Camera altitude, as a fraction of Earth's radius, at which the flat map takes
 * over from the globe.
 *
 * Roughly 13 km up. Below this the globe's curvature stops helping and starts
 * getting in the way — the ground shears under the cursor and a plotted corner
 * no longer lands where the pointer was clicked.
 */
const HANDOVER_ALTITUDE = 0.002;

/** Slippy-map zoom that frames roughly what the globe showed at handover. */
const HANDOVER_MAP_ZOOM = 15;

/** Factor each zoom-button press multiplies or divides the globe altitude by. */
const ZOOM_STEP = 1.7;

/** Where the globe sits before the user has chosen anything. */
const HOME_LATITUDE = 10.9;
const HOME_LONGITUDE = 78.2;
const HOME_ALTITUDE = 1.6;

/**
 * Map zoom that frames a match of the given width in degrees.
 *
 * The world spans 360 degrees at zoom 0 and halves each level, so the fit is a
 * log2 — plus a bias, because framing an area comfortably means showing a little
 * more than exactly its extent. Clamped so a country does not zoom past the globe
 * handover and a point does not exceed what the imagery publishes.
 */
function zoomForSpan(spanDegrees: number): number {
  const zoom = Math.log2(360 / Math.max(spanDegrees, 0.0005)) + 1.5;
  return Math.round(Math.min(Math.max(zoom, MAP_MIN_ZOOM), 19));
}

/** Never hand over to the map further out than this; the globe is better there. */
const MAP_MIN_ZOOM = 12;

/** Convert a globe camera altitude to the nearest equivalent map zoom. */
function altitudeToZoom(altitude: number): number {
  // Both scales are logarithmic in ground distance, so this is a shift plus a
  // log2. Clamped because a geocoded country would otherwise ask for zoom 0.
  const zoom = Math.round(Math.log2(1 / Math.max(altitude, 0.00001)) + 5);
  return Math.min(Math.max(zoom, HANDOVER_MAP_ZOOM), 21);
}

export default function LocationPage() {
  const { spec, update, area, setArea, districts, districtsError } = useSession();
  const navigate = useNavigate();
  const reduced = useReducedMotion();
  const [browsing, setBrowsing] = useState(false);
  const [query, setQuery] = useState('');
  // Starts in pan mode: exploring the map must never accidentally cut a boundary.
  const [mode, setMode] = useState<MapMode>('pan');
  const [zoomCommand, setZoomCommand] = useState<{ delta: number; nonce: number } | null>(
    null
  );
  /** Globe camera height, tracked so the zoom buttons have something to step. */
  const altitudeRef = useRef(HOME_ALTITUDE);
  const [target, setTarget] = useState<CameraTarget | null>(null);
  const [basemap, setBasemap] = useState<BasemapCapabilities | null>(null);
  const voice = useVoice();
  /** The outline currently being plotted, before it is closed. */
  const [previewArea, setPreviewArea] = useState<readonly LatLon[] | null>(null);
  const [saveStatus, setSaveStatus] = useState<SaveStatus>('idle');
  const [saveError, setSaveError] = useState<unknown>(null);
  /**
   * The authoritative area PostGIS computed on save, once it arrives.
   *
   * Kept separate from the quick client-side estimate so the panel can show the
   * live guess immediately and then visibly refine to the real figure — the two
   * are never blended, so what is on screen is always honestly labelled as one
   * or the other.
   */
  const [savedAreaSqFt, setSavedAreaSqFt] = useState<number | null>(null);
  /**
   * Non-null once the view has handed over to the flat map. Holds where the map
   * is looking, so switching back to the globe returns to the same place rather
   * than to a default view.
   */
  const [mapView, setMapView] = useState<{
    latitude: number;
    longitude: number;
    zoom: number;
  } | null>(null);
  /**
   * Whether the map has ever been needed.
   *
   * Once true it stays true: the map is kept mounted and merely hidden, because
   * unmounting it would throw away its loaded tiles and make every switch back
   * reload them from scratch.
   */
  const [mapEverShown, setMapEverShown] = useState(false);

  // Fetch Leaflet's chunk during idle time rather than at the moment of the
  // switch. Loading it on demand meant the handover blanked the screen while a
  // 44 kB module and its stylesheet arrived — which is the switch feeling like a
  // page load rather than a change of view.
  useEffect(() => {
    const preload = () => {
      void loadSiteMap();
    };
    // Feature-detected rather than trusted from the type declarations: the DOM
    // lib declares requestIdleCallback unconditionally, but Safari shipped it
    // only recently, so on older versions it is typed present and absent at run
    // time — exactly the shape of bug that reaches production.
    if ('requestIdleCallback' in window) {
      const handle = window.requestIdleCallback(preload);
      return () => {
        window.cancelIdleCallback(handle);
      };
    }
    const timer = setTimeout(preload, 400);
    return () => {
      clearTimeout(timer);
    };
  }, []);

  useEffect(() => {
    if (mapView !== null) {
      setMapEverShown(true);
    }
  }, [mapView]);

  // The zoom ceiling and the attribution both depend on which imagery providers
  // the server has credentials for, so they are asked for rather than assumed. A
  // failure here is not worth surfacing: the globe falls back to its own defaults
  // and stays usable, which is better than blocking site selection on a credit line.
  useEffect(() => {
    let cancelled = false;
    apiClient
      .getBasemapCapabilities()
      .then((capabilities) => {
        if (!cancelled) {
          setBasemap(capabilities);
        }
      })
      .catch(() => {
        // Deliberately ignored — see above.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const matches = useMemo(() => {
    const names = districts?.districts ?? [];
    const needle = query.trim().toLowerCase();
    return needle === '' ? names : names.filter((name) => name.toLowerCase().includes(needle));
  }, [districts, query]);

  /** Clears everything to do with a previously drawn boundary. */
  const resetSiteState = useCallback(() => {
    setPreviewArea(null);
    setSaveStatus('idle');
    setSaveError(null);
    setSavedAreaSqFt(null);
  }, []);

  const handleDraw = useCallback(
    (drawn: LatLon[]) => {
      setArea(drawn);
      // An area and a named district are alternatives, not a pair. Clearing the
      // name here is what stops a stale district being scored instead of the box
      // the user just drew.
      update({ district: '' });
      // Put the pencil down once a boundary exists. Leaving it armed means the
      // next click starts silently plotting a replacement for the box just drawn.
      setMode('pan');
      setPreviewArea(null);
      setSavedAreaSqFt(null);
      setSaveError(null);
      setSaveStatus('saving');

      // Saving is a side effect of committing the box, not a gate on continuing:
      // the scoring flow uses the bounds already held in state, so a slow or
      // failed save never blocks the user from moving on with the site they drew.
      apiClient
        .saveSite(toGeoJsonRing(drawn))
        .then((saved) => {
          setSavedAreaSqFt(saved.area_sq_ft);
          setSaveStatus('saved');
        })
        .catch((error: unknown) => {
          setSaveError(error);
          setSaveStatus('error');
        });
    },
    [setArea, update]
  );

  /**
   * Zoom by one step, whichever view is on screen.
   *
   * The globe is driven by flying its camera to a new altitude and the map by
   * stepping its zoom level, so the two need different mechanisms — but the same
   * button, because the user is not thinking about which renderer is active.
   */
  const zoomBy = useCallback(
    (direction: 1 | -1) => {
      if (mapView !== null) {
        setZoomCommand((current) => ({
          delta: direction,
          nonce: (current?.nonce ?? 0) + 1,
        }));
        return;
      }
      // Altitude is a multiplicative scale, so a step is a factor rather than an
      // increment — otherwise the same press would barely move the camera when
      // far out and slam it into the ground when close.
      const next = Math.min(
        Math.max(altitudeRef.current * (direction === 1 ? 1 / ZOOM_STEP : ZOOM_STEP), 0.0001),
        3.5
      );
      altitudeRef.current = next;
      setTarget((current) => ({
        latitude: current?.latitude ?? HOME_LATITUDE,
        longitude: current?.longitude ?? HOME_LONGITUDE,
        altitude: next,
        nonce: (current?.nonce ?? 0) + 1,
      }));
    },
    [mapView]
  );

  const flyTo = useCallback((latitude: number, longitude: number, spanDegrees: number) => {
    // A search always lands on the flat satellite map, whatever the match size.
    // Searching an address is a request to look at the ground there; answering it
    // by rotating a globe leaves the user still needing to zoom in by hand.
    setMapView({ latitude, longitude, zoom: zoomForSpan(spanDegrees) });
  }, []);

  // The globe asks for the handover once the camera drops below the threshold.
  const handleGlobeDescend = useCallback(
    (latitude: number, longitude: number, altitude: number) => {
      altitudeRef.current = altitude;
      setMapView({ latitude, longitude, zoom: altitudeToZoom(altitude) });
    },
    []
  );

  // Zooming back out on the map returns to the globe over the same ground.
  const handleMapZoomOut = useCallback(
    (centre: { latitude: number; longitude: number }) => {
      setMapView(null);
      setTarget((current) => ({
        latitude: centre.latitude,
        longitude: centre.longitude,
        altitude: HANDOVER_ALTITUDE * 4,
        nonce: (current?.nonce ?? 0) + 1,
      }));
    },
    []
  );

  /**
   * Stop the browser page-zooming when the user zooms the map.
   *
   * A pinch on a trackpad, and Ctrl with the wheel, both arrive as a wheel event
   * with `ctrlKey` set — which browsers treat as "zoom the document". Over a map
   * that is never what is meant: it scales the whole interface, panels and all,
   * while the globe underneath does its own thing. Cancelling it here leaves the
   * gesture to the map alone.
   *
   * Registered non-passively because a passive listener is forbidden from calling
   * preventDefault, and React's onWheel is passive by default — so this has to be
   * attached by hand.
   */
  const surfaceRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const element = surfaceRef.current;
    if (element === null) {
      return;
    }
    const onWheel = (event: WheelEvent) => {
      if (event.ctrlKey) {
        event.preventDefault();
      }
    };
    element.addEventListener('wheel', onWheel, { passive: false });
    return () => {
      element.removeEventListener('wheel', onWheel);
    };
  }, []);

  /** Bounding box of the committed outline, for the span readout. */
  const siteBounds = useMemo(() => (area === null ? null : boundsOf(area)), [area]);

  const ready = area !== null || spec.district !== '';

  if (districtsError !== null) {
    return (
      <div className="flex min-h-full items-center justify-center p-6">
        <Panel className="max-w-md p-6">
          <ErrorNotice error={districtsError} />
        </Panel>
      </div>
    );
  }

  return (
    <div ref={surfaceRef} className="relative h-full w-full overflow-hidden bg-void">
      {/* Both views stay mounted and are toggled by visibility rather than being
          swapped. Unmounting the globe would drop its WebGL context and unmounting
          the map would drop its tiles, so either switch would cost a reload — which
          is exactly what made the handover feel like a page change. */}
      <div className="absolute inset-0" hidden={mapView !== null}>
        <Suspense fallback={<GlobeLoading />}>
          <DistrictGlobe
            outline={area}
            drawing={mode === 'draw'}
            onDraw={handleDraw}
            onPreview={setPreviewArea}
            target={target}
            maxZoom={basemap?.max_zoom}
            attribution={basemap?.attribution}
            onDescendBelow={handleGlobeDescend}
            handoverAltitude={HANDOVER_ALTITUDE}
            fullScreen
          />
        </Suspense>
      </div>

      {mapEverShown && (
        <div className="absolute inset-0" hidden={mapView === null}>
          <Suspense fallback={<GlobeLoading />}>
            <SiteMap
              centre={mapView ?? { latitude: 11, longitude: 77 }}
              zoom={mapView?.zoom ?? HANDOVER_MAP_ZOOM}
              outline={area}
              drawing={mode === 'draw'}
              onDraw={handleDraw}
              onPreview={setPreviewArea}
              onZoomOut={handleMapZoomOut}
              zoomCommand={zoomCommand}
              maxZoom={basemap?.max_zoom ?? 19}
              attribution={
                basemap?.attribution ?? 'Imagery © Esri, Maxar, Earthstar Geographics'
              }
              visible={mapView !== null}
            />
          </Suspense>
        </div>
      )}

      {/* Chrome layer. `pointer-events-none` on the wrapper so the globe stays
          draggable everywhere except on an actual control. */}
      {/* Chrome sizes itself from the viewport rather than from fixed steps, so a
          zoomed browser or a scaled display shrinks the panels instead of pushing
          them off the edge. `max-w-full` and `min-w-0` on every column are what
          stop a long line forcing the layout wider than the screen. */}
      {/* z-index above Leaflet's own panes, which go up to 1000. Without it the
          map paints over the search bar, the controls and the site panel — the
          chrome is still in the DOM but completely hidden. */}
      <div className="pointer-events-none absolute inset-0 z-[1100] flex flex-col justify-between gap-4 overflow-hidden p-[clamp(0.75rem,2vw,2rem)]">
        {/* Deliberately unbacked. A glass panel here reads as a card sitting on
            top of the earth and crops the very thing the page is for; legibility
            over bright imagery is handled by the text shadow in `index.css`
            instead, which costs no pixels. */}
        <header className="map-chrome pointer-events-auto flex w-full min-w-0 max-w-[min(30rem,calc(100vw-6rem))] flex-col gap-[clamp(0.5rem,1.4vh,1.25rem)]">
          <StepRail />
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-atmos">
              Step 1 of 5
            </p>
            <h1 className="mt-1.5 text-[clamp(1.35rem,3.2vw,2.25rem)] font-semibold leading-tight tracking-tight text-ink-1">
              Draw your site
            </h1>
            <p className="mt-1.5 text-[clamp(0.8rem,1.1vw,0.95rem)] leading-relaxed text-ink-2">
              {mapView === null
                ? 'Search an address or PIN code, or zoom in — the view switches to a flat satellite map for close work.'
                : mode === 'draw'
                  ? previewArea === null
                    ? 'Click the first corner of your site.'
                    : previewArea.length < 4
                      ? 'Keep clicking corners — at least three.'
                      : 'Click the first corner again to close the shape, or press Enter.'
                  : 'Pick up the pencil, then click around your site to outline it. Zoom out to return to the globe.'}
            </p>
          </div>

          <VoiceExplainer
            text={buildNarration(TA.location.question, TA.location.options)}
            enabled={voice.enabled}
            className="w-fit"
          />

          <PlaceSearch onPick={flyTo} />
        </header>

        <footer className="pointer-events-auto flex flex-wrap items-end justify-between gap-3">
          <Panel className="w-[min(20rem,calc(100vw-8rem))] min-w-0 p-[clamp(0.6rem,1.2vw,1rem)]">
            <p className="text-[11px] uppercase tracking-[0.14em] text-ink-3">Site</p>

            <AnimatePresence mode="wait">
              <motion.div
                key={area === null ? spec.district : 'drawn'}
                initial={reduced === true ? false : { opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                exit={reduced === true ? { opacity: 0 } : { opacity: 0, y: -8 }}
                transition={reduced === true ? { duration: 0 } : SPRING}
              >
                {area !== null ? (
                  <>
                    <p className="mt-1 text-[clamp(1.05rem,2vw,1.5rem)] font-semibold tracking-tight text-ink-1">
                      {/* The authoritative server figure replaces the client
                          guess the instant it arrives, never blended with it. */}
                      {formatAreaSqFt(savedAreaSqFt ?? estimateAreaSqFt(area))}
                    </p>
                    <p className="mt-0.5 text-xs text-ink-3">
                      {siteBounds === null ? '—' : formatSpan(siteBounds)} across ·{' '}
                      {area.length} corners
                    </p>
                    <SaveStatusBadge status={saveStatus} error={saveError} />
                  </>
                ) : previewArea !== null ? (
                  <>
                    <p className="mt-1 text-[clamp(1.05rem,2vw,1.5rem)] font-semibold tracking-tight text-atmos">
                      {formatAreaSqFt(estimateAreaSqFt(previewArea))}
                    </p>
                    <p className="mt-0.5 text-xs text-ink-3">
                      {previewArea.length < 4
                        ? `${String(previewArea.length)} of at least 3 corners`
                        : `${String(previewArea.length)} corners · click the first to close`}
                    </p>
                  </>
                ) : (
                  <p className="mt-1 truncate text-[clamp(1.05rem,2vw,1.5rem)] font-semibold tracking-tight text-ink-1">
                    {spec.district === '' ? 'Nothing yet' : spec.district}
                  </p>
                )}
              </motion.div>
            </AnimatePresence>

            <div className="mt-3 flex items-center gap-4">
              <button
                type="button"
                onClick={() => {
                  setBrowsing(true);
                }}
                className="text-xs font-medium text-atmos underline underline-offset-4"
              >
                Or pick a district
              </button>
              {area !== null && (
                <button
                  type="button"
                  onClick={() => {
                    setArea(null);
                    resetSiteState();
                  }}
                  className="text-xs font-medium text-ink-3 underline underline-offset-4"
                >
                  Clear
                </button>
              )}
            </div>
          </Panel>

          <Button
            onClick={() => {
              void navigate('/exposure');
            }}
            disabled={!ready}
          >
            Continue
            <span aria-hidden="true">→</span>
          </Button>
        </footer>

        {/* Controls sit clear of the header and the site panel, on the middle
            right, where a thumb reaches them and nothing overlaps. */}
        <div className="pointer-events-none absolute right-[clamp(0.75rem,2vw,2rem)] top-1/2 -translate-y-1/2">
          <MapControls
            mode={mode}
            onModeChange={setMode}
            onZoomIn={() => {
              zoomBy(1);
            }}
            onZoomOut={() => {
              zoomBy(-1);
            }}
          />
        </div>
      </div>

      <Popup
        open={browsing}
        title="Find your district"
        description={`${String(districts?.districts.length ?? 0)} districts have measured climate.`}
        onClose={() => {
          setBrowsing(false);
        }}
      >
        <input
          type="search"
          className={CONTROL}
          placeholder="Start typing a district name…"
          value={query}
          autoFocus
          onChange={(event) => {
            setQuery(event.target.value);
          }}
        />
        <ul className="mt-4 max-h-72 space-y-1 overflow-y-auto pr-1">
          {matches.map((name) => (
            <li key={name}>
              <button
                type="button"
                onClick={() => {
                  update({ district: name });
                  // Naming a district replaces any drawn box, for the same reason
                  // drawing clears the name: the two are alternatives.
                  setArea(null);
                  resetSiteState();
                  setBrowsing(false);
                }}
                className={`w-full rounded-lg px-3 py-2.5 text-left text-sm transition-colors ${
                  name === spec.district
                    ? 'bg-atmos/15 font-semibold text-atmos'
                    : 'text-ink-2 hover:bg-white/[0.06] hover:text-ink-1'
                }`}
              >
                {name}
              </button>
            </li>
          ))}
          {matches.length === 0 && (
            <li className="px-3 py-6 text-center text-sm text-ink-3">
              No district matches “{query}”.
            </li>
          )}
        </ul>
      </Popup>
    </div>
  );
}

/**
 * Says whether the drawn boundary actually made it to the database.
 *
 * Never a bare "Saved" with nothing behind it — CLAUDE.md's rule against
 * fabricated states applies to this exactly: the badge only says saved once the
 * server has confirmed the write, and it says plainly when that write failed
 * rather than pretending it succeeded.
 */
function SaveStatusBadge({ status, error }: { status: SaveStatus; error: unknown }) {
  if (status === 'idle') {
    return null;
  }

  if (status === 'saving') {
    return (
      <p className="mt-1.5 flex items-center gap-1.5 text-[11px] text-ink-3">
        <span
          aria-hidden="true"
          className="h-2.5 w-2.5 animate-spin rounded-full border border-white/25 border-t-atmos"
        />
        Saving to the database…
      </p>
    );
  }

  if (status === 'saved') {
    return (
      <p className="mt-1.5 flex items-center gap-1.5 text-[11px] text-band-good">
        <span aria-hidden="true">✓</span>
        Saved to the database
      </p>
    );
  }

  const message =
    error instanceof ApiError ? error.message : "Couldn't save this boundary. You can still continue.";
  return <p className="mt-1.5 text-[11px] text-band-poor">{message}</p>;
}

/**
 * The loading state names what is loading rather than showing a bare spinner, and
 * keeps the earth's silhouette so the layout does not jump when it arrives.
 */
function GlobeLoading() {
  return (
    <div role="status" className="flex h-full w-full items-center justify-center bg-void">
      <div className="flex flex-col items-center gap-5">
        <div className="relative h-40 w-40">
          <div className="absolute inset-0 animate-pulse rounded-full bg-gradient-to-br from-atmos/25 to-transparent" />
          <div className="absolute inset-0 rounded-full border border-atmos/25" />
        </div>
        <Spinner label="Loading satellite imagery…" />
      </div>
    </div>
  );
}
