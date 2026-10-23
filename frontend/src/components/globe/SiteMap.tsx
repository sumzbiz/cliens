/**
 * Flat satellite map for close-in work.
 *
 * WHY THIS EXISTS ALONGSIDE THE GLOBE
 * A globe is the right way to *find* a place and the wrong way to *inspect* one.
 * Its camera orbits a sphere, so at building scale the ground shears under the
 * cursor and the near clipping plane starts eating the mesh. A slippy map has none
 * of those problems: it is the projection tile pyramids were designed for, so it
 * zooms to the deepest published level cleanly and a plotted corner lands exactly
 * where the pointer was when it was clicked.
 *
 * So the globe owns exploration and this owns detail. The handover is automatic —
 * see `LocationPage` — and both feed the same boundary handler, so the step after
 * cannot tell which one drew the outline.
 *
 * TILES COME STRAIGHT FROM THE PROVIDER, NOT THROUGH OUR API
 * The globe has to use our compositing endpoint because it paints a single image
 * layer, so the imagery and its labels must be flattened into one picture first.
 * Leaflet stacks layers natively, so that flattening is not just unnecessary here
 * — it is actively harmful. Routing through the server turned every tile into two
 * upstream fetches plus a decode, paste and re-encode, and a single screen is
 * twenty to forty tiles. That is what made panning stutter.
 *
 * Fetching direct restores the browser's own parallelism, its HTTP cache, and
 * Leaflet's prefetching, none of which the proxy could offer.
 *
 * Leaflet is driven directly rather than through react-leaflet's components. The
 * outline interaction needs raw map events and temporary control of dragging,
 * which is more awkward to express through the declarative wrapper than through
 * the imperative API it wraps.
 */
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import { useEffect, useRef, useState } from 'react';

import type { LatLon } from '@/lib/geo';

/** Below this the globe is the better view; at or above it, this one is. */
export const MAP_HANDOVER_ZOOM = 12;

/**
 * How far past the deepest published tile the user may keep zooming.
 *
 * Leaflet upscales the last real tile rather than requesting one that does not
 * exist, so these levels are soft rather than sharp — but a soft image that keeps
 * responding beats a zoom control that stops dead.
 */
const OVERZOOM_LEVELS = 3;

/** Deepest level the label overlay publishes; past this it returns empty tiles. */
const LABEL_MAX_ZOOM = 18;

const ESRI_BASE = 'https://server.arcgisonline.com/ArcGIS/rest/services';
const ESRI_WORLD_IMAGERY = `${ESRI_BASE}/World_Imagery/MapServer/tile/{z}/{y}/{x}`;
const ESRI_LABELS = `${ESRI_BASE}/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}`;
const ESRI_CLARITY =
  'https://clarity.maptiles.arcgis.com/arcgis/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}';

/**
 * How close, in pixels, a click must land to the first vertex to close the ring.
 *
 * Measured in screen space rather than degrees: what matters is whether the user
 * was aiming at the marker they can see, and that target is the same size on
 * screen at every zoom level.
 */
const CLOSE_RING_PIXELS = 14;

const OUTLINE_COLOUR = '#7cc7f0';

export function SiteMap({
  centre,
  zoom,
  outline,
  drawing,
  onDraw,
  onPreview,
  onZoomOut,
  maxZoom,
  attribution,
  zoomCommand,
  visible,
}: {
  centre: { latitude: number; longitude: number };
  zoom: number;
  /** The committed site outline, if one has been drawn. */
  outline: readonly LatLon[] | null;
  drawing: boolean;
  onDraw: (outline: LatLon[]) => void;
  /**
   * Fired on every vertex placed and every move, and with `null` once the outline
   * is committed or cancelled — mirrors `DistrictGlobe`'s prop of the same name
   * so the page can treat both renderers identically.
   */
  onPreview?: ((outline: readonly LatLon[] | null) => void) | undefined;
  /** Fired when the user zooms back out far enough to want the globe again. */
  onZoomOut: (centre: { latitude: number; longitude: number }) => void;
  maxZoom: number;
  attribution: string;
  /** Bumped by the zoom buttons; the sign says which way. */
  zoomCommand: { delta: number; nonce: number } | null;
  /**
   * Whether the map is the view on screen.
   *
   * It stays mounted while hidden so switching back is instant, but Leaflet
   * measures its container on creation and a hidden container measures zero — so
   * it has to be told to re-measure whenever it becomes visible again.
   */
  visible: boolean;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<L.Map | null>(null);
  const shapeRef = useRef<L.Polygon | null>(null);
  /** Vertices placed so far in the outline currently being drawn. */
  const verticesRef = useRef<L.LatLng[]>([]);
  const [ready, setReady] = useState(false);

  // Created once. Centre and zoom changes are applied through the effects below
  // rather than by rebuilding, because tearing down a Leaflet map discards its
  // tile cache and makes every prop change flash white.
  useEffect(() => {
    const element = containerRef.current;
    if (element === null || mapRef.current !== null) {
      return;
    }

    const map = L.map(element, {
      center: [centre.latitude, centre.longitude],
      zoom,
      // The page supplies its own zoom buttons, which also drive the globe. Two
      // sets of controls doing the same job in different places is worse than one.
      zoomControl: false,
      attributionControl: true,
      maxZoom: maxZoom + OVERZOOM_LEVELS,
      // Continuous rather than stepped zoom, so the wheel feels like the globe's
      // rather than jumping a whole power of two per notch.
      zoomSnap: 0,
      zoomDelta: 0.4,
      // Leaflet's default is a hard 1:1 wheel step, which feels stepped after the
      // globe's continuous zoom. Scroll-wheel smoothing makes the handover between
      // the two views far less jarring.
      scrollWheelZoom: true,
      wheelDebounceTime: 20,
      wheelPxPerZoomLevel: 100,
    });

    // Shared by every layer. `maxNativeZoom` is the deepest level actually
    // published; `maxZoom` is how far the user may keep going, with Leaflet
    // upscaling the last real tile. Letting them overshoot by OVERZOOM_LEVELS
    // means zoom never hits a wall — it goes soft, which beats stopping dead.
    const tileOptions: L.TileLayerOptions = {
      maxZoom: maxZoom + OVERZOOM_LEVELS,
      maxNativeZoom: maxZoom,
      // Keep a ring of tiles beyond the viewport so a pan reveals imagery that is
      // already loaded rather than grey.
      keepBuffer: 4,
      // Load during a pan rather than waiting for it to stop, which otherwise
      // reads as the map freezing while you drag.
      updateWhenIdle: false,
      // The opposite during a zoom: requesting a whole tile set at every
      // intermediate level throws away most of what it fetches. Updating once the
      // animation settles keeps the zoom smooth and the network quiet.
      updateWhenZooming: false,
      crossOrigin: true,
    };

    // Bottom: the layer with complete global coverage. It is the safety net that
    // shows through wherever a sharper layer above has no tile, which is why a
    // Clarity gap never appears as a hole.
    L.tileLayer(ESRI_WORLD_IMAGERY, { ...tileOptions, attribution }).addTo(map);

    // Middle: Esri's higher-resolution pool. Measured at roughly twice the edge
    // detail of the base layer at zoom 17-18. Coverage is patchy by design, hence
    // the layer beneath.
    L.tileLayer(ESRI_CLARITY, tileOptions).addTo(map);

    // Top: roads, boundaries and place names, already transparent.
    L.tileLayer(ESRI_LABELS, { ...tileOptions, maxNativeZoom: LABEL_MAX_ZOOM }).addTo(map);

    mapRef.current = map;
    setReady(true);

    // Leaflet caches the container size at creation. If this mounts before layout
    // has settled — which it does, being lazily loaded into a freshly sized
    // container — that cached size is zero and no tiles are ever requested, which
    // shows as an empty grey pane. Re-measuring on the next frame fixes it.
    requestAnimationFrame(() => {
      map.invalidateSize();
    });

    return () => {
      map.remove();
      mapRef.current = null;
    };
    // Deliberately mount-only: see the comment above about rebuilding.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Re-measure whenever the map comes back on screen. Same reason as at mount:
  // while hidden the container has no size, so Leaflet's cached dimensions are
  // stale the moment it is shown again.
  useEffect(() => {
    const map = mapRef.current;
    if (map === null || !ready || !visible) {
      return;
    }
    const frame = requestAnimationFrame(() => {
      map.invalidateSize();
    });
    return () => {
      cancelAnimationFrame(frame);
    };
  }, [visible, ready]);

  // Follow the requested view without rebuilding the map.
  useEffect(() => {
    const map = mapRef.current;
    if (map === null || !ready) {
      return;
    }
    map.setView([centre.latitude, centre.longitude], zoom);
  }, [centre.latitude, centre.longitude, zoom, ready]);

  // Hand back to the globe when the user pulls far enough out that a flat
  // projection stops being the honest way to show where they are.
  useEffect(() => {
    const map = mapRef.current;
    if (map === null || !ready) {
      return;
    }
    const onZoomEnd = () => {
      if (map.getZoom() < MAP_HANDOVER_ZOOM) {
        const middle = map.getCenter();
        onZoomOut({ latitude: middle.lat, longitude: middle.lng });
      }
    };
    map.on('zoomend', onZoomEnd);
    return () => {
      map.off('zoomend', onZoomEnd);
    };
  }, [ready, onZoomOut]);

  // Apply a zoom-button press. The nonce is the dependency rather than the delta
  // so that pressing the same button twice zooms twice.
  useEffect(() => {
    const map = mapRef.current;
    if (map === null || !ready || zoomCommand === null) {
      return;
    }
    map.setZoom(map.getZoom() + zoomCommand.delta);
  }, [zoomCommand, ready]);

  // Draw the committed outline, replacing any previous one.
  useEffect(() => {
    const map = mapRef.current;
    if (map === null || !ready) {
      return;
    }
    if (shapeRef.current !== null) {
      shapeRef.current.remove();
      shapeRef.current = null;
    }
    if (outline !== null && outline.length >= 3) {
      shapeRef.current = L.polygon(
        outline.map((vertex) => [vertex.latitude, vertex.longitude] as [number, number]),
        { color: OUTLINE_COLOUR, weight: 2, fillOpacity: 0.15 }
      ).addTo(map);
    }
  }, [outline, ready]);

  /**
   * Outline plotting: click each corner in turn, then click the first vertex
   * again — or press Enter — to close the shape.
   *
   * A polygon rather than a rectangle because real plots are rarely square, and a
   * box around a triangular corner plot claims roughly double its true area. That
   * inflated figure would then be what the user is told their site measures.
   *
   * Panning is disabled for as long as drawing is armed, not just mid-outline. A
   * pan between two clicks would put the next vertex somewhere other than where
   * the user was looking when they clicked it — the same reasoning that freezes
   * the globe's rotation. Leaflet gives latitude and longitude directly, so unlike
   * the globe there is no ray-to-sphere step that can miss.
   */
  useEffect(() => {
    const map = mapRef.current;
    if (map === null || !ready) {
      return;
    }

    if (!drawing) {
      map.dragging.enable();
      map.getContainer().style.cursor = '';
      verticesRef.current = [];
      return;
    }

    map.dragging.disable();
    map.getContainer().style.cursor = 'crosshair';

    // The edges placed so far, the rubber-band edge following the cursor, and a
    // handle on each placed vertex. Separate layers so the committed part of the
    // outline stays solid while only the last edge tracks the pointer.
    let placedLine: L.Polyline | null = null;
    let rubberBand: L.Polyline | null = null;
    let handles: L.CircleMarker[] = [];

    const toLatLon = (points: L.LatLng[]): LatLon[] =>
      points.map((point) => ({ latitude: point.lat, longitude: point.lng }));

    const clearScratch = () => {
      placedLine?.remove();
      rubberBand?.remove();
      handles.forEach((handle) => {
        handle.remove();
      });
      placedLine = null;
      rubberBand = null;
      handles = [];
    };

    const cancelPending = () => {
      verticesRef.current = [];
      clearScratch();
      onPreview?.(null);
    };

    const redraw = () => {
      const vertices = verticesRef.current;
      clearScratch();
      if (vertices.length === 0) {
        return;
      }

      if (vertices.length >= 2) {
        placedLine = L.polyline(vertices, {
          color: OUTLINE_COLOUR,
          weight: 2,
        }).addTo(map);
      }

      handles = vertices.map((vertex, index) =>
        L.circleMarker(vertex, {
          // The first handle is the one you click to close, so it is drawn larger
          // and filled — it is a target, not just a record of where you clicked.
          radius: index === 0 ? 6 : 4,
          color: OUTLINE_COLOUR,
          fillColor: index === 0 ? OUTLINE_COLOUR : '#05070f',
          fillOpacity: 1,
          weight: 2,
        }).addTo(map)
      );
    };

    const commit = () => {
      const vertices = verticesRef.current;
      // Fewer than three points is a line, not a plot. The backend rejects it
      // too, but there is no reason to make a round trip to find that out.
      if (vertices.length < 3) {
        return;
      }
      const finished = toLatLon(vertices);
      cancelPending();
      onDraw(finished);
    };

    const onMove = (event: L.LeafletMouseEvent) => {
      const vertices = verticesRef.current;
      if (vertices.length === 0) {
        return;
      }
      const last = vertices[vertices.length - 1];
      if (last === undefined) {
        return;
      }

      rubberBand?.remove();
      rubberBand = L.polyline([last, event.latlng], {
        color: OUTLINE_COLOUR,
        weight: 2,
        dashArray: '5,5',
        opacity: 0.8,
      }).addTo(map);

      // The live figure includes the point under the cursor, so the area shown is
      // the area of the shape as it currently looks.
      onPreview?.(toLatLon([...vertices, event.latlng]));
    };

    const onClick = (event: L.LeafletMouseEvent) => {
      const vertices = verticesRef.current;
      const first = vertices[0];

      if (first !== undefined && vertices.length >= 3) {
        const firstPixel = map.latLngToContainerPoint(first);
        const clickPixel = map.latLngToContainerPoint(event.latlng);
        if (firstPixel.distanceTo(clickPixel) <= CLOSE_RING_PIXELS) {
          commit();
          return;
        }
      }

      verticesRef.current = [...vertices, event.latlng];
      redraw();
      onPreview?.(toLatLon(verticesRef.current));
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
        redraw();
        onPreview?.(
          verticesRef.current.length === 0 ? null : toLatLon(verticesRef.current)
        );
      }
    };

    map.on('mousemove', onMove);
    map.on('click', onClick);
    window.addEventListener('keydown', onKeyDown);
    return () => {
      map.off('mousemove', onMove);
      map.off('click', onClick);
      window.removeEventListener('keydown', onKeyDown);
      cancelPending();
      map.dragging.enable();
      map.getContainer().style.cursor = '';
    };
  }, [drawing, ready, onDraw, onPreview]);

  // `bg-void` rather than Leaflet's default light grey: an unloaded tile should
  // read as part of this interface, not as a broken page.
  return <div ref={containerRef} className="h-full w-full bg-void" />;
}
